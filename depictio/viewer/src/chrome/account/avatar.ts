import { useSyncExternalStore } from 'react';

import { fetchMyAvatarBlob } from 'depictio-react-core';

/**
 * The reader's profile picture, shared by every avatar on the page.
 *
 * The bytes sit behind the bearer token, so an `<img src>` cannot load them.
 * They are fetched once through `authFetch` and handed out as an object URL,
 * from a module-level store: the chrome's avatar, the phone sheet's row and the
 * Account section all read the same URL, and an upload or a removal updates
 * them in one step through `syncMyAvatar`.
 *
 * The key is the server's `avatar_updated_at`. It changes on every
 * replacement, so a picture is fetched once per value and never while the
 * visitor has none (null key).
 */

interface AvatarState {
  /** The `avatar_updated_at` the current URL stands for. */
  key: string | null;
  url: string | null;
}

let state: AvatarState = { key: null, url: null };
/** Orders overlapping fetches: only the latest one may write its result. */
let generation = 0;
/** When the picture last changed on purpose (an upload or a removal). A sync
 *  carrying a `startedAt` before it comes from a request that left earlier and
 *  answered later, so it holds the stamp from before the change: ignore it. */
let changedAt = 0;
const listeners = new Set<() => void>();

function emit(next: AvatarState): void {
  state = next;
  listeners.forEach((listener) => listener());
}

function revoke(url: string | null): void {
  if (url) URL.revokeObjectURL(url);
}

async function load(key: string): Promise<void> {
  const mine = ++generation;
  try {
    const blob = await fetchMyAvatarBlob();
    if (mine !== generation) return;
    revoke(state.url);
    emit({ key, url: blob ? URL.createObjectURL(blob) : null });
  } catch {
    // Initials are the fallback, not the previous picture. Forget the key so
    // the next sync retries.
    if (mine === generation) {
      revoke(state.url);
      emit({ key: null, url: null });
    }
  }
}

/**
 * Align the store with the server's `avatar_updated_at` (null: no picture).
 * Idempotent, so every place that learns the value can call it freely (the
 * auth status on load, an upload's or a removal's answer); the fetch only
 * happens when the value is new.
 *
 * A caller reporting an upload or a removal passes no `startedAt` and marks
 * the change. A caller reading the auth status passes the time its request
 * started, so a read that began before the last change cannot revert it.
 */
export function syncMyAvatar(
  key: string | null | undefined,
  opts: { startedAt?: number } = {},
): void {
  if (opts.startedAt === undefined) changedAt = Date.now();
  else if (opts.startedAt < changedAt) return;
  const next = key ?? null;
  if (next === state.key) return;
  if (next === null) {
    generation += 1;
    revoke(state.url);
    emit({ key: null, url: null });
    return;
  }
  // Claim the key before the fetch resolves, so a second caller with the same
  // value does not start another one.
  state = { ...state, key: next };
  void load(next);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The object URL of the reader's picture, or null (draw the initials). */
export function useMyAvatar(): string | null {
  return useSyncExternalStore(
    subscribe,
    () => state.url,
    () => null,
  );
}
