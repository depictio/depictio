import { useEffect, useState } from 'react';

import { getPushDestinations, listPushTargets } from 'depictio-react-core';
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

let cachedAdhoc: Promise<boolean> | null = null;

function loadAdhocEnabled(): Promise<boolean> {
  if (!cachedAdhoc) {
    cachedAdhoc = getPushDestinations()
      .then((d) => d.enabled)
      .catch(() => {
        cachedAdhoc = null;
        return false;
      });
  }
  return cachedAdhoc;
}

/** Whether "Publish to…" has anywhere to go for this user: a registered target,
 *  or a destination URL + invite code (when the instance allows it). */
export function usePublishAvailable(enabled = true): boolean {
  const targets = usePushTargets(enabled);
  const [adhoc, setAdhoc] = useState(false);
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    void loadAdhocEnabled().then((v) => {
      if (live) setAdhoc(v);
    });
    return () => {
      live = false;
    };
  }, [enabled]);
  return targets.length > 0 || adhoc;
}
