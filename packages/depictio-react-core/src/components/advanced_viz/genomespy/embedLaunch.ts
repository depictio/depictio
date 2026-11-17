/**
 * Launch bookkeeping for a GenomeSpy embed.
 *
 * `embed()` never rejects on a failed launch: `launch()` reports the error
 * through `onError` and returns `false`, the embed result still comes back,
 * and its interaction controller (what `views.root().marks` needs) exists only
 * after a successful launch. Wiring subscriptions onto that result threw
 * "Cannot read properties of undefined (reading 'subscribeMarkEvent')" and the
 * hook's catch replaced the real message with it. The first mount after a
 * cold chunk load is the usual casualty (a race with the container's layout),
 * and a refresh worked, so one automatic retry removes the visible failure.
 */

export interface LaunchAttempt<T> {
  /** The embed result, even on a failed launch (it still has to be finalized). */
  result: T;
  /** What `onError` reported during this attempt, or `null` on a clean launch. */
  failure: Error | null;
}

/** An `onError` value as an Error, keeping its message. */
export function toError(err: unknown): Error {
  return err instanceof Error ? err : new Error(String(err));
}

/**
 * True when the embed's mark layer can take subscriptions. It does not on a
 * launch that failed without reporting (a destroyed embed, a swallowed throw),
 * so this guards the subscription block independently of `onError`.
 */
export function hasMarkEvents(result: unknown): boolean {
  try {
    const views = (result as { views?: { root?: () => { marks?: { subscribe?: unknown } } } }).views;
    return typeof views?.root?.()?.marks?.subscribe === 'function';
  } catch {
    return false;
  }
}

export interface LaunchOptions {
  /** Extra attempts after the first (default 1). */
  retries?: number;
  /** Wait before a retry, ms (default 120). */
  delayMs?: number;
  /** True once the effect was torn down: stop retrying. */
  isCancelled?: () => boolean;
  /** Pause between attempts; injectable for tests. */
  sleep?: (ms: number) => Promise<void>;
}

/**
 * Run `attempt` until it launches cleanly or the retries are spent. A failed
 * attempt's embed goes to `discard` before the next one starts. Resolves with
 * the last attempt, so the caller keeps the *original* failure message rather
 * than whatever a half-built embed throws afterwards.
 */
export async function launchWithRetry<T>(
  attempt: () => Promise<LaunchAttempt<T>>,
  discard: (result: T) => void,
  { retries = 1, delayMs = 120, isCancelled = () => false, sleep = defaultSleep }: LaunchOptions = {},
): Promise<LaunchAttempt<T>> {
  let last = await attempt();
  for (let left = retries; left > 0 && last.failure && !isCancelled(); left -= 1) {
    discard(last.result);
    await sleep(delayMs);
    if (isCancelled()) return last;
    last = await attempt();
  }
  return last;
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
