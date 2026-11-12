/**
 * Words and links for "changed since your last visit" (#1397).
 *
 * Pure and free of React, so `pnpm run check:changes` can run the real code.
 * Nothing here imports the version-history components: the viewer must not
 * (`check_served_bundle.py` asserts it), and a link into History is a URL.
 */
import type {
  CommentChange,
  DashboardChange,
  DashboardChangeSet,
  DataChange,
} from 'depictio-react-core';

export interface ReadOnlyQuery {
  since: string | null;
  beforeRun: string | null;
}

/** `?since=<iso>` / `?before_run=<ingestion_run_id>`: a read-only view that
 *  never moves a mark. Read once per load, like `?version=`. */
export function parseReadOnlyQuery(search: string): ReadOnlyQuery {
  let params: URLSearchParams;
  try {
    params = new URLSearchParams(search);
  } catch {
    return { since: null, beforeRun: null };
  }
  const clean = (v: string | null) => (v && v.trim() ? v.trim() : null);
  return { since: clean(params.get('since')), beforeRun: clean(params.get('before_run')) };
}

export const isReadOnlyQuery = (q: ReadOnlyQuery): boolean => Boolean(q.since || q.beforeRun);

export interface ChangeCounts {
  data: number;
  dashboard: number;
  comments: number;
  total: number;
}

export function changeCounts(cs: DashboardChangeSet | null): ChangeCounts {
  const data = (cs?.data.length ?? 0) + (cs?.failed_ingestions.length ?? 0);
  const dashboard = cs?.dashboard.length ?? 0;
  const comments = cs?.comments.length ?? 0;
  return { data, dashboard, comments, total: data + dashboard + comments };
}

/** The pill shows only when there is a previous visit to compare with and
 *  something differs from it. */
export function hasChanges(cs: DashboardChangeSet | null): boolean {
  return Boolean(cs && !cs.first_visit && changeCounts(cs).total > 0);
}

const unique = <T,>(items: T[]): T[] => [...new Set(items)];

/** `tabId:index` -> the lines behind its dot's tooltip. */
export function markDetails(cs: DashboardChangeSet | null): Record<string, string[]> {
  if (!cs) return {};
  const out: Record<string, string[]> = {};
  const runTags = unique(cs.data.flatMap((d) => d.new_run_tags));
  const collections = unique(cs.data.map((d) => d.data_collection_tag));
  for (const [key, reasons] of Object.entries(cs.changed_components)) {
    const lines: string[] = [];
    if (reasons.includes('definition')) {
      const authors = unique(cs.dashboard.filter((c) => c.key === key).flatMap((c) => c.authors));
      lines.push(authors.length ? `Definition changed by ${authors.join(', ')}` : 'Definition changed');
    }
    if (reasons.includes('data')) {
      const what = runTags.length ? runTags : collections;
      lines.push(what.length ? `Data refreshed: ${what.join(', ')}` : 'Data refreshed');
    }
    out[key] = lines;
  }
  return out;
}

export const MAX_SAMPLES_SHOWN = 5;

/** Up to five sample names, then how many more. */
export function sampleSummary(change: Pick<DataChange, 'new_samples' | 'new_sample_count'>): {
  shown: string[];
  more: number;
  total: number;
} {
  const names = change.new_samples ?? [];
  const total = Math.max(change.new_sample_count ?? 0, names.length);
  const shown = names.slice(0, MAX_SAMPLES_SHOWN);
  return { shown, more: Math.max(0, total - shown.length), total };
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The facts on one data row, as short phrases ("1 new run", "+5 rows"). */
export function dataFacts(change: DataChange): string[] {
  const facts: string[] = [];
  if (change.new_run_tags.length) facts.push(plural(change.new_run_tags.length, 'new run'));
  if (change.rows_added && change.rows_added > 0) facts.push(`+${change.rows_added} rows`);
  const { total } = sampleSummary(change);
  if (total > 0) facts.push(plural(total, 'new sample'));
  if (change.reports_added) facts.push(plural(change.reports_added, 'new report'));
  if (change.reports_refreshed) facts.push(plural(change.reports_refreshed, 'report') + ' refreshed');
  if (change.reports_removed) facts.push(plural(change.reports_removed, 'report') + ' removed');
  return facts;
}

/** "Edited «Mean petal length» on tab Overview". */
export function dashboardChangeText(change: DashboardChange): string {
  const title = change.component_title ? `«${change.component_title}»` : 'a component';
  const tab = change.tab_title ? ` on tab ${change.tab_title}` : '';
  switch (change.kind) {
    case 'component_added':
      return `Added ${title}${tab}`;
    case 'component_removed':
      return `Removed ${title}${tab}`;
    case 'component_edited':
      return `Edited ${title}${tab}`;
    case 'tab_added':
      return `Added tab ${change.tab_title}`;
    case 'tab_removed':
      return `Removed tab ${change.tab_title}`;
    case 'tab_renamed':
      return `Renamed tab ${change.tab_title}`;
    default:
      return 'Changed the dashboard';
  }
}

/**
 * Where a dashboard row's "Open in History" goes: the editor's History at that
 * version for someone who can edit, the read-only `?version=` preview for
 * everyone else. A removed tab has no page of its own, so it falls back to the
 * tab being viewed.
 */
export function historyHref(
  change: Pick<DashboardChange, 'version_id' | 'tab_id' | 'kind'>,
  viewedTabId: string,
  canEdit: boolean,
): string | null {
  if (!change.version_id) return null;
  const tab = change.kind === 'tab_removed' || !change.tab_id ? viewedTabId : change.tab_id;
  const at = encodeURIComponent(change.version_id);
  return canEdit
    ? `/dashboard-edit/${viewedTabId}?settings=history&at=${at}`
    : `/dashboard/${tab}?version=${at}`;
}

/** The pill's text. */
export function pillLabel(
  since: string | null,
  query: ReadOnlyQuery,
  formatRelative: (raw: unknown) => string,
  formatDate: (raw: unknown) => string,
): string {
  if (query.beforeRun) return 'Changes from this ingestion';
  if (query.since) return `Changed since ${formatDate(query.since)}`;
  return `Changed since ${formatRelative(since)}`;
}

/** Where a comment row leads: the drawer on its component, or its tab. */
export function commentTarget(
  comment: Pick<CommentChange, 'tab_id' | 'component_index'>,
  viewedTabId: string,
): { sameTab: boolean; tabHref: string | null } {
  const sameTab = !comment.tab_id || comment.tab_id === viewedTabId;
  return { sameTab, tabHref: sameTab ? null : `/dashboard/${comment.tab_id}` };
}
