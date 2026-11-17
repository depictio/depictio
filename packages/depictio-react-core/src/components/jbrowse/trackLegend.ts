/**
 * The legend of the genome browser's track colours: one entry per colour the
 * open tracks wear, labelled by the group it stands for (`group`: the tile's
 * `color_by` value or the manifest's group), else by the samples wearing it.
 */
import type { JBrowseTrackRow } from '../../api';
import type { GenomeTracksColourKey } from './genomeTracksStore';
import { sequentialRamp } from '../../categoryColors';

export interface LegendEntry {
  color: string;
  label: string;
  /** Every name the entry stands for, for its tooltip. */
  names: string[];
}

/** Labels an entry shows before folding the rest into "+N". */
const MAX_NAMES = 2;

export function trackLegend(
  rows: readonly JBrowseTrackRow[],
  openIds: readonly string[],
  colourOf: (row: JBrowseTrackRow) => string | null | undefined,
): LegendEntry[] {
  const byId = new Map(rows.map((r) => [r.track_id, r]));
  const open = openIds
    .map((id) => byId.get(id))
    .filter((r): r is JBrowseTrackRow => !!r)
    .map((row) => ({ row, colour: colourOf(row) }))
    .filter((e): e is { row: JBrowseTrackRow; colour: string } => !!e.colour);
  const collect = (nameOf: (row: JBrowseTrackRow) => string) => {
    const byColour = new Map<string, Set<string>>();
    for (const { row, colour } of open) {
      if (!byColour.has(colour)) byColour.set(colour, new Set());
      byColour.get(colour)!.add(nameOf(row));
    }
    return byColour;
  };
  let byColour = collect((row) => row.group || row.sample || row.name);
  // Colours that only one sample's label would tell apart (one sample, a
  // colour per caller): the track's name without the sample says what the
  // colour stands for.
  const labels = [...byColour.values()].map((set) => [...set].join('\u0000'));
  if (new Set(labels).size < labels.length) {
    byColour = collect(
      (row) =>
        row.group ||
        (row.sample ? row.name.replace(row.sample, '').trim() : '') ||
        row.sample ||
        row.name,
    );
  }
  return [...byColour.entries()].map(([color, set]) => {
    const names = [...set];
    const shown = names.slice(0, MAX_NAMES).join(', ');
    const more = names.length - MAX_NAMES;
    return { color, names, label: more > 0 ? `${shown} +${more}` : shown };
  });
}

/** A sequential scale's legend: a gradient between its first and last value. */
export interface LegendRamp {
  /** Colours of the gradient, first value to last. */
  stops: string[];
  /** Label of the gradient's start and end (the extreme values open). */
  from: string;
  to: string;
  /** Every value the open tracks carry, in scale order, for the tooltip. */
  values: string[];
}

/**
 * The ramp legend of a `color_scale`, over the values the open tracks carry
 * (their `group`, the scale column's value). `scale` is the condition → colour
 * map in scale order (`conditionSequentialMap`). Null when fewer than two
 * values are open: a lone value is a swatch, which `trackLegend` already
 * draws.
 */
export function legendRamp(
  rows: readonly JBrowseTrackRow[],
  openIds: readonly string[],
  scale: ReadonlyMap<string, string>,
  scheme: string | null | undefined,
): LegendRamp | null {
  const byId = new Map(rows.map((r) => [r.track_id, r]));
  const used = new Set(
    openIds.map((id) => byId.get(id)?.group).filter((g): g is string => !!g && scale.has(g)),
  );
  const values = [...scale.keys()].filter((v) => used.has(v));
  if (values.length < 2) return null;
  return {
    stops: sequentialRamp(scheme, 7),
    from: values[0],
    to: values[values.length - 1],
    values,
  };
}

/** One colour of a key and what it stands for, before colours are folded. */
export interface KeyItem {
  label: string;
  color: string;
}

/**
 * Entries of a key from `items` in order: items wearing one colour share an
 * entry (two categories drawn alike, `XR, XD`), and more than `MAX_NAMES`
 * names fold into "+N", exactly as the track legend does.
 */
export function foldByColour(items: readonly KeyItem[]): LegendEntry[] {
  const byColour = new Map<string, string[]>();
  for (const { label, color } of items) {
    if (!color) continue;
    const names = byColour.get(color) ?? [];
    if (!names.includes(label)) names.push(label);
    byColour.set(color, names);
  }
  return [...byColour.entries()].map(([color, names]) => {
    const shown = names.slice(0, MAX_NAMES).join(', ');
    const more = names.length - MAX_NAMES;
    return { color, names, label: more > 0 ? `${shown} +${more}` : shown };
  });
}

/** A column name as a reader says it: `genetic_model` is "genetic model". */
export function keyTitle(column: string): string {
  return column.replace(/[_-]+/g, ' ').trim();
}

/** The payload's key to `variant_color_by` (see `variant_color_legend`). */
export interface VariantLegendPayload {
  title: string;
  entries: KeyItem[];
  fallback?: KeyItem | null;
}

/**
 * The key to the colours of the variant tracks, or null when the tile does not
 * colour them. The categories come in the order the track tests them; the
 * fallback (what no category matched) comes last, unless it wears the colour of
 * a category already listed.
 */
export function variantLegend(
  payload: VariantLegendPayload | null | undefined,
): { title: string; entries: LegendEntry[] } | null {
  if (!payload || !payload.entries?.length) return null;
  const items = [...payload.entries];
  if (payload.fallback) items.push(payload.fallback);
  const entries = foldByColour(items);
  return entries.length ? { title: keyTitle(payload.title), entries } : null;
}

/**
 * What the browser publishes of its colour scale for other tiles' keys: the
 * column, its values in colour order and which sample carries which value.
 * `colours` is the value → colour map the tracks were painted with (its order
 * is the scale's); only samples whose tracks carry one value are listed.
 */
export function colourKeyOf(
  column: string,
  colours: ReadonlyMap<string, string>,
  ordered: boolean,
  scheme: string | null | undefined,
  rows: readonly JBrowseTrackRow[],
): GenomeTracksColourKey {
  const seen = new Map<string, Set<string>>();
  for (const row of rows) {
    if (!row.sample || !row.group || !colours.has(row.group)) continue;
    const values = seen.get(row.sample) ?? new Set<string>();
    values.add(row.group);
    seen.set(row.sample, values);
  }
  const sampleGroups: Record<string, string> = {};
  for (const [sample, values] of seen) if (values.size === 1) sampleGroups[sample] = [...values][0];
  return { column, values: [...colours.keys()], ordered, scheme: scheme ?? null, sampleGroups };
}
