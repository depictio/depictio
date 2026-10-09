// @vitest-environment jsdom
/**
 * The monitoring polling hooks.
 *
 * - `useLivePolling` applies every live event. It used to take the latest
 *   event as a state value, so several pushes landing in one tick were batched
 *   into one render and all but the last were lost.
 * - An event that arrives while a request is in flight is applied to that
 *   request's response rather than overwritten by it.
 * - A mount costs one request: not two under StrictMode, and not two when a
 *   pane remounts after some live pushes.
 *
 * Run like tests/builder (the viewer package has no vitest of its own):
 *   pnpm --filter depictio-react-core exec vitest run --root ../../depictio/viewer tests/monitoring
 */
import { StrictMode, act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createLiveFeed,
  useLivePolling,
  usePolling,
  type LiveFeed,
  type PollingState,
} from '../../src/monitoring/usePolling';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

interface Row {
  id: string;
  n: number;
}
interface Bump {
  id: string;
}

/** Bump a known row; `null` ("can't apply") for an unknown one. */
function bump(rows: Row[] | null, event: Bump): Row[] | null {
  if (!rows) return null;
  const index = rows.findIndex((r) => r.id === event.id);
  if (index === -1) return null;
  return rows.map((r, i) => (i === index ? { ...r, n: r.n + 1 } : r));
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

let state: PollingState<Row[]> | null = null;

const LiveProbe = ({ load, feed }: { load: () => Promise<Row[]>; feed: LiveFeed<Bump> }) => {
  state = useLivePolling(load, false, feed, { patch: bump });
  return null;
};

const SignalProbe = ({ load, signal }: { load: () => Promise<Row[]>; signal: number }) => {
  state = usePolling(load, false, signal);
  return null;
};

let root: Root | null = null;

async function render(element: ReturnType<typeof createElement>) {
  if (!root) root = createRoot(document.createElement('div'));
  await act(async () => {
    root!.render(element);
  });
}

afterEach(async () => {
  await act(async () => {
    root?.unmount();
  });
  root = null;
  state = null;
});

describe('useLivePolling', () => {
  it('applies every event of a batch, not only the last', async () => {
    const load = vi.fn(async () => [
      { id: 'a', n: 0 },
      { id: 'b', n: 0 },
    ]);
    const feed = createLiveFeed<Bump>();
    await render(createElement(LiveProbe, { load, feed }));

    await act(async () => {
      feed.publish({ id: 'a' });
      feed.publish({ id: 'b' });
      feed.publish({ id: 'a' });
    });

    expect(state?.data).toEqual([
      { id: 'a', n: 2 },
      { id: 'b', n: 1 },
    ]);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('applies an event that arrived mid-request to that request\'s response', async () => {
    const response = deferred<Row[]>();
    const load = vi.fn(() => response.promise);
    const feed = createLiveFeed<Bump>();
    await render(createElement(LiveProbe, { load, feed }));

    await act(async () => {
      feed.publish({ id: 'a' });
    });
    await act(async () => {
      response.resolve([{ id: 'a', n: 0 }]);
    });

    expect(state?.data).toEqual([{ id: 'a', n: 1 }]);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('refetches once for a burst of events about an unknown row', async () => {
    const load = vi
      .fn<() => Promise<Row[]>>()
      .mockResolvedValueOnce([{ id: 'a', n: 0 }])
      .mockResolvedValue([
        { id: 'a', n: 0 },
        { id: 'c', n: 0 },
      ]);
    const feed = createLiveFeed<Bump>();
    await render(createElement(LiveProbe, { load, feed }));

    await act(async () => {
      feed.publish({ id: 'c' });
      feed.publish({ id: 'c' });
      feed.publish({ id: 'c' });
    });

    // The first event starts the refetch; the other two are held and applied
    // to its response, which knows the row.
    expect(load).toHaveBeenCalledTimes(2);
    expect(state?.data).toEqual([
      { id: 'a', n: 0 },
      { id: 'c', n: 2 },
    ]);
  });

  it('fetches once on a StrictMode mount', async () => {
    const load = vi.fn(async () => [{ id: 'a', n: 0 }]);
    const feed = createLiveFeed<Bump>();
    await render(createElement(StrictMode, null, createElement(LiveProbe, { load, feed })));

    expect(load).toHaveBeenCalledTimes(1);
    await act(async () => {
      feed.publish({ id: 'a' });
    });
    // Subscribed once, not twice: the event is applied once.
    expect(state?.data).toEqual([{ id: 'a', n: 1 }]);
  });

  it('stops listening once unmounted', async () => {
    const load = vi.fn(async () => [{ id: 'a', n: 0 }]);
    const feed = createLiveFeed<Bump>();
    await render(createElement(LiveProbe, { load, feed }));
    await act(async () => {
      root?.unmount();
    });
    root = null;

    await act(async () => {
      feed.publish({ id: 'unknown' });
    });
    expect(load).toHaveBeenCalledTimes(1);
  });
});

describe('usePolling', () => {
  it('fetches once when remounted after some live pushes', async () => {
    const load = vi.fn(async () => [{ id: 'a', n: 0 }]);
    await render(createElement(SignalProbe, { load, signal: 7 }));
    expect(load).toHaveBeenCalledTimes(1);

    await render(createElement(SignalProbe, { load, signal: 8 }));
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('fetches once on a StrictMode mount', async () => {
    const load = vi.fn(async () => [{ id: 'a', n: 0 }]);
    await render(createElement(StrictMode, null, createElement(SignalProbe, { load, signal: 3 })));
    expect(load).toHaveBeenCalledTimes(1);
  });
});
