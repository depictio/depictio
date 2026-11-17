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
  TabEntry,
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

/** The bundle's own facts about one collection, stamped on the document the
 *  shim answers with (`bundle`): the live page's viewer reads them, offline only,
 *  to show the rows of a table the file carries and say when it does not. */
export interface BundleCollectionFacts {
  presence: CollectionPresence;
  /** Rows of the bundled table (null when the file has no table for it). */
  rows: number | null;
  /** User columns the file carries, in the bundled table's order. */
  columns: string[];
}

/** Id of the stand-in workflow that holds a bundle's direct collections. A
 *  name, not an engine: `isRealWorkflow` keeps it out of the Workflows panel,
 *  as the server's own wrapper around hand-added collections is. */
export const DIRECT_WORKFLOW_ID = 'bundle-direct-collections';

const DTYPE_WORDS: Record<string, string> = { utf8: 'string', str: 'string' };

/** A data collection as `/projects/get/from_id` returns it (the enriched
 *  document), from the summary's ingestion facts and what the file carries. */
function collectionDoc(
  dc: ProjectDataCollectionSummary,
  ref: DataRef | undefined,
  facts: BundleCollectionFacts,
): Record<string, unknown> {
  const type = dc.type || 'table';
  // The recorded schema (every column), else the bundled table's (the
  // columns this dashboard reads), for a manifest written before the schema.
  const specs = dc.columns?.length
    ? dc.columns.map((c) => ({
        name: c.name,
        type: c.type ?? null,
        description: c.description ?? null,
        ...(c.distinct != null ? { specs: { nunique: c.distinct } } : {}),
      }))
    : ref
      ? ref.columns
          .filter((c) => facts.columns.includes(c.name))
          .map((c) => ({
            name: c.name,
            type: DTYPE_WORDS[c.dtype.toLowerCase()] ?? c.dtype.toLowerCase(),
          }))
      : [];
  const rows = dc.rows ?? ref?.rows ?? null;
  const aggregated = rows != null || specs.length > 0 || dc.updated_at || dc.version != null;
  const size = dc.size_bytes ?? null;
  return {
    _id: dc.id,
    id: dc.id,
    data_collection_tag: dc.tag,
    ...(dc.description ? { description: dc.description } : {}),
    config: {
      type,
      ...(dc.metatype ? { metatype: dc.metatype } : {}),
      dc_specific_properties: dc.format ? { format: dc.format } : {},
    },
    ...(aggregated
      ? {
          last_aggregation: {
            ...(dc.updated_at ? { aggregation_time: dc.updated_at } : {}),
            delta_version: dc.version ?? null,
            rows_total: rows,
            aggregation_columns_specs: specs,
          },
        }
      : {}),
    flexible_metadata:
      size == null
        ? null
        : type.toLowerCase() === 'multiqc'
          ? { total_file_size_bytes: size }
          : { deltatable_size_bytes: size },
    bundle: facts,
  };
}

/**
 * The summary in the shape `fetchProject` returns.
 *
 * Its readers are the dashboard's own (the Settings drawer's About section,
 * the `params:` links' Run parameters dialog) and, with the manifest, the
 * live project page the bundle mounts: workflows holding their collections,
 * each collection with its last ingestion's facts (rows, schema, size, time)
 * and what the file holds of it (`bundle`). Nothing here was not already in
 * the summary or the manifest.
 */
export function projectAsApiProject(
  project: ProjectSummary,
  manifest: BundleManifest | null = null,
): Record<string, unknown> {
  const refs = manifest?.data_refs ?? {};
  const facts = new Map(
    (manifest ? collectionRows(manifest) : []).map((r) => [
      r.id,
      { presence: r.presence, rows: r.rows, columns: r.columns } as BundleCollectionFacts,
    ]),
  );
  const factsOf = (id: string): BundleCollectionFacts =>
    facts.get(id) ?? { presence: 'absent', rows: null, columns: [] };

  const known = new Set(project.workflows.map((w) => w.id));
  const byWorkflow = new Map<string, Record<string, unknown>[]>();
  const listed = new Set<string>();
  const place = (dc: ProjectDataCollectionSummary) => {
    if (listed.has(dc.id)) return;
    listed.add(dc.id);
    const wf = dc.workflow_id && known.has(dc.workflow_id) ? dc.workflow_id : DIRECT_WORKFLOW_ID;
    byWorkflow.set(wf, [...(byWorkflow.get(wf) ?? []), collectionDoc(dc, refs[dc.id], factsOf(dc.id))]);
  };
  project.data_collections.forEach(place);
  // A bundled table the summary does not list (a collection added since).
  Object.keys(refs).forEach((id) => place({ id, tag: id, type: 'table' }));

  const workflows: Record<string, unknown>[] = project.workflows.map((w) => ({
    _id: w.id,
    id: w.id,
    name: w.name,
    workflow_tag: w.tag ?? w.name,
    ...(w.version ? { version: w.version } : {}),
    ...(w.engine ? { engine: { name: w.engine, version: w.engine_version ?? undefined } } : {}),
    ...(w.catalog ? { catalog: { name: w.catalog } } : {}),
    ...(w.repository_url ? { repository_url: w.repository_url } : {}),
    data_collections: byWorkflow.get(w.id) ?? [],
  }));
  const direct = byWorkflow.get(DIRECT_WORKFLOW_ID);
  if (direct?.length) {
    workflows.push({
      _id: DIRECT_WORKFLOW_ID,
      id: DIRECT_WORKFLOW_ID,
      name: 'direct',
      data_collections: direct,
    });
  }

  return {
    id: project.id,
    _id: project.id,
    name: project.name,
    description: project.description ?? null,
    project_type: project.project_type ?? null,
    ...(project.registered_at ? { registration_time: project.registered_at } : {}),
    data_management_platform_project_url: project.external_url ?? null,
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
    workflows,
    joins: project.joins.map((j) => ({
      ...(j.name ? { name: j.name } : {}),
      left_dc: j.left_dc,
      right_dc: j.right_dc,
      on_columns: j.on_columns,
      ...(j.how ? { how: j.how } : {}),
    })),
    links: project.links.map(linkAsApiLink),
  };
}

/** A summary link in the shape `listProjectLinks` returns (`DCLink`), with no
 *  value mappings: the summary never carries them. */
export function linkAsApiLink(link: ProjectSummary['links'][number]): Record<string, unknown> {
  return {
    id: link.id,
    source_dc_id: link.source_dc_id,
    source_dc_tag: link.source_dc_tag ?? undefined,
    source_column: link.source_column,
    target_dc_id: link.target_dc_id,
    target_dc_tag: link.target_dc_tag ?? undefined,
    target_type: link.target_type,
    link_config: {
      resolver: link.resolver,
      ...(link.target_field ? { target_field: link.target_field } : {}),
    },
    description: link.description ?? null,
    enabled: link.enabled,
  };
}

/** The project's dashboards in the shape `listDashboards` returns: this
 *  bundle's tab family (a single-tab bundle is its own main tab). Each links
 *  to `/dashboard/<id>`, which the bundle's navigation answers in place. */
export function bundleDashboards(manifest: BundleManifest): Record<string, unknown>[] {
  type TabLike = Pick<TabEntry, 'id' | 'title' | 'doc' | 'is_main_tab' | 'icon' | 'icon_color' | 'subtitle'>;
  const projectId = manifest.project?.id ?? null;
  const tabs: TabLike[] = manifest.tabs?.length
    ? manifest.tabs
    : [
        {
          id: manifest.dashboard.id,
          title: manifest.dashboard.title,
          doc: manifest.dashboard.doc,
          is_main_tab: true,
        },
      ];
  const main = tabs.find((t) => t.is_main_tab) ?? tabs[0];
  return tabs.map((t) => {
    const doc = (t.doc ?? {}) as Record<string, unknown>;
    const str = (k: string) =>
      typeof doc[k] === 'string' && (doc[k] as string).trim() ? (doc[k] as string) : undefined;
    return {
      dashboard_id: t.id,
      title: t.title || str('title'),
      subtitle: t.subtitle ?? str('subtitle'),
      project_id: projectId ?? str('project_id'),
      parent_dashboard_id: t.id === main.id ? null : main.id,
      icon: t.icon ?? str('icon'),
      icon_color: t.icon_color ?? str('icon_color'),
      last_saved_ts: str('last_saved_ts'),
    };
  });
}
