/**
 * `default_region`: the region a locus section opens on.
 *
 * Nothing else in the dashboard can do this. An interactive filter has no
 * default value, and a `genome_selection` filter only exists once somebody has
 * brushed the genome axis or typed in the locus field. So a section whose
 * tiles only make sense inside a window (a contact matrix, a pileup, a
 * coverage track at base resolution) opened on the whole genome, or on
 * nothing, until a reader knew to type a locus.
 *
 * The fix is deliberately not a new mechanism: the tile emits, on its first
 * render, exactly the two filters `LocusInput` emits for the same text
 * (`genomeRegionFilters`), so the region travels the dashboard by the one road
 * it already travels, reaching every other tile of the section directly or
 * through a `region` link.
 *
 * The rule is a pure function so it can be read and tested without a DOM: the
 * renderer only owns the "once" part, a ref, and the decision below owns
 * everything else.
 */

import type { InteractiveFilter, StoredMetadata } from '../../../api';
import { genomePosFilterIndex, genomeRegionFilters, regionFromFilters } from '../../../selection';
import type { GeneRow } from './genomeSpySpec';
import { resolveLocus } from './locusParse';

export interface DefaultRegionInput {
  /** The emitting tile: its index and dc_id ride on both filters. */
  metadata: StoredMetadata;
  /** This tile's own chromosome and position columns. */
  chrColumn: string;
  posColumn: string;
  /** `config.default_region`, as the author wrote it. */
  defaultRegion: string | null | undefined;
  /** `region_filter_enabled` and a host that accepts filters. A read-only host
   *  emits nothing, so a shared dashboard cannot be changed by opening it. */
  enabled: boolean;
  /** Contig names the data actually carries. Empty until the collection has
   *  been read, and the answer is then "not yet", never "nowhere". */
  contigs: readonly string[] | null | undefined;
  /** Gene table, so `default_region: TP53` resolves like a typed symbol. */
  genes?: readonly GeneRow[] | null;
  /** Every dashboard filter, this tile's own included. */
  filters: readonly InteractiveFilter[] | null | undefined;
}

function hasValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (value === null || value === undefined) return false;
  return String(value) !== '';
}

/**
 * True when some filter already constrains the region roles, whoever set it.
 *
 * Column-keyed rather than source-keyed on purpose: a `genome_selection` pair
 * from another tile, a plain `Chromosome` select in the left panel and a
 * position `RangeSlider` all mean the same thing here, that the reader is
 * already somewhere and a default region would move them.
 */
export function regionFilterInForce(
  filters: readonly InteractiveFilter[] | null | undefined,
  chrColumn: string,
  posColumn: string,
): boolean {
  if (!filters?.length) return false;
  return filters.some((f) => {
    const column = f.column_name ?? f.metadata?.column_name;
    if (column !== chrColumn && column !== posColumn) return false;
    return hasValue(f.value);
  });
}

/**
 * The filters a tile should emit for its `default_region`, or `null` when it
 * should emit none.
 *
 * `null` covers four different situations on purpose, because the caller does
 * the same thing in all four: no default was written, the tile may not emit
 * region filters, a region is already in force, or the contig list is not
 * known yet. The caller decides only once the contig list exists, so the last
 * case resolves itself on the render after the data arrives.
 */
export function defaultRegionFilters(input: DefaultRegionInput): InteractiveFilter[] | null {
  const { metadata, chrColumn, posColumn, defaultRegion, enabled, filters } = input;
  if (!enabled) return null;
  const text = (defaultRegion ?? '').trim();
  if (!text) return null;
  if (regionFilterInForce(filters, chrColumn, posColumn)) return null;

  const contigs = input.contigs ?? [];
  if (!contigs.length) return null;
  const resolved = resolveLocus(text, contigs, input.genes ?? null);
  // A default region naming a contig this collection does not carry is an
  // authoring mistake, and emitting it would filter every tile down to zero
  // rows. Drawing the overview is the better failure.
  if (!resolved) return null;

  return genomeRegionFilters(metadata, chrColumn, posColumn, {
    chroms: [resolved.chrom],
    range:
      resolved.start !== null && resolved.end !== null ? [resolved.start, resolved.end] : null,
  });
}

// ---- Zooming the emitting tile to its own region ---------------------------

/** A single-contig window, the shape `zoomToRegion` takes. */
export interface ZoomRegion {
  chrom: string;
  start: number;
  end: number;
}

export type OwnRegionZoom =
  | { action: 'none' }
  | { action: 'zoom'; region: ZoomRegion }
  | { action: 'reset' };

export interface OwnRegionZoomInput {
  /** Every dashboard filter, this tile's own included. */
  filters: readonly InteractiveFilter[] | null | undefined;
  /** The emitting tile's index; its region pair rides on it and its `::pos` sibling. */
  componentIndex: string;
  chrColumn: string;
  posColumn: string;
  /** Key of the tile's own region the last time this was decided (`''` for none). */
  previousKey: string;
  /** Key of the region the tile's own brush last published, or `null`. */
  brushedKey: string | null;
  /** True while the view shows a window this tile zoomed to from code. */
  zoomedByCode: boolean;
  /** Region another tile is sending, when `follow_region_filter` is on. */
  followedRegion?: ZoomRegion | null;
}

/**
 * The tile's own `genome_selection` pair, keyed so a change is one string
 * comparison. `''` means the tile emits no region (both halves empty).
 */
export function ownRegionKey(
  filters: readonly InteractiveFilter[] | null | undefined,
  componentIndex: string,
): string {
  const posIndex = genomePosFilterIndex(componentIndex);
  let chr: unknown = [];
  let pos: unknown = [];
  for (const f of filters ?? []) {
    if (f.source !== 'genome_selection') continue;
    if (f.index === componentIndex) chr = f.value;
    else if (f.index === posIndex) pos = f.value;
  }
  const empty = (v: unknown) => !Array.isArray(v) || v.length === 0;
  if (empty(chr) && empty(pos)) return '';
  return JSON.stringify([chr, pos]);
}

/**
 * Whether a tile that just emitted (or cleared) a region should move its own
 * view.
 *
 * The emitting tile strips its own region from its fetch (so a brush can
 * widen again), which also meant it never zoomed to what it emitted: the
 * locus field and `default_region` moved every tile but the one they sit on.
 * The rule:
 *
 * - no change since last time: nothing;
 * - the region came from this tile's own brush: nothing, the brush rectangle
 *   already marks it and zooming under the cursor would fight the drag;
 * - a single-contig region from the locus field or `default_region`: zoom;
 * - cleared, after a zoom from code: back to the followed region when one is
 *   in force, else the whole genome.
 */
export function ownRegionZoom(input: OwnRegionZoomInput): { decision: OwnRegionZoom; key: string } {
  const key = ownRegionKey(input.filters, input.componentIndex);
  if (key === input.previousKey) return { decision: { action: 'none' }, key };
  if (!key) {
    if (!input.zoomedByCode) return { decision: { action: 'none' }, key };
    const followed = input.followedRegion ?? null;
    return {
      decision: followed ? { action: 'zoom', region: followed } : { action: 'reset' },
      key,
    };
  }
  if (key === input.brushedKey) return { decision: { action: 'none' }, key };
  const posIndex = genomePosFilterIndex(input.componentIndex);
  const own = (input.filters ?? []).filter(
    (f) =>
      f.source === 'genome_selection' &&
      (f.index === input.componentIndex || f.index === posIndex),
  );
  const region = regionFromFilters(own, input.chrColumn, input.posColumn);
  // Several contigs (a brush across a boundary) is not one window to zoom to.
  if (!region) return { decision: { action: 'none' }, key };
  return { decision: { action: 'zoom', region }, key };
}
