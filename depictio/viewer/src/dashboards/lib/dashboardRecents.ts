/** Recently-opened dashboards are tracked in localStorage so the dashboards
 *  page can surface a "Recently opened" section. Per-browser only — there is
 *  no backend persistence yet. Capped at 20 entries. */

const RECENTS_KEY = 'depictio.dashboards.recents.v1';
const RECENTS_CAP = 20;

export const RECENTS_EVENT = 'depictio:recents-changed';

export interface RecentEntry {
  id: string;
  ts: number;
}

export function readRecents(): RecentEntry[] {
  try {
    const raw = localStorage.getItem(RECENTS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (e): e is RecentEntry =>
        typeof e?.id === 'string' && typeof e?.ts === 'number',
    );
  } catch {
    return [];
  }
}

function writeRecents(entries: RecentEntry[]): void {
  try {
    localStorage.setItem(RECENTS_KEY, JSON.stringify(entries));
  } catch {
    /* quota or private mode — silently ignore */
  }
}

/** Record an open. Newest first; deduped on id. */
export function recordOpen(id: string): void {
  if (!id) return;
  const next = [{ id, ts: Date.now() }, ...readRecents().filter((e) => e.id !== id)].slice(
    0,
    RECENTS_CAP,
  );
  writeRecents(next);
  window.dispatchEvent(new CustomEvent(RECENTS_EVENT));
}
