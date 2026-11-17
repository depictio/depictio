/**
 * The family's change set as this tab last read it (#1399 follow-up).
 *
 * Every dashboard tab is its own page, so each one used to wait for the
 * session, the dashboard and then the change set before the pill and the
 * dots showed. The last read is painted at once and replaced by the fresh one
 * when it lands (stale while revalidate). Kept in sessionStorage, keyed by the
 * reader: one browser tab, gone when it closes, and a sign-in as someone else
 * in the same tab never paints the previous reader's news.
 */
import type { DashboardChangeSet } from 'depictio-react-core';

const KEY = (readerId: string, familyId: string) => `depictio-changeset:${readerId}:${familyId}`;

/** Older than this, a cached set is not worth a flash of stale marks. */
const MAX_AGE_MS = 15 * 60_000;

interface Entry {
  at: number;
  changeSet: DashboardChangeSet;
}

export function readCachedChangeSet(readerId: string, familyId: string): DashboardChangeSet | null {
  try {
    const raw = window.sessionStorage.getItem(KEY(readerId, familyId));
    if (!raw) return null;
    const entry = JSON.parse(raw) as Entry;
    if (!entry?.changeSet || Date.now() - entry.at > MAX_AGE_MS) return null;
    return entry.changeSet.family_id === familyId ? entry.changeSet : null;
  } catch {
    return null;
  }
}

export function writeCachedChangeSet(
  readerId: string,
  familyId: string,
  changeSet: DashboardChangeSet,
): void {
  try {
    const entry: Entry = { at: Date.now(), changeSet };
    window.sessionStorage.setItem(KEY(readerId, familyId), JSON.stringify(entry));
  } catch {
    // storage full or blocked: the next page waits for the fetch, as before
  }
}

/** A fetch that failed (no access any more, server down): the cached set is
 *  not painted again on the next tab. */
export function dropCachedChangeSet(readerId: string, familyId: string): void {
  try {
    window.sessionStorage.removeItem(KEY(readerId, familyId));
  } catch {
    // blocked storage: nothing was cached either
  }
}
