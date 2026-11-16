/**
 * The bundle's project page: what it lists and where links to the project go.
 *
 * Run like tests/projects (the viewer package has no vitest of its own):
 *   pnpm --filter depictio-react-core exec vitest run --root ../../depictio/viewer tests/static-runtime
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { BundleManifest } from 'depictio-static-core';

import {
  collectionRows,
  collectionTotals,
  collectionsReadByViews,
  projectAsApiProject,
  userColumns,
} from '../../src/static-runtime/projectModel';
import { bundleRouteFor } from '../../src/static-runtime/tabNav';

const FIXTURES = join(__dirname, '../../../../packages/depictio-static-core/fixtures');
const load = (name: string) =>
  JSON.parse(readFileSync(join(FIXTURES, name), 'utf-8')) as BundleManifest;

describe('collectionRows', () => {
  const manifest = load('manifest-tabs.json');

  it('says what the file holds of each collection of the project', () => {
    const rows = collectionRows(manifest);
    expect(rows.map((r) => [r.tag, r.presence])).toEqual([
      ['penguins', 'bundled'],
      ['multiqc_report', 'absent'],
    ]);
    const [penguins] = rows;
    expect(penguins.rows).toBe(3);
    expect(penguins.columns).toEqual(['species', 'bill_length_mm']);
    expect(penguins.workflow).toBe('fixture-pipeline');
    expect(collectionTotals(rows)).toEqual({ total: 2, bundled: 1, snapshot: 0, rows: 3 });
  });

  it('marks a collection only seen through frozen views as snapshots', () => {
    const withMqcView = structuredClone(manifest);
    (withMqcView.tabs[3].doc.stored_metadata as Record<string, unknown>[]).push({
      index: 'mqc-1',
      component_type: 'multiqc',
      dc_id: 'dc00000000000000000000m1',
    });
    expect(collectionsReadByViews(withMqcView).has('dc00000000000000000000m1')).toBe(true);
    const mqc = collectionRows(withMqcView).find((r) => r.tag === 'multiqc_report')!;
    expect(mqc.presence).toBe('snapshot');
    expect(mqc.rows).toBeNull();
  });

  it('still lists the bundled tables of a manifest without a project', () => {
    const rows = collectionRows(load('manifest-basic.json'));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ id: 'dc00000000000000000000a1', presence: 'bundled', rows: 3 });
  });

  it('hides the runtime companion columns', () => {
    expect(
      userColumns({
        uri: 'inline:dc_x',
        rows: 1,
        size_bytes: 1,
        columns: [
          { name: 'when', dtype: 'Datetime' },
          { name: '__ts__when', dtype: 'Int64' },
          { name: 'kind', dtype: 'Categorical' },
          { name: 'kind_codes', dtype: 'Int32' },
        ],
        companions: { kind_codes: '__code__kind' },
        codebooks: {},
      }),
    ).toEqual(['when', 'kind']);
  });
});

describe('projectAsApiProject', () => {
  it("answers fetchProject in the shape the dashboard's readers parse", () => {
    const project = load('manifest-tabs.json').project!;
    const api = projectAsApiProject(project) as {
      name: string;
      template_origin: { template_id: string; run_provenance: { key: string }[] };
    };
    expect(api.name).toBe('Fixture project');
    expect(api.template_origin.template_id).toBe('nf-core/fixture/1.0.0');
    expect(api.template_origin.run_provenance.map((p) => p.key)).toEqual(['island', 'input']);
  });
});

describe('bundleRouteFor', () => {
  it('sends links to the project to the project page', () => {
    expect(bundleRouteFor('/projects/f1x7000000000000000000p1')).toEqual({ kind: 'project' });
    // The ingestion banner's and the annotation panel's variants (hash and
    // query live outside the pathname).
    expect(bundleRouteFor('/projects/abc')).toEqual({ kind: 'project' });
  });

  it('switches tabs for dashboard links and dead-ends the other app routes', () => {
    expect(bundleRouteFor('/dashboard/abc')).toEqual({ kind: 'tab', id: 'abc' });
    expect(bundleRouteFor('/dashboard-edit/abc')).toEqual({ kind: 'tab', id: 'abc' });
    for (const path of ['/dashboards', '/projects', '/admin', '/profile', '/groups', '/about']) {
      expect(bundleRouteFor(path)).toEqual({ kind: 'inert' });
    }
  });

  it('leaves anything else alone', () => {
    expect(bundleRouteFor('/tmp/bundle.html')).toBeNull();
    expect(bundleRouteFor('/projectsfoo')).toBeNull();
  });
});
