/**
 * Exercises the browser telemetry client against a stub DOM and a loopback fetch.
 *
 * The client in `packages/depictio-react-core/src/telemetry.ts` is the third
 * sender, alongside the API and the CLI, and it is the only one with no test
 * coverage at all: the package ships no test runner. Its consent logic is also
 * the easiest of the three to get quietly wrong, because `localStorage` and
 * `navigator.doNotTrack` both throw rather than return null in some browsers, and
 * a client that throws there would break the host page rather than merely go quiet.
 *
 * The real TypeScript source is what runs. Types are stripped with esbuild when it
 * is available, and otherwise by Node's own `--experimental-strip-types`, so this
 * needs no devDependency and no test runner added to the package.
 *
 * Usage:
 *
 *   node scripts/telemetry_browser_check.mjs
 */

import assert from 'node:assert';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SOURCE = resolve(HERE, '..', 'packages', 'depictio-react-core', 'src', 'telemetry.ts');

/**
 * Strip the types off the client and return an importable ESM module URL.
 *
 * The file uses only type annotations and interfaces — no enums, no decorators,
 * no namespaces — so removing the annotations is a faithful transform rather than
 * a compilation that could change behaviour.
 *
 * esbuild is the only supported path on purpose. Hand-rolling type stripping was
 * tried and is a bad trade: it silently mangles generics such as
 * `Record<string, unknown>` and would make this check fail for reasons that have
 * nothing to do with telemetry. Better to say plainly that esbuild is needed.
 */
function loadClient() {
  const dir = mkdtempSync(join(tmpdir(), 'depictio-telemetry-'));
  const out = join(dir, 'telemetry.mjs');

  // Both invocations are tried because esbuild may be on PATH directly (a
  // container with the frontend toolchain installed) or only resolvable through
  // the workspace's node_modules.
  const attempts = [
    ['esbuild', []],
    ['npx', ['--no-install', 'esbuild']],
  ];

  const errors = [];
  for (const [command, prefix] of attempts) {
    try {
      // No --loader: esbuild infers `ts` from the .ts extension, and passing the
      // flag for a file input is an error ("only applies when reading from stdin").
      execFileSync(command, [...prefix, SOURCE, '--format=esm', `--outfile=${out}`], {
        stdio: 'pipe',
      });
      return pathToFileURL(out).href;
    } catch (err) {
      errors.push(`${command}: ${String(err.stderr || err.message).trim()}`);
    }
  }

  console.error(
    '\nCould not find esbuild, which this check needs to run the TypeScript source.\n' +
      'Install the frontend toolchain (pnpm install) or run this inside the viewer\n' +
      'container, where esbuild is already present. Attempts:\n  ' +
      errors.join('\n  ') +
      '\n',
  );
  process.exit(2);
}

let failures = 0;

function check(label, ok, detail = '') {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}`);
  if (!ok) failures += 1;
  return ok;
}

/** Minimal in-memory localStorage. `mode` lets a hostile browser be simulated. */
function makeStorage(mode = 'ok') {
  const data = new Map();
  return {
    getItem(key) {
      if (mode === 'throw') throw new Error('SecurityError: storage disabled');
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      if (mode === 'throw' || mode === 'readonly') throw new Error('QuotaExceededError');
      data.set(key, String(value));
    },
    removeItem(key) {
      if (mode === 'throw') throw new Error('SecurityError');
      data.delete(key);
    },
    _dump: () => Object.fromEntries(data),
  };
}

/** Install a stub browser environment and capture every outgoing request. */
function installEnv({ storageMode = 'ok', doNotTrack = null } = {}) {
  const sent = [];
  const storage = makeStorage(storageMode);

  globalThis.window = { localStorage: storage };
  globalThis.navigator = { doNotTrack };
  // `crypto` is a getter-only global in Node 18+, so plain assignment throws.
  Object.defineProperty(globalThis, 'crypto', {
    configurable: true,
    value: { randomUUID: () => '11111111-2222-3333-4444-555555555555' },
  });
  globalThis.fetch = (url, init) => {
    sent.push({ url, body: JSON.parse(init.body), keepalive: init.keepalive });
    return Promise.resolve({ ok: true });
  };

  return { sent, storage };
}

const { initTelemetry, capture, isOptedOut, setOptOut } = await import(loadClient());

console.log('\n=== 1. Not configured: silent ===');
{
  const { sent } = installEnv();
  capture('studio_export');
  check('no token configured means nothing is sent', sent.length === 0, `${sent.length} sent`);
}

console.log('\n=== 2. Configured: sends a well-formed anonymous event ===');
let firstBody;
{
  const { sent } = installEnv();
  initTelemetry({ apiKey: 'phc_browser_loopback', source: 'tool-studio', version: '1.2.2' });
  capture('studio_export', { format: 'yaml' });

  if (check('exactly one request', sent.length === 1, `${sent.length}`)) {
    const { url, body, keepalive } = sent[0];
    firstBody = body;
    check('EU endpoint', url === 'https://eu.i.posthog.com/i/v0/e/', url);
    check('keepalive set so unload events survive', keepalive === true);
    check('event name', body.event === 'studio_export');
    check('api key', body.api_key === 'phc_browser_loopback');
    check('anonymous distinct_id', typeof body.distinct_id === 'string' && body.distinct_id.length > 0);
    check(
      'person profiles suppressed, matching the Python senders',
      body.properties.$process_person_profile === false,
    );
    check('source tag', body.properties.source === 'tool-studio');
    check('version', body.properties.version === '1.2.2');
    check('caller property preserved', body.properties.format === 'yaml');
    check('timestamp present', typeof body.timestamp === 'string');
  }
}

console.log('\n=== 3. The anonymous ID is stable, not per-event ===');
{
  const { sent } = installEnv();
  initTelemetry({ apiKey: 'phc_browser_loopback', source: 'viewer' });
  capture('a');
  capture('b');
  capture('c');
  const ids = new Set(sent.map((s) => s.body.distinct_id));
  check('three events share one ID', ids.size === 1, `${ids.size} distinct IDs`);
}

console.log('\n=== 4. Opt-out ===');
{
  const { sent } = installEnv();
  initTelemetry({ apiKey: 'phc_browser_loopback', source: 'viewer' });
  setOptOut(true);
  check('isOptedOut reflects the choice', isOptedOut() === true);
  capture('should_not_send');
  check('opted out sends nothing', sent.length === 0, `${sent.length} sent`);

  setOptOut(false);
  check('opting back in is possible', isOptedOut() === false);
  capture('should_send');
  check('opting back in resumes sending', sent.length === 1, `${sent.length} sent`);
}

console.log('\n=== 5. Do Not Track is honoured ===');
{
  const { sent } = installEnv({ doNotTrack: '1' });
  initTelemetry({ apiKey: 'phc_browser_loopback', source: 'viewer' });
  check('isOptedOut true under DNT', isOptedOut() === true);
  capture('should_not_send');
  check('DNT sends nothing', sent.length === 0, `${sent.length} sent`);
}

console.log('\n=== 6. A hostile browser cannot break the page ===');
for (const mode of ['throw', 'readonly']) {
  const { sent } = installEnv({ storageMode: mode });
  initTelemetry({ apiKey: 'phc_browser_loopback', source: 'viewer' });
  let threw = null;
  try {
    capture('event');
    isOptedOut();
    setOptOut(true);
  } catch (err) {
    threw = err;
  }
  check(`localStorage '${mode}' never throws to the caller`, threw === null, String(threw));
  check(
    `localStorage '${mode}' sends nothing rather than a churning ID`,
    sent.length === 0,
    `${sent.length} sent`,
  );
}

console.log('\n=== 7. A failing network is swallowed ===');
{
  installEnv();
  globalThis.fetch = () => Promise.reject(new Error('network down'));
  initTelemetry({ apiKey: 'phc_browser_loopback', source: 'viewer' });
  let threw = null;
  try {
    capture('event');
  } catch (err) {
    threw = err;
  }
  check('a rejected fetch does not reach the caller', threw === null, String(threw));
}

console.log('\n=== 8. Payload shape matches the Python senders ===');
{
  // The three senders must agree on these keys or the collector sees three
  // different event shapes for one product.
  const required = ['api_key', 'event', 'distinct_id', 'properties', 'timestamp'];
  const missing = required.filter((key) => !(key in (firstBody ?? {})));
  check('top-level keys match build_body()', missing.length === 0, `missing ${missing}`);
}

assert.ok(true);
console.log(`\n${failures === 0 ? 'ALL CHECKS PASSED' : `${failures} CHECK(S) FAILED`}\n`);
process.exit(failures === 0 ? 0 : 1);
