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
 *
 * ## Generations
 *
 * With a bounded queue, most of a filter round is *waiting*, not in flight: 25
 * components through 4 slots means ~21 requests that haven't touched the network
 * yet. If the user changes the filter again, those 21 are already answering a
 * question nobody is asking — but without a generation they would still run,
 * and the new round would queue behind them.
 *
 * `bumpFetchGeneration()` marks everything currently queued as stale and drops
 * it. That only covers requests still waiting; the handful already in flight
 * have to be cancelled by their caller's `AbortController`. The two are
 * complementary and both are needed.
 */

const DEFAULT_CONCURRENCY = 4;

/**
 * Rejection for a task dropped before it ever ran because its generation was
 * superseded. Callers must treat it like an abort — it is a normal outcome of
 * the user changing their mind, not a failure to surface.
 */
export class StaleFetchError extends Error {
  constructor(message = 'Fetch superseded by a newer generation') {
    super(message);
    this.name = 'StaleFetchError';
  }
}

/** True for both queue-level staleness and a `fetch()` aborted mid-flight. */
export function isStaleFetch(err: unknown): boolean {
  const name = (err as { name?: string } | null)?.name;
  return name === 'StaleFetchError' || name === 'AbortError';
}

interface Waiter {
  resolve: () => void;
  reject: (err: unknown) => void;
  priority: number;
  seq: number;
  generation: number;
}

let limit = DEFAULT_CONCURRENCY;
let active = 0;
let seqCounter = 0;
let generation = 0;
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
 * Invalidate everything currently queued and start a new generation.
 *
 * **Must be called during render, not from an effect.** React runs child effects
 * before parent effects, so a bump from the owning component's effect would land
 * *after* its children had already queued the new round — and would throw away
 * the very requests it was meant to protect. Bumping while the parent renders
 * happens before any child effect runs, which is the ordering we need.
 *
 * Returns the new generation.
 */
export function bumpFetchGeneration(): number {
  generation += 1;
  // Walk backwards: we splice as we go.
  for (let i = waiting.length - 1; i >= 0; i -= 1) {
    const w = waiting[i];
    if (w.generation < generation) {
      waiting.splice(i, 1);
      w.reject(new StaleFetchError());
    }
  }
  return generation;
}

/** The generation a fetch enqueued right now would belong to. */
export function currentFetchGeneration(): number {
  return generation;
}

/**
 * Run `task` once a slot is free.
 *
 * `priority` orders the queue — pass the component's vertical position so the
 * top of the dashboard resolves first; equal priorities keep arrival order.
 *
 * The task is stamped with the generation current at enqueue time; if that
 * generation is superseded while it waits, it is dropped with a
 * `StaleFetchError` and never runs. Tasks that already started are unaffected —
 * cancel those with an `AbortController`.
 *
 * The slot is released in a `finally`, so a rejected task frees its slot like a
 * successful one. The rejection itself is passed through untouched: callers
 * already handle fetch failures and must keep seeing them.
 */
export async function enqueueFetch<T>(task: () => Promise<T>, priority = 0): Promise<T> {
  const enqueuedAt = generation;
  await new Promise<void>((resolve, reject) => {
    waiting.push({ resolve, reject, priority, seq: seqCounter++, generation: enqueuedAt });
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
export function fetchQueueState(): {
  active: number;
  waiting: number;
  limit: number;
  generation: number;
} {
  return { active, waiting: waiting.length, limit, generation };
}

/** Reset to a clean state. Tests only — there is no reason to call this in app code. */
export function __resetFetchQueue(): void {
  limit = DEFAULT_CONCURRENCY;
  active = 0;
  seqCounter = 0;
  generation = 0;
  waiting.length = 0;
}
