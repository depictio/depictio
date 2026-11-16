/**
 * What the bundle's project page shows, derived from the manifest alone.
 *
 * Pure (no React, no DOM, no `window`): the page renders it, the api shim's
 * `fetchProject` answers with it, and the unit tests read it straight from
 * the fixtures.
 */
import type {
  BundleManifest,
  DataRef,
  ProjectDataCollectionSummary,
  ProjectSummary,
} from 'depictio-static-core';

/** What the file holds of one data collection. */
export type CollectionPresence =
  /** Its table is in the file: filters and live views recompute from it. */
  | 'bundled'
  /** Only snapshots of the views that read it (frozen payloads, MultiQC). */
  | 'snapshot'
  /** Part of the project, not read by any view of this dashboard. */
  | 'absent';

export interface CollectionRow {
  id: string;
  tag: string;
  type: string;
  metatype: string | null;
  description: string | null;
  workflow: string | null;
  presence: CollectionPresence;
  /** Rows of the bundled table (the whole collection: only columns are pruned). */
  rows: number | null;
  /** User columns the file carries (companions the runtime adds are not counted). */
  columns: string[];
}

/** User columns of a bundled table: its companion columns (`__ts__…`,
 *  `__code__…`, `__fe__…`) are the runtime's own and never shown. */
export function userColumns(ref: DataRef): string[] {
  const companions = new Set(Object.keys(ref.companions ?? {}));
  return ref.columns
    .map((c) => c.name)
    .filter((name) => !companions.has(name) && !name.startsWith('__'));
}

/** Every data collection a component of the family reads, by id. */
export function collectionsReadByViews(manifest: BundleManifest): Set<string> {
  const docs = manifest.tabs?.length
    ? manifest.tabs.map((t) => t.doc)
    : [manifest.dashboard.doc];
  const out = new Set<string>();
  for (const doc of docs) {
    const meta = (doc as { stored_metadata?: { dc_id?: unknown }[] }).stored_metadata ?? [];
    for (const comp of meta) {
      if (comp && typeof comp.dc_id === 'string' && comp.dc_id) out.add(comp.dc_id);
    }
  }
  return out;
}

const PRESENCE_ORDER: Record<CollectionPresence, number> = { bundled: 0, snapshot: 1, absent: 2 };

/**
 * The project's data collections with what the file holds of each: the
 * bundled tables first (largest first), then the ones only seen through
 * snapshots, then the rest of the project. A bundled table the summary does
 * not list (a manifest written before `project`, a collection added since) is
 * still shown, under its id.
 */
export function collectionRows(manifest: BundleManifest): CollectionRow[] {
  const project = manifest.project ?? null;
  const refs = manifest.data_refs ?? {};
  const read = collectionsReadByViews(manifest);
  const workflowName = new Map((project?.workflows ?? []).map((w) => [w.id, w.name]));

  const row = (dc: ProjectDataCollectionSummary): CollectionRow => {
    const ref = refs[dc.id];
    return {
      id: dc.id,
      tag: dc.tag,
      type: dc.type || 'table',
      metatype: dc.metatype ?? null,
      description: dc.description ?? null,
      workflow: (dc.workflow_id && workflowName.get(dc.workflow_id)) || null,
      presence: ref ? 'bundled' : read.has(dc.id) ? 'snapshot' : 'absent',
      rows: ref ? ref.rows : null,
      columns: ref ? userColumns(ref) : [],
    };
  };

  const listed = new Set<string>();
  const rows: CollectionRow[] = [];
  for (const dc of project?.data_collections ?? []) {
    if (listed.has(dc.id)) continue;
    listed.add(dc.id);
    rows.push(row(dc));
  }
  for (const id of Object.keys(refs)) {
    if (listed.has(id)) continue;
    rows.push(row({ id, tag: id, type: 'table' }));
  }
  return rows
    .map((r, i) => ({ r, i }))
    .sort(
      (a, b) =>
        PRESENCE_ORDER[a.r.presence] - PRESENCE_ORDER[b.r.presence] ||
        (b.r.rows ?? -1) - (a.r.rows ?? -1) ||
        a.i - b.i,
    )
    .map(({ r }) => r);
}

/** Totals for the page head: how much of the project the file carries. */
export function collectionTotals(rows: CollectionRow[]): {
  total: number;
  bundled: number;
  snapshot: number;
  rows: number;
} {
  return {
    total: rows.length,
    bundled: rows.filter((r) => r.presence === 'bundled').length,
    snapshot: rows.filter((r) => r.presence === 'snapshot').length,
    rows: rows.reduce((sum, r) => sum + (r.rows ?? 0), 0),
  };
}

/**
 * The summary in the shape `fetchProject` returns, for the dashboard's own
 * readers of its project: the Settings drawer's About section (name, template,
 * key run parameters) and the `params:` links' Run parameters dialog.
 */
export function projectAsApiProject(project: ProjectSummary): Record<string, unknown> {
  return {
    id: project.id,
    _id: project.id,
    name: project.name,
    description: project.description ?? null,
    project_type: project.project_type ?? null,
    template_origin: project.template
      ? {
          template_id: project.template.template_id,
          template_version: project.template.template_version ?? null,
          applied_at: project.template.applied_at ?? null,
          run_provenance: project.run_parameters,
          run_provenance_files: project.run_parameter_files,
        }
      : project.run_parameters.length
        ? { run_provenance: project.run_parameters, run_provenance_files: project.run_parameter_files }
        : null,
  };
}

/** "1,234" — rows and counts read with a thousands separator. */
export function formatCount(n: number): string {
  return n.toLocaleString('en-US');
}
