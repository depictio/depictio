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
