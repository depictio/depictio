/**
 * Pure rules behind the project's "changed since" pill, the runs' "Produced"
 * block and the Timeline tab, kept out of the components so they can be tested
 * without a DOM.
 *
 * Timestamps are compared as received: the API sends naive strings and
 * `parseTs` reads every one of them the same way. Ingestion runs are stored
 * with a local clock today, so a comparison across sources (a dashboard
 * version against an ingestion's start) is only as good as the two clocks
 * agree; callers show the times and never claim more.
 */
import type {
  DashboardVersionSummary,
  DeltaVersionEntry,
  MonitoringIngestionRun,
  ProjectChangeSet,
  ReaderBaseline,
} from 'depictio-react-core';

import { parseTs } from '../../monitoring/format';
import type { CheckOutcome } from '../checkStatus';
import { commitLineage } from './deltaHistory';

// ── the anonymous reader's mark ─────────────────────────────────────────────

/** The part of Storage this module uses, so a test can pass a fake. */
export interface MarkStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export const baselineStorageKey = (projectId: string) =>
  `depictio.projectChangesSince.v1:${projectId}`;

/** Where the mark lives when storage is blocked: this page only. */
const memory = new Map<string, string>();

function browserStorage(): MarkStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

/** The mark an anonymous or temporary reader keeps in the browser; `null` when
 *  there is none, or what is stored is not a baseline. */
export function readStoredBaseline(
  projectId: string,
  storage: MarkStorage | null = browserStorage(),
): ReaderBaseline | null {
  const key = baselineStorageKey(projectId);
  let raw: string | null = null;
  try {
    raw = storage?.getItem(key) ?? null;
  } catch {
    raw = null;
  }
  raw = raw ?? memory.get(key) ?? null;
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && typeof (parsed as { seen_at?: unknown }).seen_at === 'string') {
      return parsed as ReaderBaseline;
    }
  } catch {
    // Fall through: an unreadable mark counts as none.
  }
  return null;
}

/** Keep the mark. Returns whether the browser took it (storage may be blocked;
 *  the mark then lives for this page only). */
export function writeStoredBaseline(
  projectId: string,
  baseline: ReaderBaseline,
  storage: MarkStorage | null = browserStorage(),
): boolean {
  const key = baselineStorageKey(projectId);
  const value = JSON.stringify(baseline);
  memory.set(key, value);
  try {
    if (!storage) return false;
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

/** Forget the in-page copy (tests). */
export function clearMemoryBaselines(): void {
  memory.clear();
}

// ── the change set ──────────────────────────────────────────────────────────

/** How many things the pill counts. Zero on a first visit: nothing is "new"
 *  to a reader who has no mark yet. */
export function changeCount(cs: ProjectChangeSet | null | undefined): number {
  if (!cs || cs.first_visit) return 0;
  return cs.data.length + cs.new_runs.length + cs.failed_ingestions.length + cs.dashboards.length;
}

/** Whether an event happened after the reader's mark. */
export function isNewerThan(at: string | null | undefined, since: string | null | undefined): boolean {
  if (!at || !since) return false;
  const a = parseTs(at);
  const s = parseTs(since);
  return !Number.isNaN(a) && !Number.isNaN(s) && a > s;
}

// ── what a run produced ─────────────────────────────────────────────────────

const ts = (value: string | null | undefined): number => {
  const t = parseTs(value);
  return Number.isNaN(t) ? Number.POSITIVE_INFINITY : t;
};

/** The project's ingestions that brought a run in, oldest first. */
export function ingestionsForRun(
  runs: MonitoringIngestionRun[],
  runTag: string,
): MonitoringIngestionRun[] {
  return runs
    .filter((r) => (r.run_tags ?? []).includes(runTag))
    .sort((a, b) => ts(a.started_at) - ts(b.started_at));
}

/** The ingestion that first brought a run in: what "before this run" means. */
export function firstIngestionOf(ingestions: MonitoringIngestionRun[]): MonitoringIngestionRun | null {
  return ingestions[0] ?? null;
}

/** The run tags a Delta commit records in its metadata (comma-joined, with a
 *  trailing "+N more" when the list was capped). */
export function commitRunTags(entry: DeltaVersionEntry): { tags: string[]; capped: boolean } {
  const raw = entry.metadata?.['depictio.run_tags'];
  if (!raw) return { tags: [], capped: false };
  const parts = raw.split(',').map((p) => p.trim()).filter(Boolean);
  const capped = parts.some((p) => /^\+\d+ more$/.test(p));
  return { tags: parts.filter((p) => !/^\+\d+ more$/.test(p)), capped };
}

/** The Delta commits of a collection that carry a run: the run named in the
 *  commit metadata (rows it wrote, or for a recomputation over every run, a
 *  run it read) or, when the commit does not name its runs (or the list was
 *  capped), one of the ingestions that brought the run in. */
export function commitsForRun(
  entries: DeltaVersionEntry[],
  runTag: string,
  ingestionIds: Iterable<string>,
): DeltaVersionEntry[] {
  const ids = new Set(ingestionIds);
  return entries.filter((e) => {
    const { tags, capped } = commitRunTags(e);
    if (tags.includes(runTag)) return true;
    if (commitLineage(e).computedFrom.includes(runTag)) return true;
    if (tags.length > 0 && !capped) return false;
    return Boolean(e.run_id && ids.has(e.run_id));
  });
}

export interface ReportLike {
  run_tag?: string | null;
  ingestion_run_id?: string | null;
  metadata?: { samples?: string[]; canonical_samples?: string[] };
}

/** The MultiQC reports of a run: its `run_tag`, or for a report that records
 *  no run, the ingestion that stored it. */
export function reportsForRun<T extends ReportLike>(
  reports: T[],
  runTag: string,
  ingestionIds: Iterable<string>,
): T[] {
  const ids = new Set(ingestionIds);
  return reports.filter((r) => {
    if (r.run_tag) return r.run_tag === runTag;
    return Boolean(r.ingestion_run_id && ids.has(r.ingestion_run_id));
  });
}

/** Distinct samples across reports (canonical ids when the report has them). */
export function sampleCount(reports: ReportLike[]): number {
  const seen = new Set<string>();
  for (const r of reports) {
    const list = r.metadata?.canonical_samples?.length ? r.metadata.canonical_samples : r.metadata?.samples;
    for (const s of list ?? []) seen.add(s);
  }
  return seen.size;
}

/** How an ingestion's status reads in the project's check vocabulary. */
export function ingestionOutcome(status: string | null | undefined): CheckOutcome {
  switch (status) {
    case 'success':
      return 'ok';
    case 'failed':
      return 'fail';
    case 'partial':
    case 'interrupted':
    case 'abandoned':
      return 'warn';
    case 'running':
      return 'info';
    default:
      return 'unknown';
  }
}

// ── dashboards as they were before a run ────────────────────────────────────

/** The newest version created before `startedAt`, from a list that may be in
 *  any order. `null` when none predates it, or `startedAt` is unusable. */
export function newestVersionBefore(
  versions: DashboardVersionSummary[],
  startedAt: string | null | undefined,
): DashboardVersionSummary | null {
  const limit = parseTs(startedAt);
  if (Number.isNaN(limit)) return null;
  let best: DashboardVersionSummary | null = null;
  let bestAt = Number.NEGATIVE_INFINITY;
  for (const v of versions) {
    const at = parseTs(v.created_at);
    if (Number.isNaN(at) || at >= limit) continue;
    if (at > bestAt) {
      best = v;
      bestAt = at;
    }
  }
  return best;
}

export interface VersionPage {
  versions: DashboardVersionSummary[];
  total: number;
}

/** The dashboard version that was current just before an ingestion started,
 *  reading the history newest first, one page at a time, until a version
 *  predates it. Bounded: a family with more than `maxPages` pages of newer
 *  versions answers `null` rather than reading all of them. */
export async function findVersionBeforeRun(
  fetchPage: (beforeSeq?: number) => Promise<VersionPage>,
  startedAt: string | null | undefined,
  maxPages = 5,
): Promise<DashboardVersionSummary | null> {
  let beforeSeq: number | undefined;
  for (let i = 0; i < maxPages; i += 1) {
    const page = await fetchPage(beforeSeq);
    const hit = newestVersionBefore(page.versions, startedAt);
    if (hit) return hit;
    if (page.versions.length === 0) return null;
    const oldest = Math.min(...page.versions.map((v) => v.seq));
    if (!Number.isFinite(oldest) || oldest <= 1) return null;
    beforeSeq = oldest;
  }
  return null;
}

// ── links ───────────────────────────────────────────────────────────────────

export const compareHref = (familyId: string, ingestionRunId: string) =>
  `/dashboard/${familyId}?before_run=${encodeURIComponent(ingestionRunId)}`;

export const versionHref = (familyId: string, versionId: string) =>
  `/dashboard/${familyId}?version=${encodeURIComponent(versionId)}`;

/** The project page's tabs. */
export const PROJECT_TABS = ['overview', 'runs', 'activity'] as const;
export type ProjectTab = (typeof PROJECT_TABS)[number];

/** The two views of the Activity tab: the latest ingestion's report, and what
 *  happened before it. */
export type ActivityView = 'report' | 'history';

/** Older names still in links: the Ingestion report and Timeline tabs became
 *  the two views of Activity. */
const TAB_ALIASES: Record<string, { tab: ProjectTab; view: ActivityView }> = {
  activity: { tab: 'activity', view: 'report' },
  ingestion: { tab: 'activity', view: 'report' },
  timeline: { tab: 'activity', view: 'history' },
};

/** A tab (and view) from a name or a hash: `ingestion`, `#ingestion-history`. */
export function resolveTab(name: string | null | undefined): {
  tab: ProjectTab;
  view: ActivityView | null;
} | null {
  const key = (name ?? '').replace(/^#/, '');
  if (key === 'ingestion-history') return { tab: 'activity', view: 'history' };
  if (TAB_ALIASES[key]) return TAB_ALIASES[key];
  if ((PROJECT_TABS as readonly string[]).includes(key)) return { tab: key as ProjectTab, view: null };
  return null;
}

/** `?tab=runs&run=run_c`: the tab (and run, or Activity view) a link asks the page to open. */
export function readTabRequest(search: string): {
  tab: ProjectTab | null;
  view: ActivityView | null;
  run: string | null;
} {
  const params = new URLSearchParams(search);
  const run = params.get('run') || null;
  const known = resolveTab(params.get('tab'));
  // A run named without a tab still means the Runs tab.
  return { tab: known?.tab ?? (run ? 'runs' : null), view: known?.view ?? null, run };
}
