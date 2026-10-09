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
import {
  buildDataVersionOptions,
  LIVE,
  pinToValue,
  VERSION_DEFAULT,
  withPin,
} from '../src/versions/dataVersionChoice';

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

// --- Under a version's data ("as of") -----------------------------------
//
// The bug this guards: with v1's data in use, each collection's select read
// "Latest data" while the grid showed v1's commit, and picking "Latest data"
// deleted a key that was not there, so nothing changed. Under as-of the
// default is the version's data, and "Latest data" is an explicit `null`,
// which the server reads as "stay live" for that collection.
const AS_OF = true;
check('as-of: no pin of its own reads as the version\'s data', pinToValue(undefined, AS_OF), VERSION_DEFAULT);
check('no as-of: no pin reads as the latest data', pinToValue(undefined, false), LIVE);
check('as-of: a null pin reads as the latest data', pinToValue(null, AS_OF), LIVE);
check('a commit reads as itself', pinToValue(0, AS_OF), '0');
check('as-of: picking Latest data sets null', withPin({}, DC, LIVE, AS_OF), { [DC]: null });
check(
  'as-of: Latest data reaches the body as null, not as nothing',
  dataVersionBody({ asOfVersionId: 'v1', pins: withPin({}, DC, LIVE, AS_OF) }),
  { as_of_version: 'v1', data_versions: { [DC]: null } },
);
check(
  "as-of: back to the version's data drops the exception",
  dataVersionBody({
    asOfVersionId: 'v1',
    pins: withPin(withPin({}, DC, LIVE, AS_OF), DC, VERSION_DEFAULT, AS_OF),
  }),
  { as_of_version: 'v1' },
);
check(
  'as-of: Latest data is a different request from the version default',
  keyFor(withPin({}, DC, LIVE, AS_OF)) !== keyFor(withPin({}, DC, VERSION_DEFAULT, AS_OF)),
  true,
);
const asOfOptions = buildDataVersionOptions({
  commits: [{ version: 1 }, { version: 0 }],
  currentVersion: 1,
  withVersionDefault: AS_OF,
  versionDataVersion: 0,
});
check(
  "as-of: the version's data is offered first, with its commit",
  asOfOptions.slice(0, 2),
  [
    { value: VERSION_DEFAULT, label: "This version's data (v0)" },
    { value: LIVE, label: 'Latest data (v1)' },
  ],
);
check(
  'as-of: the default value matches an offered option',
  asOfOptions.some((o) => o.value === pinToValue(undefined, AS_OF)),
  true,
);

console.log(failures === 0 ? '\nALL PASS' : `\nFAILED (${failures})`);
process.exit(failures === 0 ? 0 : 1);
