/**
 * Presentation helpers for the version timeline.
 *
 * Timestamp parsing is deliberately re-exported from the monitoring helpers
 * rather than reimplemented: `parseTs` exists to handle the API's offset-less
 * UTC timestamps, and a second definition would drift.
 */

import type { DashboardVersionSummary } from 'depictio-react-core';

export { absTime, parseTs, relTime } from '../monitoring/format';
import { parseTs } from '../monitoring/format';

/**
 * Full date and time for one version, e.g. "29 Jul 2026, 14:32:07".
 *
 * The monitoring `absTime` gives time-of-day only, which is right for a live
 * log where every row is from today. A version timeline spans months, and a
 * bare "14:32:07" against a version from March is actively misleading — the
 * day-group heading is easy to scroll past, and the row is what gets read when
 * choosing what to restore.
 */
export function absDateTime(iso?: string | null): string {
  const ms = parseTs(iso);
  if (Number.isNaN(ms)) return '—';
  return new Date(ms).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

/** Day bucket label: "Today" / "Yesterday" / "3 Mar 2026". */
export function dayLabel(iso?: string | null): string {
  const ms = parseTs(iso);
  if (Number.isNaN(ms)) return 'Unknown date';

  const then = new Date(ms);
  const now = new Date();
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(then)) / 86_400_000);

  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return then.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

/** Group versions into day buckets, preserving the newest-first order. */
export function groupByDay(
  versions: DashboardVersionSummary[],
): Array<{ label: string; versions: DashboardVersionSummary[] }> {
  const groups: Array<{ label: string; versions: DashboardVersionSummary[] }> = [];
  for (const version of versions) {
    const label = dayLabel(version.created_at);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.versions.push(version);
    else groups.push({ label, versions: [version] });
  }
  return groups;
}

/** "12 saves over 4 min" — only meaningful once saves have folded together. */
export function saveSpanLabel(version: DashboardVersionSummary): string | null {
  if (!version.save_count || version.save_count <= 1) return null;
  const start = parseTs(version.created_at);
  const end = parseTs(version.updated_at);
  if (Number.isNaN(start) || Number.isNaN(end) || end <= start) {
    return `${version.save_count} saves`;
  }
  const mins = Math.max(1, Math.round((end - start) / 60_000));
  return `${version.save_count} saves over ${mins} min`;
}

/** What to call a version in the UI. A user label wins; otherwise "v12". */
export function versionTitle(version: DashboardVersionSummary): string {
  return version.label?.trim() || `v${version.seq}`;
}

export const KIND_META: Record<string, { icon: string; color: string; label: string }> = {
  auto: { icon: 'mdi:content-save-outline', color: 'gray', label: 'Autosave' },
  explicit: { icon: 'mdi:content-save', color: 'blue', label: 'Saved' },
  restore: { icon: 'mdi:backup-restore', color: 'yellow', label: 'Restored' },
  import: { icon: 'mdi:import', color: 'grape', label: 'Imported' },
};

export function kindMeta(kind: string) {
  return KIND_META[kind] ?? { icon: 'mdi:circle-small', color: 'gray', label: kind };
}

/**
 * One-line summary of how reproducible a version's data is.
 *
 * Coverage is genuinely heterogeneous — a dashboard can pin a Delta version
 * for one collection while another has no provenance at all — so this states
 * the split rather than implying uniform fidelity.
 */
export function dataCoverageLabel(kinds: Record<string, number>): string | null {
  const total = Object.values(kinds).reduce((a, b) => a + b, 0);
  if (!total) return null;

  const pinned = (kinds.delta ?? 0) + (kinds.manifest ?? 0) + (kinds.asset ?? 0);
  if (pinned === 0) return `${total} data collection${total === 1 ? '' : 's'} · live data`;
  if (pinned === total) return `${total} data collection${total === 1 ? '' : 's'} pinned`;
  return `${pinned} of ${total} data collections pinned`;
}
