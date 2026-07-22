/**
 * Bounded concurrency for component render fetches.
 *
 * Every renderer owns its own `useEffect` fetch, so opening a dashboard fires
 * one request per in-view component simultaneously. `useInView` already keeps
 * off-screen components quiet, but a dense dashboard still bursts 15-25 render
 * POSTs at once — all of which queue behind the same API workers. The result is
 * that the component the user is actually looking at finishes last, because it
 * shares the pool with everything else that happened to mount with it.
 *
 * Limiting in-flight requests doesn't reduce total work, it reorders it: the
 * first few components paint quickly instead of everything painting at the end.
 *
 * The limit is deliberately modest. Browsers cap concurrent connections per
 * origin (~6 for HTTP/1.1) anyway, so a higher number just moves the queue from
 * here into the browser where we can't prioritise it.
 */

const DEFAULT_CONCURRENCY = 4;

interface Waiter {
  resolve: () => void;
  priority: number;
  seq: number;
}

let limit = DEFAULT_CONCURRENCY;
let active = 0;
let seqCounter = 0;
const waiting: Waiter[] = [];

function pump(): void {
  while (active < limit && waiting.length > 0) {
    // Lowest priority value first; ties broken by arrival order so a component
    // can never be starved by a steady trickle of equal-priority peers.
    let bestIndex = 0;
    for (let i = 1; i < waiting.length; i += 1) {
      const w = waiting[i];
      const best = waiting[bestIndex];
      if (w.priority < best.priority || (w.priority === best.priority && w.seq < best.seq)) {
        bestIndex = i;
      }
    }
    const [next] = waiting.splice(bestIndex, 1);
    active += 1;
    next.resolve();
  }
}

/**
 * Run `task` once a slot is free.
 *
 * `priority` orders the queue — pass the component's vertical position so the
 * top of the dashboard resolves first; equal priorities keep arrival order.
 *
 * The slot is released in a `finally`, so a rejected task frees its slot like a
 * successful one. The rejection itself is passed through untouched: callers
 * already handle fetch failures and must keep seeing them.
 */
export async function enqueueFetch<T>(task: () => Promise<T>, priority = 0): Promise<T> {
  await new Promise<void>((resolve) => {
    waiting.push({ resolve, priority, seq: seqCounter++ });
    pump();
  });
  try {
    return await task();
  } finally {
    active -= 1;
    pump();
  }
}

/** Override the concurrency limit (tests, or a deployment that wants it wider). */
export function setFetchConcurrency(n: number): void {
  limit = Math.max(1, n);
  pump();
}

/** Introspection for tests and debugging. */
export function fetchQueueState(): { active: number; waiting: number; limit: number } {
  return { active, waiting: waiting.length, limit };
}

/** Reset to a clean state. Tests only — there is no reason to call this in app code. */
export function __resetFetchQueue(): void {
  limit = DEFAULT_CONCURRENCY;
  active = 0;
  seqCounter = 0;
  waiting.length = 0;
}
