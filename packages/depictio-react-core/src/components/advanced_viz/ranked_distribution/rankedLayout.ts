/**
 * Pure logic for the `ranked_distribution` kind.
 *
 * Free of React, Plotly and the DOM so vitest covers it in the node
 * environment: row parsing for both distribution shapes, the ranking and the
 * top-N cut, the box statistics of a long-form feature, and the assembly of
 * the two Plotly panels that share one ordered category axis. The renderer
 * keeps only the fetch, the colours it reads off the theme and the dashboard,
 * the controls and the click.
 *
 * Row contract (canonical `ranked_distribution` roles):
 *   feature_id, score                          required
 *   rank, label, group                         optional, per feature
 *   value                                      long form: one row per feature and sample
 *   q1, median, q3 (+ lower, upper, mean)      pre-aggregated: one row per feature
 */

/** Which of the two row shapes a binding reads. */
export type DistributionShape = 'long' | 'stats';
export type DistributionMark = 'box' | 'violin';
export type RankedOrientation = 'horizontal' | 'vertical';

/** Column names the renderer binds, straight off `RankedDistributionConfig`. */
export interface RankedColumns {
  featureId: string;
  score: string;
  rank?: string | null;
  label?: string | null;
  group?: string | null;
  value?: string | null;
  q1?: string | null;
  median?: string | null;
  q3?: string | null;
  lower?: string | null;
  upper?: string | null;
  mean?: string | null;
  /** The column a click selects on, when it is not one of the above. */
  selection?: string | null;
}

/** The five numbers a box is drawn from, plus the optional mean and count. */
export interface BoxStats {
  q1: number;
  median: number;
  q3: number;
  lower: number;
  upper: number;
  mean: number | null;
  /** Values summarised (long form only). */
  n: number | null;
}

/** One feature, its score and its distribution. */
export interface RankedFeature {
  id: string;
  label: string;
  score: number;
  /** 1 = first. NaN until `rankFeatures` places it, unless the rank column gave one. */
  rank: number;
  group: string | null;
  /** The value of the selection column on this feature's (first) row. */
  selectionValue: string | null;
  stats: BoxStats | null;
  /** The raw values (long form); empty for the pre-aggregated shape. */
  values: number[];
}

/** The shape a binding reads, or null when it binds neither (an incomplete config). */
export function shapeOf(cols: RankedColumns): DistributionShape | null {
  if (cols.value) return 'long';
  if (cols.q1 && cols.median && cols.q3) return 'stats';
  return null;
}

/** Every column the renderer fetches for `cols`, required first, deduplicated. */
export function columnsToFetch(cols: RankedColumns): string[] {
  const out: string[] = [];
  const shape = shapeOf(cols);
  const candidates = [
    cols.featureId,
    cols.score,
    cols.rank,
    cols.label,
    cols.group,
    cols.selection,
    ...(shape === 'long' ? [cols.value] : []),
    ...(shape === 'stats' ? [cols.q1, cols.median, cols.q3, cols.lower, cols.upper, cols.mean] : []),
  ];
  for (const c of candidates) if (c && !out.includes(c)) out.push(c);
  return out;
}

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

const text = (v: unknown): string | null => {
  if (v === null || v === undefined) return null;
  const s = String(v);
  return s === '' ? null : s;
};

/**
 * The `p` quantile of an ascending-sorted array, linearly interpolated
 * between order statistics (numpy's default, R's type 7). NaN for no values.
 */
export function quantile(sorted: readonly number[], p: number): number {
  if (sorted.length === 0) return Number.NaN;
  if (sorted.length === 1) return sorted[0];
  const h = (sorted.length - 1) * Math.min(1, Math.max(0, p));
  const lo = Math.floor(h);
  const hi = Math.ceil(h);
  return sorted[lo] + (h - lo) * (sorted[hi] - sorted[lo]);
}

/**
 * Box statistics of raw values: quartiles by `quantile`, Tukey whiskers (the
 * most extreme values within 1.5 IQR of the box) and the mean. Null for no
 * finite value.
 */
export function boxStats(values: readonly number[]): BoxStats | null {
  const sorted = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (sorted.length === 0) return null;
  const q1 = quantile(sorted, 0.25);
  const median = quantile(sorted, 0.5);
  const q3 = quantile(sorted, 0.75);
  const iqr = q3 - q1;
  const lowFence = q1 - 1.5 * iqr;
  const highFence = q3 + 1.5 * iqr;
  let lower = q1;
  let upper = q3;
  for (const v of sorted) {
    if (v >= lowFence) {
      lower = Math.min(v, q1);
      break;
    }
  }
  for (let i = sorted.length - 1; i >= 0; i--) {
    if (sorted[i] <= highFence) {
      upper = Math.max(sorted[i], q3);
      break;
    }
  }
  const mean = sorted.reduce((acc, v) => acc + v, 0) / sorted.length;
  return { q1, median, q3, lower, upper, mean, n: sorted.length };
}

/** log10(x + 1), the transform a count axis spanning decades is drawn on. Null below -1. */
export function log1p10(x: number): number | null {
  return x > -1 ? Math.log10(x + 1) : null;
}

/** What one pre-aggregated row publishes. */
export interface PublishedStats {
  q1: number;
  median: number;
  q3: number;
  lower: number | null;
  upper: number | null;
  mean: number | null;
}

/**
 * A pre-aggregated box from what a row publishes, on the drawn axis.
 *
 * Quartiles and fences are order statistics, so they map through the log
 * transform; a mean does not (the log of a mean is not the mean of the logs),
 * so on the log axis it is dropped rather than drawn where it does not belong.
 * Whiskers a recipe did not publish are Tukey's fences around the box, taken
 * on the drawn axis: on a log axis a linear fence would fall below zero for
 * any count. A published fence the transform cannot take is replaced the
 * same way. Null when a quartile has no log.
 */
export function statsFromRow(row: PublishedStats, logValue = false): BoxStats | null {
  const t = (v: number | null): number | null => (v === null ? null : logValue ? log1p10(v) : v);
  const q1 = t(row.q1);
  const median = t(row.median);
  const q3 = t(row.q3);
  if (q1 === null || median === null || q3 === null) return null;
  const iqr = q3 - q1;
  return {
    q1,
    median,
    q3,
    lower: t(row.lower) ?? q1 - 1.5 * iqr,
    upper: t(row.upper) ?? q3 + 1.5 * iqr,
    mean: logValue ? null : row.mean,
    n: null,
  };
}

export interface ParseOptions {
  /** Draw the distribution on log10(value + 1). */
  logValue?: boolean;
}

export interface ParsedRanked {
  shape: DistributionShape | null;
  features: RankedFeature[];
  /** Features dropped for want of a finite score or of any distribution. */
  dropped: number;
}

/**
 * Column-oriented rows into one `RankedFeature` per distinct feature id.
 *
 * Long form folds every row of a feature into its values and computes its box;
 * a feature's score, rank, label and group are read from its first row that
 * carries them (they repeat on every row of the long table). Pre-aggregated,
 * the first row of a feature id wins (see `statsFromRow`). Features come back
 * in first-seen order, unranked: see `rankFeatures`.
 */
export function parseRankedRows(
  rows: Record<string, unknown[]>,
  cols: RankedColumns,
  opts: ParseOptions = {},
): ParsedRanked {
  const shape = shapeOf(cols);
  const ids = (rows[cols.featureId] ?? []) as unknown[];
  const col = (name: string | null | undefined): unknown[] | null =>
    name ? ((rows[name] as unknown[] | undefined) ?? null) : null;
  const scores = col(cols.score) ?? [];
  const ranks = col(cols.rank);
  const labels = col(cols.label);
  const groups = col(cols.group);
  const selection = col(cols.selection);

  type Acc = {
    id: string;
    label: string | null;
    score: number | null;
    rank: number | null;
    group: string | null;
    selectionValue: string | null;
    values: number[];
    stats: BoxStats | null;
  };
  const byId = new Map<string, Acc>();

  const values = shape === 'long' ? col(cols.value) : null;
  const q1s = shape === 'stats' ? col(cols.q1) : null;
  const medians = shape === 'stats' ? col(cols.median) : null;
  const q3s = shape === 'stats' ? col(cols.q3) : null;
  const lowers = shape === 'stats' ? col(cols.lower) : null;
  const uppers = shape === 'stats' ? col(cols.upper) : null;
  const means = shape === 'stats' ? col(cols.mean) : null;

  for (let i = 0; i < ids.length; i++) {
    const id = text(ids[i]);
    if (id === null) continue;
    let acc = byId.get(id);
    const isNew = acc === undefined;
    if (!acc) {
      acc = {
        id,
        label: null,
        score: null,
        rank: null,
        group: null,
        selectionValue: null,
        values: [],
        stats: null,
      };
      byId.set(id, acc);
    }
    if (acc.score === null) acc.score = num(scores[i]);
    if (acc.rank === null && ranks) acc.rank = num(ranks[i]);
    if (acc.label === null && labels) acc.label = text(labels[i]);
    if (acc.group === null && groups) acc.group = text(groups[i]);
    if (acc.selectionValue === null && selection) acc.selectionValue = text(selection[i]);

    if (values) {
      const v = num(values[i]);
      if (v !== null) {
        const t = opts.logValue ? log1p10(v) : v;
        if (t !== null) acc.values.push(t);
      }
    } else if (isNew && q1s && medians && q3s) {
      const q1 = num(q1s[i]);
      const median = num(medians[i]);
      const q3 = num(q3s[i]);
      if (q1 !== null && median !== null && q3 !== null) {
        acc.stats = statsFromRow(
          {
            q1,
            median,
            q3,
            lower: lowers ? num(lowers[i]) : null,
            upper: uppers ? num(uppers[i]) : null,
            mean: means ? num(means[i]) : null,
          },
          opts.logValue,
        );
      }
    }
  }

  const features: RankedFeature[] = [];
  let dropped = 0;
  for (const acc of byId.values()) {
    const stats = shape === 'long' ? boxStats(acc.values) : acc.stats;
    if (acc.score === null || stats === null) {
      dropped++;
      continue;
    }
    features.push({
      id: acc.id,
      label: acc.label ?? acc.id,
      score: acc.score,
      rank: acc.rank ?? Number.NaN,
      group: acc.group,
      selectionValue: acc.selectionValue,
      stats,
      values: acc.values,
    });
  }
  return { shape, features, dropped };
}

export interface RankOptions {
  /** Lowest score first (a stability score, a CV), else highest first. */
  ascending: boolean;
  /** Keep the bound rank column's order and numbers when every feature has one. */
  useRankColumn?: boolean;
}

/**
 * Features in rank order with `rank` set, 1 first.
 *
 * A bound rank column wins when every feature carries a finite rank: the
 * pipeline ranked them on more than the one score shown (stableexpression
 * aggregates several stability measures), so re-ranking by the score here
 * would contradict its own table. Otherwise the order is the score's, in the
 * direction asked, ties broken by id so the axis never shuffles between
 * renders. Does not mutate its input.
 */
export function rankFeatures(features: readonly RankedFeature[], opts: RankOptions): RankedFeature[] {
  const byId = (a: RankedFeature, b: RankedFeature) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  const byScore = (a: RankedFeature, b: RankedFeature) =>
    (opts.ascending ? a.score - b.score : b.score - a.score) || byId(a, b);
  const ranked =
    opts.useRankColumn && features.length > 0 && features.every((f) => Number.isFinite(f.rank));
  if (ranked) {
    return [...features].sort((a, b) => a.rank - b.rank || byScore(a, b)).map((f) => ({ ...f }));
  }
  return [...features].sort(byScore).map((f, i) => ({ ...f, rank: i + 1 }));
}

/** `n`, clamped to `[1, maxFeatures]`; a non-finite `n` takes the default. */
export function clampTopN(n: number, maxFeatures: number, fallback = 25): number {
  const cap = Math.max(1, Math.floor(Number.isFinite(maxFeatures) ? maxFeatures : fallback));
  const value = Number.isFinite(n) ? Math.floor(n) : fallback;
  return Math.min(Math.max(1, value), cap);
}

/** The first `n` ranked features, `n` clamped by `clampTopN`. */
export function topFeatures(
  ranked: readonly RankedFeature[],
  n: number,
  maxFeatures: number,
): RankedFeature[] {
  return ranked.slice(0, clampTopN(n, maxFeatures));
}

/** Distinct groups of `features`, sorted, with null (no group) last. */
export function groupsOf(features: readonly RankedFeature[]): (string | null)[] {
  const named = Array.from(
    new Set(features.map((f) => f.group).filter((g): g is string => g !== null)),
  ).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
  return features.some((f) => f.group === null) ? [...named, null] : named;
}

/** The ids of the features whose selection value (or id) is in `values`. */
export function selectedFeatureIds(
  features: readonly RankedFeature[],
  values: ReadonlySet<string>,
): Set<string> {
  const out = new Set<string>();
  if (values.size === 0) return out;
  for (const f of features) {
    if (values.has(f.selectionValue ?? f.id)) out.add(f.id);
  }
  return out;
}

/**
 * The feature a Plotly click landed on: slot 0 of the point's customdata (the
 * lollipop heads carry it), else the category coordinate (a box or a violin
 * reports the category it sits on, not the customdata of one row).
 */
export function featureIdFromPoint(
  point: { customdata?: unknown; x?: unknown; y?: unknown } | null | undefined,
  orientation: RankedOrientation,
): string | null {
  if (!point) return null;
  const cd = point.customdata;
  if (Array.isArray(cd) && cd.length > 0 && cd[0] != null && cd[0] !== '') return String(cd[0]);
  const category = orientation === 'horizontal' ? point.y : point.x;
  return category == null || category === '' ? null : String(category);
}

/** The value a click on `id` selects, or null for an id no feature holds. */
export function selectionValueOf(features: readonly RankedFeature[], id: string): string | null {
  const f = features.find((x) => x.id === id);
  return f ? (f.selectionValue ?? f.id) : null;
}

/** A Plotly fill colour: `colour` at `alpha`, for a hex (#rgb / #rrggbb) or an rgb() colour. */
export function withAlpha(colour: string, alpha: number): string {
  const a = Math.min(1, Math.max(0, alpha));
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(colour.trim());
  if (hex) {
    const h = hex[1].length === 3 ? hex[1].replace(/./g, (c) => c + c) : hex[1];
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
  }
  const rgb = /^rgba?\(([^)]+)\)$/i.exec(colour.trim());
  if (rgb) {
    const [r, g, b] = rgb[1].split(',').map((s) => s.trim());
    return `rgba(${r},${g},${b},${a})`;
  }
  return colour;
}

export interface FigureOptions {
  orientation: RankedOrientation;
  mark: DistributionMark;
  shape: DistributionShape;
  /** The colour a group's marks wear (null = the features with no group). */
  colourOf: (group: string | null) => string;
  /** The stems of the lollipop. */
  stemColour: string;
  /** The outline of a selected feature. */
  selectedOutline: string;
  /** Feature ids currently selected; the others are dimmed while it is non-empty. */
  selected?: ReadonlySet<string>;
  scoreTitle: string;
  valueTitle: string;
  /** Legend title, the group column's name; no legend without groups. */
  groupTitle?: string | null;
}

export interface RankedFigure {
  data: Record<string, unknown>[];
  layout: Record<string, unknown>;
}

const DIMMED = 0.3;
/** Horizontal: the distribution's share of the width, then the gap, then the score's. */
const H_SPLIT = { value: [0, 0.64], score: [0.7, 1] } as const;
/** Vertical: the score panel at the bottom, the distribution above it. */
const V_SPLIT = { score: [0, 0.3], value: [0.38, 1] } as const;

/**
 * The two linked panels as one Plotly figure.
 *
 * One category axis carries the features in rank order (rank 1 at the top, or
 * on the left): the distribution panel and the score panel are two value axes
 * on it, so a feature's box and its lollipop always sit on the same line. The
 * category values are the feature ids and the tick text their labels, so two
 * features that share a display name still get a line each.
 *
 * One distribution trace per (group, selected) pair, because a box trace has
 * one fill colour: that is how a group keeps its colour and a selection dims
 * the rest. The lollipop is a stems trace (line segments from zero, broken by
 * nulls) under one marker trace per group; the heads carry the feature id in
 * customdata for the click.
 */
export function buildRankedFigure(top: readonly RankedFeature[], opts: FigureOptions): RankedFigure {
  const horizontal = opts.orientation === 'horizontal';
  const selected = opts.selected ?? new Set<string>();
  const selecting = selected.size > 0;
  const violin = opts.mark === 'violin' && opts.shape === 'long';
  const groups = groupsOf(top);
  const showLegend = Boolean(opts.groupTitle) && groups.some((g) => g !== null);
  const ids = top.map((f) => f.id);
  const catKey = horizontal ? 'y' : 'x';
  const valKey = horizontal ? 'x' : 'y';
  const data: Record<string, unknown>[] = [];
  const legendShown = new Set<string>();
  const legendFor = (group: string | null) => {
    const key = group ?? '';
    if (!showLegend || group === null || legendShown.has(key)) return false;
    legendShown.add(key);
    return true;
  };

  const hoverOf = (f: RankedFeature) =>
    `<b>${f.label}</b>` +
    (f.label !== f.id ? ` (${f.id})` : '') +
    `<br>Rank ${f.rank}<br>${opts.scoreTitle}: ${formatNumber(f.score)}` +
    (f.stats
      ? `<br>Median ${formatNumber(f.stats.median)} (IQR ${formatNumber(f.stats.q1)} to ${formatNumber(f.stats.q3)})`
      : '') +
    (f.stats?.n != null ? `<br>${f.stats.n} values` : '') +
    (f.group ? `<br>${opts.groupTitle ?? 'Group'}: ${f.group}` : '');

  for (const group of groups) {
    const members = top.filter((f) => f.group === group);
    const parts: [RankedFeature[], boolean][] = selecting
      ? [
          [members.filter((f) => selected.has(f.id)), true],
          [members.filter((f) => !selected.has(f.id)), false],
        ]
      : [[members, true]];
    const colour = opts.colourOf(group);
    for (const [part, isSelected] of parts) {
      if (part.length === 0) continue;
      const opacity = selecting && !isSelected ? DIMMED : 1;
      const common = {
        name: group ?? '',
        legendgroup: group ?? '',
        showlegend: legendFor(group),
        opacity,
        xaxis: 'x',
        yaxis: 'y',
        orientation: horizontal ? 'h' : 'v',
        line: {
          color: selecting && isSelected ? opts.selectedOutline : colour,
          width: selecting && isSelected ? 2 : 1.2,
        },
        fillcolor: withAlpha(colour, 0.45),
        marker: { color: colour },
        hoverinfo: 'text',
        hoveron: violin ? 'violins' : 'boxes',
      };
      if (violin) {
        const cat: string[] = [];
        const val: number[] = [];
        for (const f of part) {
          for (const v of f.values) {
            cat.push(f.id);
            val.push(v);
          }
        }
        data.push({
          ...common,
          type: 'violin',
          [catKey]: cat,
          [valKey]: val,
          points: false,
          spanmode: 'hard',
          scalemode: 'width',
          width: 0.8,
          box: { visible: true, width: 0.25 },
          meanline: { visible: true },
          hovertext: cat.map((id) => hoverOf(part.find((f) => f.id === id)!)),
        });
      } else {
        const stats = part.map((f) => f.stats!);
        const allMeans = stats.every((s) => s.mean !== null);
        data.push({
          ...common,
          type: 'box',
          [catKey]: part.map((f) => f.id),
          q1: stats.map((s) => s.q1),
          median: stats.map((s) => s.median),
          q3: stats.map((s) => s.q3),
          lowerfence: stats.map((s) => s.lower),
          upperfence: stats.map((s) => s.upper),
          ...(allMeans ? { mean: stats.map((s) => s.mean), boxmean: true } : {}),
          boxpoints: false,
          width: 0.6,
          hovertext: part.map(hoverOf),
        });
      }
    }
  }

  // The stems: one segment per feature from zero to its score, in one trace.
  const stemCat: (string | null)[] = [];
  const stemVal: (number | null)[] = [];
  for (const f of top) {
    stemCat.push(f.id, f.id, null);
    stemVal.push(0, f.score, null);
  }
  const scoreX = horizontal ? 'x2' : 'x';
  const scoreY = horizontal ? 'y' : 'y2';
  data.push({
    type: 'scatter',
    mode: 'lines',
    [catKey]: stemCat,
    [valKey]: stemVal,
    xaxis: scoreX,
    yaxis: scoreY,
    line: { color: opts.stemColour, width: 1.5 },
    hoverinfo: 'skip',
    showlegend: false,
  });
  for (const group of groups) {
    const members = top.filter((f) => f.group === group);
    if (members.length === 0) continue;
    const colour = opts.colourOf(group);
    data.push({
      type: 'scatter',
      mode: 'markers',
      name: group ?? '',
      legendgroup: group ?? '',
      showlegend: false,
      [catKey]: members.map((f) => f.id),
      [valKey]: members.map((f) => f.score),
      xaxis: scoreX,
      yaxis: scoreY,
      customdata: members.map((f) => [f.id, f.rank]),
      hovertext: members.map(hoverOf),
      hoverinfo: 'text',
      marker: {
        color: colour,
        size: 10,
        opacity: members.map((f) => (selecting && !selected.has(f.id) ? DIMMED : 1)),
        line: {
          color: opts.selectedOutline,
          width: members.map((f) => (selected.has(f.id) ? 2 : 0)),
        },
      },
    });
  }

  const categoryAxis = {
    type: 'category',
    categoryorder: 'array',
    categoryarray: ids,
    tickmode: 'array',
    tickvals: ids,
    ticktext: top.map((f) => f.label),
    automargin: true,
    showgrid: false,
    ...(horizontal ? { autorange: 'reversed' } : { tickangle: -45 }),
  };
  const valueAxis = {
    title: { text: opts.valueTitle },
    zeroline: false,
    automargin: true,
  };
  const scoreAxis = {
    title: { text: opts.scoreTitle },
    zeroline: true,
    rangemode: 'tozero',
    automargin: true,
  };
  const layout: Record<string, unknown> = horizontal
    ? {
        yaxis: categoryAxis,
        xaxis: { ...valueAxis, domain: [...H_SPLIT.value], anchor: 'y' },
        xaxis2: { ...scoreAxis, domain: [...H_SPLIT.score], anchor: 'y' },
      }
    : {
        // The shared category axis sits under the score panel, the bottom one.
        xaxis: { ...categoryAxis, anchor: 'y2' },
        yaxis: { ...valueAxis, domain: [...V_SPLIT.value], anchor: 'x' },
        yaxis2: { ...scoreAxis, domain: [...V_SPLIT.score], anchor: 'x' },
      };
  return {
    data,
    layout: {
      ...layout,
      boxmode: 'overlay',
      violinmode: 'overlay',
      hovermode: 'closest',
      showlegend: showLegend,
      // Above the plot, one line: a legend at the side would steal the
      // panels' width, and one inside them would sit over the boxes.
      legend: {
        orientation: 'h',
        x: 0,
        xanchor: 'left',
        y: 1,
        yanchor: 'bottom',
        ...(opts.groupTitle ? { title: { text: opts.groupTitle } } : {}),
      },
      margin: { l: 8, r: 12, t: showLegend ? 30 : 8, b: 8 },
      autosize: true,
    },
  };
}

/** Pixels each feature needs on a horizontal category axis to keep its label legible. */
export const PX_PER_FEATURE = 20;
/** Axis titles, tick labels of the value axes and the legend line. */
export const FIGURE_CHROME_PX = 110;
/** A vertical figure's height does not grow with the features (they share the width). */
export const VERTICAL_FIGURE_PX = 460;

/** A short, readable number for hover text: 3 significant digits, no exponent for ordinary values. */
export function formatNumber(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  const abs = Math.abs(v);
  if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) return v.toExponential(2);
  return String(Number(v.toPrecision(3)));
}

/** "Top 25 of 200 features, lowest score first", the line the frame echoes under the title. */
export function rankingEcho(opts: {
  shown: number;
  total: number;
  ascending: boolean;
  byRankColumn: boolean;
  noun?: string;
}): string {
  const noun = opts.noun ?? 'features';
  const order = opts.byRankColumn
    ? 'in the table’s rank order'
    : opts.ascending
      ? 'lowest score first'
      : 'highest score first';
  return opts.shown >= opts.total
    ? `All ${opts.total} ${noun}, ${order}`
    : `Top ${opts.shown} of ${opts.total} ${noun}, ${order}`;
}
