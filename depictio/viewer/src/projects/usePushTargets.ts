import { useEffect, useState } from 'react';

import { listPushTargets } from 'depictio-react-core';
import type { MigrationTarget } from 'depictio-react-core';

/** One fetch shared by every row of a project list: the menu of each row asks
 *  whether to offer "Migrate to another instance…", and the answer is the same. */
let cached: Promise<MigrationTarget[]> | null = null;

function loadTargets(): Promise<MigrationTarget[]> {
  if (!cached) {
    cached = listPushTargets().catch(() => {
      // Not configured, or the endpoint is missing on an older backend: no entry.
      cached = null;
      return [] as MigrationTarget[];
    });
  }
  return cached;
}

/** Push targets the current user may use; empty until loaded or when none. */
export function usePushTargets(enabled = true): MigrationTarget[] {
  const [targets, setTargets] = useState<MigrationTarget[]>([]);
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    void loadTargets().then((t) => {
      if (live) setTargets(t);
    });
    return () => {
      live = false;
    };
  }, [enabled]);
  return targets;
}
