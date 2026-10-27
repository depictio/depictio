/**
 * The legend of the genome browser's track colours: one entry per colour the
 * open tracks wear, labelled by the group it stands for (`group`: the tile's
 * `color_by` value or the manifest's group), else by the samples wearing it.
 */
import type { JBrowseTrackRow } from '../../api';

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
