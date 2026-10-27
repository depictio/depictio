/**
 * Pure spec builder for the `genome_view` kind.
 *
 * Turns the column-oriented rows `/advanced_viz/data` returns plus the
 * component config into a GenomeSpy root spec. No DOM, no React, no colour
 * literals: the palette and the axis colours come in from the renderer, which
 * resolves them from the Mantine theme. Kept separate from the renderer so
 * vitest (node environment) can cover it (see genomeSpySpec.test.ts).
 *
 * Grammar references (GenomeSpy 0.88): `encoding.x = {chrom, pos, type:
 * "locus"}` for chromosome-aware positions, root `genomes.<name>.contigs` for a
 * data-derived assembly, `params[].select` for point / interval selections,
 * `datasets` + `data.name` so the renderer can swap rows with
 * `api.datasets.set()` instead of re-embedding.
 *
 * Three facts about GenomeSpy 0.88 shape this file:
 *
 * 1. **There is no line or area mark.** `markTypes` in the package is
 *    point / rect / arrow / rule / tick / link / text. A coverage profile is
 *    therefore drawn as `rect` bars from a baseline (`mark: 'bar'` here), not
 *    as a filled curve. `CoverageTrackRenderer` keeps the Plotly line for the
 *    dashboards that want one.
 * 2. **`facet` is an app-level feature**, so per-sample lanes are a hand-built
 *    `vconcat` of one view per sample, each narrowed by a `filter` transform
 *    over the one shared dataset.
 * 3. **An interval selection declared on the `vconcat` root** is the supported
 *    way to brush across every lane at once: `gridView.js` builds a
 *    container-wide overlay for it and `gridChild.js` deliberately skips it so
 *    the controllers do not double up.
 */

export interface GenomeViewConfig {
  /** `table` reads rows from /advanced_viz/data; `file` hands GenomeSpy an
   *  indexed file it range-loads itself (see fileSpec.ts). */
  source?: 'table' | 'file';
  chr_col: string;
  pos_col: string;
  score_col: string;
  feature_col?: string | null;
  end_col?: string | null;
  sample_col?: string | null;
  category_col?: string | null;
  mark?: 'point' | 'rect' | 'bar';
  facet_by_sample?: boolean;
  max_facets?: number;
  /** Y scale of the stacked lanes (default `shared`). */
  facet_y_scale?: 'shared' | 'independent';
  annotation?: 'none' | 'hg38' | 'mm10';
  assembly?: string | null;
  score_title?: string;
  score_threshold?: number | null;
  point_size?: number;
  opacity?: number;
  region_filter_enabled?: boolean;
  /** `select` (default): a drag brushes a region. `pan`: a drag moves the
   *  view and shift + drag brushes. */
  drag_mode?: 'select' | 'pan';
  follow_region_filter?: boolean;
  /** `chr1:10,000,000-12,000,000`: the region the section opens on, emitted
   *  once on the tile's first render. See `defaultRegion.ts`. */
  default_region?: string | null;
  /** Fixed height of each stacked lane in px; unset, they share the tile. */
  lane_height?: number | null;
  /** On opening: the whole chromosome of the region (default) or the region. */
  default_view?: 'chromosome' | 'region';
  selection_enabled?: boolean;
  selection_column?: string | null;
  // --- source: 'file' only -------------------------------------------------
  file_info_fields?: string[] | null;
  file_category_field?: string | null;
  file_categories?: string[] | null;
  file_add_chr_prefix?: boolean;
  file_window_size?: number | null;
  file_max_lanes?: number;
  file_tabix_columns?: string[] | null;
  file_bam_view?: 'coverage' | 'pileup';
}

export interface GenomeSpyThemeColors {
  /** Axis labels, tick labels, titles. */
  textColor: string;
  /** Grid and axis lines. */
  gridColor: string;
  /** The threshold rule. */
  ruleColor: string;
  /** Categorical hues, one per chromosome or category, cycled. */
  palette: readonly string[];
  /** Resolved CSS colours of the overlays (see `overlayRows.ts`). Unset:
   *  the spec carries no overlay layers. */
  overlay?: OverlayColors | null;
  /** Colours the dashboard pins, by column then value (see
   *  `columnCategoryColors`): a value they name keeps that colour, the others
   *  cycle the palette. */
  pinned?: Record<string, Record<string, string>> | null;
  /** Sample → colour of the genome browser tracks of the same samples (see
   *  `trackSampleColours`): a lane, or a sample's marks, wear its track's
   *  colour, so one library is one colour on both tiles. */
  laneColors?: Record<string, string> | null;
  /** The one colour of marks no category, lane colour or pin names. Unset:
   *  the palette's first hue. */
  neutral?: string | null;
}

/** One gene of the bundled annotation asset, already decoded. */
export interface GeneRow {
  name: string;
  chrom: string;
  start: number;
  end: number;
  strand: string;
}

export interface Contig {
  name: string;
  size: number;
}

/** The two named data sources of one lane's overlay layers. */
export interface OverlaySources {
  window: string;
  hover: string;
  selection: string;
}

/** Colours of the overlay layers, resolved from the theme by the renderer. */
export interface OverlayColors {
  /** The genome browser's window: a dashed outline. */
  windowColor: string;
  /** A hovered feature's rule. */
  hoverColor: string;
  /** The selected region's frame. Defaults to `windowColor`. */
  selectionColor?: string;
  /** The overlay labels. */
  labelColor?: string;
}

export interface BuildSpecInput {
  rows: Record<string, unknown[]>;
  config: GenomeViewConfig;
  colors: GenomeSpyThemeColors;
  /** A click on a mark filters the dashboard: the marks show a pointer. */
  clickable?: boolean;
  /**
   * Contigs of a built-in GenomeSpy assembly, resolved by the renderer through
   * `@genome-spy/core/genome/genomes.js`. Absent (or empty) means the contig
   * list is derived from the rows themselves, which is what a viral reference
   * or a draft assembly needs.
   */
  assemblyContigs?: readonly Contig[] | null;
  /** Genes for the annotation lane, or null for no lane. */
  genes?: readonly GeneRow[] | null;
}

export interface BuiltGenomeSpec {
  spec: Record<string, unknown>;
  /** The contig list the locus scale linearises over. The renderer needs it to
   *  turn a brushed interval back into a chromosome and a position range. */
  contigs: Contig[];
  /** Sample values that got a lane, in genome order. Empty when not faceted. */
  facets: string[];
  /** Samples `max_facets` left out. */
  droppedFacets: number;
  /** Rows that survived the chromosome / position guard. */
  rowCount: number;
  /** Genes drawn in the annotation lane. */
  geneCount: number;
  /** Names of the named data sources that feed the overlay layers, one pair
   *  per data lane (see `overlaySourceNames`). Empty without `colors.overlay`. */
  overlays: OverlaySources[];
}

/** Name of the dataset the spec reads; `api.datasets.set(DATASET_NAME, …)`
 *  replaces it live. */
export const DATASET_NAME = 'rows';
/** Dataset holding the annotation lane's genes. */
export const GENES_DATASET_NAME = 'genes';
/** Point selection param: a click on a mark. One per lane, suffixed when the
 *  view is faceted, because GenomeSpy addresses params by name alone and two
 *  independent params of the same name are an ambiguity error. */
export const PICK_PARAM = 'pick';
/** Interval selection param along the genome axis, declared once on the root. */
export const BRUSH_PARAM = 'brush';
/** Named data source of the band the genome browser's visible window draws. */
export const WINDOW_SOURCE = 'depictioWindow';
/** Named data source of the rule a hovered feature draws. */
export const HOVER_SOURCE = 'depictioHover';
/** Named data source of the selected region, framed by two rules. */
export const SELECTION_SOURCE = 'depictioSelection';
/** Name of the data-derived assembly when `config.assembly` is unset. */
export const DATA_ASSEMBLY = 'data';
/** Named x scale, so the renderer can reach it with
 *  `api.getScaleResolutionByName()` and zoom to an incoming region filter. */
export const GENOME_SCALE_NAME = 'genomeX';

/** GenomeSpy's bundled assemblies. Anything else is treated as data-derived. */
export const BUILTIN_ASSEMBLIES: readonly string[] = ['hg38', 'hg19', 'hg18', 'mm10', 'mm9', 'dm6'];

/** Assemblies a gene annotation lane ships for. */
export const ANNOTATION_ASSEMBLIES: readonly string[] = ['hg38', 'mm10'];

/** Natural chromosome order: chr1..chr22, chrX, chrY, chrM(T), then the rest
 *  alphabetically. Same rule ManhattanRenderer uses. */
export function chromosomeSortKey(label: string): number {
  const stripped = label.replace(/^chr/i, '').toUpperCase();
  if (stripped === 'X') return 23;
  if (stripped === 'Y') return 24;
  if (stripped === 'MT' || stripped === 'M') return 25;
  const n = Number.parseInt(stripped, 10);
  return Number.isFinite(n) ? n : 100;
}

export function sortChromosomes(labels: Iterable<string>): string[] {
  return Array.from(new Set(labels)).sort((a, b) => {
    const d = chromosomeSortKey(a) - chromosomeSortKey(b);
    return d !== 0 ? d : a.localeCompare(b);
  });
}

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Column-oriented rows → array of plain objects, dropping rows with no
 *  usable chromosome or position. Only the listed columns are carried. */
export function rowsToObjects(
  rows: Record<string, unknown[]>,
  columns: readonly string[],
  chrCol: string,
  posCol: string,
): Record<string, unknown>[] {
  const chrs = rows[chrCol] ?? [];
  const n = chrs.length;
  const out: Record<string, unknown>[] = [];
  for (let i = 0; i < n; i += 1) {
    const chr = chrs[i];
    if (chr === null || chr === undefined || chr === '') continue;
    if (num(rows[posCol]?.[i]) === null) continue;
    const obj: Record<string, unknown> = {};
    for (const c of columns) {
      const col = rows[c];
      if (col) obj[c] = col[i];
    }
    obj[chrCol] = String(chr);
    out.push(obj);
  }
  return out;
}

/**
 * The rows the spec is built from: the first fetch that carries at least one
 * usable row, kept for the life of the tile.
 *
 * A fetch with no usable rows (the tile mounted under a persistent filter that
 * matches nothing) must not become the seed: `contigsFromRows` would derive an
 * empty assembly and every later fetch would be swapped into a spec with no
 * contigs to draw on. Once a seed is latched it is never replaced, so a later
 * empty fetch only empties the dataset and the embed stays up.
 */
export function latchSeedRows(
  seed: Record<string, unknown[]> | null,
  rows: Record<string, unknown[]> | null,
  chrCol: string,
  posCol: string,
): Record<string, unknown[]> | null {
  if (seed) return seed;
  if (!rows) return null;
  return rowsToObjects(rows, [], chrCol, posCol).length > 0 ? rows : null;
}

/** One contig per chromosome seen in the data, sized to the largest position
 *  (or interval end) it carries, in natural order. */
export function contigsFromRows(
  data: readonly Record<string, unknown>[],
  chrCol: string,
  posCol: string,
  endCol?: string | null,
): Contig[] {
  const maxBy = new Map<string, number>();
  for (const row of data) {
    const chr = String(row[chrCol]);
    const p = num(row[posCol]) ?? 0;
    const e = endCol ? (num(row[endCol]) ?? p) : p;
    const prev = maxBy.get(chr) ?? 0;
    const m = Math.max(p, e);
    if (m > prev) maxBy.set(chr, m);
  }
  return sortChromosomes(maxBy.keys()).map((name) => ({
    name,
    // A contig must be longer than its last position, so GenomeSpy has room to
    // draw the mark and a locus axis tick after it.
    size: Math.max(1, Math.ceil((maxBy.get(name) ?? 0) * 1.02) + 1),
  }));
}

/** The columns the renderer must fetch for a config. */
export function requiredColumns(config: GenomeViewConfig, selectionColumn?: string): string[] {
  const cols = [config.chr_col, config.pos_col, config.score_col];
  for (const c of [
    config.end_col,
    config.feature_col,
    config.sample_col,
    config.category_col,
    selectionColumn,
  ]) {
    if (c && !cols.includes(c)) cols.push(c);
  }
  return cols;
}

/**
 * Whether the config resolves to interval marks.
 *
 * `rect` is a span from `pos` to `end`, so without an end column it has
 * nothing to span and degrades to points. `bar` draws the score from a
 * baseline and is meaningful with or without an end: without one it is a
 * one-pixel-wide spike, which is the coverage look at genome scale.
 */
export function effectiveMark(config: GenomeViewConfig): 'point' | 'rect' | 'bar' {
  const mark = config.mark ?? 'rect';
  if (mark === 'bar') return 'bar';
  return mark === 'rect' && config.end_col ? 'rect' : 'point';
}

/** Whether per-sample lanes are actually on: the config asked for them AND a
 *  sample column is bound. */
export function facetingEnabled(config: GenomeViewConfig): boolean {
  return Boolean(config.facet_by_sample && config.sample_col);
}

/** Distinct sample values in first-seen order, capped at `max_facets`. */
export function facetValues(
  data: readonly Record<string, unknown>[],
  sampleCol: string,
  maxFacets: number,
): { kept: string[]; dropped: number } {
  const seen: string[] = [];
  const set = new Set<string>();
  for (const row of data) {
    const v = row[sampleCol];
    if (v === null || v === undefined || v === '') continue;
    const s = String(v);
    if (set.has(s)) continue;
    set.add(s);
    seen.push(s);
  }
  seen.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const cap = Math.max(1, maxFacets);
  return { kept: seen.slice(0, cap), dropped: Math.max(0, seen.length - cap) };
}

// --- Linearised genome coordinates ----------------------------------------

export interface GenomeRegion {
  /** Chromosomes the brushed interval touches, in genome order. */
  chroms: string[];
  /** Position range within the chromosome, or null when the brush spans more
   *  than one: a single `[start, end]` pair has no meaning across contigs. */
  range: [number, number] | null;
}

/**
 * Turn a brushed interval of linearised coordinates back into a chromosome set
 * plus a position range.
 *
 * The brush GenomeSpy hands back (`IntervalSelection.intervals.x`) is in the
 * concatenated coordinate space, which no data collection has a column for.
 * The dashboard filter pipeline, on the other hand, only knows columns, so a
 * region has to be expressed as "`chr` is one of these" plus "`pos` is in this
 * range". When the brush covers several contigs the range is dropped rather
 * than faked: the honest filter is then the chromosome list alone.
 */
export function regionFromInterval(
  contigs: readonly Contig[],
  interval: readonly number[] | null | undefined,
): GenomeRegion | null {
  if (!interval || interval.length < 2) return null;
  const lo = Math.min(interval[0], interval[1]);
  const hi = Math.max(interval[0], interval[1]);
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return null;

  const touched: Array<{ name: string; from: number; to: number }> = [];
  let acc = 0;
  for (const c of contigs) {
    const cStart = acc;
    const cEnd = acc + c.size;
    acc = cEnd;
    if (hi <= cStart || lo >= cEnd) continue;
    touched.push({
      name: c.name,
      from: Math.max(0, Math.floor(lo - cStart)),
      to: Math.min(c.size, Math.ceil(hi - cStart)),
    });
  }
  if (touched.length === 0) return null;
  if (touched.length === 1) {
    return { chroms: [touched[0].name], range: [touched[0].from, touched[0].to] };
  }
  return { chroms: touched.map((t) => t.name), range: null };
}

// --- Spec assembly ---------------------------------------------------------

/** Height in pixels of the gene annotation lane. */
const ANNOTATION_LANE_HEIGHT = 34;
/** Minimum height of one data lane once several are stacked. */
export const FACET_LANE_HEIGHT = 26;
/** A stacked lane takes its share of the tile and never less than its floor,
 *  so a taller tile, or the tile in fullscreen, draws taller lanes. */
const FACET_LANE_SIZE = { grow: 1, minPx: FACET_LANE_HEIGHT };

/** Unset, lanes share the tile (fit, a resize redraws them); set, each lane
 *  is that tall whatever the tile, which scrolls when they do not fit. */
export function laneSize(
  laneHeight: number | null | undefined,
): number | { grow: number; minPx: number } {
  return laneHeight ? laneHeight : FACET_LANE_SIZE;
}

/** The distinct values of the sample column, sorted; none without one. */
function samplesOf(data: Record<string, unknown>[], config: GenomeViewConfig): string[] {
  const col = config.sample_col;
  if (!col) return [];
  const seen = new Set<string>();
  for (const d of data) {
    const v = d[col];
    if (v !== null && v !== undefined && v !== '') seen.add(String(v));
  }
  return [...seen].sort((a, b) => a.localeCompare(b));
}

function colourEncoding(
  field: string,
  domain: string[],
  palette: readonly string[],
  pinned?: Record<string, string> | null,
): Record<string, unknown> {
  return {
    field,
    type: 'nominal',
    legend: null,
    scale: {
      domain,
      range: domain.map((value, i) => pinned?.[value] ?? palette[i % palette.length]),
    },
  };
}

/**
 * The marks' colour: by `category_col` when the rows carry one (dashboard pins,
 * then the palette); else by sample, from the genome browser tracks of the same
 * samples (`laneColors`) or the dashboard's pins on the sample column; else one
 * neutral colour. A chromosome is never a colour of its own: the axis already
 * separates them, and a hue per contig reads as a grouping the data lacks.
 */
function markColour(
  config: GenomeViewConfig,
  colors: GenomeSpyThemeColors,
  categories: string[],
  samples: string[],
  laneSample: string | undefined,
): Record<string, unknown> {
  const neutral = colors.neutral || colors.palette[0];
  if (config.category_col && categories.length) {
    return colourEncoding(
      config.category_col,
      categories,
      colors.palette,
      colors.pinned?.[config.category_col],
    );
  }
  const sampleCol = config.sample_col;
  const bySample = {
    ...(sampleCol ? colors.pinned?.[sampleCol] : null),
    ...colors.laneColors,
  };
  if (laneSample !== undefined) return { value: bySample[laneSample] ?? neutral };
  if (sampleCol && samples.some((v) => bySample[v])) {
    return colourEncoding(sampleCol, samples, [neutral], bySample);
  }
  return { value: neutral };
}

function markFor(
  mark: 'point' | 'rect' | 'bar',
  config: GenomeViewConfig,
): Record<string, unknown> {
  if (mark === 'point') return { type: 'point', size: (config.point_size ?? 5) ** 2 };
  // A bar has to stay visible when a whole chromosome is a handful of pixels
  // wide, hence the clamped minimum width and the opacity floor that keeps the
  // clamping from fading it away entirely.
  return { type: 'rect', minWidth: mark === 'bar' ? 1 : 0.5, minOpacity: 0.4 };
}

/**
 * The overlay sources of data lane `lane`. The first lane owns the plain names
 * and later lanes take a suffix: a named source is addressed by name alone, so
 * two lanes declaring the same one would be an ambiguity GenomeSpy may refuse.
 * The renderer feeds every pair the same rows.
 */
export function overlaySourceNames(lane: number): OverlaySources {
  return lane === 0
    ? { window: WINDOW_SOURCE, hover: HOVER_SOURCE, selection: SELECTION_SOURCE }
    : {
        window: `${WINDOW_SOURCE}_${lane}`,
        hover: `${HOVER_SOURCE}_${lane}`,
        selection: `${SELECTION_SOURCE}_${lane}`,
      };
}

/**
 * The overlay layers of a lane, under nothing and over its marks:
 *
 * - the selection (rows `{chrom, start, end}`): the region left clear between
 *   two solid rules, nothing drawn over the rest (a tint or a veil reads as a
 *   blur over the data);
 * - the genome browser's visible window (rows `{chrom, start, end}`): a faint
 *   band between two dashed rules, so it never reads as the selection;
 * - a rule at a hovered position (rows `{chrom, pos}`).
 *
 * The first lane (`labelled`) also names the selection and the window, the
 * selection at its left edge and the window at its right one, both at the top.
 * None of them selects or filters: they only read the rows `updateNamedData`
 * hands them. The loci are on the lane's own genome scale, so they follow the
 * zoom.
 */
function buildOverlayLayers(
  lane: string,
  sources: OverlaySources,
  overlay: OverlayColors,
  labelled: boolean,
): Record<string, unknown>[] {
  const x = (pos: string) => ({
    chrom: 'chrom',
    pos,
    type: 'locus',
    scale: { name: GENOME_SCALE_NAME },
  });
  const span = { x: x('start'), x2: { chrom: 'chrom', pos: 'end' }, y: { value: 0 }, y2: { value: 1 } };
  const selectionColor = overlay.selectionColor ?? overlay.windowColor;
  const labelColor = overlay.labelColor ?? selectionColor;
  const label = (
    name: string,
    source: string,
    pos: string,
    align: 'left' | 'right',
    color: string,
  ) => ({
    name,
    data: { name: source },
    mark: {
      type: 'text',
      color,
      size: 11,
      align,
      baseline: 'top',
      dx: align === 'left' ? 5 : -5,
      dy: 3,
      tooltip: null,
    },
    encoding: { x: x(pos), y: { value: 1 }, text: { field: 'label' } },
  });
  const edges = (
    name: string,
    source: string,
    color: string,
    style: Record<string, unknown>,
  ) =>
    ['start', 'end'].map((pos) => ({
      name: `${name}-${pos}`,
      data: { name: source },
      mark: { type: 'rule', color, tooltip: null, ...style },
      encoding: { x: x(pos) },
    }));

  const layers: Record<string, unknown>[] = [
    ...edges(`${lane}-selection`, sources.selection, selectionColor, { size: 2 }),
    {
      name: `${lane}-window`,
      data: { name: sources.window },
      mark: { type: 'rect', color: overlay.windowColor, opacity: 0.06, minWidth: 2, tooltip: null },
      encoding: span,
    },
    ...edges(`${lane}-window`, sources.window, overlay.windowColor, {
      size: 1.5,
      strokeDash: [5, 4],
    }),
  ];
  if (labelled) {
    layers.push(
      label(`${lane}-selection-label`, sources.selection, 'start', 'left', labelColor),
      label(`${lane}-window-label`, sources.window, 'end', 'right', overlay.windowColor),
    );
  }
  layers.push({
    name: `${lane}-hover`,
    data: { name: sources.hover },
    mark: { type: 'rule', color: overlay.hoverColor, size: 1.5, tooltip: null },
    encoding: { x: x('pos') },
  });
  return layers;
}

function buildDataLane(
  config: GenomeViewConfig,
  colors: GenomeSpyThemeColors,
  mark: 'point' | 'rect' | 'bar',
  categories: string[],
  samples: string[],
  opts: {
    name: string;
    /** The sample a faceted lane draws. */
    laneSample?: string;
    pickParam: string;
    /** Show a pointer over the marks (a click filters). */
    clickable?: boolean;
    filterExpr?: string;
    title?: string;
    /** Leave the y axis untitled (stacked lanes: the lane title names it). */
    noYTitle?: boolean;
    height?: number | { grow: number; minPx: number };
    overlay?: { sources: OverlaySources; colors: OverlayColors; labelled: boolean };
  },
): Record<string, unknown> {
  const color = markColour(config, colors, categories, samples, opts.laneSample);

  const encoding: Record<string, unknown> = {
    x: {
      chrom: config.chr_col,
      pos: config.pos_col,
      type: 'locus',
      scale: { name: GENOME_SCALE_NAME },
      axis: { chromGrid: true, title: null },
    },
    y: {
      field: config.score_col,
      type: 'quantitative',
      title: opts.noYTitle ? null : (config.score_title ?? config.score_col),
      axis: { grid: true },
    },
    color,
    opacity: {
      value: config.opacity ?? 0.85,
      // A picked mark is drawn fully opaque, so the click has visible feedback
      // before the dashboard filter lands.
      condition: { param: opts.pickParam, value: 1 },
    },
  };
  if (config.end_col && (mark === 'rect' || mark === 'bar')) {
    encoding.x2 = { chrom: config.chr_col, pos: config.end_col };
  }
  if (mark === 'bar') {
    // GenomeSpy has no area mark: a rect anchored at the baseline is the
    // coverage profile. `datum` pins the second endpoint to a constant.
    encoding.y2 = { datum: 0 };
  }

  const layers: Record<string, unknown>[] = [
    {
      name: `${opts.name}-marks`,
      // The point selection belongs to the *unit* view that owns the mark, not
      // to the layer above it: GenomeSpy allocates the selection texture from
      // the mark's own view, and a param declared one level up makes it throw
      // "Bug: no selection texture found". The name is suffixed per lane
      // because params are addressed by name alone across the whole spec.
      params: [{ name: opts.pickParam, select: { type: 'point', on: 'click' } }],
      mark: { ...markFor(mark, config), ...(opts.clickable ? { cursor: 'pointer' } : {}) },
      encoding,
    },
  ];
  const threshold = config.score_threshold;
  if (threshold !== null && threshold !== undefined && Number.isFinite(threshold)) {
    layers.push({
      name: `${opts.name}-threshold`,
      data: { values: [{}] },
      mark: { type: 'rule', color: colors.ruleColor, strokeDash: [4, 4], tooltip: null },
      encoding: { y: { datum: threshold, type: 'quantitative' } },
    });
  }

  if (opts.overlay) {
    layers.push(
      ...buildOverlayLayers(opts.name, opts.overlay.sources, opts.overlay.colors, opts.overlay.labelled),
    );
  }

  const lane: Record<string, unknown> = {
    name: opts.name,
    // A drag selects a region (see the brush param), as the crosshair says,
    // or moves the view in pan mode; a mark a click filters on overrides it
    // with a pointer.
    cursor: config.drag_mode === 'pan' ? 'grab' : 'crosshair',
    layer: layers,
  };
  if (opts.filterExpr) lane.transform = [{ type: 'filter', expr: opts.filterExpr }];
  if (opts.title) {
    // Above the lane, horizontal: a rotated title on the left collides with the
    // y axis and cannot be read once the lanes are short.
    lane.title = {
      text: opts.title,
      orient: 'top',
      anchor: 'start',
      // Bold and clear of the lane's top grid line, so the library name reads
      // even under the browser's window band.
      fontSize: 12,
      fontWeight: 'bold',
      offset: 4,
      color: colors.textColor,
    };
  }
  if (opts.height) lane.height = opts.height;
  return lane;
}

/**
 * The gene annotation lane: one rect per gene plus a label that fades in as the
 * reader zooms.
 *
 * `opacity: { unitsPerPixel, values }` is GenomeSpy's semantic-zoom knob: at
 * genome scale 20 000 labels would be a grey smear, so they are invisible until
 * the visible window is small enough for the names to be readable. The rects
 * stay drawn at every zoom level, which is what makes the lane useful as an
 * orientation strip.
 */
function buildAnnotationLane(
  genes: readonly GeneRow[],
  colors: GenomeSpyThemeColors,
): Record<string, unknown> {
  const [geneColor] = colors.palette;
  return {
    name: 'annotation',
    height: ANNOTATION_LANE_HEIGHT,
    data: { name: GENES_DATASET_NAME },
    // No y scale at all: constant positional `value`s are normalised 0..1
    // within the lane, so this view resolves nothing against the data tracks'
    // score axis.
    layer: [
      {
        name: 'annotation-genes',
        mark: { type: 'rect', minWidth: 1, minOpacity: 0.4 },
        encoding: {
          x: { chrom: 'chrom', pos: 'start', type: 'locus', scale: { name: GENOME_SCALE_NAME } },
          x2: { chrom: 'chrom', pos: 'end' },
          y: { value: 0.3 },
          y2: { value: 0.7 },
          color: { value: geneColor ?? colors.gridColor },
        },
      },
      {
        name: 'annotation-labels',
        opacity: { unitsPerPixel: [100000, 20000], values: [0, 1] },
        mark: { type: 'text', size: 10, align: 'center', baseline: 'middle', tooltip: null },
        encoding: {
          x: { chrom: 'chrom', pos: 'start', type: 'locus', scale: { name: GENOME_SCALE_NAME } },
          x2: { chrom: 'chrom', pos: 'end' },
          y: { value: 0.5 },
          text: { field: 'name' },
          color: { value: colors.textColor },
        },
      },
    ],
    // `genes` is a static asset: the count is large and the geometry never
    // changes, so it stays out of the pick path.
    resolve: { scale: { y: 'independent' } },
  };
}

/**
 * Build the root spec. `data` is the dataset the spec starts with; the
 * renderer may later replace it through `api.datasets.set(DATASET_NAME, …)`.
 */
export function buildGenomeSpySpec({
  rows,
  config,
  colors,
  assemblyContigs,
  genes,
  clickable = false,
}: BuildSpecInput): BuiltGenomeSpec {
  const columns = requiredColumns(
    config,
    config.selection_enabled && config.selection_column ? config.selection_column : undefined,
  );
  const data = rowsToObjects(rows, columns, config.chr_col, config.pos_col);
  const mark = effectiveMark(config);

  const builtin =
    config.assembly && BUILTIN_ASSEMBLIES.includes(config.assembly) ? config.assembly : null;
  const useBuiltinContigs = Boolean(builtin && assemblyContigs && assemblyContigs.length);
  const assembly = builtin ?? DATA_ASSEMBLY;
  const contigs: Contig[] = useBuiltinContigs
    ? Array.from(assemblyContigs as readonly Contig[])
    : contigsFromRows(data, config.chr_col, config.pos_col, config.end_col);

  const chromosomes = sortChromosomes(data.map((d) => String(d[config.chr_col])));
  const categories = config.category_col
    ? Array.from(
        new Set(
          data
            .map((d) => d[config.category_col as string])
            .filter((v) => v !== null && v !== undefined && v !== '')
            .map((v) => String(v)),
        ),
      ).sort((a, b) => a.localeCompare(b))
    : [];

  const faceted = facetingEnabled(config);
  const { kept, dropped } = faceted
    ? facetValues(data, config.sample_col as string, config.max_facets ?? 8)
    : { kept: [] as string[], dropped: 0 };

  const overlayColors = colors.overlay ?? null;
  const overlays: OverlaySources[] = [];
  const overlayFor = (lane: number) => {
    if (!overlayColors) return undefined;
    const sources = overlaySourceNames(lane);
    overlays.push(sources);
    return { sources, colors: overlayColors, labelled: lane === 0 };
  };

  const lanes: Record<string, unknown>[] = [];
  if (faceted && kept.length > 0) {
    const sampleCol = config.sample_col as string;
    kept.forEach((sample, i) => {
      lanes.push(
        buildDataLane(config, colors, mark, categories, kept, {
          name: `track_${i}`,
          laneSample: sample,
          pickParam: `${PICK_PARAM}_${i}`,
          clickable,
          // vega-expression over the one shared dataset, so N lanes cost one
          // copy of the rows rather than N.
          filterExpr: `datum[${JSON.stringify(sampleCol)}] === ${JSON.stringify(sample)}`,
          // The score's name goes in the lane title, once, not on every y axis.
          // ASCII only: GenomeSpy's bundled font has no middle dot.
          title: i === 0 ? `${sample} | ${config.score_title ?? config.score_col}` : sample,
          noYTitle: true,
          height: laneSize(config.lane_height),
          overlay: overlayFor(i),
        }),
      );
    });
  } else {
    lanes.push(
      buildDataLane(config, colors, mark, categories, samplesOf(data, config), {
        name: 'track',
        pickParam: PICK_PARAM,
        clickable,
        overlay: overlayFor(0),
      }),
    );
  }

  const laneGenes =
    genes && genes.length
      ? genes.filter((g) => contigs.some((c) => c.name === g.chrom))
      : [];
  if (laneGenes.length) lanes.push(buildAnnotationLane(laneGenes, colors));

  const datasets: Record<string, unknown[]> = { [DATASET_NAME]: data };
  if (laneGenes.length) datasets[GENES_DATASET_NAME] = laneGenes as unknown[];
  // Seeded empty so the named sources exist before the first window or hover.
  for (const o of overlays) {
    datasets[o.window] = [];
    datasets[o.hover] = [];
    datasets[o.selection] = [];
  }

  const spec: Record<string, unknown> = {
    // Axis and view colours follow the Mantine scheme; the container shows
    // through, so the tile matches the card it sits in.
    config: {
      view: { fill: null, stroke: null },
      axis: {
        labelColor: colors.textColor,
        titleColor: colors.textColor,
        tickColor: colors.gridColor,
        domainColor: colors.gridColor,
        gridColor: colors.gridColor,
      },
    },
    assembly,
    datasets,
    data: { name: DATASET_NAME },
    // One genome axis under the whole stack. The y scale is one ruler across
    // the lanes (two samples' coverage compared) unless `facet_y_scale` asks
    // for one per lane (peak scores, where one sample would flatten the rest).
    resolve: {
      axis: { x: 'shared' },
      scale: {
        x: 'shared',
        y: faceted && config.facet_y_scale === 'independent' ? 'independent' : 'shared',
      },
    },
    vconcat: lanes,
    // Room for each lane's title above it.
    spacing: 7,
  };
  if (config.region_filter_enabled !== false) {
    // Declared on the vconcat root on purpose: GenomeSpy builds a
    // container-wide selection overlay for an interval param owned by a grid
    // view, so one drag brushes every lane at once.
    // A plain drag brushes, as in a Plotly figure's default drag mode, and
    // the axis zooms with Cmd/Ctrl + wheel. In pan mode a plain drag moves the
    // view and the brush takes shift + drag, GenomeSpy's own default on a
    // zoomable axis; the hover hint says which.
    const on =
      config.drag_mode === 'pan' ? { type: 'mousedown', filter: 'event.shiftKey' } : 'mousedown';
    spec.params = [{ name: BRUSH_PARAM, select: { type: 'interval', encodings: ['x'], on } }];
  }
  if (!useBuiltinContigs) {
    spec.genomes = { [DATA_ASSEMBLY]: { contigs } };
  }

  return {
    spec,
    contigs,
    facets: kept,
    droppedFacets: dropped,
    rowCount: data.length,
    geneCount: laneGenes.length,
    overlays,
  };
}
