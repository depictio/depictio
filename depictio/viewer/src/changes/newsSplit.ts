/**
 * How "What's new" shows itself on the figures and cards (#1397).
 *
 *  - overlay  every changed figure marks what is new in place (rings, dimmed
 *             old points, faded unchanged traces);
 *  - split    what is new against what the reader had seen, side by side:
 *               * Delta collections, on the run column every CLI row carries
 *                 (`depictio_run_id`): figures split into one panel per side
 *                 and keep their own colours, cards compare the two sides;
 *               * MultiQC collections, on their samples: each MultiQC figure
 *                 is drawn once for the new samples, once for those seen;
 *  - new      only the new side of the split: the same groups, the first one
 *             applied as a filter, so everything else is hidden.
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
  /** Set by the change marks: both sides, or the new side alone. */
  mode?: 'split' | 'new';
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

function runGroups(cs: DashboardChangeSet | null | undefined, colors: SplitColors) {
  const fresh = new Set<string>();
  const seen = new Set<string>();
  for (const d of cs?.data ?? []) {
    if (d.kind !== 'refreshed' || !Array.isArray(d.seen_run_tags)) continue;
    for (const t of d.new_run_tags) fresh.add(t);
    for (const t of d.seen_run_tags) seen.add(t);
  }
  for (const t of fresh) seen.delete(t);
  if (fresh.size === 0) return null;
  const freshTags = [...fresh].sort();
  const groups: GroupRenderDef[] = [
    { name: freshName(freshTags, 'New'), column_name: RUN_COLUMN, values: freshTags, color: colors.fresh },
  ];
  if (seen.size > 0) {
    groups.push({ name: 'Seen before', column_name: RUN_COLUMN, values: [...seen].sort(), color: colors.seen });
  }
  return { groups, showOther: seen.size === 0 };
}

/** Both sides of a MultiQC collection, or null when either is unknown or empty. */
function sampleGroups(d: DataChange, colors: SplitColors): GroupRenderDef[] | null {
  const fresh = d.new_samples ?? [];
  const seen = d.seen_samples;
  if (d.kind !== 'refreshed' || !Array.isArray(seen)) return null;
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
): NewsSplit | null {
  const runs = runGroups(cs, colors);
  const samples: Record<string, GroupRenderDef[]> = {};
  for (const d of cs?.data ?? []) {
    const groups = sampleGroups(d, colors);
    if (groups) samples[d.dc_id] = groups;
  }
  if (!runs && Object.keys(samples).length === 0) return null;
  return { groups: runs?.groups ?? [], showOther: runs?.showOther ?? false, samples };
}
