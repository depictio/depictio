/**
 * Contract check for version preview.
 *
 * Run:  cd depictio/viewer && npm run check:preview
 *
 * Executes the real `dashboardFromVersion` rather than a reimplementation of
 * it. That distinction matters here: the bug this guards against was a merge
 * that silently dropped `project_id`, and any check that restates the merge
 * can only confirm the restatement agrees with itself.
 *
 * There is no JS test runner in this tree, so this is a plain script over
 * hand-built fixtures shaped exactly like the two API responses the viewer
 * consumes. Assertions live on the seam, so they stay meaningful whatever the
 * rendering layer does downstream.
 */

import {
  dashboardFromVersion,
  extractPreviewVersionId,
} from '../src/versions/preview.ts';

let failures = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}`);
  if (!ok) console.log(`        got ${JSON.stringify(actual)} want ${JSON.stringify(expected)}`);
}

const OLD_LAYOUT = [
  { i: 'a', x: 0, y: 0, w: 4, h: 6 },
  { i: 'b', x: 4, y: 0, w: 4, h: 3 },
];

// What GET /dashboards/get/{id} returns today.
const live = {
  dashboard_id: 'dash-1',
  project_id: 'proj-1',
  permissions: { owners: [{ email: 'admin@example.com' }] },
  is_public: false,
  title: 'Q4 report',
  stored_metadata: [{ index: 'a' }],
  left_panel_layout_data: [],
  right_panel_layout_data: [{ i: 'a', x: 0, y: 0, w: 8, h: 2 }],
  last_saved_ts: '2026-07-29 10:00:00',
};

// What GET /dashboards/versions/{vid} returns: no project_id/permissions.
const version = {
  version_id: 'v-abc',
  family_id: 'dash-1',
  seq: 3,
  kind: 'explicit',
  pinned: false,
  created_at: '2026-07-01T09:00:00',
  updated_at: '2026-07-01T09:00:00',
  save_count: 1,
  content_hash: 'x',
  tab_count: 2,
  component_count: 2,
  data_version_kinds: {},
  project_id: 'proj-1',
  data_collections: [],
  tabs: [
    {
      dashboard_id: 'dash-1',
      is_main_tab: true,
      tab_order: 0,
      title: 'Q3 report',
      subtitle: '',
      stored_metadata: [{ index: 'a' }, { index: 'b' }],
      left_panel_layout_data: [],
      right_panel_layout_data: OLD_LAYOUT,
    },
    {
      dashboard_id: 'dash-2',
      is_main_tab: false,
      tab_order: 1,
      title: 'Tab 2',
      subtitle: '',
      stored_metadata: [{ index: 'c' }],
      left_panel_layout_data: [],
      right_panel_layout_data: [],
    },
  ],
};

console.log('— content comes from the version —');
const merged = dashboardFromVersion(version, 'dash-1', live);
check('exact layout geometry restored', merged.right_panel_layout_data, OLD_LAYOUT);
check('components from the version', merged.stored_metadata.length, 2);
check('title from the version', merged.title, 'Q3 report');

console.log('— identity/access come from the live doc —');
check('project_id survives (data resolution)', merged.project_id, 'proj-1');
check('permissions survive (notes footer)', merged.permissions, live.permissions);
check('dashboard_id is the live one', merged.dashboard_id, 'dash-1');

console.log('— addressing a child tab —');
const child = dashboardFromVersion(version, 'dash-2', live);
check('child tab content selected', child.stored_metadata, [{ index: 'c' }]);
check('child still carries project_id', child.project_id, 'proj-1');

console.log('— a tab absent from the snapshot falls back to main —');
const missing = dashboardFromVersion(version, 'dash-99', live);
check('falls back to main tab', missing.stored_metadata.length, 2);
check('keeps the addressed identity', missing.dashboard_id, 'dash-1');

console.log('— a snapshot with no tabs is an error, not a blank screen —');
let threw = false;
try {
  dashboardFromVersion({ ...version, tabs: [] }, 'dash-1', live);
} catch {
  threw = true;
}
check('empty snapshot raises', threw, true);

console.log('— ?version= parsing —');
global.window = { location: { search: '?version=abc123' } };
check('reads the id', extractPreviewVersionId(), 'abc123');
global.window = { location: { search: '' } };
check('absent -> null', extractPreviewVersionId(), null);
global.window = { location: { search: '?version=%20%20' } };
check('blank -> null', extractPreviewVersionId(), null);

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
