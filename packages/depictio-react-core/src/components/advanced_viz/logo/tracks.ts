/**
 * Vertical tracks of the logo panel: which lanes belong to a track the reader
 * can hide or collapse, and the one function that stacks them. Pure,
 * unit-tested in `tracks.test.ts`.
 *
 * A track is a run of neighbouring lanes (`consensus` is the consensus, RF and
 * CS rows; `insert` the insert probability and length strips; `hits` the
 * coverage area and the hit bars). The logo stacks themselves are no track:
 * they are never hidden or collapsed.
 */

export type TrackKey = 'consensus' | 'insert' | 'occupancy' | 'hits' | 'ruler';

/** Stable names, top to bottom; the values `hidden_tracks` / `collapsed_tracks` take. */
export const TRACK_KEYS: readonly TrackKey[] = ['consensus', 'insert', 'occupancy', 'hits', 'ruler'];

export const TRACK_LABELS: Readonly<Record<TrackKey, string>> = {
  consensus: 'Consensus rows',
  insert: 'Insert rows',
  occupancy: 'Occupancy',
  hits: 'Hits',
  ruler: 'Ruler',
};

/** Height of a collapsed track: a thin strip that still carries its name. */
export const COLLAPSED_TRACK_PX = 10;

export type TrackState = 'shown' | 'collapsed' | 'hidden';

export function isTrackKey(value: unknown): value is TrackKey {
  return typeof value === 'string' && (TRACK_KEYS as readonly string[]).includes(value);
}

/** Known track names of a persisted list, in track order, without repeats. */
export function cleanTracks(value: unknown): TrackKey[] {
  if (!Array.isArray(value)) return [];
  const set = new Set(value.filter(isTrackKey));
  return TRACK_KEYS.filter((t) => set.has(t));
}

/** Hidden wins over collapsed; a lane outside any track is always shown. */
export function trackState(
  track: TrackKey | null,
  hidden: ReadonlySet<TrackKey>,
  collapsed: ReadonlySet<TrackKey>,
): TrackState {
  if (track == null) return 'shown';
  if (hidden.has(track)) return 'hidden';
  return collapsed.has(track) ? 'collapsed' : 'shown';
}

export interface StackInput {
  /** Lane name, passed through. */
  lane: string;
  /** Track the lane belongs to; null for a lane that is never hidden. */
  track: TrackKey | null;
  /** Natural height, CSS px. */
  h: number;
}

export interface StackSlot {
  /** The lane's name, or `strip` for a collapsed track. */
  lane: string;
  track: TrackKey | null;
  y: number;
  h: number;
  collapsed: boolean;
}

export interface TrackStack {
  slots: StackSlot[];
  total: number;
}

/**
 * Stack lanes top to bottom. Consecutive lanes of one track form a group: a
 * hidden group is left out, a collapsed one becomes a single strip of
 * `collapsedPx`, and a shown one keeps its lanes. Lanes of no height are
 * skipped, and a group of none draws nothing (not even a strip).
 */
export function stackTracks(
  inputs: readonly StackInput[],
  hidden: ReadonlySet<TrackKey>,
  collapsed: ReadonlySet<TrackKey>,
  collapsedPx: number = COLLAPSED_TRACK_PX,
): TrackStack {
  const slots: StackSlot[] = [];
  let y = 0;
  let i = 0;
  while (i < inputs.length) {
    const track = inputs[i].track;
    let j = i + 1;
    while (track != null && j < inputs.length && inputs[j].track === track) j++;
    const group = inputs.slice(i, j).filter((x) => x.h > 0);
    i = j;
    if (!group.length) continue;
    const state = trackState(track, hidden, collapsed);
    if (state === 'hidden') continue;
    if (state === 'collapsed') {
      slots.push({ lane: 'strip', track, y, h: collapsedPx, collapsed: true });
      y += collapsedPx;
      continue;
    }
    for (const lane of group) {
      slots.push({ lane: lane.lane, track: lane.track, y, h: lane.h, collapsed: false });
      y += lane.h;
    }
  }
  return { slots, total: y };
}

/** A track with its extent in the stack (a strip when collapsed). */
export interface TrackSpan {
  track: TrackKey;
  y: number;
  h: number;
  collapsed: boolean;
}

/** One span per track present in the stack, in order. */
export function trackSpans(slots: readonly StackSlot[]): TrackSpan[] {
  const spans: TrackSpan[] = [];
  for (const s of slots) {
    if (s.track == null) continue;
    const last = spans[spans.length - 1];
    if (last && last.track === s.track) {
      last.h = s.y + s.h - last.y;
    } else {
      spans.push({ track: s.track, y: s.y, h: s.h, collapsed: s.collapsed });
    }
  }
  return spans;
}
