/**
 * How "What's new" shows itself on the figures and cards (#1397).
 *
 *  - overlay  every changed figure marks what is new in place (rings, dimmed
 *             old points, faded unchanged traces);
 *  - split    the new runs against the runs the reader had seen, as two
 *             selection groups on the run column every Delta row carries
 *             (`depictio_run_id`): figures split into one panel per side and
 *             keep their own colours, cards compare the two sides.
 *
 * The split groups are virtual: held by the change marks, never written to the
 * reader's saved groups and never applied as a filter.
 *
 * Pure and free of React so `pnpm run check:changes` can run the real code.
 */
import type { DashboardChangeSet, GroupRenderDef } from 'depictio-react-core';

export type NewsView = 'off' | 'overlay' | 'split';

/** Written by the CLI on every Delta row: the run the row came from. */
export const RUN_COLUMN = 'depictio_run_id';

export interface NewsSplit {
  groups: GroupRenderDef[];
  /** False when both sides are named: no row is left over. */
  showOther: boolean;
}

/**
 * The two sides of the split, or null when nothing came as a new run (a
 * re-ingested run changes values in place: only Before | Now can show that).
 * MultiQC changes carry no `seen_run_tags`, their rows no run column.
 */
export function newsSplitGroups(
  cs: DashboardChangeSet | null | undefined,
  colors: { fresh: string; seen: string },
): NewsSplit | null {
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
    {
      name: freshTags.length === 1 ? `New: ${freshTags[0]}` : `New: ${freshTags.length} runs`,
      column_name: RUN_COLUMN,
      values: freshTags,
      color: colors.fresh,
    },
  ];
  if (seen.size > 0) {
    groups.push({ name: 'Seen before', column_name: RUN_COLUMN, values: [...seen].sort(), color: colors.seen });
  }
  return { groups, showOther: seen.size === 0 };
}
