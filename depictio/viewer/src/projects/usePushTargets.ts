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

let cachedTargetsValue: MigrationTarget[] | null = null;

/** Push targets the current user may use; empty until loaded or when none. */
export function usePushTargets(enabled = true): MigrationTarget[] {
  return usePushTargetsState(enabled) ?? [];
}

/** Like `usePushTargets`, but `null` until the answer is in. */
function usePushTargetsState(enabled: boolean): MigrationTarget[] | null {
  const [targets, setTargets] = useState<MigrationTarget[] | null>(cachedTargetsValue);
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    void loadTargets().then((t) => {
      cachedTargetsValue = t;
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

export type PublishStatus = 'loading' | 'available' | 'unavailable';

/** Whether "Send to another instance" has anywhere to go for this user: a registered target,
 *  or a destination URL + invite code (when the instance allows it).
 *  `loading` until both answers are in, so a control never flashes disabled. */
export function usePublishStatus(enabled = true): PublishStatus {
  const targets = usePushTargetsState(enabled);
  const [adhoc, setAdhoc] = useState<boolean | null>(null);
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
  if (targets && targets.length > 0) return 'available';
  if (adhoc === true) return 'available';
  if (targets === null || adhoc === null) return 'loading';
  return 'unavailable';
}

/** True once a destination exists; see `usePublishStatus` for the pending case. */
export function usePublishAvailable(enabled = true): boolean {
  return usePublishStatus(enabled) === 'available';
}

/** Why "Send to another instance" is disabled when migration is shown but nothing is set up. */
export const NO_DESTINATION_REASON =
  'No destination is configured. An administrator must add a push target or allow sending with a destination URL and invite code.';
