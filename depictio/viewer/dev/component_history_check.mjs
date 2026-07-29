/**
 * The component-history modal's decisions, executed rather than read.
 *
 * Every previous check on this feature inspected the source and passed while
 * the feature did not work — twice. So this imports the real functions the
 * modal uses and asserts on what they produce.
 *
 * Four claims the modal makes to a user:
 *
 *   1. picking a version reads that version's data (data travel follows the
 *      version by default);
 *   2. choosing a commit explicitly overrides the version's own stamp, so
 *      "same chart, different data" and "different chart, same data" are both
 *      reachable — the whole point of separating the two axes;
 *   3. the compare pane is drawn from *live* data, or it is not a comparison
 *      against current;
 *   4. Delta version 0 survives every hop. It is falsy, and the first commit
 *      is the one people most want to reach.
 */

import { dataVersionBody } from '../../../packages/depictio-react-core/src/dataVersions';
// The real functions the modal calls, not a re-implementation of them.
import { pinsForComponent, resolveDataVersion } from '../src/versions/dataVersionChoice';

let failures = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}: ${JSON.stringify(got)}`);
  if (!ok) {
    console.log(`      want ${JSON.stringify(want)}`);
    failures++;
  }
}

const DC = '646b0f3c1e4a2d7f8e5b9003';

function bodyFor(args) {
  return dataVersionBody({ pins: pinsForComponent(DC, resolveDataVersion(args)) });
}

console.log('1. By default the data follows the selected version');
check(
  'v1 Survey (stamped delta 0)',
  bodyFor({ dataOverride: undefined, useHistoricalData: true, versionDataVersion: 0 }),
  { data_versions: { [DC]: 0 } },
);
check(
  'v4 Complete (stamped delta 3)',
  bodyFor({ dataOverride: undefined, useHistoricalData: true, versionDataVersion: 3 }),
  { data_versions: { [DC]: 3 } },
);

console.log('\n2. "Historical data" off reads current data, keeping the old config');
check(
  'toggle off',
  bodyFor({ dataOverride: undefined, useHistoricalData: false, versionDataVersion: 0 }),
  {},
);

console.log('\n3. An explicit commit overrides the version, in both directions');
// Old config against today's data: "has this chart's answer changed?"
check(
  'v1 config + live data',
  bodyFor({ dataOverride: null, useHistoricalData: true, versionDataVersion: 0 }),
  {},
);
// Today's config against old data: "what would this chart have shown then?"
check(
  'v4 config + delta 0',
  bodyFor({ dataOverride: 0, useHistoricalData: true, versionDataVersion: 3 }),
  { data_versions: { [DC]: 0 } },
);
// The override must win even when the toggle says otherwise, or the select
// would silently do nothing while the toggle is off.
check(
  'override beats the toggle',
  bodyFor({ dataOverride: 2, useHistoricalData: false, versionDataVersion: 3 }),
  { data_versions: { [DC]: 2 } },
);

console.log('\n4. Delta version 0 is not swallowed as falsy');
check('pin at commit 0', pinsForComponent(DC, 0), { [DC]: 0 });
check('body at commit 0', dataVersionBody({ pins: { [DC]: 0 } }), {
  data_versions: { [DC]: 0 },
});

console.log('\n5. The compare pane reads live data');
// The "current" half is rendered with `pins={{}}` — hardcoded, not derived —
// so this asserts the value that hardcoding must produce. A compare view whose
// second pane inherited the pin would show the same thing twice.
check('current pane body', dataVersionBody({ pins: {} }), {});

console.log('\n6. Each distinct selection produces a distinct effect key');
// The renderers key their fetch effects on this string. Two selections sharing
// a key means the body changes while the fetch never re-runs — stale numbers
// under a new label, which is exactly how this feature failed before.
const keys = [0, 1, 2, 3].map((v) => JSON.stringify(dataVersionBody({ pins: { [DC]: v } })));
keys.push(JSON.stringify(dataVersionBody({ pins: {} })));
check('distinct keys', new Set(keys).size, keys.length);

console.log();
if (failures) {
  console.log(`FAILED (${failures})`);
  process.exit(1);
}
console.log('ALL PASS');
