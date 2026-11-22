import { afterEach, describe, expect, it, vi } from 'vitest';

import { realtimeAvailable, resetRealtimeAvailableForTests } from './realtime';

function serverSays(body: Record<string, unknown> | null, ok = true) {
  const fetchMock = vi.fn(async () => ({ ok, json: async () => body }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  resetRealtimeAvailableForTests();
});

describe('realtimeAvailable', () => {
  it('is false when the server says events are off', async () => {
    serverSays({ auth_mode: 'standard', user: null, events_enabled: false });
    expect(await realtimeAvailable()).toBe(false);
  });

  it('is true when the server says events are on', async () => {
    serverSays({ auth_mode: 'standard', user: null, events_enabled: true });
    expect(await realtimeAvailable()).toBe(true);
  });

  it('keeps trying on an older backend that does not say', async () => {
    serverSays({ auth_mode: 'standard', user: null });
    expect(await realtimeAvailable()).toBe(true);
  });

  it('keeps trying when the probe fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('network down');
      }),
    );
    expect(await realtimeAvailable()).toBe(true);
  });

  it('asks the server once per page', async () => {
    const fetchMock = serverSays({ auth_mode: 'standard', user: null, events_enabled: false });
    await Promise.all([realtimeAvailable(), realtimeAvailable(), realtimeAvailable()]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
