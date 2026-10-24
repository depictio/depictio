/**
 * Presentation options of the stacked composition bar that do not depend on
 * the data: which controls the tile offers, what the sample axis is called and
 * where the legend sits. Pure, so the choices are tested without Plotly.
 *
 * The kind stacks any per-sample composition, not only taxa (CCS outcomes per
 * library, structural categories per sample), so a tile can drop the taxonomy
 * controls that mean nothing for it. Every default reproduces the taxonomy
 * tile as it was.
 */

export type TaxonomyControl = 'rank' | 'sample_sort' | 'top_n' | 'normalise' | 'group' | 'zoom';

const ALL_CONTROLS: readonly TaxonomyControl[] = [
  'rank',
  'sample_sort',
  'top_n',
  'normalise',
  'group',
  'zoom',
];

/** Which primary controls the tile offers, given the config's hidden list. */
export function visibleTaxonomyControls(
  hidden: readonly string[] | null | undefined,
): Record<TaxonomyControl, boolean> {
  const off = new Set(hidden ?? []);
  return Object.fromEntries(ALL_CONTROLS.map((c) => [c, !off.has(c)])) as Record<
    TaxonomyControl,
    boolean
  >;
}

/** Sample axis title: unset reads "Sample", an empty string hides it. */
export function taxonomyAxisTitle(xTitle: string | null | undefined): string | undefined {
  if (xTitle === '') return undefined;
  return xTitle ?? 'Sample';
}

/** Past this many bars the tilted labels overlap each other; hover names each
 *  bar instead. */
export const DENSE_AXIS_BARS = 40;

/** Whether `bars` samples make the axis too dense for its tick labels. */
export function isDenseTaxonomyAxis(bars: number): boolean {
  return bars > DENSE_AXIS_BARS;
}

export type TaxonomyLegendPos = 'right' | 'bottom';

/** What every placement shares: the key is titled with the rank it shows. */
const legendCommon = (title: string) => ({ title: { text: `${title} ` }, font: { size: 10 } });

/**
 * The taxa's legend. `right` (the default): a column right of the plot, clear
 * of the tilted sample labels. `bottom`: rows under the whole figure, below the
 * sample labels and the axis title; on a dense axis, whose labels are hidden,
 * rows above the bars instead, where it does not float in their empty band.
 */
export function taxonomyLegend(
  pos: TaxonomyLegendPos | null | undefined,
  denseAxis: boolean,
  title: string,
): Record<string, unknown> {
  if (pos !== 'bottom') {
    return { orientation: 'v', x: 1.02, xanchor: 'left', y: 1, yanchor: 'top', ...legendCommon(title) };
  }
  if (denseAxis) {
    return { orientation: 'h', x: 0, xanchor: 'left', y: 1.02, yanchor: 'bottom', ...legendCommon(title) };
  }
  // Anchored to the figure's own bottom edge (`yref: 'container'`), so it
  // clears the automargined sample labels whatever their length.
  return {
    orientation: 'h',
    x: 0,
    xanchor: 'left',
    y: 0,
    yref: 'container',
    yanchor: 'bottom',
    ...legendCommon(title),
  };
}

/** Extra top margin, px, a legend drawn above the bars takes. */
export function taxonomyLegendTopPx(
  pos: TaxonomyLegendPos | null | undefined,
  denseAxis: boolean,
  showLegend: boolean,
): number {
  return showLegend && pos === 'bottom' && denseAxis ? 40 : 0;
}

// ---------------------------------------------------------------------------
// Wide tables: one numeric column per category
// ---------------------------------------------------------------------------

/** A category's display name in the wide form: its label, else its column. */
export function wideCategoryName(
  column: string,
  labels: Readonly<Record<string, string>> | null | undefined,
): string {
  return labels?.[column] || column;
}

/** The long form the renderer aggregates: one entry per (sample, category). */
export interface LongComposition {
  samples: string[];
  taxa: string[];
  abundances: number[];
}

/**
 * Melt a wide table (one row per sample, one numeric column per category)
 * into the long form. Row by row, then column by column, so the samples keep
 * the table's order and, on equal totals, the categories keep `valueCols`'
 * order. A column the table lacks contributes nothing; a non-numeric or empty
 * cell counts as 0.
 */
export function meltWideRows(
  rows: Readonly<Record<string, readonly unknown[] | undefined>>,
  sampleCol: string,
  valueCols: readonly string[],
  labels?: Readonly<Record<string, string>> | null,
): LongComposition {
  const ids = rows[sampleCol] ?? [];
  const present = valueCols.filter((c) => Array.isArray(rows[c]));
  const out: LongComposition = { samples: [], taxa: [], abundances: [] };
  for (let i = 0; i < ids.length; i++) {
    const sample = String(ids[i] ?? '');
    for (const c of present) {
      const v = Number(rows[c]![i]);
      out.samples.push(sample);
      out.taxa.push(wideCategoryName(c, labels));
      out.abundances.push(Number.isFinite(v) ? v : 0);
    }
  }
  return out;
}

/** Columns a stacked composition fetches: the long-form bindings, or the
 *  sample id and the value columns of a wide table; then the per-sample
 *  annotation columns, each once. */
export function compositionColumns(opts: {
  sampleCol: string | null | undefined;
  taxonCol: string | null | undefined;
  rankCol: string | null | undefined;
  abundanceCol: string | null | undefined;
  valueCols: readonly string[] | null | undefined;
  extra: readonly (string | null | undefined)[];
}): string[] {
  const wide = (opts.valueCols ?? []).filter(Boolean);
  const head = wide.length
    ? [opts.sampleCol, ...wide]
    : [opts.sampleCol, opts.taxonCol, opts.rankCol, opts.abundanceCol];
  const out: string[] = [];
  for (const c of [...head, ...opts.extra]) if (c && !out.includes(c)) out.push(c);
  return out;
}

// ---------------------------------------------------------------------------
// Bar order: sort modes and grouping (multi-level sort)
// ---------------------------------------------------------------------------

/** How the bars are ordered. `input`, `total_abundance` and `first_taxon` are
 *  the shipped values; `name` and `category` came with non-taxonomy tiles. */
export type TaxonomySampleSort = 'input' | 'name' | 'total_abundance' | 'first_taxon' | 'category';

/** The sort picker's entries, in the order the picker lists them. */
export const SAMPLE_SORT_OPTIONS: readonly { value: TaxonomySampleSort; label: string }[] = [
  { value: 'input', label: 'Input order' },
  { value: 'name', label: 'Name' },
  { value: 'total_abundance', label: 'Total' },
  { value: 'first_taxon', label: 'Top category' },
  { value: 'category', label: 'Category share' },
];

const NATURAL = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });

/** Natural order: `S2` before `S10`, case-insensitive; ties fall back to the
 *  exact string so the order is total. */
export function naturalCompare(a: string, b: string): number {
  const c = NATURAL.compare(a, b);
  if (c !== 0) return c;
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Per-sample values a value sort reads. */
export interface SampleSortScores {
  /** Raw total of the bar. */
  total: (sample: string) => number;
  /** Raw value of the overall most abundant category (`first_taxon`). */
  firstTaxon: (sample: string) => number;
  /** Plotted value (the share, when normalised) of the chosen category. */
  category: (sample: string) => number;
}

/**
 * The bars in display order. `input` keeps the table's order, `name` is
 * natural ascending, every value sort is largest first. The sort is stable, so
 * ties keep the table's order; an unknown mode is `input`.
 */
export function sortSamples(
  samples: readonly string[],
  mode: string | null | undefined,
  scores: SampleSortScores,
): string[] {
  const out = [...samples];
  switch (mode) {
    case 'name':
      return out.sort(naturalCompare);
    case 'total_abundance':
      return out.sort((a, b) => scores.total(b) - scores.total(a));
    case 'first_taxon':
      return out.sort((a, b) => scores.firstTaxon(b) - scores.firstTaxon(a));
    case 'category':
      return out.sort((a, b) => scores.category(b) - scores.category(a));
    default:
      return out;
  }
}

/** The category a `category` sort reads: the configured one when it is shown,
 *  else the first (most abundant) category. */
export function resolveSortCategory(
  wanted: string | null | undefined,
  categories: readonly string[],
): string | null {
  if (wanted && categories.includes(wanted)) return wanted;
  return categories[0] ?? null;
}

export interface BarGroup {
  name: string;
  samples: string[];
}

/**
 * Split already-sorted bars into groups by `groupOf`, keeping the sort inside
 * each group. Groups follow the first appearance of their value in
 * `inputOrder`, or natural name order when `byName` (a `name` sort).
 */
export function groupSamples(
  sorted: readonly string[],
  inputOrder: readonly string[],
  groupOf: (sample: string) => string,
  byName: boolean,
): BarGroup[] {
  const members = new Map<string, string[]>();
  for (const s of sorted) {
    const g = groupOf(s);
    if (!members.has(g)) members.set(g, []);
    members.get(g)!.push(s);
  }
  const order: string[] = [];
  const placed = new Set<string>();
  for (const s of [...inputOrder, ...sorted]) {
    const g = groupOf(s);
    if (members.has(g) && !placed.has(g)) {
      placed.add(g);
      order.push(g);
    }
  }
  if (byName) order.sort(naturalCompare);
  return order.map((name) => ({ name, samples: members.get(name)! }));
}

/** A spacer slot is a run of zero-width spaces: blank as a tick label, and
 *  never a sample id a table carries. */
const SPACER_CHAR = '​';

export function isSpacerSlot(slot: string): boolean {
  return slot.length > 0 && [...slot].every((c) => c === SPACER_CHAR);
}

export interface BarSlots {
  /** Category-axis entries in order: sample ids, with spacers between groups. */
  slots: string[];
  /** Each group's name, its slot span (inclusive), and the spacer slot just
   *  before it, if any (`labelSlot`). */
  spans: { name: string; start: number; end: number; labelSlot: number | null }[];
}

/**
 * Lay groups out on the category axis. One spacer slot sits between two
 * groups, so they read apart; `leading` also puts one before the first group,
 * which is where a horizontal chart writes each group's name.
 */
export function barSlots(groups: readonly BarGroup[], leading: boolean): BarSlots {
  const slots: string[] = [];
  const spans: BarSlots['spans'] = [];
  let spacers = 0;
  groups.forEach((g, k) => {
    let labelSlot: number | null = null;
    if (k > 0 || leading) {
      spacers += 1;
      labelSlot = slots.length;
      slots.push(SPACER_CHAR.repeat(spacers));
    }
    const start = slots.length;
    slots.push(...g.samples);
    spans.push({ name: g.name, start, end: slots.length - 1, labelSlot });
  });
  return { slots, spans };
}

// ---------------------------------------------------------------------------
// Value-axis zoom: crop a near-identical base and mark the break
// ---------------------------------------------------------------------------

/** A "nice" step at least `x`: 1, 2 or 5 times a power of ten. */
export function niceStep(x: number): number {
  if (!(x > 0) || !Number.isFinite(x)) return 1;
  const p = 10 ** Math.floor(Math.log10(x));
  for (const m of [1, 2, 5, 10]) {
    const step = m * p;
    if (step >= x * (1 - 1e-9)) return Number(step.toPrecision(12));
  }
  return Number((10 * p).toPrecision(12));
}

/** Margin under the smallest bottom segment, as a share of the part shown. */
const ZOOM_MARGIN = 0.1;
/** A crop whose floor stays under this share of the axis gains nothing. */
const ZOOM_MIN_GAIN = 0.1;

export interface ValueAxisZoom {
  /** Where the cropped axis starts. */
  floor: number;
  /** Where it ends: 1 when normalised, else just over the tallest bar. */
  top: number;
  /** The rounding step the floor sits on; sets the tick precision. */
  step: number;
}

/**
 * The cropped value-axis range, or null when cropping would gain nothing.
 *
 * `bottom[i]` is bar i's bottom segment (the overall largest category, which
 * stacks first) and `totals[i]` its stacked height. The axis starts a little
 * under the smallest bottom segment, rounded down to a nice step, so the part
 * that varies fills the plot. Bars of zero height (spacers) are ignored.
 */
export function zoomedValueRange(
  bottom: readonly (number | null | undefined)[],
  totals: readonly (number | null | undefined)[],
  normalised: boolean,
): ValueAxisZoom | null {
  let min = Infinity;
  let max = 0;
  totals.forEach((t, i) => {
    const total = Number(t) || 0;
    if (total <= 0) return;
    min = Math.min(min, Number(bottom[i]) || 0);
    max = Math.max(max, total);
  });
  if (!Number.isFinite(min) || min <= 0) return null;
  const top = normalised ? 1 : max;
  if (!(top > min)) return null;
  const raw = min - ZOOM_MARGIN * (top - min);
  const step = niceStep((top - raw) / 4);
  const floor = Number((Math.floor(raw / step + 1e-9) * step).toPrecision(12));
  if (floor <= 0 || floor < ZOOM_MIN_GAIN * top) return null;
  const paddedTop = normalised ? 1 : Number((top + 0.02 * (top - floor)).toPrecision(12));
  return { floor, top: paddedTop, step };
}

/** Decimals a value printed on `unit` steps needs. */
function decimalsFor(unit: number): number {
  return Math.max(0, Math.ceil(-Math.log10(unit) - 1e-9));
}

/** Tick format of a cropped percent axis: enough decimals for its step. */
export function percentTickFormat(step: number): string {
  return `.${decimalsFor(step * 100)}%`;
}

/** The floor as the axis prints it. */
export function formatAxisFloor(zoom: ValueAxisZoom, normalised: boolean): string {
  if (normalised) return `${(zoom.floor * 100).toFixed(decimalsFor(zoom.step * 100))}%`;
  const d = decimalsFor(zoom.step);
  return zoom.floor.toLocaleString('en', { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** Value-axis title, saying so when the axis is cropped. Unset reads
 *  `fallback`; an empty string shows none, unless the axis is cropped. */
export function valueAxisTitle(
  configured: string | null | undefined,
  fallback: string,
  croppedFrom: string | null,
): string | undefined {
  const base = configured === '' ? '' : (configured ?? fallback);
  if (!croppedFrom) return base || undefined;
  return base ? `${base} (axis from ${croppedFrom})` : `Axis from ${croppedFrom}`;
}

export type TaxonomyOrientation = 'v' | 'h';

/**
 * The classic `//` break marker at the base of the value axis, as Plotly line
 * shapes sized in pixels around a paper-coordinate anchor, so the slashes keep
 * their angle whatever the plot's aspect.
 *
 * `v`: the value axis is vertical at paper x = `anchor.x`, its base at paper
 * y = `anchor.y`, and the marker sits a few px above the base. `h`: the value
 * axis is horizontal at paper y = `anchor.y`, its base at paper x = `anchor.x`,
 * and the marker sits a few px right of it. A short background-coloured stroke
 * cuts the axis line between the two slashes.
 */
export function axisBreakShapes(
  orientation: TaxonomyOrientation,
  anchor: { x: number; y: number },
  colors: { line: string; background: string },
): Record<string, unknown>[] {
  const base = {
    type: 'line',
    xref: 'paper',
    yref: 'paper',
    xsizemode: 'pixel',
    ysizemode: 'pixel',
    xanchor: anchor.x,
    yanchor: anchor.y,
    layer: 'above',
  };
  /** Distance of the marker's centre from the axis base, px. */
  const at = 10;
  /** Half the distance between the slashes, px. */
  const half = 3;
  /** Half a slash's length across the axis, px. */
  const reach = 5;
  /** Half a slash's run along the axis, px: the lean. */
  const lean = 3;
  const cut = { ...base, line: { color: colors.background, width: 4 } };
  const slash = { ...base, line: { color: colors.line, width: 1.5 } };
  if (orientation === 'h') {
    return [
      { ...cut, x0: at - half, x1: at + half, y0: 0, y1: 0 },
      { ...slash, x0: at - half - lean, x1: at - half + lean, y0: -reach, y1: reach },
      { ...slash, x0: at + half - lean, x1: at + half + lean, y0: -reach, y1: reach },
    ];
  }
  return [
    { ...cut, x0: 0, x1: 0, y0: at - half, y1: at + half },
    { ...slash, x0: -reach, x1: reach, y0: at - half - lean, y1: at - half + lean },
    { ...slash, x0: -reach, x1: reach, y0: at + half - lean, y1: at + half + lean },
  ];
}
