import type { JBrowseTrackRow } from '../../api';

/** "Show all" opens at most this many tracks: every open track fetches its
 *  own data, so opening hundreds at once would stall the browser. */
export const SHOW_ALL_CAP = 60;

export type TrackSource = NonNullable<JBrowseTrackRow['source']>;

export interface TrackGroup {
  /** Stable React key (a manifest category may itself be called "UCSC"). */
  key: string;
  label: string;
  rows: JBrowseTrackRow[];
}

/** A row's origin; rows from a backend that predates ``source`` are manifest rows. */
export function rowSource(row: JBrowseTrackRow): TrackSource {
  return row.source ?? 'manifest';
}

export function isManifestRow(row: JBrowseTrackRow): boolean {
  return rowSource(row) === 'manifest';
}

/** Track ids of the manifest rows: the ones the dashboard filters drive. */
export function manifestTrackIds(rows: JBrowseTrackRow[]): string[] {
  return rows.filter(isManifestRow).map((r) => r.track_id);
}

/**
 * Case-insensitive search over the fields a user would type: every
 * whitespace-separated term must appear in the name, id, category, sample or
 * selection value (so "h3k27 liver" narrows on both).
 */
export function rowMatchesQuery(row: JBrowseTrackRow, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return true;
  const hay = [row.name, row.track_id, row.category, row.sample, row.selection_value, row.format]
    .filter((v): v is string => typeof v === 'string' && v.length > 0)
    .join('\u0000')
    .toLowerCase();
  return terms.every((t) => hay.includes(t));
}

/**
 * The track menu's sections, for the rows matching ``query``: manifest rows
 * grouped by ``category`` (in first-appearance order, uncategorised ones last),
 * then the UCSC tracks, then the reference tracks (assembly annotation and
 * ``extra_tracks``). Empty groups are dropped.
 */
export function groupTrackRows(rows: JBrowseTrackRow[], query = ''): TrackGroup[] {
  const categories = new Map<string, JBrowseTrackRow[]>();
  const uncategorised: JBrowseTrackRow[] = [];
  const ucsc: JBrowseTrackRow[] = [];
  const reference: JBrowseTrackRow[] = [];
  for (const row of rows) {
    if (!rowMatchesQuery(row, query)) continue;
    const source = rowSource(row);
    if (source === 'ucsc') {
      ucsc.push(row);
    } else if (source === 'annotation' || source === 'extra') {
      reference.push(row);
    } else if (row.category) {
      const list = categories.get(row.category);
      if (list) list.push(row);
      else categories.set(row.category, [row]);
    } else {
      uncategorised.push(row);
    }
  }
  const groups: TrackGroup[] = [...categories].map(([label, list]) => ({
    key: `category:${label}`,
    label,
    rows: list,
  }));
  if (uncategorised.length) {
    groups.push({
      key: 'uncategorised',
      label: groups.length ? 'Other tracks' : 'Tracks',
      rows: uncategorised,
    });
  }
  if (ucsc.length) groups.push({ key: 'ucsc', label: 'UCSC', rows: ucsc });
  if (reference.length) groups.push({ key: 'reference', label: 'Reference', rows: reference });
  return groups;
}

/**
 * What "Show all" opens: the first ``cap`` matching rows in menu order.
 * ``total`` is every matching row (the button's count), ``capped`` whether
 * some were left out (the menu then says so).
 */
export function showAllPlan(
  groups: TrackGroup[],
  cap: number = SHOW_ALL_CAP,
): { ids: string[]; total: number; capped: boolean } {
  const all = groups.flatMap((g) => g.rows.map((r) => r.track_id));
  return { ids: all.slice(0, Math.max(0, cap)), total: all.length, capped: all.length > cap };
}

/** The open tracks "Hide all" closes: manifest rows only, so the reference
 *  annotation and UCSC tracks stay as orientation. */
export function hideAllIds(open: string[], rows: JBrowseTrackRow[]): string[] {
  const manifest = new Set(manifestTrackIds(rows));
  return open.filter((id) => manifest.has(id));
}

/** How many of ``rows`` are open, for the "k / N open" header. */
export function countOpen(rows: JBrowseTrackRow[], open: Iterable<string>): number {
  const isOpen = new Set(open);
  return rows.reduce((n, r) => n + (isOpen.has(r.track_id) ? 1 : 0), 0);
}
