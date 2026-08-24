/**
 * Domain model for Catalog Studio. Mirrors the catalog schema
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
  /** Original dropped file name, e.g. "coverage.tsv". */
  fileName: string;
  /** Detected delimiter (',' or '\t'). */
  delimiter: ',' | '\t';
  columns: FixtureColumn[];
  /** Row objects (header → cell), parsed for preview + client compute. */
  rows: Record<string, unknown>[];
  /** Raw file text, exported verbatim as the fixture. */
  raw: string;
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
}

// ── Render specs (one per catalog `renders_as` entry) ──────────────────────
// Discriminated union on `component`. Only the subset the client can author is
// modelled; each maps 1:1 to a catalog Render.

export type FigureVisuType = 'scatter' | 'line' | 'bar' | 'box' | 'histogram' | 'heatmap';

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
}

export interface TableRender {
  uid: string;
  component: 'table';
  id?: string;
}

/** Interactive filter control. The catalog `Render` model (extra="forbid")
 *  carries NOTHING for interactive beyond `component` — not even `column` — so
 *  the builder's column/variant/styling choices are authoring-preview only and
 *  are intentionally not part of the emitted render. */
export interface InteractiveRender {
  uid: string;
  component: 'interactive';
  id?: string;
}

export interface AdvancedVizRender {
  uid: string;
  component: 'advanced_viz';
  id?: string;
  kind: string;
  /** role → column. */
  roles: Record<string, string>;
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
  description?: string;
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
}
export type KindsMap = Record<string, KindDescriptor>;
