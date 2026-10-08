/**
 * Contract check for version preview.
 *
 * Run:  cd depictio/viewer && pnpm run check:preview
 *
 * The server overlays a version's content onto the live document
 * (`GET /dashboards/get/{id}?version_id=`), so the client no longer merges
 * snapshots. What it still owns is the render half: every render request of a
 * preview has to carry the version's data pins (`as_of_version`) and its
 * component definitions (`component_overrides`), or a past layout is drawn
 * through today's definitions over today's data and labelled as the past.
 *
 * Executes the real `previewDataRequest` and `dataVersionBody` rather than a
 * reimplementation: a check that restates the logic can only confirm the
 * restatement agrees with itself. There is no JS test runner in this tree, so
 * this is a plain script over hand-built fixtures shaped exactly like the API
 * response the viewer consumes.
 */

import {
  extractPreviewVersionId,
  overridesFromVersion,
  previewDataRequest,
} from '../src/versions/preview.ts';
// Straight at the source file, as the sibling checks do: importing the package
// entry pulls in every React component it re-exports, which esbuild cannot
// resolve from this directory.
import { dataVersionBody } from '../../../packages/depictio-react-core/src/dataVersions';

let failures = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}`);
  if (!ok) console.log(`        got ${JSON.stringify(actual)} want ${JSON.stringify(expected)}`);
}

// What GET /dashboards/get/{id} returns for the live dashboard.
const live = {
  dashboard_id: 'dash-1',
  project_id: 'proj-1',
  permissions: { owners: [{ email: 'admin@example.com' }] },
  is_public: false,
  title: 'Q4 report',
  stored_metadata: [{ index: 'a', aggregation: 'max' }],
  left_panel_layout_data: [],
  right_panel_layout_data: [{ i: 'a', x: 0, y: 0, w: 8, h: 2 }],
  last_saved_ts: '2026-07-29 10:00:00',
};

// What GET /dashboards/get/{id}?version_id=v-abc returns: the version's content
// laid over the live document, plus the `preview` block.
const overlaid = {
  ...live,
  title: 'Q3 report',
  stored_metadata: [
    { index: 'a', aggregation: 'average' },
    { index: 'b', visu_type: 'histogram' },
  ],
  right_panel_layout_data: [
    { i: 'a', x: 0, y: 0, w: 4, h: 6 },
    { i: 'b', x: 4, y: 0, w: 4, h: 3 },
  ],
  preview: {
    version_id: 'v-abc',
    seq: 3,
    label: null,
    kind: 'explicit',
    pinned: false,
    created_at: '2026-07-01 09:00:00',
    author_email: 'admin@example.com',
  },
};

console.log('— a live dashboard adds nothing to render requests —');
check('no preview block -> null', previewDataRequest(live), null);
check('no dashboard yet -> null', previewDataRequest(null), null);
check('a live read sends neither key', Object.keys(dataVersionBody({})), []);

console.log('— the data follows the previewed version —');
const req = previewDataRequest(overlaid);
check('as-of is the version from the preview block', req?.asOfVersionId, 'v-abc');

console.log('— the overlaid definitions travel as component_overrides —');
check('every overlaid component is keyed by index', Object.keys(req?.componentOverrides ?? {}).sort(), [
  'a',
  'b',
]);
// The bug this guards: the card's live definition says `max`, the version
// says `average`. The override has to carry the version's, not the live one.
check('the version definition wins, not the live one', req?.componentOverrides?.a, {
  index: 'a',
  aggregation: 'average',
});
check(
  'a preview of an empty tab sends no overrides key',
  previewDataRequest({ ...overlaid, stored_metadata: [] })?.componentOverrides,
  undefined,
);

console.log('— the pins follow the server, not the URL —');
// `?version=` in the URL is not proof the overlay was applied. Pinning data on
// the strength of the URL alone would draw the live layout over past data.
global.window = { location: { search: '?version=v-abc' } };
check('URL says preview, payload does not -> null', previewDataRequest(live), null);

console.log('— overridesFromVersion —');
check('a component with no index is skipped', overridesFromVersion([{ title: 'x' }]), {});
check('undefined metadata is empty, not a throw', overridesFromVersion(undefined), {});

// The seam that actually matters: the request has to survive into the body.
// Checking `previewDataRequest` alone would pass even if the body builder
// dropped a key on the way.
console.log('— the request reaches the body —');
const body = dataVersionBody(req ?? {});
check('as_of_version reaches the body', body.as_of_version, 'v-abc');
check('component_overrides reaches the body', Object.keys(body.component_overrides ?? {}).sort(), [
  'a',
  'b',
]);
check('no stray data_versions for a whole-version preview', 'data_versions' in body, false);

console.log('— ?version= parsing —');
global.window = { location: { search: '?version=abc123' } };
check('reads the id', extractPreviewVersionId(), 'abc123');
global.window = { location: { search: '' } };
check('absent -> null', extractPreviewVersionId(), null);
global.window = { location: { search: '?version=%20%20' } };
check('blank -> null', extractPreviewVersionId(), null);

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
