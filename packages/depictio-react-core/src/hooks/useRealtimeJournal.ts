import { useCallback, useState } from 'react';

/**
 * Persistent log of realtime events captured from the WebSocket.
 *
 * Stored in ``localStorage`` under ``depictio.realtime.journal`` (per-origin,
 * shared across dashboards) so the journal survives full-page reloads. Capped
 * at ``maxEntries`` (default 50) — older entries fall off the front.
 *
 * Returned tuple is ``[entries, append, clear]``. The journal lives in the
 * RealtimeIndicator dropdown; ``clear`` is wired to the "Reset log" button
 * the user can hit when they want a clean slate (e.g. before running a fresh
 * stream test).
 */

export interface RealtimeJournalEntry {
  /** ISO 8601 timestamp captured client-side at the moment ``append`` was
   *  called. The server-side event ``timestamp`` field is stored separately
   *  in ``payload.serverTimestamp`` because clock skew between API + browser
   *  can be annoyingly large in dev. */
  receivedAt: string;
  /** ``data_collection_updated`` / ``data_collection_created`` etc. */
  eventType: string;
  /** DC id from the event, if present. */
  dataCollectionId?: string;
  /** Dashboard id from the event, if present. */
  dashboardId?: string;
  /** Human-readable short summary built from the event payload. */
  summary?: string;
  /** Free-form payload dict (capped to ~512 chars when serialised). */
  payload?: Record<string, unknown>;
}

const STORAGE_KEY = 'depictio.realtime.journal';

function readStored(maxEntries: number): RealtimeJournalEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Trim if storage was capped lower in a previous session.
    return parsed.slice(-maxEntries) as RealtimeJournalEntry[];
  } catch {
    return [];
  }
}

function persist(entries: RealtimeJournalEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // localStorage may be disabled (private mode) or full — degrade silently.
  }
}

export function useRealtimeJournal(
  maxEntries: number = 50,
): [
  RealtimeJournalEntry[],
  (entry: Omit<RealtimeJournalEntry, 'receivedAt'>) => void,
  () => void,
] {
  const [entries, setEntries] = useState<RealtimeJournalEntry[]>(() =>
    readStored(maxEntries),
  );

  const append = useCallback(
    (entry: Omit<RealtimeJournalEntry, 'receivedAt'>) => {
      const next: RealtimeJournalEntry = {
        receivedAt: new Date().toISOString(),
        ...entry,
      };
      setEntries((prev) => {
        const out = [...prev, next];
        const trimmed = out.length > maxEntries ? out.slice(-maxEntries) : out;
        persist(trimmed);
        return trimmed;
      });
    },
    [maxEntries],
  );

  const clear = useCallback(() => {
    setEntries([]);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }, []);

  return [entries, append, clear];
}

export default useRealtimeJournal;
