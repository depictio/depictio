/**
 * Contract check for "changed since your last visit" (#1397).
 *
 * Run:  cd depictio/viewer && pnpm run check:changes
 *
 * Executes the real helpers in `src/changes/describe.ts` over fixtures shaped
 * like `POST /changes/dashboard/{id}`: which URL params make a read-only view,
 * when the pill shows, what a dot's tooltip says, and where "Open in History"
 * leads. The browser-held mark (`changesStore`) has its own vitest in
 * `packages/depictio-react-core`.
 */

import {
  changeCounts,
  commentTarget,
  dashboardChangeText,
  dataFacts,
  hasChanges,
  historyHref,
  isReadOnlyQuery,
  markDetails,
  newsByRun,
  parseReadOnlyQuery,
  runFacts,
  pillLabel,
  sampleSummary,
} from '../src/changes/describe.ts';
import { beforePane, diffTables } from '../src/changes/compare.ts';
import { focusedRuns, newSideOnly, newsSplitGroups } from '../src/changes/newsSplit.ts';
import { commitLineage, entriesForRun, historyRuns, scopeLabel } from '../src/projects/detail/deltaHistory.ts';
import { commitsForRun } from '../src/projects/detail/projectChanges.ts';

let failures = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}`);
  if (!ok) console.log(`        got ${JSON.stringify(actual)} want ${JSON.stringify(expected)}`);
}

const empty = {
  family_id: 'fam',
  first_visit: false,
  since: '2026-11-01 10:00:00',
  approximate: false,
  data: [],
  failed_ingestions: [],
  dashboard: [],
  comments: [],
  changed_components: {},
  baseline_version_id: 'v1',
  server_held: true,
  mark_mode: 'sticky',
};
const data = {
  dc_id: 'dc1',
  dc_type: 'table',
  workflow_tag: 'wf',
  data_collection_tag: 'samples',
  kind: 'refreshed',
  new_run_tags: ['run_c'],
  touched_run_tags: [],
  rows_added: 5,
  new_samples: ['s1', 's2', 's3', 's4', 's5', 's6', 's7'],
  new_sample_count: 7,
  ingestion_run_ids: ['r1'],
  by: ['a@b'],
  at: '2026-11-02 10:00:00',
};
const edit = {
  kind: 'component_edited',
  tab_id: 'tab1',
  tab_title: 'Overview',
  component_index: 'c1',
  component_title: 'Mean length',
  key: 'tab1:c1',
  authors: ['a@b'],
  version_id: 'ver-9',
  seq: 9,
  at: '2026-11-02 11:00:00',
};
const changed = {
  ...empty,
  data: [data],
  dashboard: [edit],
  changed_components: { 'tab1:c1': ['definition', 'data'], 'tab1:c2': ['data'] },
};

console.log('== read-only URL params ==');
check('?since=', parseReadOnlyQuery('?since=2026-10-01T00:00:00Z'), { since: '2026-10-01T00:00:00Z', beforeRun: null });
check('?before_run=', parseReadOnlyQuery('?before_run=run-1'), { since: null, beforeRun: 'run-1' });
check('blank values are none', parseReadOnlyQuery('?since=%20&before_run='), { since: null, beforeRun: null });
check('a plain URL is not read-only', isReadOnlyQuery(parseReadOnlyQuery('?version=v1')), false);
check('since is read-only', isReadOnlyQuery(parseReadOnlyQuery('?since=x')), true);

console.log('== when the pill shows ==');
check('first visit: hidden', hasChanges({ ...changed, first_visit: true }), false);
check('nothing changed: hidden', hasChanges(empty), false);
check('no change set: hidden', hasChanges(null), false);
check('something changed: shown', hasChanges(changed), true);
check('a failed ingestion alone counts', hasChanges({ ...empty, failed_ingestions: [{ run_id: 'x' }] }), true);
check('counts', changeCounts(changed), { data: 1, dashboard: 1, comments: 0, total: 2 });

console.log('== the pill label ==');
const rel = () => '3 days ago';
const date = () => '2026-10-01';
check('relative', pillLabel('x', { since: null, beforeRun: null }, rel, date), 'Changed since 3 days ago');
check('?since= shows a date', pillLabel('x', { since: 'y', beforeRun: null }, rel, date), 'Changed since 2026-10-01');
check('?before_run= names the ingestion', pillLabel('x', { since: null, beforeRun: 'r' }, rel, date), 'Changes from this ingestion');

console.log('== a dot says why ==');
const details = markDetails(changed);
check('definition + data', details['tab1:c1'], ['Definition changed by a@b', 'Data refreshed: run_c']);
check('data only', details['tab1:c2'], ['Data refreshed: run_c']);
check('no run tags: the collection', markDetails({ ...changed, data: [{ ...data, new_run_tags: [] }] })['tab1:c2'], [
  'Data refreshed: samples',
]);
check('no change set', markDetails(null), {});

console.log('== data rows ==');
check('facts', dataFacts(data), ['1 new run', '+5 rows', '7 new samples']);
check('up to five samples, then +N', sampleSummary(data), {
  shown: ['s1', 's2', 's3', 's4', 's5'],
  more: 2,
  total: 7,
});
check('count only (no names)', sampleSummary({ new_sample_count: 2 }), { shown: [], more: 2, total: 2 });
check('an overwrite shows the totals', dataFacts({ ...data, new_run_tags: [], new_samples: [], new_sample_count: 0, rows_added: 0, rows_before: 150, rows_after: 154 }), [
  '150 \u2192 154 rows',
]);
check('a run-scoped rewrite counts by totals, not rows written', dataFacts({ ...data, new_run_tags: [], new_samples: [], new_sample_count: 0, rows_added: 50, rows_before: 150, rows_after: 154 }), [
  '150 \u2192 154 rows',
]);
check('same total says nothing about rows', dataFacts({ ...data, new_run_tags: [], new_samples: [], new_sample_count: 0, rows_added: 50, rows_before: 150, rows_after: 150 }), []);
check('singular', dataFacts({ ...data, rows_added: 0, new_sample_count: 1, new_samples: ['s1'] }), [
  '1 new run',
  '1 new sample',
]);
check('a recomputation says the seen runs changed', dataFacts({ ...data, new_samples: [], new_sample_count: 0, rows_added: 0, recomputed_run_tags: ['athens', 'barcelona'] }), [
  '1 new run',
  'recomputed: 2 runs seen before changed',
]);

console.log('== news by run (#1399) ==');
const ch = (tag, extra) => ({ ...data, dc_id: tag, data_collection_tag: tag, new_samples: [], new_sample_count: 0, ...extra });
const byRun = newsByRun([
  ch('samplesheet', { new_run_tags: ['naples'], new_samples: ['s1', 's2'], new_sample_count: 2 }),
  ch('alpha', { new_run_tags: ['naples'] }),
  ch('bray', { new_run_tags: ['naples'], run_scope: 'aggregate', recomputed_run_tags: ['athens'] }),
  ch('upset', { new_run_tags: [], run_scope: 'aggregate', recomputed_run_tags: ['athens'] }),
  ch('metadata', { new_run_tags: [] }),
  // MultiQC names a sample per read and per module: 243 "samples" for 30.
  ch('mqc', { new_run_tags: ['naples'], dc_type: 'multiqc', new_samples: ['s1', 's1 - Read 1'], new_sample_count: 243 }),
]);
check('one entry per new run', byRun.runs.map((r) => r.run), ['naples']);
check('collections that gained the run', byRun.runs[0].collections.map((d) => d.dc_id), ['samplesheet', 'alpha', 'mqc']);
check('recomputed listed once, whether or not its rows name the run', byRun.recomputed.map((d) => d.dc_id), ['bray', 'upset']);
check('a rewrite in place stays by collection', byRun.other.map((d) => d.dc_id), ['metadata']);
check('run facts', runFacts(byRun.runs[0]), ['3 collections', '2 new samples']);
check('the pill counts runs, not the collections they refreshed', changeCounts({ ...empty, data: [
  ch('a', { new_run_tags: ['barcelona', 'naples'] }),
  ch('b', { new_run_tags: ['barcelona', 'naples'] }),
  ch('c', { new_run_tags: ['naples'] }),
  ch('upset', { new_run_tags: [], run_scope: 'aggregate' }),
  ch('metadata', { new_run_tags: [] }),
] }).data, 3);
check('no new run: everything by collection', newsByRun([ch('a', { new_run_tags: [] })]).runs, []);
const dated = newsByRun([
  ch('a1', { new_run_tags: ['athens'], at: '2026-11-01T10:00:00Z', by: ['a@x'] }),
  ch('n1', { new_run_tags: ['naples'], at: '2026-11-03T10:00:00Z', by: ['n@x'] }),
  ch('b1', { new_run_tags: ['barcelona'], at: '2026-11-02T10:00:00Z', by: [] }),
  // Its last commit is naples': it dates neither run.
  ch('both', { new_run_tags: ['athens', 'naples'], at: '2026-11-04T10:00:00Z', by: ['late@x'] }),
  ch('r2', { new_run_tags: ['run_2'], at: null, by: [] }),
  ch('r10', { new_run_tags: ['run_10'], at: null, by: [] }),
]);
check('newest first, undated after, by name', dated.runs.map((r) => r.run), ['naples', 'barcelona', 'athens', 'run_10', 'run_2']);
check('a run is dated by the collections it alone brought', dated.runs[2].at, '2026-11-01T10:00:00Z');
check('nor authored by a later run', dated.runs[2].by, ['a@x']);
const both = newsByRun([
  ch('t', {
    new_run_tags: ['athens', 'naples'],
    at: '2026-11-04T10:00:00',
    run_at: { athens: '2026-11-01T10:00:00', naples: '2026-11-03T10:00:00' },
    run_by: { athens: ['a@x'], naples: ['n@x'] },
  }),
]);
check('the server dates each run of a collection that gained several', both.runs.map((r) => [r.run, r.at, r.by]), [
  ['naples', '2026-11-03T10:00:00', ['n@x']],
  ['athens', '2026-11-01T10:00:00', ['a@x']],
]);

console.log('== runs and lineage of a commit (#1399) ==');
const meta = (m) => ({ origin: 'delta', version: 1, metadata: m });
const perRun = meta({ 'depictio.run_tags': 'naples', 'depictio.run_scope': 'run' });
const aggregate = meta({
  'depictio.run_tags': 'athens,naples',
  'depictio.computed_from': 'athens,barcelona,naples',
  'depictio.run_scope': 'aggregate',
  'depictio.inputs': 'taxonomy_heatmap@3,metadata@2',
});
const fileBacked = meta({ 'depictio.run_tags': 'barcelona' });
const anonymous = meta({});
check('lineage of an aggregate', commitLineage(aggregate), {
  scope: 'aggregate',
  runTags: ['athens', 'naples'],
  computedFrom: ['athens', 'barcelona', 'naples'],
  inputs: [{ tag: 'taxonomy_heatmap', version: '3' }, { tag: 'metadata', version: '2' }],
  capped: false,
});
check('aggregate label', scopeLabel(commitLineage(aggregate)), 'recomputed over 3 runs');
check('per-run label', scopeLabel(commitLineage(perRun)), 'per run');
check('a file-backed commit has no scope', scopeLabel(commitLineage(fileBacked)), null);
check('runs of a history', historyRuns([perRun, aggregate, fileBacked]), ['athens', 'barcelona', 'naples']);
check('filter: a run read by a recomputation counts', entriesForRun([perRun, aggregate, fileBacked, anonymous], 'barcelona'), [aggregate, fileBacked, anonymous]);
check('no filter keeps everything', entriesForRun([perRun, aggregate], null).length, 2);
check('a run sees the recomputation that read it', commitsForRun([perRun, aggregate, fileBacked], 'barcelona', []), [aggregate, fileBacked]);

console.log('== dashboard rows ==');
check('edit text', dashboardChangeText(edit), 'Edited «Mean length» on tab Overview');
check('tab text', dashboardChangeText({ ...edit, kind: 'tab_added' }), 'Added tab Overview');
check('editor reads go to History at the version', historyHref(edit, 'tab1', true), '/dashboard-edit/tab1?settings=history&at=ver-9');
check('others get the preview', historyHref(edit, 'tab1', false), '/dashboard/tab1?version=ver-9');
check('a removed tab previews the viewed tab', historyHref({ ...edit, kind: 'tab_removed', tab_id: 'gone' }, 'tab1', false), '/dashboard/tab1?version=ver-9');
check('no version, no link', historyHref({ ...edit, version_id: null }, 'tab1', true), null);

console.log('== comment rows ==');
check('same tab', commentTarget({ tab_id: 'tab1', component_index: 'c1' }, 'tab1'), { sameTab: true, tabHref: null });
check('another tab', commentTarget({ tab_id: 'tab2', component_index: 'c1' }, 'tab1'), { sameTab: false, tabHref: '/dashboard/tab2' });

console.log('== before | now ==');
const pointsDiff = {
  supported: true,
  shape: 'points',
  key_column: 'id',
  x: 'sepal',
  y: 'petal',
  color: null,
  counts: { added: 1, removed: 1, changed: 1, before: 3, after: 3 },
  added: [{ key: 'n1', x: 1, y: 2 }],
  removed: [{ key: 'r1', x: 5, y: 6 }],
  changed: [{ key: 'm1', before: { key: 'm1', x: 3, y: 3 }, after: { key: 'm1', x: 4, y: 3 } }],
  delta_from: 2,
  delta_to: 3,
};
check(
  'a figure pins its collection to the commit it compared from',
  beforePane('figure', 'dc1', pointsDiff, 'ver-4'),
  { kind: 'render', state: { pins: { dc1: 2 }, definitionVersionId: 'ver-4' } },
);
check(
  'a card, with no diff, follows the version stamps',
  beforePane('card', 'dc1', { supported: false, reason: 'no' }, 'ver-4'),
  {
    kind: 'render',
    state: { asOfVersionId: 'ver-4', definitionVersionId: 'ver-4' },
    note: 'The data shown follows the dashboard version of your last visit.',
  },
);
check('multiqc without report ids follows the version stamps', beforePane('multiqc', 'dc1', pointsDiff, 'ver-4').state, {
  asOfVersionId: 'ver-4',
  definitionVersionId: 'ver-4',
});
const samplesDiff = {
  supported: true,
  shape: 'samples',
  counts: { added: 1, removed: 0, before: 2, after: 3 },
  added: ['S3'],
  removed: [],
  report_ids_before: ['r1', 'r2'],
};
check('multiqc pins the report set the reader saw', beforePane('multiqc', 'dc1', samplesDiff, 'ver-4').state, {
  reportSets: { dc1: ['r1', 'r2'] },
  definitionVersionId: 'ver-4',
});
check('advanced viz is not redrawn', beforePane('advanced_viz', 'dc1', pointsDiff, 'ver-4').kind, 'unavailable');
check('nothing stored, nothing to pin', beforePane('card', 'dc1', null, null).kind, 'unavailable');
check('a pin works without a stored version', beforePane('table', 'dc1', pointsDiff, null), {
  kind: 'render',
  state: { pins: { dc1: 2 }, definitionVersionId: null },
});
const tables = diffTables(pointsDiff);
check('point tables: new, gone, moved', tables.map((t) => t.id), ['added', 'removed', 'changed']);
check('moved row shows before to after', tables[2].rows, [['m1', '3 \u2192 4', '3']]);
const unkeyed = {
  ...pointsDiff,
  key_column: null,
  color: 'variety',
  added: [{ key: null, x: 1, y: 2, color: 'Setosa' }],
  changed: [],
};
check('an unkeyed point leads with its colour', [diffTables(unkeyed)[0].columns, diffTables(unkeyed)[0].rows], [
  ['variety', 'sepal', 'petal'],
  [['Setosa', '1', '2']],
]);
check('no key, no colour: x and y alone', diffTables({ ...unkeyed, color: null })[0].columns, ['sepal', 'petal']);
const many = { ...pointsDiff, added: Array.from({ length: 60 }, (_, i) => ({ key: `k${i}`, x: i, y: i })) };
check('first 50 rows, then a count', [diffTables(many)[0].rows.length, diffTables(many)[0].more], [50, 10]);
check(
  'sample table',
  diffTables({ supported: true, shape: 'samples', counts: {}, added: ['s1'], removed: [] })[0].rows,
  [['s1']],
);
check('unsupported has no table', diffTables({ supported: false, reason: 'x' }), []);

// The "what's new" split: new runs against the runs seen before.
const COLORS = { fresh: '#159090', seen: '#adb5bd' };
const delta = (over) => ({
  dc_id: 'dc1',
  dc_type: 'table',
  kind: 'refreshed',
  new_run_tags: ['run_3'],
  touched_run_tags: ['run_1', 'run_2', 'run_3'],
  seen_run_tags: ['run_1', 'run_2'],
  ingestion_run_ids: [],
  by: [],
  at: null,
  ...over,
});
check('split: new run against the runs seen', newsSplitGroups({ ...empty, data: [delta({})] }, COLORS), {
  groups: [
    { name: 'New: run_3', column_name: 'depictio_run_id', values: ['run_3'], color: '#159090' },
    { name: 'Seen before', column_name: 'depictio_run_id', values: ['run_1', 'run_2'], color: '#adb5bd' },
  ],
  showOther: false,
  samples: {},
});
console.log('== one run in focus (#1399) ==');
const twoNew = { ...empty, data: [delta({ new_run_tags: ['run_3', 'run_4'], seen_run_tags: ['run_1', 'run_2'] })] };
check('focus: that run against every other', newsSplitGroups(twoNew, COLORS, 'run_4'), {
  groups: [
    { name: 'New: run_4', column_name: 'depictio_run_id', values: ['run_4'], color: '#159090' },
    { name: 'Other runs', column_name: 'depictio_run_id', values: ['run_1', 'run_2', 'run_3'], color: '#adb5bd' },
  ],
  showOther: false,
  samples: {},
});
check('focus: a run that is not new is ignored', newsSplitGroups(twoNew, COLORS, 'run_1'), newsSplitGroups(twoNew, COLORS));
const mqcTwo = { ...empty, data: [delta({ new_run_tags: ['run_3', 'run_4'] }), { ...delta({}), dc_id: 'm', new_run_tags: ['run_3', 'run_4'], new_samples: ['a'], seen_samples: ['b'], new_sample_count: 1 }] };
check('focus: MultiQC samples that mix runs are not split', Object.keys(newsSplitGroups(mqcTwo, COLORS, 'run_4').samples), []);
check('focus: the new runs a collection shows', focusedRuns({ a: ['run_3', 'run_4'], b: ['run_3'] }, 'run_4'), { a: ['run_4'] });
check('focus: none, every new run', focusedRuns({ a: ['run_3'] }, null), { a: ['run_3'] });

check('split: no new run, no split', newsSplitGroups({ ...empty, data: [delta({ new_run_tags: [] })] }, COLORS), null);
check(
  'split: no seen runs and no samples, no split',
  newsSplitGroups({ ...empty, data: [delta({ seen_run_tags: undefined })] }, COLORS),
  null,
);
check(
  'split: nothing seen keeps the rest as Other',
  newsSplitGroups({ ...empty, data: [delta({ seen_run_tags: [], new_run_tags: ['a', 'b'] })] }, COLORS),
  {
    groups: [{ name: 'New: 2 runs', column_name: 'depictio_run_id', values: ['a', 'b'], color: '#159090' }],
    showOther: true,
    samples: {},
  },
);
const mqc = (over) => ({
  dc_id: 'mqc1',
  dc_type: 'multiqc',
  kind: 'refreshed',
  new_run_tags: ['run_c'],
  touched_run_tags: ['run_c'],
  new_samples: ['S3_1'],
  new_sample_count: 1,
  seen_samples: ['S1_1', 'S2_1'],
  ingestion_run_ids: [],
  by: [],
  at: null,
  ...over,
});
check('split: MultiQC splits on its own samples', newsSplitGroups({ ...empty, data: [mqc({})] }, COLORS), {
  groups: [],
  showOther: false,
  samples: {
    mqc1: [
      { name: 'New: run_c', column_name: 'sample', values: ['S3_1'], color: '#159090', dc_id: 'mqc1' },
      { name: 'Seen before', column_name: 'sample', values: ['S1_1', 'S2_1'], color: '#adb5bd', dc_id: 'mqc1' },
    ],
  },
});
check(
  'split: a truncated sample list is not split',
  newsSplitGroups({ ...empty, data: [mqc({ new_sample_count: 300 })] }, COLORS),
  null,
);
check(
  'split: no samples seen, no MultiQC split',
  newsSplitGroups({ ...empty, data: [mqc({ seen_samples: null })] }, COLORS),
  null,
);

check(
  'new only: the first side of each split, nothing left over',
  newSideOnly({
    groups: [{ name: 'New: run_c', column_name: 'depictio_run_id', values: ['run_c'] }, { name: 'Seen before', column_name: 'depictio_run_id', values: ['run_a'] }],
    showOther: true,
    samples: { mqc1: [{ name: 'New', column_name: 'sample', values: ['S3_1'] }, { name: 'Seen before', column_name: 'sample', values: ['S1_1'] }] },
  }),
  {
    groups: [{ name: 'New: run_c', column_name: 'depictio_run_id', values: ['run_c'] }],
    showOther: false,
    samples: { mqc1: [{ name: 'New', column_name: 'sample', values: ['S3_1'] }] },
    mode: 'new',
  },
);

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
