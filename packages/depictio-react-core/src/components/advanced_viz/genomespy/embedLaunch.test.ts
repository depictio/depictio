import { describe, expect, it, vi } from 'vitest';

import { hasMarkEvents, launchWithRetry, toError } from './embedLaunch';

const noSleep = async () => undefined;

describe('hasMarkEvents', () => {
  it('is true when the root view exposes subscribable marks', () => {
    expect(hasMarkEvents({ views: { root: () => ({ marks: { subscribe: () => undefined } }) } })).toBe(true);
  });

  it('is false for the half-built embed of a failed launch', () => {
    // GenomeSpy 0.88: no interaction controller, so `marks` is missing or throws.
    expect(hasMarkEvents({ views: { root: () => ({}) } })).toBe(false);
    expect(
      hasMarkEvents({
        views: {
          root: () => {
            throw new TypeError("Cannot read properties of undefined (reading 'subscribeMarkEvent')");
          },
        },
      }),
    ).toBe(false);
    expect(hasMarkEvents({})).toBe(false);
  });
});

describe('launchWithRetry', () => {
  it('retries a failed first launch once and returns the clean one', async () => {
    const discard = vi.fn();
    const attempt = vi
      .fn()
      .mockResolvedValueOnce({ result: 'a', failure: new Error('layout race') })
      .mockResolvedValueOnce({ result: 'b', failure: null });
    const out = await launchWithRetry(attempt, discard, { sleep: noSleep });
    expect(out).toEqual({ result: 'b', failure: null });
    expect(discard).toHaveBeenCalledTimes(1);
    expect(discard).toHaveBeenCalledWith('a');
  });

  it('keeps the original message when the retry fails too', async () => {
    const attempt = vi
      .fn()
      .mockResolvedValueOnce({ result: 'a', failure: new Error('first') })
      .mockResolvedValueOnce({ result: 'b', failure: new Error('second') });
    const out = await launchWithRetry(attempt, vi.fn(), { sleep: noSleep });
    expect(attempt).toHaveBeenCalledTimes(2);
    expect(out.failure?.message).toBe('second');
    expect(out.result).toBe('b');
  });

  it('does not retry a clean launch or a cancelled effect', async () => {
    const ok = vi.fn().mockResolvedValue({ result: 'a', failure: null });
    await launchWithRetry(ok, vi.fn(), { sleep: noSleep });
    expect(ok).toHaveBeenCalledOnce();

    const bad = vi.fn().mockResolvedValue({ result: 'a', failure: new Error('x') });
    await launchWithRetry(bad, vi.fn(), { sleep: noSleep, isCancelled: () => true });
    expect(bad).toHaveBeenCalledOnce();
  });
});

describe('toError', () => {
  it('keeps an Error and wraps anything else', () => {
    const e = new Error('boom');
    expect(toError(e)).toBe(e);
    expect(toError('text').message).toBe('text');
  });
});
