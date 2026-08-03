import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { MANIFEST_VERSION, parseManifest, type BundleManifest } from '../src/manifest';

const PKG_ROOT = join(__dirname, '..');
const REPO_ROOT = join(PKG_ROOT, '..', '..');
const FIXTURE = join(PKG_ROOT, 'fixtures', 'manifest-basic.json');
const SCHEMA_SNAPSHOT = join(
  REPO_ROOT,
  'depictio',
  'models',
  'models',
  'serverless.schema.json',
);

describe('parseManifest', () => {
  it('accepts the shared fixture', () => {
    const manifest = parseManifest(JSON.parse(readFileSync(FIXTURE, 'utf-8')));
    expect(manifest.manifest_version).toBe(MANIFEST_VERSION);
    expect(manifest.mode).toBe('single-file');
    expect(manifest.dashboard.id).not.toHaveLength(0);
  });

  it('rejects a wrong manifest_version', () => {
    const raw = JSON.parse(readFileSync(FIXTURE, 'utf-8')) as BundleManifest;
    raw.manifest_version = 999;
    expect(() => parseManifest(raw)).toThrow(/version 999/);
  });

  it('rejects an empty dashboard id', () => {
    const raw = JSON.parse(readFileSync(FIXTURE, 'utf-8')) as BundleManifest;
    raw.dashboard.id = '';
    expect(() => parseManifest(raw)).toThrow(/dashboard\.id/);
  });

  it('rejects an inline uri without a matching blob', () => {
    const raw = JSON.parse(readFileSync(FIXTURE, 'utf-8')) as BundleManifest;
    raw.inline_blobs = {};
    expect(() => parseManifest(raw)).toThrow(/missing inline blob/);
  });
});

describe('contract pinning against the committed JSON-schema snapshot', () => {
  // The Python side asserts model == snapshot; this side asserts the TS mirror
  // covers the same top-level surface, so neither language can drift silently.
  const schema = JSON.parse(readFileSync(SCHEMA_SNAPSHOT, 'utf-8')) as {
    properties: Record<string, unknown>;
    required?: string[];
  };

  it('mirrors every top-level manifest property', () => {
    const fixture = parseManifest(JSON.parse(readFileSync(FIXTURE, 'utf-8')));
    const tsKeys = Object.keys(fixture).sort();
    const schemaKeys = Object.keys(schema.properties).sort();
    expect(tsKeys).toEqual(schemaKeys);
  });

  it('DataRef mirrors the snapshot definition', () => {
    const defs = (JSON.parse(readFileSync(SCHEMA_SNAPSHOT, 'utf-8')) as {
      $defs: Record<string, { properties: Record<string, unknown> }>;
    }).$defs;
    const fixture = parseManifest(JSON.parse(readFileSync(FIXTURE, 'utf-8')));
    const ref = Object.values(fixture.data_refs)[0];
    expect(Object.keys(ref).sort()).toEqual(Object.keys(defs.DataRef.properties).sort());
  });
});
