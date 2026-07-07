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

export interface ToolMeta {
  id: string;
  name: string;
  nf_core_url?: string;
  homepage?: string;
  biotools_url?: string;
  description?: string;
}

// ── Render specs (one per catalog `renders_as` entry) ──────────────────────
// Discriminated union on `component`. Only the subset the client can author is
// modelled; each maps 1:1 to a catalog Render.

export type FigureVisuType = 'scatter' | 'line' | 'bar' | 'box' | 'histogram' | 'heatmap';

export type Aggregation =
  | 'count'
  | 'sum'
  | 'average'
  | 'median'
  | 'min'
  | 'max'
  | 'range'
  | 'variance'
  | 'std_dev'
  | 'nunique'
  | 'mode';

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

export interface FigureRender {
  uid: string;
  component: 'figure';
  visu_type: FigureVisuType;
  /** Column-valued kwargs (x/y/color/…) + free kwargs (title, log_x, …). */
  dict_kwargs: Record<string, string>;
}

export interface CardRender {
  uid: string;
  component: 'card';
  column: string;
  aggregation: Aggregation;
}

export interface TableRender {
  uid: string;
  component: 'table';
}

export interface AdvancedVizRender {
  uid: string;
  component: 'advanced_viz';
  kind: string;
  /** role → column. */
  roles: Record<string, string>;
}

export type RenderSpec = FigureRender | CardRender | TableRender | AdvancedVizRender;

export interface OutputMeta {
  /** Short output slug, e.g. "coverage" → output id "<tool>_<slug>". */
  slug: string;
  path_glob: string;
  description?: string;
}

// ── kinds.json (generated from schemas.py at build) ────────────────────────

export interface KindDescriptor {
  roles: Record<string, string[]>;
  required_roles: string[];
  heavy: boolean;
  label: string;
}
export type KindsMap = Record<string, KindDescriptor>;
