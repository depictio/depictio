#!/usr/bin/env node
/**
 * Build the static runtime's conditional add-ons next to the template.
 *
 *   dist-static/addons/3dmol.js     3Dmol.js's own minified UMD build (BSD-3)
 *   dist-static/addons/addons.json  {name: {version, file, bytes, sha256}}
 *
 * The base runtime (static.html) never contains these; a producer appends an
 * add-on to one bundle's HTML only when a component needs it
 * (depictio/serverless/addons.py, and scripts/addons.mjs for the demos and the
 * offline specs). Run after `vite build` — that step empties dist-static/.
 */
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const VIEWER_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(VIEWER_DIR, 'dist-static', 'addons');
const require = createRequire(join(VIEWER_DIR, 'package.json'));

mkdirSync(OUT, { recursive: true });
const registry = {};

function add(name, version, body) {
  if (/<\/script/i.test(body)) {
    throw new Error(`add-on ${name} contains "</script" and cannot be inlined`);
  }
  const file = `${name}.js`;
  writeFileSync(join(OUT, file), body);
  registry[name] = {
    version,
    file,
    bytes: Buffer.byteLength(body),
    sha256: createHash('sha256').update(body).digest('hex'),
  };
  console.log(`addon ${name}@${version}: ${(Buffer.byteLength(body) / 1e6).toFixed(2)} MB`);
}

// 3Dmol.js: the package's prebuilt minified UMD (defines window["3Dmol"]).
// 0.54 MB raw / 0.16 MB gzip, against ~0.56 MB gzip when Vite compiled the
// package's unminified ES entry into the runtime.
{
  const pkgPath = require.resolve('3dmol/package.json');
  const pkg = JSON.parse(readFileSync(pkgPath, 'utf-8'));
  const min = readFileSync(join(dirname(pkgPath), 'build', '3Dmol-min.js'), 'utf-8');
  const license = readFileSync(join(dirname(pkgPath), 'build', '3Dmol-min.js.LICENSE.txt'), 'utf-8');
  // The LICENSE.txt is itself a `/*! ... */` banner (BSD-3-Clause).
  add('3dmol', pkg.version, `${license.trim()}\n${min}`);
}

writeFileSync(join(OUT, 'addons.json'), `${JSON.stringify(registry, null, 2)}\n`);
