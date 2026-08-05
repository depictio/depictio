/**
 * TypeScript mirror of the serverless bundle-manifest contract.
 *
 * Source of truth: `depictio/models/models/serverless.py` (Pydantic).
 * Both sides are pinned by the committed JSON-schema snapshot
 * `depictio/models/models/serverless.schema.json` — the vitest suite asserts
 * this module's top-level keys against that snapshot, and the Python suite
 * asserts the snapshot against the model. Change the contract there first,
 * regenerate the snapshot, then update this mirror.
 */

export const MANIFEST_VERSION = 1;

export type BundleMode = 'single-file' | 'static-dir' | 'remote';

/** A = export-from-instance, B = build-from-spec, C = API endpoint. */
export type Producer = 'A' | 'B' | 'C';

export type ComponentTier = 'live' | 'partial' | 'frozen' | 'omitted';

export type TierReason =
  | 'multiqc'
  | 'celery_compute'
  | 'code_mode'
  | 'binding_miss'
  | 'max_points'
  | 'link_table_too_big'
  | 'map_tiles'
  | 'jbrowse'
  | 'image'
  | 'whole_frame_viz'
  | 'filter_expr_window'
  | 'unsupported';

export interface ColumnSpec {
  name: string;
  /** Polars dtype string at export time (e.g. 'Int64', 'Utf8'). */
  dtype: string;
}

/** One data collection's bundled table (mirrors load_deltatable_lite's init_data). */
export interface DataRef {
  /**
   * 'inline:dc_<id>' (single-file, resolved against inline_blobs),
   * a bundle-relative path like 'data/<id>.parquet' (static-dir),
   * or an absolute URL (remote). Resolve only via resolveUri().
   */
  uri: string;
  rows: number;
  size_bytes: number;
  row_group_bytes?: number | null;
  columns: ColumnSpec[];
  /**
   * Companion column name -> source: '__ts__<col>' epoch-µs datetime companion,
   * '__fe__<sha8>' boolean filter_expr column (value = source expr text),
   * '__code__<col>' Int32 codebook codes for categorical column <col>.
   */
  companions: Record<string, string>;
  /**
   * Per categorical non-String column: JSON-serialized option value -> integer
   * code in the '__code__<col>' companion. A selected value absent from the
   * codebook matches nothing (same as a failed cast server-side).
   */
  codebooks: Record<string, Record<string, number>>;
  aggregation_hash?: string | null;
}

export interface TierEntry {
  tier: ComponentTier;
  reason?: TierReason | null;
  detail?: string | null;
}

export interface FrozenPayload {
  kind: string;
  /** Exactly what the corresponding api.ts function would have returned. */
  payload: Record<string, unknown>;
  filter_state: Record<string, unknown>[];
}

export interface TraceBinding {
  /** Trace index in the scaffold figure. */
  i: number;
  /** Equality predicates (grouping column -> value) selecting this trace's rows. */
  group: Record<string, unknown>;
  /** Trace field path (e.g. 'x', 'y', 'marker.size') -> source column. */
  fields: Record<string, string>;
  /** Facet-cell disambiguation: 'xaxis'/'yaxis' -> plotly axis id. */
  axes: Record<string, string>;
}

export interface TrendlineBinding {
  i: number;
  /** Index of the raw-data trace the OLS refit runs against. */
  on: number;
}

export interface BindingTable {
  /** Full figure JSON from the real create_figure_from_data, data arrays stripped. */
  scaffold: Record<string, unknown>;
  /** px grouping columns in order [color, symbol, line_dash, line_group, pattern_shape, facet_row, facet_col]. */
  group_cols: string[];
  traces: TraceBinding[];
  trendlines: TrendlineBinding[];
  /** True when the build sampled before filtering -> partial tier. */
  sampled: boolean;
}

/** JSON scalar allowed in predicate comparisons / is_in lists. */
export type PrologueScalar = string | number | boolean | null;

export type CmpOp = '<' | '<=' | '>' | '>=' | '==' | '!=';

/**
 * Predicate tree for the `filter` prologue op. Evaluation is polars-faithful
 * three-valued logic: a comparison involving null is null, and/or/not are
 * Kleene, and a row passes only when the tree is strictly true.
 */
export type Pred =
  | { and: Pred[] }
  | { or: Pred[] }
  | { not: Pred }
  | { cmp: { col: string; op: CmpOp; value: PrologueScalar } }
  | { is_null: { col: string } }
  | { is_not_null: { col: string } }
  | { is_in: { col: string; values: PrologueScalar[] } };

/** Closed group_by aggregation allowlist (the agg kernel's AggFn minus mode). */
export type PrologueAggFn =
  | 'sum'
  | 'mean'
  | 'median'
  | 'min'
  | 'max'
  | 'count'
  | 'nunique'
  | 'std'
  | 'var'
  | 'first'
  | 'last';

export interface PrologueAgg {
  col: string;
  fn: PrologueAggFn;
  alias: string;
}

/**
 * One step of a component's data prologue — the closed JSON IR the Python
 * transpiler emits and `runPrologue` (../prologue.ts) executes in the browser
 * with pinned Polars semantics. Shapes are the phase-6 contract, byte-for-byte
 * shared with the Python side; the polars-generated differential fixture is
 * the arbiter.
 */
export type PrologueOp =
  | { op: 'filter'; pred: Pred }
  | { op: 'unpivot'; on: string[]; index: string[]; variable: string; value: string }
  | { op: 'group_by'; by: string[]; agg: PrologueAgg[] }
  | { op: 'sort'; by: string[]; desc: boolean[] }
  | { op: 'rename'; map: Record<string, string> };

export interface LinkTable {
  /** Source value -> translated target values. */
  values: Record<string, string[]>;
}

export interface LinksSection {
  configs: Record<string, unknown>[];
  tables: Record<string, LinkTable>;
}

export interface DashboardSection {
  /**
   * Dashboard id passed to App. Must be non-empty: ComponentRenderer silently
   * no-ops figure/table/image/map/jbrowse/multiqc without a dashboardId.
   */
  id: string;
  title: string;
  /** DashboardDataLite-shaped document: layout + stored_metadata components. */
  doc: Record<string, unknown>;
}

export interface BundleManifest {
  manifest_version: number;
  mode: BundleMode;
  producer: Producer;
  built_at: string;
  depictio_version: string;
  dashboard: DashboardSection;
  data_refs: Record<string, DataRef>;
  tiers: Record<string, TierEntry>;
  frozen: Record<string, FrozenPayload>;
  bindings: Record<string, BindingTable>;
  prologues: Record<string, PrologueOp[]>;
  links: LinksSection;
  allow_network_tiles: boolean;
  /** single-file only: 'dc_<id>' -> base64 Parquet bytes. */
  inline_blobs: Record<string, string>;
}

/** Runtime parse with the checks the runtime actually depends on. */
export function parseManifest(json: unknown): BundleManifest {
  if (typeof json !== 'object' || json === null) {
    throw new Error('bundle manifest: not an object');
  }
  const m = json as BundleManifest;
  if (m.manifest_version !== MANIFEST_VERSION) {
    throw new Error(
      `bundle manifest: version ${String(m.manifest_version)} not supported (runtime speaks ${MANIFEST_VERSION})`,
    );
  }
  if (!m.dashboard || typeof m.dashboard.id !== 'string' || m.dashboard.id.length === 0) {
    throw new Error('bundle manifest: dashboard.id must be a non-empty string');
  }
  if (m.mode !== 'single-file' && m.mode !== 'static-dir' && m.mode !== 'remote') {
    throw new Error(`bundle manifest: unknown mode "${String(m.mode)}"`);
  }
  for (const [dcId, ref] of Object.entries(m.data_refs ?? {})) {
    if (ref.uri.startsWith('inline:') && !(ref.uri.slice('inline:'.length) in (m.inline_blobs ?? {}))) {
      throw new Error(`bundle manifest: data_refs[${dcId}] points at missing inline blob "${ref.uri}"`);
    }
  }
  return m;
}
