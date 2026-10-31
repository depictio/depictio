/**
 * Hover across the genome browser and the other tiles, both ways.
 *
 * Out: the feature under the pointer (a variant, a peak, a read, a coverage
 * bin) is read off JBrowse's display models and published on the hover bus
 * with its coordinates and name, so a Manhattan plot rings the nearest point,
 * a coverage track draws a line and a table lights the matching row.
 *
 * In: a hover on another tile arrives as a `genomic` span (a browser, a plot)
 * or as the hovered table row (`record`); a row is read through the columns
 * of the tile's `locus_from`. The span becomes a band, never a navigation.
 *
 * The functions here are pure over the slice of the models they read; the one
 * piece of mobx wiring (`watchFeatureHover`) is a thin shell around them.
 * Coordinates leave and enter here the way the bus carries them: 1-based,
 * inclusive. JBrowse's own features are 0-based, end-exclusive.
 */
import { comparer, reaction } from 'mobx';

import type { JBrowseLocusSource } from '../../api';
import type { HighlightEvent, HighlightPayload } from '../../highlight/bus';
import { locusHighlight, type LocusHighlight } from './locusHighlight';

/** A genomic span as the bus carries it (1-based, inclusive). */
export interface GenomicHover {
  refName: string;
  start: number;
  end: number;
  /** Other names the assembly knows the contig by. */
  aliases?: string[];
}

/** A hover event with the genomic fields. Declared here so this file does
 *  not depend on the bus types having grown them: the bus spreads a payload,
 *  so the extra fields reach subscribers either way. */
export type FeatureHoverEvent = HighlightPayload & {
  genomic?: GenomicHover;
  record?: Record<string, unknown>;
};

/** What a hover reads off a JBrowse feature (0-based start, end-exclusive). */
export interface HoverFeature {
  id?: string;
  refName: string;
  start: number;
  end: number;
  name?: string;
}

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);

/** The id JBrowse gives the synthetic bin the multi-wiggle display builds
 *  under the pointer (it has no `featureIdUnderMouse`). */
const MOUSEOVER_FEATURE_ID = 'mouseoverfeat';

// ---------------------------------------------------------------------------
// Out: JBrowse feature -> bus event
// ---------------------------------------------------------------------------

/** A JBrowse `Feature` (`get(key)`, `id()`) or a plain object. */
type FeatureLike = {
  get?: (key: string) => unknown;
  id?: () => string;
  [key: string]: unknown;
};

function pick(feature: FeatureLike, key: string): unknown {
  return typeof feature.get === 'function' ? feature.get(key) : feature[key];
}

function idOf(feature: FeatureLike): string | undefined {
  if (typeof feature.id === 'function') return String(feature.id());
  return typeof feature.id === 'string' ? feature.id : undefined;
}

/** The plain summary of a feature, or null without a readable span. */
export function summariseFeature(feature: unknown): HoverFeature | null {
  if (!feature || typeof feature !== 'object') return null;
  const f = feature as FeatureLike;
  const refName = pick(f, 'refName');
  const start = Number(pick(f, 'start'));
  const end = Number(pick(f, 'end'));
  if (typeof refName !== 'string' || !refName || !finite(start) || !finite(end)) return null;
  const rawName = pick(f, 'name');
  // A VCF record without an ID reads "." and a read can lack a name.
  const name =
    (typeof rawName === 'string' || typeof rawName === 'number') &&
    String(rawName) !== '' &&
    String(rawName) !== '.'
      ? String(rawName)
      : undefined;
  return { id: idOf(f), refName, start, end: Math.max(start, end), ...(name ? { name } : {}) };
}

/** The slice of a JBrowse display model a hover reads. */
interface HoverDisplay {
  featureIdUnderMouse?: string;
  featureUnderMouse?: unknown;
  features?: { get?: (id: string) => unknown };
  /** The two halves of the alignments wrapper display. */
  PileupDisplay?: HoverDisplay;
  SNPCoverageDisplay?: HoverDisplay;
}

/**
 * The feature under the pointer on one display, or null.
 *
 * Feature and variant displays fill `featureUnderMouse` by RPC some 50 ms
 * after the id changes, so a value whose id is not the current one is stale
 * and the rendered block's own copy (`features.get(id)`) stands in until the
 * RPC lands (the caller reacts to both). The alignments display is a wrapper:
 * its read comes from the pileup half, its bin from the coverage half. The
 * multi-wiggle display has no id at all, only a synthetic bin.
 */
export function hoverFeatureOf(display: unknown): HoverFeature | null {
  const d = display as HoverDisplay | null | undefined;
  if (!d || typeof d !== 'object') return null;
  if (d.PileupDisplay || d.SNPCoverageDisplay) {
    return hoverFeatureOf(d.PileupDisplay) ?? hoverFeatureOf(d.SNPCoverageDisplay);
  }
  const id = d.featureIdUnderMouse;
  const under = d.featureUnderMouse as FeatureLike | undefined;
  if (id) {
    const fresh = under && idOf(under) === id ? under : undefined;
    return summariseFeature(fresh ?? d.features?.get?.(id));
  }
  return under && idOf(under) === MOUSEOVER_FEATURE_ID ? summariseFeature(under) : null;
}

/**
 * The bus event for a hovered feature.
 *
 * `entity` is the feature's name (a VCF ID, a peak, a gene) so a table can
 * ring the row it names, and the contig when there is none. `genomic` is the
 * span, `record` the hovered row in the terms of `locusSource`'s columns, so
 * a table that shares them matches on value and one that does not ignores it.
 */
export function hoverEventFromFeature(
  feature: HoverFeature,
  locusSource: JBrowseLocusSource | null | undefined,
  aliases?: string[],
): FeatureHoverEvent {
  const start = feature.start + 1;
  const end = Math.max(start, feature.end);
  const aliasList = aliases?.length ? aliases : undefined;
  return {
    entity: feature.name ?? feature.refName,
    ...(!feature.name && aliasList ? { entityAliases: aliasList } : {}),
    ...(feature.name ? { rowKeys: [feature.name] } : {}),
    genomic: {
      refName: feature.refName,
      start,
      end,
      ...(aliasList ? { aliases: aliasList } : {}),
    },
    ...(locusSource
      ? {
          record: {
            [locusSource.chrom_column]: feature.refName,
            [locusSource.start_column]: start,
          },
        }
      : {}),
    positionColumn: '__genome__',
    start,
    end,
  };
}

/**
 * Which feature the reader is on when several displays hold one (a variant
 * track above a coverage track, the pointer crossing from one to the other):
 * the display that reported one last. A display leaving gives the turn back.
 */
export function createHoverTracker(): {
  set: (key: object, feature: HoverFeature | null) => HoverFeature | null;
} {
  const held = new Map<object, HoverFeature>();
  return {
    set(key, feature) {
      held.delete(key);
      if (feature) held.set(key, feature);
      let last: HoverFeature | null = null;
      for (const f of held.values()) last = f;
      return last;
    },
  };
}

/** The displays of every open track of the view. */
function displaysOf(view: { tracks?: Array<{ displays?: unknown[] }> }): unknown[] {
  return (view.tracks ?? []).flatMap((t) => [...(t.displays ?? [])]);
}

/**
 * Report the feature under the pointer, whichever display it is on.
 *
 * One mobx `reaction` per display (the pattern JBrowse's own tooltips use),
 * with a reaction over the list of displays keeping them in step with the
 * open tracks: a track opened later is watched, one closed is let go.
 * `onHover` gets the feature, or null once the pointer left every display.
 * Returns the disposer.
 */
export function watchFeatureHover(
  view: { tracks?: Array<{ displays?: unknown[] }> },
  onHover: (feature: HoverFeature | null) => void,
  alive: (node: unknown) => boolean = () => true,
): () => void {
  const tracker = createHoverTracker();
  const watched = new Map<object, () => void>();
  // Only a change is reported: a display that never held a hover leaving
  // (a closed track) must not clear the one another display holds.
  let reported = '';
  const report = (feature: HoverFeature | null) => {
    const key = feature
      ? `${feature.refName}:${feature.start}:${feature.end}:${feature.name ?? ''}`
      : '';
    if (key === reported) return;
    reported = key;
    onHover(feature);
  };
  const forget = (display: object) => {
    watched.get(display)?.();
    watched.delete(display);
    report(tracker.set(display, null));
  };
  const sync = (displays: unknown[]) => {
    const current = new Set(displays.filter((d): d is object => !!d && typeof d === 'object'));
    for (const display of [...watched.keys()]) if (!current.has(display)) forget(display);
    for (const display of current) {
      if (watched.has(display)) continue;
      watched.set(
        display,
        reaction(
          () => {
            if (!alive(display)) return null;
            try {
              return hoverFeatureOf(display);
            } catch {
              return null;
            }
          },
          (feature) => report(tracker.set(display, feature)),
          { equals: comparer.structural },
        ),
      );
    }
  };
  const stop = reaction(
    () => (alive(view) ? displaysOf(view) : []),
    sync,
    { fireImmediately: true, equals: comparer.shallow },
  );
  return () => {
    stop();
    for (const dispose of watched.values()) dispose();
    watched.clear();
  };
}

// ---------------------------------------------------------------------------
// In: bus event -> band on the browser
// ---------------------------------------------------------------------------

/** A hover event as the browser reads it. */
export type ReceivedHover = HighlightEvent & {
  genomic?: GenomicHover;
  record?: Record<string, unknown>;
};

const toPosition = (v: unknown): number | null => {
  if (typeof v === 'bigint') return Number(v);
  if (typeof v === 'string' && v.trim() === '') return null;
  const n = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
};

/**
 * The span a hovered table row (or any record) stands for, through the
 * columns of the tile's `locus_from`. The end column is optional: a point is
 * a span of one base. Values may arrive as strings or bigints (a grid cell
 * is not typed); a missing contig, a missing or unreadable start, or a
 * position below 1 gives null (the event is not about this tile's data).
 */
export function recordToRegion(
  record: Record<string, unknown> | null | undefined,
  locusSource: JBrowseLocusSource | null | undefined,
): GenomicHover | null {
  if (!record || !locusSource) return null;
  const chrom = record[locusSource.chrom_column];
  if ((typeof chrom !== 'string' && typeof chrom !== 'number') || String(chrom) === '') return null;
  const start = toPosition(record[locusSource.start_column]);
  if (start === null || start < 1) return null;
  const end = locusSource.end_column ? toPosition(record[locusSource.end_column]) : null;
  return { refName: String(chrom), start, end: end !== null && end >= start ? end : start };
}

/** The span an event asks for: its own `genomic` field, else the `record`
 *  read through `locusSource`; null when it carries neither. */
export function hoverRegion(
  event: ReceivedHover | null | undefined,
  locusSource: JBrowseLocusSource | null | undefined,
): GenomicHover | null {
  if (!event) return null;
  const g = event.genomic;
  if (g && g.refName && finite(g.start) && finite(g.end)) return g;
  return recordToRegion(event.record, locusSource);
}

/** Pixels a band is at least wide; JBrowse draws 3 px but only to the right
 *  of the start, so a narrow span is widened around its centre here. */
export const MIN_BAND_PX = 3;

/** `band` widened (about its centre) to at least `minPx` pixels at `bpPerPx`. */
export function widenBand(
  band: LocusHighlight,
  bpPerPx: number | undefined,
  minPx: number = MIN_BAND_PX,
): LocusHighlight {
  if (!bpPerPx || !Number.isFinite(bpPerPx) || bpPerPx <= 0) return band;
  const minBp = minPx * bpPerPx;
  if (band.end - band.start >= minBp) return band;
  const centre = (band.start + band.end) / 2;
  return {
    ...band,
    start: Math.max(0, Math.floor(centre - minBp / 2)),
    end: Math.ceil(centre + minBp / 2),
  };
}

/**
 * The band a hover on another tile draws on the browser, or null.
 *
 * An event with a span (`genomic`, or a `record` this tile's columns read) is
 * resolved by contig name, then by each alias, through the assembly's own
 * `canonicalRefName`; anything else (a protein tile's residue hover, the
 * cursor of a tile on another contig naming) falls back to the position-only
 * rule of `locusHighlight`.
 */
export function hoverBand(
  event: ReceivedHover | null | undefined,
  locusSource: JBrowseLocusSource | null | undefined,
  canonicalRefName: (name: string) => string | undefined,
  assemblyName: string,
  fallbackColor?: string,
  bpPerPx?: number,
): LocusHighlight | null {
  if (!event) return null;
  const region = hoverRegion(event, locusSource);
  let band: LocusHighlight | null = null;
  if (region) {
    for (const name of [region.refName, ...(region.aliases ?? [])]) {
      band = locusHighlight(
        { ...event, entity: name, start: region.start, end: region.end },
        canonicalRefName,
        assemblyName,
        fallbackColor,
      );
      if (band) break;
    }
  } else if (!event.record) {
    band = locusHighlight(event, canonicalRefName, assemblyName, fallbackColor);
  }
  return band ? widenBand(band, bpPerPx) : null;
}
