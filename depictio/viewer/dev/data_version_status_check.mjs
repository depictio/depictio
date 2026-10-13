/**
 * What the data-version banners say, executed over server-shaped status.
 *
 * Run:  cd depictio/viewer && pnpm run check:dataversionstatus
 *
 * Both banners once generalised from what the client inferred: "every value on
 * this dashboard is computed from the pinned dataset version", "layout,
 * components and data are all from this version". Neither held when one
 * collection was left on its latest data, another had recorded no data
 * version, or a MultiQC tile ignored the pin. The text now comes from
 * `POST /dashboards/data_version_status/{id}`; this asserts every collection
 * is named in the right group and no sentence claims all of the data.
 */

import {
  currentDataOnlyNote,
  describeDataVersionStatus,
  groupStatus,
} from '../src/versions/dataVersionStatus';

let failures = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}: ${JSON.stringify(got)}`);
  if (!ok) {
    console.log(`      want ${JSON.stringify(want)}`);
    failures++;
  }
}

// What the endpoint returns for the penguins fixture under one version: one
// collection pinned at commit 0, one kept on its latest data, one unstamped.
const status = [
  {
    dc_id: 'dc-a',
    workflow_tag: 'wf',
    data_collection_tag: 'penguins',
    dc_type: 'table',
    status: 'pinned',
    delta_version: 0,
    reason: null,
  },
  {
    dc_id: 'dc-b',
    workflow_tag: 'wf',
    data_collection_tag: 'islands',
    dc_type: 'table',
    status: 'live',
    delta_version: null,
    reason: 'Latest data chosen for this collection',
  },
  {
    dc_id: 'dc-c',
    workflow_tag: 'wf',
    data_collection_tag: null,
    dc_type: 'multiqc',
    status: 'not_versioned',
    delta_version: null,
    reason: 'No data version recorded',
  },
];

const text = describeDataVersionStatus(status);

console.log('1. Each collection is named in its own group');
check(
  'the full sentence',
  text,
  'Past data: penguins (v0). Latest data: islands. ' +
    'No data version recorded, so the latest data is shown: dc-c.',
);
const grouped = groupStatus(status);
check('pinned', grouped.pinned.map((p) => p.dcId), ['dc-a']);
check('live', grouped.live.map((p) => p.dcId), ['dc-b']);
check('not versioned', grouped.notVersioned.map((p) => p.dcId), ['dc-c']);

console.log('\n2. No sentence claims all of the data');
// The very phrases the old banners used, plus the obvious variants.
const forbidden = [/every value/i, /all data/i, /\ball\b.*from this version/i, /entire/i];
const samples = [
  text,
  describeDataVersionStatus([status[0]]),
  describeDataVersionStatus([status[1]]),
  describeDataVersionStatus([status[2]]),
  describeDataVersionStatus([]),
  currentDataOnlyNote(1),
  currentDataOnlyNote(3),
];
for (const sample of samples) {
  check(`no generalisation in "${sample}"`, forbidden.some((re) => re.test(sample)), false);
}

console.log('\n3. Commit 0 is a version, a missing one is not invented');
check('v0 is shown', describeDataVersionStatus([status[0]]), 'Past data: penguins (v0).');
check(
  'pinned without a number names the collection only',
  describeDataVersionStatus([{ ...status[0], delta_version: null }]),
  'Past data: penguins.',
);

console.log('\n4. Edge cases');
check('no collections', describeDataVersionStatus([]), 'No data collection on this tab.');
check('no current-data tiles -> no note', currentDataOnlyNote(0), null);
check('one tile', currentDataOnlyNote(1), 'The tile marked Current data shows the latest data.');
check('three tiles', currentDataOnlyNote(3), 'The 3 tiles marked Current data show the latest data.');

console.log();
if (failures) {
  console.log(`FAILED (${failures})`);
  process.exit(1);
}
console.log('ALL PASS');
