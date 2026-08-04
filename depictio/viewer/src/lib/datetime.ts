/** Timestamp parsing and formatting for the user's local timezone.
 *
 * The backend stores wall-clock timestamps as naive strings formatted
 * `"YYYY-MM-DD HH:MM:SS"` (see `depictio/models/timestamps.py`). Those strings
 * are **always UTC**, but `new Date("2026-08-04 09:00:00")` parses a naive
 * string as *local* time in every browser — which is exactly why a CEST user
 * saw dashboard times two hours in the past (issue #932).
 *
 * `parseServerTimestamp` therefore appends an explicit `Z` to naive strings so
 * they're read as UTC, then all formatting happens in the viewer's own
 * timezone via `Intl`.
 */

/** Matches a naive `YYYY-MM-DD[ T]HH:MM[:SS[.fff]]` with no timezone suffix. */
const NAIVE_TS = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

/** Parse a server timestamp into a Date, treating naive strings as UTC.
 *  Returns `null` when the value isn't a usable timestamp. */
export function parseServerTimestamp(raw: unknown): Date | null {
  if (typeof raw === 'number') {
    // Heuristic: values below ~1e11 are seconds, above are milliseconds.
    const d = new Date(raw < 1e11 ? raw * 1000 : raw);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (typeof raw !== 'string') return null;
  const s = raw.trim();
  if (!s) return null;
  const normalized = NAIVE_TS.test(s) ? `${s.replace(' ', 'T')}Z` : s;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** `YYYY-MM-DD HH:MM` in the viewer's local timezone. */
export function formatDateTime(raw: unknown, fallback = '—'): string {
  const d = parseServerTimestamp(raw);
  if (!d) return typeof raw === 'string' && raw ? raw : fallback;
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** `YYYY-MM-DD` in the viewer's local timezone. */
export function formatDate(raw: unknown, fallback = '—'): string {
  const d = parseServerTimestamp(raw);
  if (!d) return fallback;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The viewer's IANA timezone name (e.g. `Europe/Berlin`), best-effort. */
export function localTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'local time';
  } catch {
    return 'local time';
  }
}

/** Full, unambiguous rendering for tooltips: local time down to the second,
 *  with the timezone name and the original UTC value spelled out. */
export function formatDateTimeVerbose(raw: unknown, fallback = 'Unknown'): string {
  const d = parseServerTimestamp(raw);
  if (!d) return fallback;
  const local =
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  const utc =
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
  return `${local} (${localTimeZone()}) · ${utc} UTC`;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Compact relative age, e.g. `just now`, `3h ago`, `12d ago`.
 *  Falls back to an absolute date beyond ~30 days. */
export function formatRelative(raw: unknown, fallback = '—'): string {
  const d = parseServerTimestamp(raw);
  if (!d) return fallback;
  const diff = Date.now() - d.getTime();
  if (diff < 0) return formatDateTime(raw, fallback);
  if (diff < MINUTE) return 'just now';
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m ago`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`;
  if (diff < 30 * DAY) return `${Math.floor(diff / DAY)}d ago`;
  return formatDate(raw, fallback);
}

/** Sort key for timestamps: epoch ms, with unparsable values sorting last
 *  regardless of direction (callers compare the numbers directly). */
export function timestampSortKey(raw: unknown): number {
  const d = parseServerTimestamp(raw);
  return d ? d.getTime() : Number.NEGATIVE_INFINITY;
}
