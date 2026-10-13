/**
 * When `auto_run` may dispatch a comparison on its own.
 *
 * The rule is one dispatch per distinct request key per mount: the key is
 * everything the server hashes into its cache key (groups, test, transform,
 * filters, refresh tick), so a re-render, a threshold tweak or a new saved
 * group that leaves the two picks alone never queues a second job. A remount
 * (tab switch, React StrictMode's simulated unmount) resets the gate, and the
 * dispatch it then allows is answered by the server's result cache, or joins
 * the job already pending under the same key, rather than computing again.
 *
 * Kept as a plain object so the rule is testable without a DOM.
 */
export interface AutoRunGate {
  /** True exactly once per key while `enabled` and `ready` both hold. */
  claim(key: string, enabled: boolean, ready: boolean): boolean;
  /** Forget the last key, so the next claim after a remount goes through. */
  reset(): void;
}

export function createAutoRunGate(): AutoRunGate {
  let last: string | null = null;
  return {
    claim(key, enabled, ready) {
      if (!enabled || !ready || key === last) return false;
      last = key;
      return true;
    },
    reset() {
      last = null;
    },
  };
}
