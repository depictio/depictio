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

console.log('\n5. Each compare pane picks its own commit');
// The right pane resolves independently of the left, and deliberately ignores
// `useHistoricalData` — that switch describes the version being examined, and
// this pane is not it.
function comparePane(compareOverride) {
  return dataVersionBody({
    pins: pinsForComponent(
      DC,
      resolveDataVersion({
        dataOverride: compareOverride,
        useHistoricalData: false,
        versionDataVersion: undefined,
      }),
    ),
  });
}

// Default: live. "Compare against current" has to mean current.
check('current pane defaults to live', comparePane(null), {});
// Pointed at a commit, it reads that commit.
check('current pane pinned to v1', comparePane(1), { data_versions: { [DC]: 1 } });
// And commit 0 survives here too, on the pane whose default is `null` — the
// one place where falsy-vs-null confusion is most likely.
check('current pane pinned to v0', comparePane(0), { data_versions: { [DC]: 0 } });

console.log('\n6. Holding the data equal isolates the configuration change');
// The point of per-pane selection: with both sides on the same commit, the
// only difference left between the two charts is the definition. If these
// bodies diverge, the "same data on both sides" hint would be a lie.
const leftAtV1 = bodyFor({
  dataOverride: 1,
  useHistoricalData: true,
  versionDataVersion: 0,
});
check('left pinned to v1 matches right pinned to v1', leftAtV1, comparePane(1));

console.log('\n7. Each distinct selection produces a distinct effect key');
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
