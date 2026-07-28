/**
 * Formatting helpers shared by every monitoring surface.
 *
 * Extracted verbatim from AdminMonitoringPanel. `parseTs` in particular must
 * stay the single definition — see its comment for the UTC trap it exists to
 * avoid.
 */

/** Parse a backend ISO timestamp to epoch ms. The API stamps with
 *  `datetime.now()` in UTC containers and serializes without an offset, so an
 *  offset-less value must be read as UTC — otherwise JS treats it as local time
 *  (a fresh event reads hours off for non-UTC users). */
export function parseTs(iso?: string | null): number {
  if (!iso) return NaN;
  const hasTz = /([zZ]|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasTz ? iso : `${iso}Z`).getTime();
}

/** Compact relative-time string from an ISO timestamp, with absolute tooltip. */
export function relTime(iso?: string | null): string {
  if (!iso) return '—';
  const then = parseTs(iso);
  if (Number.isNaN(then)) return '—';
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

/** Exact local clock time (with seconds) from an ISO timestamp. */
export function absTime(iso?: string | null): string {
  const ms = parseTs(iso);
  if (Number.isNaN(ms)) return '—';
  return new Date(ms).toLocaleTimeString(undefined, { hour12: false });
}

export function formatDuration(ms?: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

/** Wall-clock duration between two ISO timestamps, in ms (null if either is missing). */
export function spanMs(start?: string | null, end?: string | null): number | null {
  const a = parseTs(start);
  const b = parseTs(end);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.max(0, b - a);
}

/** Compact "N ok · M failed · K skipped" tally from a run's step list. */
export function stepTally(steps?: { status: string }[]): string {
  if (!steps || steps.length === 0) return '—';
  const counts = { success: 0, failed: 0, skipped: 0, partial: 0, other: 0 };
  for (const s of steps) {
    const key = (s.status || '').toLowerCase();
    if (key === 'success') counts.success += 1;
    else if (key === 'failed' || key === 'failure') counts.failed += 1;
    else if (key === 'skipped') counts.skipped += 1;
    else if (key === 'partial' || key === 'running') counts.partial += 1;
    else counts.other += 1;
  }
  const parts: string[] = [`${counts.success} ok`];
  if (counts.failed) parts.push(`${counts.failed} failed`);
  if (counts.skipped) parts.push(`${counts.skipped} skipped`);
  if (counts.partial) parts.push(`${counts.partial} partial`);
  if (counts.other) parts.push(`${counts.other} other`);
  return parts.join(' · ');
}

/** Collapse a long filesystem path to `head/…/last-two-segments` so it fits on
 *  one line; the full value is surfaced via tooltip in `PathTip`. */
export function shortenPath(p: string, maxLen = 44): string {
  if (p.length <= maxLen) return p;
  const parts = p.split('/').filter(Boolean);
  if (parts.length <= 2) return `…${p.slice(-(maxLen - 1))}`;
  const lead = p.startsWith('/') ? '/' : '';
  const tail = parts.slice(-2).join('/');
  const short = `${lead}${parts[0]}/…/${tail}`;
  return short.length <= maxLen ? short : `…/${tail}`;
}

/** Case-insensitive substring match of `q` against any of the given fields.
 *  Empty query matches everything. Shared by the pane search boxes. */
export function matchesQuery(
  q: string,
  ...fields: Array<string | number | null | undefined>
): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return fields.some((f) => f != null && String(f).toLowerCase().includes(needle));
}

/** Compact count formatting for counter chips: 1234 → "1.2k". */
export function compactCount(n?: number | null): string {
  if (n == null) return '—';
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}
