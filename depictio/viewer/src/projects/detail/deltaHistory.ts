/**
 * Pure rules behind DeltaVersionHistory, kept out of the component so they
 * can be tested without a DOM.
 */

import type { DeltaVersionEntry } from 'depictio-react-core';

import { parseTs } from '../../monitoring/format';

/** Entries asked for. The API cuts the merged list at this many, and puts
 *  depictio's own records after the Delta commits, so a full page may have
 *  lost some of them: the panel says so rather than looking complete. */
export const HISTORY_LIMIT = 20;

export function timestampOf(entry: DeltaVersionEntry): string | null | undefined {
  return entry.timestamp ?? entry.aggregation_time;
}

/** A row from depictio's own record of a write that the API could not match to
 *  a commit in the Delta log it read. It carries no `version`: either its
 *  commit was not among those read (older than the window, or the log could
 *  not be read at all), or the write predates depictio recording commit
 *  versions. Nothing in the row says which, so the label claims neither. */
export function isUnmatchedRecord(entry: DeltaVersionEntry): boolean {
  return entry.origin === 'mongo' || entry.version == null;
}

/** Newest first. The merged response appends depictio's records after the
 *  Delta commits, so it is not ordered by time; rows with no usable time go
 *  last, in the order they came. */
export function orderHistory(versions: DeltaVersionEntry[]): DeltaVersionEntry[] {
  return [...versions].sort((a, b) => {
    const ta = parseTs(timestampOf(a));
    const tb = parseTs(timestampOf(b));
    if (Number.isNaN(ta) && Number.isNaN(tb)) return (b.version ?? -1) - (a.version ?? -1);
    if (Number.isNaN(ta)) return 1;
    if (Number.isNaN(tb)) return -1;
    return tb - ta;
  });
}

export interface HistorySummary {
  /** Rows matched to a Delta commit. */
  commits: number;
  /** depictio records with no matching commit; never counted as commits. */
  unmatched: number;
  /** The API cut rows off this page (its `truncated` flag), or, from a server
   *  that does not send the flag, the response filled the page. */
  mayBeTruncated: boolean;
}

export function summarizeHistory(
  versions: DeltaVersionEntry[],
  limit: number = HISTORY_LIMIT,
  truncated?: boolean,
): HistorySummary {
  const unmatched = versions.filter(isUnmatchedRecord).length;
  return {
    commits: versions.length - unmatched,
    unmatched,
    mayBeTruncated: truncated ?? versions.length >= limit,
  };
}

// ── runs and lineage (epic #1399) ───────────────────────────────────────────

/** A comma list from commit metadata, without the "+N more" cap marker. */
function metaList(entry: DeltaVersionEntry, key: string): { items: string[]; capped: boolean } {
  const raw = entry.metadata?.[key];
  if (!raw) return { items: [], capped: false };
  const parts = raw
    .split(',')
    .map((p) => p.trim())
    .filter(Boolean);
  const isCap = (p: string) => /^\+\d+ more$/.test(p);
  return { items: parts.filter((p) => !isCap(p)), capped: parts.some(isCap) };
}

export type RunScope = 'run' | 'aggregate' | 'pipeline';

/** One colour per scope wherever it shows (Runs tab, history, produced). */
export { SCOPE_COLOR } from '../../changes/palette';

export interface CommitLineage {
  /** How the commit relates to the runs, when a recipe wrote it. */
  scope: RunScope | null;
  /** The runs whose rows this commit wrote. */
  runTags: string[];
  /** The runs a recomputed collection read (an aggregate reads them all). */
  computedFrom: string[];
  /** The collections it read, at the version it read them. */
  inputs: { tag: string; version: string }[];
  capped: boolean;
}

export function commitLineage(entry: DeltaVersionEntry): CommitLineage {
  const runs = metaList(entry, 'depictio.run_tags');
  const from = metaList(entry, 'depictio.computed_from');
  const rawScope = entry.metadata?.['depictio.run_scope'];
  const scope =
    rawScope === 'run' || rawScope === 'aggregate' || rawScope === 'pipeline' ? rawScope : null;
  const inputs = metaList(entry, 'depictio.inputs').items.map((item) => {
    const at = item.lastIndexOf('@');
    return at < 0
      ? { tag: item, version: '' }
      : { tag: item.slice(0, at), version: item.slice(at + 1) };
  });
  return {
    scope,
    runTags: runs.items,
    computedFrom: from.items,
    inputs,
    capped: runs.capped || from.capped,
  };
}

/** Every run named by the history, for the run filter. */
export function historyRuns(entries: DeltaVersionEntry[]): string[] {
  const seen = new Set<string>();
  for (const entry of entries) {
    const { runTags, computedFrom } = commitLineage(entry);
    for (const tag of [...runTags, ...computedFrom]) seen.add(tag);
  }
  return [...seen].sort();
}

/** The commits that touched ``run``: wrote its rows, or recomputed from it.
 *  A commit that names no run (or whose list was capped) is kept: nothing
 *  says it did not. */
export function entriesForRun(entries: DeltaVersionEntry[], run: string | null): DeltaVersionEntry[] {
  if (!run) return entries;
  return entries.filter((entry) => {
    const { runTags, computedFrom, capped } = commitLineage(entry);
    if (runTags.includes(run) || computedFrom.includes(run)) return true;
    return capped || (runTags.length === 0 && computedFrom.length === 0);
  });
}

/** One line for a recipe commit's scope, or null for a file-backed one. */
export function scopeLabel(lineage: CommitLineage): string | null {
  if (lineage.scope === 'aggregate') {
    const n = lineage.computedFrom.length;
    return n > 1 ? `recomputed over ${n} runs` : 'mixes samples';
  }
  if (lineage.scope === 'pipeline') return 'per run (pipeline statistic)';
  if (lineage.scope === 'run') return 'per run';
  return null;
}
