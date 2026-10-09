/**
 * Contract check for version preview.
 *
 * Run:  cd depictio/viewer && pnpm run check:preview
 *
 * The server overlays a version's content onto the live document
 * (`GET /dashboards/get/{id}?version_id=`), so the client no longer merges
 * snapshots. What it still owns is the render half: every render request of a
 * preview has to carry the version's data pins (`as_of_version`) and the
 * version to read component definitions from (`definition_version`), or a past
 * layout is drawn through today's definitions over today's data and labelled
 * as the past.
 *
 * The client sends no definitions of its own any more: the server reads them
 * from the stored version, and `component_overrides` is refused with a 400.
 * So this also asserts the old key never comes back.
 *
 * Executes the real `previewDataRequest` and `dataVersionBody` rather than a
 * reimplementation: a check that restates the logic can only confirm the
 * restatement agrees with itself. There is no JS test runner in this tree, so
 * this is a plain script over hand-built fixtures shaped exactly like the API
 * response the viewer consumes.
 */

import {
  definitionVersionFromPreview,
  extractPreviewVersionId,
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

console.log('== a live dashboard adds nothing to render requests ==');
check('no preview block -> null', previewDataRequest(live), null);
check('no dashboard yet -> null', previewDataRequest(null), null);
check('a live read sends neither key', Object.keys(dataVersionBody({})), []);

console.log('== the data and the definitions follow the previewed version ==');
const req = previewDataRequest(overlaid);
check('as-of is the version from the preview block', req?.asOfVersionId, 'v-abc');
// The bug this guards: the card's live definition says `max`, the version
// says `average`. The server reads the version's definition when it is told
// which version, so the request has to name it.
check('the definition version is the previewed one', req?.definitionVersionId, 'v-abc');
check('definitionVersionFromPreview reads the block', definitionVersionFromPreview(overlaid), 'v-abc');
check('definitionVersionFromPreview on live -> null', definitionVersionFromPreview(live), null);

console.log('== the pins follow the server, not the URL ==');
// `?version=` in the URL is not proof the overlay was applied. Pinning data on
// the strength of the URL alone would draw the live layout over past data.
global.window = { location: { search: '?version=v-abc' } };
check('URL says preview, payload does not -> null', previewDataRequest(live), null);

// The seam that actually matters: the request has to survive into the body.
// Checking `previewDataRequest` alone would pass even if the body builder
// dropped a key on the way.
console.log('== the request reaches the body ==');
const body = dataVersionBody(req ?? {});
check('as_of_version reaches the body', body.as_of_version, 'v-abc');
check('definition_version reaches the body', body.definition_version, 'v-abc');
check('no component_overrides: the server refuses it', 'component_overrides' in body, false);
check('no stray data_versions for a whole-version preview', 'data_versions' in body, false);
check(
  'the editor sends no definition version (data only)',
  'definition_version' in dataVersionBody({ asOfVersionId: 'v-abc', pins: {} }),
  false,
);

console.log('== ?version= parsing ==');
global.window = { location: { search: '?version=abc123' } };
check('reads the id', extractPreviewVersionId(), 'abc123');
global.window = { location: { search: '' } };
check('absent -> null', extractPreviewVersionId(), null);
global.window = { location: { search: '?version=%20%20' } };
check('blank -> null', extractPreviewVersionId(), null);

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
