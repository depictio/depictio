/**
 * Does a pin chosen in the picker actually reach the request body?
 *
 * The API returns 50/100/100/150 correctly and the source reads correctly, yet
 * the running dashboard showed 150 at every version and the backend logged
 * zero requests carrying `data_versions`. That gap is a state-flow bug, not a
 * logic bug, so this executes the pin update `DatasetVersionPicker` calls
 * (`withPin`) and `dataVersionBody`, and asserts on the body that results.
 *
 * Executing rather than reading is the point: every previous check inspected
 * the code and passed while the feature did not work.
 */

import { dataVersionBody } from '../../../packages/depictio-react-core/src/dataVersions';
// The real functions the picker calls, not a re-implementation of them.
import { LIVE, withPin } from '../src/versions/dataVersionChoice';

let failures = 0;
function check(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}: ${JSON.stringify(got)}`);
  if (!ok) {
    console.log(`      want ${JSON.stringify(want)}`);
    failures++;
  }
}

// --- The exact sequence the UI performs when a user picks "v0" -------------
//
// `withPin` builds the next pins object, the editor stores it, and
// `dataVersionBody` turns it into a request fragment.
const DC = '646b0f3c1e4a2d7f8e5b9003';

check('picking v0 pins version 0', withPin({}, DC, '0'), { [DC]: 0 });
check(
  'v0 survives into the request body',
  dataVersionBody({ pins: withPin({}, DC, '0') }),
  { data_versions: { [DC]: 0 } },
);
check(
  'picking v2 then back to live clears it',
  dataVersionBody({ pins: withPin(withPin({}, DC, '2'), DC, LIVE) }),
  {},
);
check(
  'switching v0 -> v3 replaces rather than accumulates',
  dataVersionBody({ pins: withPin(withPin({}, DC, '0'), DC, '3') }),
  { data_versions: { [DC]: 3 } },
);

// --- The dependency key that drives refetching ------------------------------
//
// The body changing is necessary but not sufficient: every fetch effect keys
// on a stringified version of it. If two different pins produce the same key,
// the request body changes while the effect never re-runs — which is exactly
// "the number never changed on screen".
const keyFor = (pins) => JSON.stringify(dataVersionBody({ pins }));
const keys = ['0', '1', '2', '3'].map((v) => keyFor(withPin({}, DC, v)));
check('each version yields a distinct effect key', new Set(keys).size, 4);
check('live differs from every pinned key', keys.includes(keyFor({})), false);

console.log(failures === 0 ? '\nALL PASS' : `\nFAILED (${failures})`);
process.exit(failures === 0 ? 0 : 1);
