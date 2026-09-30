/**
 * The genomic axis substrate: one place that knows which columns a genomic
 * kind binds for chromosome, start and end, and one hook that turns the
 * dashboard's region filter into an x-range a renderer can clamp to.
 *
 * Why this file exists: `genome_view`'s brush publishes a region as two
 * ordinary filters (a `MultiSelect` on a chromosome column, a `RangeSlider` on
 * a position column, both `source: 'genome_selection'`, see
 * `genomeRegionFilters` in `src/selection.ts`). Any tile bound to the same
 * collection therefore *already* fetches the narrowed rows, because the
 * renderers forward the dashboard filters to `fetchAdvancedVizData` untouched.
 * What was missing is the other half: the tile did not know that the region
 * concerned *it*, so it could not clamp its x-axis to the brushed window, nor
 * reflect the region in its own chromosome control.
 *
 * The obstacle was purely nominal. Every genomic kind names the same three
 * roles differently (`chr_col`/`pos_col`, `chromosome_col`/`position_col`,
 * `chrom_col`/`start_col`/`end_col`, `contig_col`, `chrom1_col`/`start1_col`),
 * and renaming any of them is forbidden: stored dashboards carry those keys
 * and `test_advanced_viz_config_alignment` pins them. So the translation table
 * lives here instead, keyed by kind, and every renderer reads the region
 * through `useFollowedRegion` rather than re-deriving it.
 *
 * Nothing here is a new bus. The dashboard filter list stays the single source
 * of truth, which is what makes a plain `Chromosome` select in the left panel
 * drive the same tiles as a brush.
 */

import { useMemo, useRef } from 'react';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import { genomePosFilterIndex, regionFromFilters } from '../../selection';
import type { RegionRoleColumns } from '../../selection';

/** Chromosome / start / optional end, as columns of the tile's own DC. */
export type GenomicRoles = RegionRoleColumns;

/** A region a tile follows. `end` is `Infinity` when the filter named a
 *  chromosome but no range: the whole contig is still somewhere to go. */
export interface FollowedRegion {
  chrom: string;
  start: number;
  end: number;
}

/**
 * One entry per role: the config field that holds the column name, and the
 * default the Pydantic model applies when the YAML leaves it out. A `null`
 * default means the field is optional (`str | None`) and the role is only
 * bound when the author set it.
 */
interface RoleField {
  field: string;
  fallback: string | null;
}

interface KindRoles {
  chrom: RoleField;
  start: RoleField;
  end?: RoleField;
}

/**
 * Kind -> role columns, mirroring `depictio/models/components/advanced_viz/
 * configs.py`. Field names and defaults are copied from the models on purpose:
 * this table is the only translation layer, so a divergence shows up as a tile
 * that ignores the region rather than as a crash.
 *
 * A kind absent from this table is not genomic and never follows a region.
 */
const KIND_ROLES: Record<string, KindRoles[]> = {
  // chr / pos / score family
  manhattan: [{ chrom: { field: 'chr_col', fallback: 'chr' }, start: { field: 'pos_col', fallback: 'pos' } }],
  genome_view: [
    {
      chrom: { field: 'chr_col', fallback: 'chr' },
      start: { field: 'pos_col', fallback: 'pos' },
      end: { field: 'end_col', fallback: null },
    },
  ],
  // chromosome / position family
  coverage_track: [
    {
      chrom: { field: 'chromosome_col', fallback: 'chromosome' },
      start: { field: 'position_col', fallback: 'position' },
      end: { field: 'end_col', fallback: null },
    },
  ],
  // chrom / start / end family
  cnv_profile: [
    {
      chrom: { field: 'chrom_col', fallback: 'chrom' },
      start: { field: 'start_col', fallback: 'start' },
      end: { field: 'end_col', fallback: 'end' },
    },
  ],
  transcript_structure: [
    {
      chrom: { field: 'chrom_col', fallback: 'chrom' },
      start: { field: 'start_col', fallback: 'start' },
      end: { field: 'end_col', fallback: 'end' },
    },
  ],
  gene_arrow_track: [
    {
      // A metagenomic contig is the same role as a chromosome here.
      chrom: { field: 'contig_col', fallback: 'contig' },
      start: { field: 'start_col', fallback: 'start' },
      end: { field: 'end_col', fallback: 'end' },
    },
  ],
  // Sashimi binds twice: the junction table, then an optional second
  // collection holding real read depth. Both follow the same region.
  sashimi: [
    {
      chrom: { field: 'chr_col', fallback: 'chr' },
      start: { field: 'start_col', fallback: 'start' },
      end: { field: 'end_col', fallback: 'end' },
    },
    {
      chrom: { field: 'coverage_chr_col', fallback: 'chromosome' },
      start: { field: 'coverage_position_col', fallback: 'position' },
      end: { field: 'coverage_end_col', fallback: null },
    },
  ],
  // The first bin of a contact pair is the one on the shared x axis when the
  // matrix is drawn as a triangle under a genome_view track.
  contact_map: [
    {
      chrom: { field: 'chrom1_col', fallback: 'chrom1' },
      start: { field: 'start1_col', fallback: 'start1' },
      end: { field: 'end1_col', fallback: null },
    },
  ],
};

function asRecord(config: unknown): Record<string, unknown> {
  return config && typeof config === 'object' ? (config as Record<string, unknown>) : {};
}

function resolve(config: Record<string, unknown>, role: RoleField): string | null {
  const raw = config[role.field];
  if (typeof raw === 'string' && raw.trim()) return raw;
  return role.fallback;
}

function resolveRoles(config: Record<string, unknown>, spec: KindRoles): GenomicRoles | null {
  const chrom = resolve(config, spec.chrom);
  const start = resolve(config, spec.start);
  if (!chrom || !start) return null;
  const end = spec.end ? resolve(config, spec.end) : null;
  return end ? { chrom, start, end } : { chrom, start };
}

/**
 * The chromosome / start / end columns `kind` binds in `config`, or `null`
 * when the kind is not coordinate-bound.
 *
 * For `sashimi` this is the junction binding; `genomicRoleBindings` returns
 * the coverage binding too.
 */
export function genomicRoles(
  kind: string | undefined | null,
  // `unknown` rather than `Record<string, unknown>`: every renderer narrows its
  // config to a per-kind interface, and those have no index signature, so
  // anything tighter would reject the exact callers this helper exists for.
  config: unknown,
): GenomicRoles | null {
  const specs = kind ? KIND_ROLES[kind] : undefined;
  if (!specs || !specs.length) return null;
  return resolveRoles(asRecord(config), specs[0]);
}

/** Every coordinate binding of a kind, primary first. One entry for every kind
 *  but `sashimi`, which can bind a second collection for read depth. */
export function genomicRoleBindings(
  kind: string | undefined | null,
  config: unknown,
): GenomicRoles[] {
  const specs = kind ? KIND_ROLES[kind] : undefined;
  if (!specs) return [];
  const cfg = asRecord(config);
  const out: GenomicRoles[] = [];
  for (const spec of specs) {
    const roles = resolveRoles(cfg, spec);
    if (roles) out.push(roles);
  }
  return out;
}

/** True when `kind` is coordinate-bound at all. */
export function isGenomicKind(kind: string | undefined | null): boolean {
  return Boolean(kind && KIND_ROLES[kind]);
}

/** The region as a finite Plotly `xaxis.range`, or `null` when there is
 *  nothing to clamp (no region, or a whole contig of unknown length). */
export function regionXRange(region: FollowedRegion | null): [number, number] | null {
  if (!region) return null;
  if (!Number.isFinite(region.start) || !Number.isFinite(region.end)) return null;
  if (region.end <= region.start) return null;
  return [region.start, region.end];
}

/**
 * The region a tile should follow, read off the dashboard filters through the
 * tile's own column names. The pure core of `useFollowedRegion`, so the rule
 * is testable without a DOM.
 *
 * Returns `null` unless a single chromosome is selected on the tile's own
 * chromosome column: "chr1 and chr7" is not somewhere to zoom, and a region
 * naming another collection's columns is none of this tile's business (it
 * reaches the tile rewritten onto its own columns, through the project's
 * links, or not at all).
 *
 * A tile's *own* emitted region is excluded, so a kind that both emits and
 * follows (genome_view) cannot narrow itself into a corner it can never widen
 * again.
 */
export function followedRegion(
  kind: string | undefined | null,
  componentIndex: string | undefined | null,
  config: unknown,
  filters: InteractiveFilter[] | undefined | null,
): FollowedRegion | null {
  const roles = genomicRoles(kind, config);
  if (!roles || !filters?.length) return null;
  const posIndex = componentIndex ? genomePosFilterIndex(componentIndex) : null;
  const foreign = filters.filter(
    (f) =>
      !(
        f.source === 'genome_selection' &&
        (f.index === componentIndex || (posIndex !== null && f.index === posIndex))
      ),
  );
  return regionFromFilters(foreign, roles);
}

function sameRegion(a: FollowedRegion | null, b: FollowedRegion | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return a.chrom === b.chrom && a.start === b.start && a.end === b.end;
}

/**
 * `followedRegion` as a hook, memoised on the tile's kind, columns and the
 * dashboard filter list.
 *
 * The identity is held stable across renders while the region's value does not
 * change: hosts hand renderers a fresh `filters` array on every render, and a
 * renderer's figure memo keys on this result.
 */
export function useFollowedRegion(
  metadata: (StoredMetadata & { viz_kind?: string; config?: unknown }) | undefined | null,
  config: unknown,
  filters: InteractiveFilter[] | undefined | null,
): FollowedRegion | null {
  const kind = metadata?.viz_kind ?? (asRecord(config).viz_kind as string | undefined);
  const index = metadata?.index;
  const rolesKey = JSON.stringify(genomicRoles(kind, config) ?? null);
  const region = useMemo(
    () => followedRegion(kind, index, config, filters),
    // `config` is a fresh object every render on most renderers (they spread
    // their control state into it), so key on the resolved roles instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [kind, index, rolesKey, filters],
  );
  const held = useRef<FollowedRegion | null>(null);
  if (!sameRegion(held.current, region)) held.current = region;
  return held.current;
}
