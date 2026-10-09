/**
 * Does a renderer refetch when its definition is replaced in place?
 *
 * Restoring a single component swaps its definition while its `index` — the
 * only thing the fetch effects keyed on — stays the same. The chart kept
 * showing the old render until a page reload, and cards did not, because their
 * values come from the dashboard's bulk-compute pass rather than a renderer.
 *
 * "Works after refresh" is the signature of a missing dependency, and a
 * dependency array is not something a compile can check.
 */

import { renderDefinitionKey } from '../../../packages/depictio-react-core/src/renderKey';
import {
  isTableReady,
  tableGridIdentity,
  tableGridKey,
} from '../../../packages/depictio-react-core/src/components/tableVersionFollow';

let failures = 0;
function check(label, got, want) {
  const ok = got === want;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}: ${got}`);
  if (!ok) {
    console.log(`      want ${want}`);
    failures++;
  }
}

const base = {
  index: 'abc',
  component_type: 'figure',
  dc_id: 'dc1',
  wf_id: 'wf1',
  visu_type: 'box',
  dict_kwargs: { x: 'petal.length', y: 'variety' },
  last_updated: '2026-01-01T00:00:00',
};

console.log('1. The same definition yields the same key');
check('stable', renderDefinitionKey(base) === renderDefinitionKey({ ...base }), true);

console.log('\n2. Anything that changes the render changes the key');
// Each of these is a real difference between two versions of a component in
// the demo, and each must force a refetch.
const changes = {
  'chart type (histogram -> box)': { visu_type: 'histogram' },
  'axes / dict_kwargs': { dict_kwargs: { x: 'sepal.width', y: 'variety' } },
  'collection repointed': { dc_id: 'dc2' },
  'workflow repointed': { wf_id: 'wf2' },
  'card column': { column_name: 'petal.width' },
  'card aggregation': { aggregation: 'count' },
  'table columns': { columns: ['a', 'b'] },
  'save stamp': { last_updated: '2026-06-01T00:00:00' },
};
for (const [label, patch] of Object.entries(changes)) {
  check(label, renderDefinitionKey({ ...base, ...patch }) !== renderDefinitionKey(base), true);
}

console.log('\n3. Presentation-only changes do NOT refetch');
// These change many times a second while dragging. Refetching on them would
// hammer the API for renders that would come back identical.
const cosmetic = {
  'grid position': { x: 4, y: 2 },
  'size': { w: 6, h: 3 },
  'title colour': { title_color: '#ff0000' },
  'title size': { title_size: 'h1' },
};
for (const [label, patch] of Object.entries(cosmetic)) {
  check(label, renderDefinitionKey({ ...base, ...patch }) === renderDefinitionKey(base), true);
}

console.log('\n4. A missing or absent component is handled');
check('null', renderDefinitionKey(null), '');
check('undefined', renderDefinitionKey(undefined), '');

console.log('\n5. A restore that only reverts the definition still refetches');
// The exact scenario reported: same id, same position, definition rolled back
// to a previous version. If these keys matched, the chart would not reload.
const restored = { ...base, visu_type: 'histogram', last_updated: base.last_updated };
check(
  'restored component differs from live',
  renderDefinitionKey(restored) !== renderDefinitionKey(base),
  true,
);

console.log('\n6. The definition version is part of the key');
// A preview or the component-history modal reads the definition from a stored
// version the client never sees. Two versions can hold identical local
// metadata (the overlay already swapped it in) yet different server-side
// definitions; without the id in the key, stepping between them keeps the
// first chart.
check('v1 differs from live', renderDefinitionKey(base, 'v1') !== renderDefinitionKey(base), true);
check('v1 differs from v2', renderDefinitionKey(base, 'v1') !== renderDefinitionKey(base, 'v2'), true);
check('null is live', renderDefinitionKey(base, null) === renderDefinitionKey(base), true);
check('absent component with a version -> empty', renderDefinitionKey(null, 'v1'), '');

console.log('\n7. The table follows a pin or definition change after mount');
// The table grid is an infinite-row model: its datasource is installed once.
// Before, changing the data version under a mounted table kept the rows of
// the first one. The grid identity is what remounts it.
const live = tableGridIdentity('{}', renderDefinitionKey(base));
const pinned = tableGridIdentity('{"data_versions":{"dc1":0}}', renderDefinitionKey(base));
const defV1 = tableGridIdentity('{}', renderDefinitionKey(base, 'v1'));
check('a pin changes the identity', live !== pinned, true);
check('a definition version changes the identity', live !== defV1, true);
check('the grid key moves with it', tableGridKey(false, 1, live) !== tableGridKey(false, 1, pinned), true);
// Ready is derived, not stored: the render right after the change must not
// count as ready for the new identity, or the grid would mount once with the
// previous datasource and fetch the old rows.
check('ready for the identity it bootstrapped', isTableReady(live, live), true);
check('not ready for a new identity', isTableReady(live, pinned), false);
check('not ready before any bootstrap', isTableReady(null, live), false);

console.log();
if (failures) {
  console.log(`FAILED (${failures})`);
  process.exit(1);
}
console.log('ALL PASS');
