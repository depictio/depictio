/**
 * Shared plumbing for an async, worker-side ingestion run.
 *
 * `POST /projects/refresh_manifest` and `POST /projects/from_run` both hand
 * back a `run_id` that is read through the same poll endpoint, so the
 * "Refresh data" panel and the "From a run folder" flow watch a run in
 * exactly the same way: poll every `POLL_INTERVAL_MS`, stop once no row is
 * queued or running any more, give up after `MAX_POLL_MS` or after
 * `MAX_CONSECUTIVE_POLL_ERRORS` failed polls in a row.
 *
 * The wording of the two give-up messages is left to the caller: each screen
 * says where the outcome shows up once its watcher stops.
 */

import { useEffect, useRef, useState } from 'react';

import { getManifestRefreshRun } from 'depictio-react-core';
import type { ManifestRefreshReport, ManifestRefreshStatus } from 'depictio-react-core';

export const POLL_INTERVAL_MS = 2_000;
/** Give up polling after this long; the run keeps going server-side. */
export const MAX_POLL_MS = 30 * 60 * 1_000;
/** Transient poll failures tolerated before a watcher stops and reports. */
export const MAX_CONSECUTIVE_POLL_ERRORS = 3;

/** Visual treatment per run status. Colors are Mantine palette names (theme
 *  tokens), not literals, mirroring IngestionReportPanel. The key order is
 *  the order `summarizeManifestRun` lists its counts in. */
export const MANIFEST_RUN_STATUS_META: Record<
  ManifestRefreshStatus,
  { color: string; icon: string; label: string }
> = {
  ingested: { color: 'green', icon: 'mdi:check-circle', label: 'Ingested' },
  planned: { color: 'blue', icon: 'mdi:clock-outline', label: 'Planned' },
  dispatched: { color: 'blue', icon: 'mdi:tray-arrow-down', label: 'Queued' },
  running: { color: 'blue', icon: 'mdi:progress-clock', label: 'Running' },
  failed: { color: 'red', icon: 'mdi:alert-circle', label: 'Failed' },
  skipped: { color: 'gray', icon: 'mdi:minus-circle-outline', label: 'Skipped' },
};

/** A report is final once no row is still queued for, or running on, a
 *  worker. The poll endpoint has no run-level status field, so this is the
 *  only terminal signal a client gets. */
export function isManifestRunTerminal(report: ManifestRefreshReport): boolean {
  return report.refreshed.every(
    (entry) => entry.status !== 'dispatched' && entry.status !== 'running',
  );
}

export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1_000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/** Milliseconds since `startedAt`, re-rendering once a second while `active`
 *  and frozen at `finishedAt - startedAt` once the run stops. Reads
 *  `Date.now()` at render time rather than caching it in state, so there is
 *  nothing to reset when a new `startedAt` arrives. */
export function useElapsedMs(
  active: boolean,
  startedAt: number | null,
  finishedAt: number | null,
): number {
  const [, forceTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => forceTick((t) => t + 1), 1_000);
    return () => window.clearInterval(id);
  }, [active]);
  return startedAt == null ? 0 : (finishedAt ?? Date.now()) - startedAt;
}

/** "3 ingested, 1 failed" style summary of the per-collection statuses. */
export function summarizeManifestRun(report: ManifestRefreshReport): string {
  const counts = new Map<ManifestRefreshStatus, number>();
  for (const entry of report.refreshed) {
    counts.set(entry.status, (counts.get(entry.status) ?? 0) + 1);
  }
  const parts: string[] = [];
  (Object.keys(MANIFEST_RUN_STATUS_META) as ManifestRefreshStatus[]).forEach((status) => {
    const n = counts.get(status);
    if (n) parts.push(`${n} ${MANIFEST_RUN_STATUS_META[status].label.toLowerCase()}`);
  });
  return parts.length > 0 ? parts.join(', ') : 'no collections refreshed';
}

export interface ManifestRunPollOptions {
  /** Run to watch. Null (or a null `startedAt`) polls nothing. */
  runId: string | null;
  /** When the run started, for the give-up deadline. */
  startedAt: number | null;
  /** Called with every successful poll response. */
  onReport: (report: ManifestRefreshReport) => void;
  /** Called once when the loop stops, with the reason: null when the run
   *  reached a terminal state, otherwise the message to show the user. */
  onStop: (error: string | null) => void;
  /** Message when the poll itself kept failing, given the last error. */
  pollErrorMessage: (err: Error) => string;
  /** Message when the deadline passed with the run still going. */
  timeoutMessage: string;
}

/** Poll `runId` until it is terminal, the deadline passes, or the poll itself
 *  keeps failing. Cleanup cancels the pending timer and drops any response
 *  that lands after unmount or after a new run replaced this one. */
export function useManifestRunPoll({
  runId,
  startedAt,
  onReport,
  onStop,
  pollErrorMessage,
  timeoutMessage,
}: ManifestRunPollOptions): void {
  // Handlers live in a ref so a caller that re-creates them on every render
  // does not restart the loop: the run itself is the only dependency.
  const handlers = useRef({ onReport, onStop, pollErrorMessage, timeoutMessage });
  useEffect(() => {
    handlers.current = { onReport, onStop, pollErrorMessage, timeoutMessage };
  });

  useEffect(() => {
    if (!runId || startedAt == null) return;
    let cancelled = false;
    let timer: number | undefined;
    let consecutiveErrors = 0;
    const tick = async () => {
      let next: ManifestRefreshReport | null = null;
      try {
        next = await getManifestRefreshRun(runId);
        consecutiveErrors = 0;
      } catch (err) {
        if (cancelled) return;
        consecutiveErrors += 1;
        if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
          handlers.current.onStop(handlers.current.pollErrorMessage(err as Error));
          return;
        }
      }
      if (cancelled) return;
      if (next) {
        handlers.current.onReport(next);
        if (isManifestRunTerminal(next)) {
          handlers.current.onStop(null);
          return;
        }
      }
      if (Date.now() - startedAt >= MAX_POLL_MS) {
        handlers.current.onStop(handlers.current.timeoutMessage);
        return;
      }
      timer = window.setTimeout(tick, POLL_INTERVAL_MS);
    };
    timer = window.setTimeout(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runId, startedAt]);
}
