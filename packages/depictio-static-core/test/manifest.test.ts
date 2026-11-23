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

  // The tab-family fixture fills every TabEntry and ProjectSummary field, so
  // its keys ARE the TS mirror's surface: a field added on the Python side
  // without the fixture (and so this mirror) following fails here.
  const TABS_FIXTURE = join(PKG_ROOT, 'fixtures', 'manifest-tabs.json');
  const defs = (JSON.parse(readFileSync(SCHEMA_SNAPSHOT, 'utf-8')) as {
    $defs: Record<string, { properties: Record<string, unknown> }>;
  }).$defs;
  const tabsFixture = parseManifest(JSON.parse(readFileSync(TABS_FIXTURE, 'utf-8')));

  it('TabEntry mirrors the snapshot definition', () => {
    for (const tab of tabsFixture.tabs) {
      expect(Object.keys(tab).sort()).toEqual(Object.keys(defs.TabEntry.properties).sort());
    }
  });

  it('InitialGrouping mirrors the snapshot definition', () => {
    const fixture = parseManifest(JSON.parse(readFileSync(FIXTURE, 'utf-8')));
    const grouping = fixture.initial_grouping;
    expect(grouping).toBeTruthy();
    if (!grouping) return;
    expect(Object.keys(grouping).sort()).toEqual(Object.keys(defs.InitialGrouping.properties).sort());
    expect(Object.keys(grouping.groups[0]).sort()).toEqual(
      Object.keys(defs.AnalysisGroup.properties).sort(),
    );
  });

  it('ProjectSummary and its parts mirror the snapshot definitions', () => {
    const project = tabsFixture.project;
    expect(project).toBeTruthy();
    if (!project) return;
    const keys = (o: object) => Object.keys(o).sort();
    expect(keys(project)).toEqual(keys(defs.ProjectSummary.properties));
    expect(keys(project.template!)).toEqual(keys(defs.ProjectTemplateSummary.properties));
    expect(keys(project.workflows[0])).toEqual(keys(defs.ProjectWorkflowSummary.properties));
    expect(keys(project.data_collections[0])).toEqual(
      keys(defs.ProjectDataCollectionSummary.properties),
    );
    expect(keys(project.data_collections[0].columns![0])).toEqual(
      keys(defs.ProjectColumnSummary.properties),
    );
    expect(keys(project.links[0])).toEqual(keys(defs.ProjectLinkSummary.properties));
    expect(keys(project.joins[0])).toEqual(keys(defs.ProjectJoinSummary.properties));
    expect(keys(project.run_parameters[0])).toEqual(keys(defs.RunParameter.properties));
  });
});
