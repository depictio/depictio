/**
 * Follow one offloaded job until it stops, for the "Run ingestion" button.
 *
 * Kept out of the component so the two ways the old in-component loop went
 * wrong can be pinned by a test without a DOM: it kept polling after the
 * component unmounted, and it treated a refusal (a 404 for a job another user
 * started, or one that expired) as a blip and asked again every 10 s forever,
 * with the button stuck on "Starting…".
 */

import type { JobStatusResponse } from 'depictio-react-core';

export const TERMINAL_JOB_STATUSES: ReadonlySet<string> = new Set([
  'success',
  'failed',
  'cancelled',
]);

/** How following ended, unless the caller stopped it first. */
export type JobFollowEnd =
  | { kind: 'finished'; job: JobStatusResponse }
  /** The server refused to report the job. It may well still be running. */
  | { kind: 'refused'; status: number; message: string };

export interface FollowJobOptions {
  fetchJob: (jobId: string) => Promise<JobStatusResponse>;
  onUpdate: (job: JobStatusResponse) => void;
  onEnd: (end: JobFollowEnd) => void;
  firstDelayMs?: number;
  /** Wait after a failure worth retrying (network, 5xx). */
  retryDelayMs?: number;
}

/** The status of a 4xx that asking again will not change, else null. 408 and
 *  429 are 4xx too, but they mean "not now" rather than "no". */
export function refusalStatus(err: unknown): number | null {
  const status = (err as { status?: unknown } | null)?.status;
  if (typeof status !== 'number' || status < 400 || status >= 500) return null;
  return status === 408 || status === 429 ? null : status;
}

/**
 * Poll `jobId` until it reaches a terminal state or the server refuses it.
 * Returns `stop`: after it is called nothing is fetched or reported, including
 * the answer to a request already in flight.
 */
export function followJob(jobId: string, options: FollowJobOptions): () => void {
  const { fetchJob, onUpdate, onEnd, firstDelayMs = 1500, retryDelayMs = 10_000 } = options;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const tick = async () => {
    timer = null;
    let delayMs = retryDelayMs;
    try {
      const job = await fetchJob(jobId);
      if (stopped) return;
      onUpdate(job);
      if (TERMINAL_JOB_STATUSES.has(job.status)) {
        onEnd({ kind: 'finished', job });
        return;
      }
      // The server says how long to wait; reading it from the response rather
      // than from component state avoids a stale closure.
      delayMs = Math.max(1, job.poll_after_seconds ?? 3) * 1000;
    } catch (err) {
      if (stopped) return;
      const status = refusalStatus(err);
      if (status != null) {
        onEnd({
          kind: 'refused',
          status,
          message: err instanceof Error ? err.message : String(err),
        });
        return;
      }
      // A transient failure is not a failed ingestion: keep asking.
    }
    timer = setTimeout(tick, delayMs);
  };

  timer = setTimeout(tick, firstDelayMs);
  return () => {
    stopped = true;
    if (timer != null) clearTimeout(timer);
    timer = null;
  };
}
