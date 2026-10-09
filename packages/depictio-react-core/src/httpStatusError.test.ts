import { afterEach, describe, expect, it, vi } from 'vitest';

import { HttpStatusError, fetchJob } from './api';

// A job poller has to tell "the server refuses this job" (stop) from a
// transient failure (ask again). Before HttpStatusError the status was folded
// into the message, so a 404 looked like a network blip and was polled forever.

function respond(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('HttpStatusError', () => {
  it('carries the status of a refused job read, with the API detail as message', async () => {
    respond(404, { detail: 'Job not found' });
    const err = await fetchJob('job-1').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(HttpStatusError);
    expect(err).toBeInstanceOf(Error);
    expect((err as HttpStatusError).status).toBe(404);
    expect((err as HttpStatusError).message).toBe('Job not found');
  });

  it('keeps the old message when the body has no detail', async () => {
    respond(503, { nope: true });
    const err = (await fetchJob('job-1').catch((e: unknown) => e)) as HttpStatusError;
    expect(err.status).toBe(503);
    expect(err.message).toBe('Failed to read job status: 503');
  });

  it('does not throw on success', async () => {
    respond(200, { job_id: 'job-1', kind: 'project.ingest', status: 'running' });
    await expect(fetchJob('job-1')).resolves.toMatchObject({ status: 'running' });
  });
});
