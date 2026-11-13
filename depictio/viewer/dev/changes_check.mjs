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
  parseReadOnlyQuery,
  pillLabel,
  sampleSummary,
} from '../src/changes/describe.ts';
import { beforePane, diffTables } from '../src/changes/compare.ts';

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

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
