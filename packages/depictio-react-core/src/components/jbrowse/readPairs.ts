/**
 * The initial display of DNA alignment tracks (`read_pairs_display`).
 *
 * In JBrowse 4.3.0 the read arcs and the read cloud are not track displays of
 * their own: they are lower panels of `LinearAlignmentsDisplay`, chosen when
 * the track is shown (`showTrack(id, {}, { lowerPanelType })`). The pileup is
 * the default and needs nothing passed. The other panels stay one click away in
 * the track menu.
 */
export type ReadPairsDisplay = 'pileup' | 'arcs' | 'cloud';

const LOWER_PANEL: Record<Exclude<ReadPairsDisplay, 'pileup'>, string> = {
  arcs: 'LinearReadArcsDisplay',
  cloud: 'LinearReadCloudDisplay',
};

/** The display snapshot to show an alignment track with, `{}` for the pileup
 *  (and for a value this build does not know). */
export function pairsDisplaySnapshot(mode: unknown): Record<string, unknown> {
  return mode === 'arcs' || mode === 'cloud' ? { lowerPanelType: LOWER_PANEL[mode] } : {};
}

/** Ids of the alignment tracks among the track configs. */
export function alignmentTrackIds(tracks: ReadonlyArray<{ trackId: string; type?: unknown }>): Set<string> {
  return new Set(tracks.filter((t) => t.type === 'AlignmentsTrack').map((t) => t.trackId));
}

/** An entry of `init.tracks`: the bare id, or, for an alignment track under a
 *  non-default read-pairs display, the id with the display snapshot. */
export function initTrackEntry(
  id: string,
  alignments: ReadonlySet<string>,
  mode: unknown,
): string | { trackId: string; displaySnapshot: Record<string, unknown> } {
  const snapshot = alignments.has(id) ? pairsDisplaySnapshot(mode) : {};
  return Object.keys(snapshot).length ? { trackId: id, displaySnapshot: snapshot } : id;
}
