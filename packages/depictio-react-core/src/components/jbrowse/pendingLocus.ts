/**
 * A locus handed to the genome browser of a tab family from another tile.
 *
 * Switching tab is a full page load, so the in-memory stores are gone by the
 * time the browser mounts: the locus rides in `sessionStorage`, keyed by the
 * family, and the browser reads it once when it builds its view. When the
 * browser is on the page already there is no reload, and the same locus goes
 * out as a window event instead. Pure helpers around the two, no React.
 */

/** Prefix of the `sessionStorage` key; the family id follows. */
export const PENDING_LOCUS_PREFIX = 'depictio:pending-locus:';

/** Name of the window event announcing a locus to a browser on this page. */
export const PENDING_LOCUS_EVENT = 'depictio:pending-locus';

/** How long a written locus stays valid. A reload that comes later than this
 *  is not the hand-over the entry was written for. */
export const PENDING_LOCUS_TTL_MS = 60_000;

/** Where a locus is going: the browser tile, and the locus it opens on. */
export interface PendingLocus {
  dashboardId: string;
  index: string;
  locus: string;
}

interface StoredPendingLocus extends PendingLocus {
  ts: number;
}

/** The detail of the window event: the family it belongs to, and the locus. */
export interface PendingLocusEventDetail extends PendingLocus {
  familyId: string;
}

function storage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

const keyOf = (familyId: string) => `${PENDING_LOCUS_PREFIX}${familyId}`;

function parse(raw: string | null): StoredPendingLocus | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as Partial<StoredPendingLocus> | null;
    if (
      v &&
      typeof v.dashboardId === 'string' &&
      typeof v.index === 'string' &&
      typeof v.locus === 'string' &&
      typeof v.ts === 'number'
    ) {
      return v as StoredPendingLocus;
    }
  } catch {
    // A corrupt entry is no entry.
  }
  return null;
}

/** Remember a locus for the family's browser to open on after a page load.
 *  Storage can refuse (a private window): then the browser opens where it
 *  would have anyway. */
export function writePendingLocus(
  familyId: string,
  pending: PendingLocus,
  now: number = Date.now(),
): void {
  const store = storage();
  if (!store || !familyId || !pending.locus) return;
  try {
    const entry: StoredPendingLocus = { ...pending, ts: now };
    store.setItem(keyOf(familyId), JSON.stringify(entry));
  } catch {
    // Not remembered.
  }
}

/**
 * The locus waiting for this browser tile, or null. Read once: a matching
 * entry is deleted as it is returned, and an expired or unreadable one is
 * dropped. An entry written for another tile of the family stays, since that
 * tile may still be about to mount.
 *
 * `familyId` null looks through every family's entry: a tile that renders
 * before its tab family is known has no key to look under, and the match on
 * dashboard and index is what scopes the entry then.
 */
export function takePendingLocus(
  familyId: string | null,
  dashboardId: string,
  index: string,
  now: number = Date.now(),
): string | null {
  const store = storage();
  if (!store) return null;
  try {
    let keys: string[];
    if (familyId) {
      keys = [keyOf(familyId)];
    } else {
      keys = [];
      for (let i = 0; i < store.length; i += 1) {
        const k = store.key(i);
        if (k && k.startsWith(PENDING_LOCUS_PREFIX)) keys.push(k);
      }
    }
    for (const key of keys) {
      const entry = parse(store.getItem(key));
      if (!entry) {
        if (store.getItem(key) !== null) store.removeItem(key);
        continue;
      }
      if (now - entry.ts > PENDING_LOCUS_TTL_MS || now < entry.ts) {
        store.removeItem(key);
        continue;
      }
      if (entry.dashboardId !== dashboardId || entry.index !== index) continue;
      store.removeItem(key);
      return entry.locus;
    }
  } catch {
    // Storage went away mid-read.
  }
  return null;
}

/** Tell a browser tile on this page to go to a locus (the same-tab case). */
export function announcePendingLocus(detail: PendingLocusEventDetail): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<PendingLocusEventDetail>(PENDING_LOCUS_EVENT, { detail }));
}

/** The event's detail when it is for this tile, else null. */
export function pendingLocusFor(
  event: Event,
  dashboardId: string,
  index: string,
): PendingLocusEventDetail | null {
  const detail = (event as CustomEvent<PendingLocusEventDetail>).detail;
  if (!detail || typeof detail.locus !== 'string' || !detail.locus) return null;
  return detail.dashboardId === dashboardId && detail.index === index ? detail : null;
}
