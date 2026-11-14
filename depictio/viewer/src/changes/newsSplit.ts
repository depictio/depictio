/**
 * How "What's new" shows itself on the figures and cards (#1397).
 *
 *  - overlay  one panel per figure: the rows of the new runs in the
 *             dashboard's colour, those of the runs seen before in grey
 *             (Delta collections, on `depictio_run_id`); a MultiQC figure
 *             fades the samples seen before. A collection rewritten in place
 *             (no new run) is marked by the figure's own before/after rings;
 *  - split    what is new against what the reader had seen, side by side:
 *               * Delta collections, on the run column every CLI row carries
 *                 (`depictio_run_id`): figures split into one panel per side
 *                 and keep their own colours, cards compare the two sides;
 *               * MultiQC collections, on their samples: each MultiQC figure
 *                 is drawn once for the new samples, once for those seen;
 *  - new      only the new side of the split: the same groups, the first one
 *             applied as a filter, so everything else is hidden.
 *
 * Each of them can follow one new run instead of all of them (`focus`): that
 * run is the new side, every other run, new or seen, the other one.
 *
 * The split groups are virtual: held by the change marks, never written to the
 * reader's saved groups and never applied as a filter.
 *
 * Pure and free of React so `pnpm run check:changes` can run the real code.
 */
import type { DashboardChangeSet, DataChange, GroupRenderDef } from 'depictio-react-core';

export type NewsView = 'off' | 'overlay' | 'split' | 'new';

/** Written by the CLI on every Delta row: the run the row came from. */
export const RUN_COLUMN = 'depictio_run_id';
/** The MultiQC sample column the render route filters on. */
export const SAMPLE_COLUMN = 'sample';

export interface NewsSplit {
  /** New runs against the runs seen, on `RUN_COLUMN`. Empty when no Delta
   *  collection gained a run. */
  groups: GroupRenderDef[];
  /** False when both sides are named: no row is left over. */
  showOther: boolean;
  /** MultiQC collections, by `dc_id`: new samples against the samples seen. */
  samples: Record<string, GroupRenderDef[]>;
  /** Set by the change marks: both sides side by side, coloured in one
   *  panel, or the new side alone. */
  mode?: 'split' | 'overlay' | 'new';
}

/** Both sides in one panel ("Overlay"): the run groups only, MultiQC keeps
 *  its own fade (its renderer reads the change marks, not these groups). */
export function overlaySides(split: NewsSplit): NewsSplit {
  return { ...split, samples: {}, mode: 'overlay' };
}

/** The view a family's tabs share for the session: chosen on one tab, carried
 *  to the next (a tab switch reloads the page). */
const VIEW_KEY = 'depictio-news-view:';
const VIEWS: readonly NewsView[] = ['off', 'overlay', 'split', 'new'];

export function readSharedView(familyId: string): NewsView | null {
  try {
    const v = sessionStorage.getItem(VIEW_KEY + familyId);
    return v && (VIEWS as readonly string[]).includes(v) ? (v as NewsView) : null;
  } catch {
    return null;
  }
}

export function writeSharedView(familyId: string, view: NewsView): void {
  try {
    if (view === 'off') sessionStorage.removeItem(VIEW_KEY + familyId);
    else sessionStorage.setItem(VIEW_KEY + familyId, view);
  } catch {
    // Private mode or blocked storage: the view stays on this tab.
  }
}

/** The new side alone of each split ("New only"): the first group is always it. */
export function newSideOnly(split: NewsSplit): NewsSplit {
  const samples: Record<string, GroupRenderDef[]> = {};
  for (const [dcId, groups] of Object.entries(split.samples)) samples[dcId] = groups.slice(0, 1);
  return { groups: split.groups.slice(0, 1), showOther: false, samples, mode: 'new' };
}

export interface SplitColors {
  fresh: string;
  seen: string;
}

const freshName = (tags: string[], fallback: string): string =>
  tags.length === 1 ? `New: ${tags[0]}` : tags.length > 1 ? `New: ${tags.length} runs` : fallback;

function runGroups(cs: DashboardChangeSet | null | undefined, colors: SplitColors, focus: string | null) {
  const fresh = new Set<string>();
  const seen = new Set<string>();
  for (const d of cs?.data ?? []) {
    if (d.kind !== 'refreshed' || !Array.isArray(d.seen_run_tags)) continue;
    for (const t of d.new_run_tags) fresh.add(t);
    for (const t of d.seen_run_tags) seen.add(t);
  }
  for (const t of fresh) seen.delete(t);
  if (fresh.size === 0) return null;
  // One run in focus: the other new runs join the runs seen, as "other runs".
  let others: string[] = [];
  if (focus && fresh.has(focus)) {
    others = [...fresh].filter((t) => t !== focus);
    for (const t of others) seen.add(t);
    fresh.clear();
    fresh.add(focus);
  }
  const freshTags = [...fresh].sort();
  const groups: GroupRenderDef[] = [
    { name: freshName(freshTags, 'New'), column_name: RUN_COLUMN, values: freshTags, color: colors.fresh },
  ];
  if (seen.size > 0) {
    groups.push({
      name: others.length ? 'Other runs' : 'Seen before',
      column_name: RUN_COLUMN,
      values: [...seen].sort(),
      color: colors.seen,
    });
  }
  return { groups, showOther: seen.size === 0 };
}

/** The new runs of each collection, narrowed to the one in focus (a
 *  collection that did not gain it drops out). */
export function focusedRuns(
  byDc: Record<string, string[]>,
  focus: string | null,
): Record<string, string[]> {
  if (!focus) return byDc;
  const out: Record<string, string[]> = {};
  for (const [dcId, runs] of Object.entries(byDc)) if (runs.includes(focus)) out[dcId] = [focus];
  return out;
}

/** The run in focus, shared by a family's tabs like the view. */
const FOCUS_KEY = 'depictio-news-run:';

export function readSharedFocus(familyId: string): string | null {
  try {
    return sessionStorage.getItem(FOCUS_KEY + familyId);
  } catch {
    return null;
  }
}

export function writeSharedFocus(familyId: string, run: string | null): void {
  try {
    if (run) sessionStorage.setItem(FOCUS_KEY + familyId, run);
    else sessionStorage.removeItem(FOCUS_KEY + familyId);
  } catch {
    // Private mode or blocked storage: the focus stays on this tab.
  }
}

/** Both sides of a MultiQC collection, or null when either is unknown or empty. */
function sampleGroups(d: DataChange, colors: SplitColors, focus: string | null): GroupRenderDef[] | null {
  const fresh = d.new_samples ?? [];
  const seen = d.seen_samples;
  if (d.kind !== 'refreshed' || !Array.isArray(seen)) return null;
  // The new samples are not filed by run: with one run in focus, only a
  // collection whose news is that run alone can be split.
  if (focus && d.new_run_tags.length > 0 && !(d.new_run_tags.length === 1 && d.new_run_tags[0] === focus)) {
    return null;
  }
  if (fresh.length === 0 || seen.length === 0) return null;
  // A truncated list would file the samples it left out under neither side.
  if ((d.new_sample_count ?? fresh.length) !== fresh.length) return null;
  return [
    {
      name: freshName([...d.new_run_tags].sort(), 'New samples'),
      column_name: SAMPLE_COLUMN,
      values: [...fresh].sort(),
      color: colors.fresh,
      dc_id: d.dc_id,
    },
    { name: 'Seen before', column_name: SAMPLE_COLUMN, values: [...seen].sort(), color: colors.seen, dc_id: d.dc_id },
  ];
}

/**
 * The sides of the split, or null when nothing can be split: no Delta
 * collection gained a run (a re-ingested run changes values in place: only
 * Before | Now shows that) and no MultiQC collection has both new samples and
 * samples seen before.
 */
export function newsSplitGroups(
  cs: DashboardChangeSet | null | undefined,
  colors: SplitColors,
  focus: string | null = null,
): NewsSplit | null {
  const newRuns = new Set((cs?.data ?? []).flatMap((d) => (d.kind === 'refreshed' ? d.new_run_tags : [])));
  const run = focus && newRuns.has(focus) ? focus : null;
  const runs = runGroups(cs, colors, run);
  const samples: Record<string, GroupRenderDef[]> = {};
  for (const d of cs?.data ?? []) {
    const groups = sampleGroups(d, colors, run);
    if (groups) samples[d.dc_id] = groups;
  }
  if (!runs && Object.keys(samples).length === 0) return null;
  return { groups: runs?.groups ?? [], showOther: runs?.showOther ?? false, samples };
}
