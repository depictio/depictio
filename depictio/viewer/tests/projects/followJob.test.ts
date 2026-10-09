/**
 * The "Run ingestion" button's job poller: it must stop when told to (the
 * component unmounted), and stop on a refusal instead of polling a 404 forever
 * with the button stuck on "Starting…".
 *
 * Run like tests/builder (the viewer package has no vitest of its own):
 *   pnpm --filter depictio-react-core exec vitest run --root ../../depictio/viewer tests/projects
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { JobStatusResponse } from 'depictio-react-core';

import { followJob, refusalStatus, type JobFollowEnd } from '../../src/projects/detail/followJob';

const job = (status: JobStatusResponse['status'], extra: Partial<JobStatusResponse> = {}) =>
  ({ job_id: 'j1', kind: 'project.ingest', status, poll_after_seconds: 2, ...extra }) as JobStatusResponse;

const httpError = (status: number, message = `HTTP ${status}`) =>
  Object.assign(new Error(message), { status });

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('refusalStatus', () => {
  it('stops on a 4xx', () => {
    expect(refusalStatus(httpError(404))).toBe(404);
    expect(refusalStatus(httpError(403))).toBe(403);
    expect(refusalStatus(httpError(401))).toBe(401);
  });

  it('keeps asking on "not now" 4xx, 5xx and network errors', () => {
    expect(refusalStatus(httpError(408))).toBeNull();
    expect(refusalStatus(httpError(429))).toBeNull();
    expect(refusalStatus(httpError(503))).toBeNull();
    expect(refusalStatus(new TypeError('Failed to fetch'))).toBeNull();
    expect(refusalStatus(null)).toBeNull();
  });
});

describe('followJob', () => {
  it('follows to a terminal status, then stops fetching', async () => {
    const fetchJob = vi
      .fn()
      .mockResolvedValueOnce(job('running'))
      .mockResolvedValueOnce(job('success'));
    const onUpdate = vi.fn();
    const onEnd = vi.fn();
    followJob('j1', { fetchJob, onUpdate, onEnd, firstDelayMs: 100 });

    await vi.advanceTimersByTimeAsync(100);
    expect(onUpdate).toHaveBeenLastCalledWith(job('running'));
    await vi.advanceTimersByTimeAsync(2000);
    expect(onEnd).toHaveBeenCalledWith({ kind: 'finished', job: job('success') });

    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchJob).toHaveBeenCalledTimes(2);
  });

  it('stops on a 404 and says so, instead of polling forever', async () => {
    const fetchJob = vi.fn().mockRejectedValue(httpError(404, 'Job not found'));
    const onEnd = vi.fn<(end: JobFollowEnd) => void>();
    followJob('j1', { fetchJob, onUpdate: vi.fn(), onEnd, firstDelayMs: 100 });

    await vi.advanceTimersByTimeAsync(100);
    expect(onEnd).toHaveBeenCalledWith({ kind: 'refused', status: 404, message: 'Job not found' });

    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(fetchJob).toHaveBeenCalledTimes(1);
  });

  it('retries a transient failure', async () => {
    const fetchJob = vi
      .fn()
      .mockRejectedValueOnce(httpError(502))
      .mockResolvedValueOnce(job('success'));
    const onEnd = vi.fn();
    followJob('j1', { fetchJob, onUpdate: vi.fn(), onEnd, firstDelayMs: 100, retryDelayMs: 500 });

    await vi.advanceTimersByTimeAsync(100);
    expect(onEnd).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(500);
    expect(onEnd).toHaveBeenCalledWith({ kind: 'finished', job: job('success') });
  });

  it('reports nothing once stopped, even for a request already in flight', async () => {
    let answer: (value: JobStatusResponse) => void = () => undefined;
    const fetchJob = vi.fn(
      () =>
        new Promise<JobStatusResponse>((resolve) => {
          answer = resolve;
        }),
    );
    const onUpdate = vi.fn();
    const onEnd = vi.fn();
    const stop = followJob('j1', { fetchJob, onUpdate, onEnd, firstDelayMs: 100 });

    await vi.advanceTimersByTimeAsync(100);
    expect(fetchJob).toHaveBeenCalledTimes(1);
    stop();
    answer(job('success'));
    await vi.advanceTimersByTimeAsync(60_000);

    expect(onUpdate).not.toHaveBeenCalled();
    expect(onEnd).not.toHaveBeenCalled();
    expect(fetchJob).toHaveBeenCalledTimes(1);
  });

  it('never starts when stopped before the first tick', async () => {
    const fetchJob = vi.fn().mockResolvedValue(job('running'));
    const stop = followJob('j1', { fetchJob, onUpdate: vi.fn(), onEnd: vi.fn(), firstDelayMs: 100 });
    stop();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchJob).not.toHaveBeenCalled();
  });
});
