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
  DIRECT_WORKFLOW_ID,
  bundleDashboards,
  collectionRows,
  collectionsReadByViews,
  linkAsApiLink,
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

type ApiDc = {
  _id: string;
  data_collection_tag: string;
  config: { type: string; metatype?: string; dc_specific_properties: { format?: string } };
  last_aggregation?: {
    rows_total: number | null;
    delta_version: number | null;
    aggregation_time?: string;
    aggregation_columns_specs: { name: string; type: string | null; specs?: { nunique: number } }[];
  };
  flexible_metadata: Record<string, number> | null;
  bundle: { presence: string; rows: number | null; columns: string[] };
};
type ApiProject = {
  workflows: {
    _id: string;
    name: string;
    engine?: { name: string };
    catalog?: { name: string };
    data_collections: ApiDc[];
  }[];
  joins: { left_dc: string; right_dc: string }[];
  links: { id: string; link_config: { resolver: string } }[];
};

describe('projectAsApiProject: the live project page, offline', () => {
  const manifest = load('manifest-tabs.json');
  const api = projectAsApiProject(manifest.project!, manifest) as unknown as ApiProject;
  const dcs = api.workflows.flatMap((w) => w.data_collections);
  const byTag = Object.fromEntries(dcs.map((d) => [d.data_collection_tag, d]));

  it('nests the collections under their workflow, as the enriched project does', () => {
    expect(api.workflows.map((w) => w.name)).toEqual(['fixture-pipeline']);
    expect(api.workflows[0].engine?.name).toBe('nextflow');
    expect(api.workflows[0].catalog?.name).toBe('nf-core');
    expect(dcs.map((d) => d.data_collection_tag)).toEqual(['penguins', 'multiqc_report']);
    expect(api.joins[0]).toMatchObject({ left_dc: 'penguins', right_dc: 'multiqc_report' });
    expect(api.links[0].link_config.resolver).toBe('sample_mapping');
  });

  it("gives each collection its last ingestion's facts, the whole schema included", () => {
    const penguins = byTag.penguins;
    expect(penguins.config).toMatchObject({ type: 'table', metatype: 'Aggregate' });
    expect(penguins.config.dc_specific_properties.format).toBe('csv');
    expect(penguins.last_aggregation).toMatchObject({ rows_total: 3, delta_version: 2 });
    expect(penguins.last_aggregation!.aggregation_columns_specs.map((c) => c.name)).toEqual([
      'species',
      'bill_length_mm',
      'island',
    ]);
    expect(penguins.last_aggregation!.aggregation_columns_specs[0].specs).toEqual({ nunique: 2 });
    expect(penguins.flexible_metadata).toEqual({ deltatable_size_bytes: 2048 });
    // A report's size is its files'.
    expect(byTag.multiqc_report.flexible_metadata).toEqual({ total_file_size_bytes: 4096 });
    expect(byTag.multiqc_report.last_aggregation).toBeUndefined();
  });

  it('says what the file holds of each collection', () => {
    expect(byTag.penguins.bundle).toEqual({
      presence: 'bundled',
      rows: 3,
      columns: ['species', 'bill_length_mm'],
    });
    expect(byTag.multiqc_report.bundle).toEqual({ presence: 'absent', rows: null, columns: [] });
  });

  it("reads a bundled table's schema from the file when the summary has none", () => {
    const old = structuredClone(manifest);
    for (const dc of old.project!.data_collections) delete dc.columns;
    const doc = (projectAsApiProject(old.project!, old) as unknown as ApiProject).workflows[0]
      .data_collections[0];
    expect(doc.last_aggregation!.aggregation_columns_specs).toEqual([
      { name: 'species', type: 'string' },
      { name: 'bill_length_mm', type: 'float64' },
    ]);
  });

  it('wraps direct collections and bundled tables the summary misses in a non-workflow', () => {
    const basic = load('manifest-basic.json');
    const api2 = projectAsApiProject(
      { ...manifest.project!, workflows: [], data_collections: [] },
      basic,
    ) as unknown as ApiProject;
    expect(api2.workflows.map((w) => w._id)).toEqual([DIRECT_WORKFLOW_ID]);
    expect(api2.workflows[0].engine).toBeUndefined();
    expect(api2.workflows[0].data_collections[0]).toMatchObject({
      _id: 'dc00000000000000000000a1',
      bundle: { presence: 'bundled', rows: 3 },
    });
  });

  it('answers links without value mappings', () => {
    const link = linkAsApiLink(manifest.project!.links[0]);
    expect(link).toMatchObject({
      source_column: 'species',
      link_config: { resolver: 'sample_mapping', target_field: 'sample_name' },
      enabled: true,
    });
    expect(JSON.stringify(link)).not.toContain('mappings');
  });
});

describe('bundleDashboards', () => {
  it("lists the bundle's family as the project's dashboards", () => {
    const manifest = load('manifest-tabs.json');
    const rows = bundleDashboards(manifest) as {
      dashboard_id: string;
      parent_dashboard_id: string | null;
      project_id: string;
    }[];
    expect(rows).toHaveLength(manifest.tabs.length);
    const main = manifest.tabs.find((t) => t.is_main_tab)!;
    expect(rows.filter((r) => r.parent_dashboard_id === null).map((r) => r.dashboard_id)).toEqual([
      main.id,
    ]);
    expect(rows.every((r) => r.project_id === manifest.project!.id)).toBe(true);
  });

  it('makes a single-tab bundle its own main dashboard', () => {
    const basic = load('manifest-basic.json');
    expect(bundleDashboards(basic)).toEqual([
      expect.objectContaining({ dashboard_id: basic.dashboard.id, parent_dashboard_id: null }),
    ]);
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
