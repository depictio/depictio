import { useCallback, useSyncExternalStore } from 'react';

import { useServerInfo } from './useServerInfo';

/**
 * Whether the admin has an unread "a newer Depictio is out" notice.
 *
 * The server only sends `version_check` to admins, so `show` is false for
 * everyone else without a role check of our own. The acknowledgement stores
 * the *version* that was read, not a flag: the next release notifies again,
 * while an unchanged one stays quiet.
 */

const ACK_KEY = 'depictio-update-ack';
const ACK_EVENT = 'depictio:update-ack';

/** Where an acknowledgement lives when storage is blocked: this page only. */
let memoryAck: string | null = null;

function readAck(): string | null {
  try {
    return localStorage.getItem(ACK_KEY) ?? memoryAck;
  } catch {
    return memoryAck;
  }
}

function subscribe(listener: () => void): () => void {
  window.addEventListener(ACK_EVENT, listener);
  // Another tab's acknowledgement.
  window.addEventListener('storage', listener);
  return () => {
    window.removeEventListener(ACK_EVENT, listener);
    window.removeEventListener('storage', listener);
  };
}

export interface UpdateNotice {
  /** An update is out, the check is on, and the admin has not read it yet. */
  show: boolean;
  /** An update is out (read or not): the panel still names it quietly. */
  available: boolean;
  latestVersion: string | null;
  releaseUrl: string | null;
  publishedAt: string | null;
  /** Mark this version as read; every mounted trigger clears its dot at once. */
  acknowledge: () => void;
}

export function useUpdateNotice(): UpdateNotice {
  const { info } = useServerInfo();
  const ack = useSyncExternalStore(subscribe, readAck, () => null);
  const check = info?.version_check ?? null;
  const latest = check?.latest_version ?? null;
  const available = Boolean(check?.enabled && check.update_available && latest);

  const acknowledge = useCallback(() => {
    if (!latest) return;
    memoryAck = latest;
    try {
      localStorage.setItem(ACK_KEY, latest);
    } catch {
      // Storage blocked: the dot returns on the next page load.
    }
    window.dispatchEvent(new Event(ACK_EVENT));
  }, [latest]);

  return {
    show: available && ack !== latest,
    available,
    latestVersion: latest,
    releaseUrl: check?.release_url ?? null,
    publishedAt: check?.published_at ?? null,
    acknowledge,
  };
}
