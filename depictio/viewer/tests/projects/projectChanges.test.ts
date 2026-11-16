/**
 * The rules behind the project's "changed since" pill, the runs' "Produced"
 * block and the Timeline tab: the anonymous reader's browser-held mark, which
 * dashboard version stood before a run, and which commits and reports belong
 * to a run.
 *
 * Run like tests/builder (the viewer package has no vitest of its own):
 *   pnpm --filter depictio-react-core exec vitest run --root ../../depictio/viewer tests/projects
 */
import { beforeEach, describe, expect, it } from 'vitest';
import type {
  DashboardVersionSummary,
  DeltaVersionEntry,
  MonitoringIngestionRun,
  ProjectChangeSet,
} from 'depictio-react-core';

import {
  baselineStorageKey,
  changeCount,
  clearMemoryBaselines,
  commitsForRun,
  compareHref,
  findVersionBeforeRun,
  firstIngestionOf,
  ingestionsForRun,
  isNewerThan,
  newestVersionBefore,
  readStoredBaseline,
  readTabRequest,
  reportsForRun,
  sampleCount,
  versionHref,
  writeStoredBaseline,
  type MarkStorage,
} from '../../src/projects/detail/projectChanges';

const fakeStorage = (): MarkStorage & { data: Map<string, string> } => {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
  };
};

const blocked: MarkStorage = {
  getItem: () => {
    throw new Error('blocked');
  },
  setItem: () => {
    throw new Error('blocked');
  },
};

const version = (seq: number, created_at: string): DashboardVersionSummary =>
  ({ version_id: `v${seq}`, family_id: 'fam', seq, created_at }) as DashboardVersionSummary;

beforeEach(() => clearMemoryBaselines());

describe('the browser-held mark', () => {
  it('is keyed per project', () => {
    expect(baselineStorageKey('p1')).toBe('depictio.projectChangesSince.v1:p1');
  });

  it('round-trips a baseline', () => {
    const s = fakeStorage();
    expect(readStoredBaseline('p1', s)).toBeNull();
    expect(writeStoredBaseline('p1', { seen_at: '2026-11-12T10:00:00', runs: ['a'] }, s)).toBe(true);
    expect(readStoredBaseline('p1', s)).toEqual({ seen_at: '2026-11-12T10:00:00', runs: ['a'] });
    expect(readStoredBaseline('p2', s)).toBeNull();
  });

  it('treats unreadable or foreign values as no mark', () => {
    const s = fakeStorage();
    s.setItem(baselineStorageKey('p1'), '{not json');
    expect(readStoredBaseline('p1', s)).toBeNull();
    s.setItem(baselineStorageKey('p1'), JSON.stringify({ nothing: 1 }));
    expect(readStoredBaseline('p1', s)).toBeNull();
  });

  it('survives blocked storage for the page', () => {
    expect(writeStoredBaseline('p1', { seen_at: '2026-11-12T10:00:00' }, blocked)).toBe(false);
    expect(readStoredBaseline('p1', blocked)).toEqual({ seen_at: '2026-11-12T10:00:00' });
    expect(readStoredBaseline('p1', null)).toEqual({ seen_at: '2026-11-12T10:00:00' });
  });
});

describe('the pill', () => {
  const cs = (over: Partial<ProjectChangeSet>): ProjectChangeSet => ({
    project_id: 'p',
    first_visit: false,
    since: '2026-11-12T10:00:00',
    data: [],
    new_runs: [],
    failed_ingestions: [],
    dashboards: [],
    server_held: true,
    ...over,
  });

  it('counts nothing on a first visit or without a change set', () => {
    expect(changeCount(null)).toBe(0);
    expect(changeCount(cs({ first_visit: true, since: null }))).toBe(0);
    expect(changeCount(cs({}))).toBe(0);
  });

  it('counts runs, collections, failures and dashboards', () => {
    const run = { workflow_id: 'w', run_tag: 'r', run_location: null, registered: null };
    expect(
      changeCount(
        cs({
          new_runs: [run, run],
          failed_ingestions: [{ run_id: 'x', status: 'failed', run_tags: [], data_collection_tags: [], at: null }],
          dashboards: [{ family_id: 'f', title: 't', versions: 2, authors: [] }],
        }),
      ),
    ).toBe(4);
  });

  it('marks only events after the mark as new', () => {
    expect(isNewerThan('2026-11-12T11:00:00', '2026-11-12T10:00:00')).toBe(true);
    expect(isNewerThan('2026-11-12 09:00:00', '2026-11-12T10:00:00')).toBe(false);
    expect(isNewerThan('2026-11-12T11:00:00', null)).toBe(false);
    expect(isNewerThan('garbage', '2026-11-12T10:00:00')).toBe(false);
  });
});

describe('the dashboard version before a run', () => {
  const versions = [
    version(4, '2026-11-12 12:00:00'),
    version(3, '2026-11-12 09:30:00'),
    version(2, '2026-11-12 09:00:00'),
    version(1, '2026-11-11 08:00:00'),
  ];

  it('picks the newest version created before the ingestion started', () => {
    expect(newestVersionBefore(versions, '2026-11-12 10:00:00')?.version_id).toBe('v3');
    expect(newestVersionBefore([...versions].reverse(), '2026-11-12 10:00:00')?.version_id).toBe('v3');
  });

  it('is strictly before: a version made at the start does not count', () => {
    expect(newestVersionBefore(versions, '2026-11-12 09:30:00')?.version_id).toBe('v2');
  });

  it('is null when none predates the run or the start is unusable', () => {
    expect(newestVersionBefore(versions, '2026-11-10 00:00:00')).toBeNull();
    expect(newestVersionBefore(versions, null)).toBeNull();
    expect(newestVersionBefore(versions, 'soon')).toBeNull();
    expect(newestVersionBefore([], '2026-11-12 10:00:00')).toBeNull();
  });

  it('reads older pages until one predates the run', async () => {
    const pages: Record<string, DashboardVersionSummary[]> = {
      first: [version(6, '2026-11-12 12:00:00'), version(5, '2026-11-12 11:00:00')],
      '5': [version(4, '2026-11-12 10:30:00'), version(3, '2026-11-12 09:30:00')],
    };
    const asked: Array<number | undefined> = [];
    const hit = await findVersionBeforeRun(async (beforeSeq) => {
      asked.push(beforeSeq);
      return { versions: pages[beforeSeq === undefined ? 'first' : String(beforeSeq)] ?? [], total: 6 };
    }, '2026-11-12 10:00:00');
    expect(hit?.version_id).toBe('v3');
    expect(asked).toEqual([undefined, 5]);
  });

  it('stops at the first version and at the page bound', async () => {
    expect(
      await findVersionBeforeRun(
        async () => ({ versions: [version(1, '2026-11-12 12:00:00')], total: 1 }),
        '2026-11-12 10:00:00',
      ),
    ).toBeNull();
    let calls = 0;
    expect(
      await findVersionBeforeRun(
        async (before) => {
          calls += 1;
          const seq = (before ?? 100) - 1;
          return { versions: [version(seq, '2026-11-12 12:00:00')], total: 100 };
        },
        '2026-11-12 10:00:00',
        3,
      ),
    ).toBeNull();
    expect(calls).toBe(3);
  });
});

describe('what a run produced', () => {
  const ing = (run_id: string, run_tags: string[] | undefined, started_at: string) =>
    ({ run_id, run_tags, started_at, status: 'success', command: 'ingest' }) as MonitoringIngestionRun;

  it('finds the ingestions that brought a run, oldest first', () => {
    const runs = [
      ing('i3', ['run_c'], '2026-11-12 12:00:00'),
      ing('i2', ['run_b'], '2026-11-12 11:00:00'),
      ing('i1', ['run_c', 'run_b'], '2026-11-12 10:00:00'),
      ing('i0', undefined, '2026-11-12 09:00:00'),
    ];
    const found = ingestionsForRun(runs, 'run_c');
    expect(found.map((r) => r.run_id)).toEqual(['i1', 'i3']);
    expect(firstIngestionOf(found)?.run_id).toBe('i1');
    expect(firstIngestionOf(ingestionsForRun(runs, 'nope'))).toBeNull();
  });

  const commit = (version: number, meta: Record<string, string>, run_id?: string): DeltaVersionEntry => ({
    version,
    rows_added: 10,
    metadata: meta,
    run_id,
    origin: 'both',
  });

  it('matches commits by the run tags in their metadata', () => {
    const entries = [
      commit(3, { 'depictio.run_tags': 'run_b,run_c' }),
      commit(2, { 'depictio.run_tags': 'run_b' }, 'i1'),
      commit(1, { 'depictio.run_tags': 'run_a' }),
    ];
    expect(commitsForRun(entries, 'run_c', ['i1']).map((e) => e.version)).toEqual([3]);
  });

  it('falls back to the ingestion when a commit names no runs, or its list was capped', () => {
    const entries = [
      commit(4, {}, 'i1'),
      commit(3, {}, 'other'),
      commit(2, { 'depictio.run_tags': 'a,b,+30 more' }, 'i1'),
      commit(1, { 'depictio.run_tags': 'a,b' }, 'i1'),
    ];
    expect(commitsForRun(entries, 'run_c', ['i1']).map((e) => e.version)).toEqual([4, 2]);
  });

  it('matches reports by run tag, or by ingestion when the report records no run', () => {
    const reports = [
      { run_tag: 'run_c', metadata: { canonical_samples: ['s1', 's2'] } },
      { run_tag: 'run_b', metadata: { canonical_samples: ['s3'] } },
      { run_tag: null, ingestion_run_id: 'i1', metadata: { samples: ['s2', 's9'] } },
      { run_tag: null, ingestion_run_id: 'zzz', metadata: { samples: ['s7'] } },
    ];
    const mine = reportsForRun(reports, 'run_c', ['i1']);
    expect(mine).toHaveLength(2);
    expect(sampleCount(mine)).toBe(3);
  });
});

describe('links and the tab request', () => {
  it('builds the dashboard links', () => {
    expect(compareHref('fam', 'run id')).toBe('/dashboard/fam?before_run=run%20id');
    expect(versionHref('fam', 'v1')).toBe('/dashboard/fam?version=v1');
  });

  it('reads ?tab= and ?run=', () => {
    expect(readTabRequest('?tab=runs&run=run_c')).toEqual({ tab: 'runs', run: 'run_c' });
    expect(readTabRequest('?tab=timeline')).toEqual({ tab: 'timeline', run: null });
    expect(readTabRequest('?run=run_c')).toEqual({ tab: 'runs', run: 'run_c' });
    expect(readTabRequest('?tab=bogus')).toEqual({ tab: null, run: null });
    expect(readTabRequest('')).toEqual({ tab: null, run: null });
  });
});
