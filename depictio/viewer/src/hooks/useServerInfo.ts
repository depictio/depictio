import { useEffect, useSyncExternalStore } from 'react';

import { AUTH_SESSION_EVENT, currentSessionId, fetchServerInfo } from 'depictio-react-core';
import type { ServerInfo } from 'depictio-react-core';

/**
 * What the server says about itself (version, links, and for an admin the
 * update check), shared by every piece of chrome that shows it.
 *
 * One module-level store, not a hook-local fetch: the sidebar foot, the
 * account page and the update dot all read the same answer, so mounting five
 * of them costs one request. It is refreshed
 *   - every 30 minutes while a consumer is mounted (the server itself only
 *     re-checks GitHub every few hours, so this is cheap);
 *   - when the window regains focus after that long;
 *   - when the signed-in user changes, since the admin block depends on the
 *     token;
 *   - on demand, through `refreshServerInfo()` (the admin toggle calls it).
 *
 * `useServerStatus` keeps the 30 s online/offline poll: this store never
 * decides whether the server is up, it only fills in the details.
 */

export interface ServerInfoState {
  info: ServerInfo | null;
  /** True until the first answer (or failure) of the current session. */
  loading: boolean;
}

const STALE_MS = 30 * 60_000;

let state: ServerInfoState = { info: null, loading: true };
let fetchedAt = 0;
let session: string | null | undefined;
let inflight: Promise<void> | null = null;
let consumers = 0;
let timer: number | undefined;
const listeners = new Set<() => void>();

function publish(next: ServerInfoState): void {
  state = next;
  listeners.forEach((l) => l());
}

/** Fetch again now. Resolves when the new answer is in the store. */
export function refreshServerInfo(): Promise<void> {
  if (inflight) return inflight;
  const forSession = currentSessionId();
  inflight = fetchServerInfo()
    .then((info) => {
      // Signed in or out while this was in flight: the answer is for someone
      // else, and the session handler has already asked again.
      if (forSession !== currentSessionId()) return;
      fetchedAt = Date.now();
      publish({ info, loading: false });
    })
    .catch(() => {
      if (forSession !== currentSessionId()) return;
      // A failure is not a fresh answer: leave the store stale so the next
      // mount or window focus tries again instead of waiting out STALE_MS.
      fetchedAt = 0;
      publish({ ...state, loading: false });
    })
    .finally(() => {
      inflight = null;
      if (forSession !== currentSessionId()) void refreshServerInfo();
    });
  return inflight;
}

function onSessionChange(): void {
  const now = currentSessionId();
  if (now === session) return;
  session = now;
  // The previous user's admin block must not outlive them.
  publish({ info: null, loading: true });
  void refreshServerInfo();
}

function onFocus(): void {
  onSessionChange();
  if (Date.now() - fetchedAt >= STALE_MS) void refreshServerInfo();
}

function start(): void {
  const before = session;
  session = currentSessionId();
  // Nobody was listening while the user changed: what is held is theirs.
  if (before !== undefined && before !== session) {
    fetchedAt = 0;
    state = { info: null, loading: true };
  }
  window.addEventListener(AUTH_SESSION_EVENT, onSessionChange);
  window.addEventListener('storage', onSessionChange);
  window.addEventListener('focus', onFocus);
  timer = window.setInterval(() => void refreshServerInfo(), STALE_MS);
  if (!fetchedAt || Date.now() - fetchedAt >= STALE_MS) void refreshServerInfo();
}

function stop(): void {
  window.removeEventListener(AUTH_SESSION_EVENT, onSessionChange);
  window.removeEventListener('storage', onSessionChange);
  window.removeEventListener('focus', onFocus);
  window.clearInterval(timer);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const getSnapshot = (): ServerInfoState => state;

export function useServerInfo(): ServerInfoState {
  useEffect(() => {
    if (consumers++ === 0) start();
    return () => {
      if (--consumers === 0) stop();
    };
  }, []);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
