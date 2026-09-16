/**
 * Pure spec builder for the `genomespy_track` kind.
 *
 * Turns the column-oriented rows `/advanced_viz/data` returns plus the
 * component config into a GenomeSpy root spec. No DOM, no React, no colour
 * literals: the palette and the axis colours come in from the renderer, which
 * resolves them from the Mantine theme. Kept separate from the renderer so
 * vitest (node environment) can cover it — see genomeSpySpec.test.ts.
 *
 * Grammar references (GenomeSpy 0.88): `encoding.x = {chrom, pos, type:
 * "locus"}` for chromosome-aware positions, root `genomes.<name>.contigs` for a
 * data-derived assembly, `params[].select` for point / interval selections,
 * `datasets` + `data.name` so the renderer can swap rows with
 * `api.datasets.set()` instead of re-embedding.
 */

export interface GenomeSpyTrackConfig {
  chr_col: string;
  pos_col: string;
  score_col: string;
  feature_col?: string | null;
  end_col?: string | null;
  mark?: 'point' | 'rect';
  assembly?: string | null;
  score_title?: string;
  score_threshold?: number | null;
  point_size?: number;
  opacity?: number;
  selection_enabled?: boolean;
  selection_column?: string | null;
}

export interface GenomeSpyThemeColors {
  /** Axis labels, tick labels, titles. */
  textColor: string;
  /** Grid and axis lines. */
  gridColor: string;
  /** The threshold rule. */
  ruleColor: string;
  /** Categorical hues, one per chromosome, cycled. */
  palette: readonly string[];
}

export interface BuildSpecInput {
  rows: Record<string, unknown[]>;
  config: GenomeSpyTrackConfig;
  colors: GenomeSpyThemeColors;
}

/** Name of the dataset the spec reads; `api.datasets.set(DATASET_NAME, …)`
 *  replaces it live. */
export const DATASET_NAME = 'rows';
/** Point selection param: a click on a mark. */
export const PICK_PARAM = 'pick';
/** Interval selection param along the genome axis. */
export const BRUSH_PARAM = 'brush';
/** Name of the data-derived assembly when `config.assembly` is unset. */
export const DATA_ASSEMBLY = 'data';

/** GenomeSpy's bundled assemblies. Anything else is treated as data-derived. */
export const BUILTIN_ASSEMBLIES: readonly string[] = ['hg38', 'hg19', 'hg18', 'mm10', 'mm9', 'dm6'];

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

export interface Contig {
  name: string;
  size: number;
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
export function requiredColumns(config: GenomeSpyTrackConfig, selectionColumn?: string): string[] {
  const cols = [config.chr_col, config.pos_col, config.score_col];
  for (const c of [config.end_col, config.feature_col, selectionColumn]) {
    if (c && !cols.includes(c)) cols.push(c);
  }
  return cols;
}

/** Whether the config resolves to interval marks. `rect` without an end column
 *  has nothing to span, so it degrades to points. */
export function effectiveMark(config: GenomeSpyTrackConfig): 'point' | 'rect' {
  return config.mark === 'rect' && config.end_col ? 'rect' : 'point';
}

/**
 * Build the root spec. `data` is the dataset the spec starts with; the
 * renderer may later replace it through `api.datasets.set(DATASET_NAME, …)`.
 */
export function buildGenomeSpySpec({ rows, config, colors }: BuildSpecInput): Record<string, unknown> {
  const columns = requiredColumns(
    config,
    config.selection_enabled && config.selection_column ? config.selection_column : undefined,
  );
  const data = rowsToObjects(rows, columns, config.chr_col, config.pos_col);
  const mark = effectiveMark(config);
  const assembly =
    config.assembly && BUILTIN_ASSEMBLIES.includes(config.assembly) ? config.assembly : DATA_ASSEMBLY;
  const contigs = assembly === DATA_ASSEMBLY ? contigsFromRows(data, config.chr_col, config.pos_col, config.end_col) : null;
  const chromosomes = sortChromosomes(data.map((d) => String(d[config.chr_col])));

  const xEncoding: Record<string, unknown> = {
    chrom: config.chr_col,
    pos: config.pos_col,
    type: 'locus',
    axis: { chromGrid: true, title: null },
  };
  const encoding: Record<string, unknown> = {
    x: xEncoding,
    y: {
      field: config.score_col,
      type: 'quantitative',
      title: config.score_title ?? config.score_col,
      axis: { grid: true },
    },
    color: {
      field: config.chr_col,
      type: 'nominal',
      legend: null,
      scale: {
        domain: chromosomes,
        range: chromosomes.map((_, i) => colors.palette[i % colors.palette.length]),
      },
    },
    opacity: {
      value: config.opacity ?? 0.85,
      // A picked mark is drawn fully opaque, so the click has visible feedback
      // before the dashboard filter lands.
      condition: { param: PICK_PARAM, value: 1 },
    },
  };
  if (mark === 'rect' && config.end_col) {
    encoding.x2 = { chrom: config.chr_col, pos: config.end_col };
  }

  const trackLayer: Record<string, unknown> = {
    name: 'track',
    params: [
      { name: PICK_PARAM, select: { type: 'point', on: 'click' } },
      { name: BRUSH_PARAM, select: { type: 'interval', encodings: ['x'] } },
    ],
    mark:
      mark === 'rect'
        ? { type: 'rect', minWidth: 1, minOpacity: 0.4 }
        : { type: 'point', size: (config.point_size ?? 5) ** 2 },
    encoding,
  };

  const layers: Record<string, unknown>[] = [trackLayer];
  if (config.score_threshold !== null && config.score_threshold !== undefined && Number.isFinite(config.score_threshold)) {
    layers.push({
      name: 'threshold',
      data: { values: [{}] },
      mark: { type: 'rule', color: colors.ruleColor, strokeDash: [4, 4], tooltip: null },
      encoding: {
        y: { datum: config.score_threshold, type: 'quantitative' },
      },
    });
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
    datasets: { [DATASET_NAME]: data },
    data: { name: DATASET_NAME },
    layer: layers,
  };
  if (contigs) {
    spec.genomes = { [DATA_ASSEMBLY]: { contigs } };
  }
  return spec;
}
