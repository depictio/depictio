/**
 * Domain model for Tool Studio. Mirrors the catalog schema
 * (depictio/catalog/catalog.schema.json) as far as the client needs to author
 * a single tool entry: a ToolMeta (module.yaml) + one output (an <output>.yaml)
 * carrying a fixture and a list of render specs.
 *
 * The client authors exactly ONE output per entry (drop one file → one output);
 * multi-output tools are assembled by running the flow once per file and
 * merging folders — kept out of scope for the MVP.
 */

/** Polars-style dtype name, as the catalog grounding layer speaks it. */
export type Dtype = 'String' | 'Int64' | 'Float64' | 'Boolean' | 'Datetime';

export interface FixtureColumn {
  name: string;
  dtype: Dtype;
}

export interface ParsedFixture {
  /** Name the fixture is committed under, e.g. "coverage.tsv". Usually the file
   *  you provided; `renamedFrom` covers the one case where it is not. */
  fileName: string;
  /** Set only when the name had to change: depictio reads a fixture as
   *  tab-delimited *only* when it is named `.tsv`, so a tab-delimited file
   *  under any other name is committed as `.tsv` to stay readable. */
  renamedFrom?: string;
  /** Detected delimiter (',' or '\t'). */
  delimiter: ',' | '\t';
  columns: FixtureColumn[];
  /** Row objects (header → cell), parsed for preview + client compute. */
  rows: Record<string, unknown>[];
  /** Raw file text, exported verbatim as the fixture. */
  raw: string;
  /** Structural problems found while parsing (ragged rows, unclosed quotes,
   *  no data rows). Shown next to the preview: a file that parses here with a
   *  row silently dropped will not ground the same way in CI. */
  parseWarnings?: string[];
}

/** Where the tool comes from — drives the picker favicon + which module.yaml
 *  URL field the source URL lands in (nf-core → nf_core_url; others → homepage). */
export type ToolSource = 'nf-core' | 'snakemake' | 'galaxy';

export interface ToolMeta {
  id: string;
  name: string;
  source: ToolSource;
  nf_core_url?: string;
  /** Where a non-nf-core source (Snakemake wrapper / Galaxy tool) was fetched
   *  from — kept distinct from `homepage` so an extractor can preserve the
   *  pasted source URL *and* fill the tool's own upstream homepage. */
  source_url?: string;
  homepage?: string;
  biotools_url?: string;
  description?: string;
  /** Semver of the entry (model default 1.0.0, omitted when unchanged). */
  version?: string;
  /** Pipeline stage: drives tab placement in `template compose`. */
  stage?: Stage;
  /** EDAM topic URIs or `topic_NNNN` ids. */
  edam_topics?: string[];
}

// ── Render specs (one per catalog `renders_as` entry) ──────────────────────
// Discriminated union on `component`. Only the subset the client can author is
// modelled; each maps 1:1 to a catalog Render.

// Derived from the catalog schema (13 types); a hand-copied list had fallen to 6.
import type { VisuType, InteractiveType, Stage } from './catalog/generated/renderSpec';
export type FigureVisuType = VisuType;
export type { Stage };

// The card enums come from `generated/cardSpec.ts`, derived from
// catalog.schema.json at build time — they used to be hand-copied here and fell
// a release behind depictio. `fromBuilderStore` aliases the builder's 'unique'
// → 'nunique' so the emitted value stays within the aggregation enum.
import type { Aggregation, SecondaryLayout, ThresholdDirection } from './catalog/generated/cardSpec';

export type { Aggregation, SecondaryLayout, ThresholdDirection };

/** plotly-express kwargs the catalog treats as column references (grounded). */
export const FIGURE_COLUMN_KWARGS = [
  'x',
  'y',
  'color',
  'facet_col',
  'facet_row',
  'size',
  'symbol',
  'names',
  'values',
  'hover_name',
] as const;
export type FigureColumnKwarg = (typeof FIGURE_COLUMN_KWARGS)[number];

/** Optional first-class handle: dashboards reuse a render via `use: <tool>/<id>`
 *  (unique within a tool). Present on every render type. */
export interface FigureRender {
  uid: string;
  component: 'figure';
  id?: string;
  /** UI mode: plotly-express visu type. Omitted for code-mode figures. */
  visu_type?: FigureVisuType;
  /** UI mode: column-valued kwargs (x/y/color/…) + free kwargs (title, log_x…). */
  dict_kwargs?: Record<string, string>;
  /** Code mode: inline python snippet that assigns `fig` (depictio code_content). */
  code?: string;
  /** Preview-only: the Plotly {data,layout} produced by executing a code-mode
   *  figure in-browser. NOT exported — lets the render list show the real plot. */
  _previewFigure?: { data: unknown[]; layout: Record<string, unknown> };
}

export interface CardRender {
  uid: string;
  component: 'card';
  id?: string;
  column: string;
  aggregation: Aggregation;
  /** Optional multi-metric strip (depictio card builder). */
  aggregations?: Aggregation[];
  secondary_layout?: SecondaryLayout;
  /** Group-by column — required by top_n / concentration / composition / donut. */
  breakdown_col?: string;
  top_n_count?: number;
  /** Denominator — required by coverage / gauge. */
  coverage_max?: number;
  /** QC cut-off — required by threshold. */
  threshold_value?: number;
  threshold_direction?: ThresholdDirection;
  threshold_warn?: number;
  /** Ordered stages after the card's own column — required by attrition. */
  attrition_cols?: string[];
  /** Ordered axis the sparkline buckets along — required by trend. */
  trend_col?: string;
  /** Optional polars pre-filter applied before the aggregation. */
  filter_expr?: string;
  /** Promote to a composed dashboard's Overview strip. */
  headline?: boolean;
  /** Order among headline cards (lower first). */
  priority?: number;
}

/** Display options, mirroring `TableLiteComponent`. All optional: a bare
 *  `{component: table}` means "every column, defaults", which is what most
 *  committed entries say. */
export interface TableRender {
  uid: string;
  component: 'table';
  id?: string;
  /** Displayed columns. Omitted (not an empty list) when all are visible. */
  columns?: string[];
  page_size?: number;
  sortable?: boolean;
  filterable?: boolean;
  /** Row selection turns the table into a filter source for other components. */
  row_selection_enabled?: boolean;
  row_selection_column?: string;
}

/** Interactive filter control. Both fields are required by depictio's
 *  `InteractiveLiteComponent`, so a render carrying neither could not be turned
 *  into a control at all — which is why the catalog held zero of them until the
 *  model learned to express them. */
export interface InteractiveRender {
  uid: string;
  component: 'interactive';
  id?: string;
  interactive_type: InteractiveVariant;
  column_name: string;
}

/** depictio's `InteractiveType` literal, generated from the catalog schema. */
export type InteractiveVariant = InteractiveType;

export interface AdvancedVizRender {
  uid: string;
  component: 'advanced_viz';
  id?: string;
  kind: string;
  /** role → column, or → ordered column list for the few list-typed roles
   *  (`sankey.steps`, `sunburst.ranks`, ComplexHeatmap's column lists) and
   *  role → setting for `embedding.compute_method`. Mirrors `Render.roles`. */
  roles: Record<string, string | string[]>;
}

export type RenderSpec =
  | FigureRender
  | CardRender
  | TableRender
  | InteractiveRender
  | AdvancedVizRender;

export interface OutputMeta {
  /** Short output slug, e.g. "coverage" → output id "<tool>_<slug>". */
  slug: string;
  path_glob: string;
  /** Alternative globs for runs that name the file differently (needs path_glob). */
  path_glob_alt?: string[];
  /** Exact file name, the other `find` key (used when no glob is needed). */
  filename?: string;
  /** Display name in the output picker; unique within the tool. */
  name?: string;
  description?: string;
  /** A reshape the raw file needs before it is bindable. When set, the
   *  fixture is the recipe's OUTPUT (what the renders bind), the raw samples
   *  below are only for running it here, and the recipe ships as
   *  `<tool>/<slug>.py` (`recipe:` in the output YAML). */
  recipe?: RecipeDraft;
}

export interface RecipeDraft {
  /** Python module: SOURCES, OUTPUT_SCHEMA, transform(sources). */
  code: string;
  /** Samples of the raw file(s) the recipe reads; not committed. */
  inputs?: Array<{ ref?: string; fileName: string; text: string }>;
}

/** A file output channel parsed from a tool source's metadata (nf-core
 *  `meta.yml` `output:`, Snakemake wrapper `meta.yaml` `output:`, Galaxy tool
 *  `<outputs>`) — used to auto-fill the Output slug / path_glob / description.
 *  `pattern` may be empty when the source only describes outputs in prose
 *  (Snakemake), in which case only slug + description are auto-filled. */
export interface OutputChannel {
  /** Channel name, e.g. "summary_txt". */
  name: string;
  /** Glob pattern for the file, e.g. "*.summary.txt" (may be ''). */
  pattern: string;
  description: string;
  /** meta.yml `type` (kept for filtering; only "file" outputs are surfaced). */
  type: string;
}

/** Identity bag returned by every source extractor (nf-core / Snakemake /
 *  Galaxy), used to auto-fill the Tool step. Missing fields are ''. */
export interface ExtractedMeta {
  name: string;
  description: string;
  /** The tool's own upstream homepage, when the source declares one. */
  homepage: string;
  biotools_url: string;
  /** Canonicalised URL the metadata was fetched from (→ `ToolMeta.source_url`,
   *  or `nf_core_url` for nf-core). */
  source_url: string;
  outputs: OutputChannel[];
}

// ── kinds.json (generated from schemas.py at build) ────────────────────────

export interface KindDescriptor {
  roles: Record<string, string[]>;
  required_roles: string[];
  heavy: boolean;
  label: string;
  /** Roles bound to an ordered column list (generated from `_LIST_ROLES`). */
  list_roles?: string[];
  /** Roles that pick a setting, not a column (`_NON_COLUMN_ROLES`). */
  setting_roles?: string[];
}
export type KindsMap = Record<string, KindDescriptor>;
