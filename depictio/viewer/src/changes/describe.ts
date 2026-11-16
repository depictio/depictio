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

import { compactCount } from '../monitoring/format';

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

/**
 * What the panel lists, counted as it lists it: one per new run (however many
 * collections it refreshed), one per collection no run explains, one per
 * failed ingestion. A recomputation over every run follows from the new runs
 * and adds nothing.
 */
export function changeCounts(cs: DashboardChangeSet | null): ChangeCounts {
  const news = newsByRun(cs?.data ?? []);
  const data = news.runs.length + news.other.length + (cs?.failed_ingestions.length ?? 0);
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

/** "1 run", "12 runs", "2.6k rows": counts read the same in every feed. */
export const plural = (n: number, one: string, many = `${one}s`) => `${compactCount(n)} ${n === 1 ? one : many}`;

/**
 * How the row count moved. The totals win when both are known: an overwrite
 * reports no added rows, and a run-scoped write (`replace-runs`) counts the
 * rewritten rows of an edited run as written, so "+N" would overstate what
 * is new. The sum of written rows is shown only when no total is.
 */
export function rowsFact(
  change: Pick<DataChange, 'rows_added' | 'rows_before' | 'rows_after'>,
  fmt: (n: number) => string,
): string | null {
  const { rows_before: before, rows_after: after, rows_added: added } = change;
  if (before != null && after != null) return before === after ? null : `${fmt(before)} \u2192 ${fmt(after)} rows`;
  return added && added > 0 ? `+${fmt(added)} rows` : null;
}

/** The facts on one data row, as short phrases ("1 new run", "150 → 154 rows"). */
export function dataFacts(change: DataChange): string[] {
  const facts: string[] = [];
  if (change.new_run_tags.length) facts.push(plural(change.new_run_tags.length, 'new run'));
  const rows = rowsFact(change, compactCount);
  if (rows) facts.push(rows);
  const { total } = sampleSummary(change);
  if (total > 0) facts.push(plural(total, 'new sample'));
  if (change.reports_added) facts.push(plural(change.reports_added, 'new report'));
  if (change.reports_refreshed) facts.push(plural(change.reports_refreshed, 'report') + ' refreshed');
  if (change.reports_removed) facts.push(plural(change.reports_removed, 'report') + ' removed');
  // A collection that mixes samples is recomputed over every run: the rows of
  // runs already seen changed too, so "seen before" is not what it was.
  const recomputed = change.recomputed_run_tags ?? [];
  if (recomputed.length) facts.push(`recomputed: ${plural(recomputed.length, 'run')} seen before changed`);
  return facts;
}

/** What one new run brought: the collections that gained its rows, and the
 *  collections that mix samples, recomputed because it came in. */
export interface RunNews {
  run: string;
  collections: DataChange[];
  /** New samples, from the tables that name this run alone (not MultiQC). */
  samples: number;
  /** When the run arrived and who brought it, read off the collections that
   *  gained this run alone: a collection's last commit may be a later run's. */
  at: string | null;
  by: string[];
}

export interface NewsByRun {
  /** Newest first. */
  runs: RunNews[];
  /** Recipes recomputed over every run: listed once, not under each run. */
  recomputed: DataChange[];
  /** What no new run explains, listed by collection. */
  other: DataChange[];
}

/** Newest first; a run with no time of its own after the dated ones, by name. */
function newestFirst(a: RunNews, b: RunNews): number {
  if (a.at && b.at && a.at !== b.at) return a.at < b.at ? 1 : -1;
  if (Boolean(a.at) !== Boolean(b.at)) return a.at ? -1 : 1;
  return b.run.localeCompare(a.run, undefined, { numeric: true });
}

/**
 * The data news read run by run, the way runs arrive (epic #1399), rather
 * than collection by collection. A collection that gained several runs is
 * listed under each. A recipe recomputed over every run belongs to no run in
 * particular (its rows mix the runs' samples), so it is listed once, apart.
 * What no new run explains (a rewrite in place, an emptied table, a MultiQC
 * refresh) is `other`, listed by collection.
 */
export function newsByRun(data: DataChange[]): NewsByRun {
  const newRuns = unique(
    data.filter((d) => d.kind === 'refreshed').flatMap((d) => d.new_run_tags),
  );
  const byRun = new Map<string, RunNews>(
    newRuns.map((run) => [run, { run, collections: [], samples: 0, at: null, by: [] }]),
  );
  const recomputed: DataChange[] = [];
  const other: DataChange[] = [];
  for (const d of data) {
    const refreshed = d.kind === 'refreshed';
    if (refreshed && d.run_scope === 'aggregate' && newRuns.length > 0) {
      recomputed.push(d);
      continue;
    }
    if (refreshed && d.new_run_tags.length > 0) {
      const alone = d.new_run_tags.length === 1;
      for (const run of d.new_run_tags) {
        const news = byRun.get(run);
        if (!news) continue;
        news.collections.push(d);
        // The server dates each run by the commit that wrote it; without that
        // (an older server), only a collection that gained this run alone does.
        const at = d.run_at?.[run] ?? (alone ? d.at : null);
        if (at && (!news.at || at > news.at)) news.at = at;
        const by = d.run_by?.[run] ?? (alone ? d.by : null);
        if (by) news.by = unique([...news.by, ...by]);
        if (!alone) continue;
        // MultiQC lists an entry per read and per module, not per sample: only a
        // table counts the run's samples.
        if (d.dc_type !== 'multiqc') news.samples = Math.max(news.samples, sampleSummary(d).total);
      }
      continue;
    }
    other.push(d);
  }
  return { runs: [...byRun.values()].sort(newestFirst), recomputed, other };
}

/** "3 collections · 29 new samples". */
export function runFacts(news: RunNews): string[] {
  const out: string[] = [];
  if (news.collections.length) out.push(plural(news.collections.length, 'collection'));
  if (news.samples > 0) out.push(plural(news.samples, 'new sample'));
  return out;
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

/** A project's Runs tab, with one run in focus. */
export function projectRunsHref(projectId: string, runTag?: string): string {
  const base = `/projects/${encodeURIComponent(projectId)}`;
  return runTag ? `${base}?tab=runs&run=${encodeURIComponent(runTag)}` : base;
}
