/**
 * The card's secondary-strip payloads, computed in the browser.
 *
 * Ports two pure-Polars server modules, function for function:
 *   depictio/api/v1/services/card_metrics.py    → the numeric / QC layouts
 *   depictio/api/v1/services/card_breakdown.py  → the categorical layouts
 *
 * They cannot simply be reused: the studio has no backend, and polars has no
 * Pyodide wheel. So the port is pinned instead — `scripts/genKinds.ts`
 * regenerates `src/test/generated/cardMetricsGolden.json` by running the real
 * Python over `e2e/golden/card_metrics.csv`, and `src/test/cardMetrics.test.ts`
 * asserts this file reproduces it. A divergence is a failing test, not a
 * preview that quietly disagrees with what depictio will render.
 *
 * Every function returns `null` where the Python returns `None`: the strip is
 * then not rendered at all, which is the point — an empty histogram or a
 * zeroed bar reads as a real answer.
 */
import type {
  AttritionPayload,
  BreakdownPayload,
  CompletenessPayload,
  HistogramPayload,
  ThresholdPayload,
  TrendPayload,
  UniquenessPayload,
} from 'depictio-react-core';
import { aggregate, quantileLinear } from './aggregations';
import type { FrameColumn, FrameValue, StudioFrame } from './frame';
import { isNumericKind, numericValues } from './frame';

/** Twenty bars is what fits a ~260px card legibly (`HISTOGRAM_BINS`). */
const HISTOGRAM_BINS = 20;
/** Beyond this a trend line has more points than the card has pixels. */
const TREND_MAX_POINTS = 24;
/** Past five segments the strip is illegible; the model agrees (`le=5`). */
const MAX_TOP_N = 5;

const nullCount = (col: FrameColumn): number => col.values.length - col.present.length;

export function computeHistogram(
  frame: StudioFrame,
  column: string,
  bins = HISTOGRAM_BINS,
): HistogramPayload | null {
  const col = frame.byName.get(column);
  if (!col) return null;
  const nums = numericValues(col);
  const total = frame.height;
  const nulls = nullCount(col);
  if (nums.length === 0) return null;
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  // No spread means every bar is the same height, which the reader would take
  // for a uniform distribution when it is really a single value.
  if (total - nulls <= 1 || lo === hi) return null;

  const width = (hi - lo) / bins;
  const breakpoints: number[] = [];
  for (let i = 0; i < bins; i += 1) breakpoints.push(lo + width * (i + 1));
  const counts = new Array<number>(bins).fill(0);
  for (const v of nums) {
    // polars bins on half-open (lo, hi] intervals with the first bin closed at
    // the minimum, so a value exactly on a breakpoint belongs to the bin below.
    let idx = Math.ceil((v - lo) / width) - 1;
    if (idx < 0) idx = 0;
    if (idx >= bins) idx = bins - 1;
    counts[idx] += 1;
  }
  const sorted = [...nums].sort((a, b) => a - b);
  return {
    bins: counts,
    breakpoints,
    min: lo,
    max: hi,
    median: quantileLinear(sorted, 0.5),
    total,
    nulls,
  };
}

export function computeThreshold(
  frame: StudioFrame,
  column: string,
  threshold: number,
  direction = 'min',
  warnThreshold: number | null = null,
): ThresholdPayload | null {
  const col = frame.byName.get(column);
  if (!col) return null;
  const nums = numericValues(col);
  const higherIsBetter = direction !== 'max';
  const warnValid =
    warnThreshold !== null &&
    warnThreshold !== undefined &&
    (higherIsBetter ? warnThreshold < threshold : warnThreshold > threshold);

  let passing = 0;
  let warning = 0;
  for (const v of nums) {
    const passes = higherIsBetter ? v >= threshold : v <= threshold;
    if (passes) {
      passing += 1;
    } else if (warnValid) {
      const warns = higherIsBetter ? v >= warnThreshold! : v <= warnThreshold!;
      if (warns) warning += 1;
    }
  }

  const total = frame.height;
  const nulls = nullCount(col);
  const measured = total - nulls;
  const sorted = [...nums].sort((a, b) => a - b);
  return {
    column,
    threshold,
    warn_threshold: warnValid ? warnThreshold : null,
    direction: higherIsBetter ? 'min' : 'max',
    total,
    measured,
    nulls,
    passing,
    warning,
    // A null is neither a pass nor a fail: a missing measurement is not a
    // failed one.
    failing: Math.max(0, measured - passing - warning),
    pass_rate: measured > 0 ? passing / measured : 0,
    min: sorted.length ? sorted[0] : null,
    max: sorted.length ? sorted[sorted.length - 1] : null,
    median: quantileLinear(sorted, 0.5),
  };
}

export function computeCompleteness(
  frame: StudioFrame,
  column: string,
): CompletenessPayload | null {
  const col = frame.byName.get(column);
  if (!col) return null;
  const total = frame.height;
  const nulls = nullCount(col);
  const filled = Math.max(0, total - nulls);
  return {
    column,
    total,
    filled,
    nulls,
    fill_rate: total > 0 ? filled / total : 0,
  };
}

export function computeUniqueness(
  frame: StudioFrame,
  column: string,
): UniquenessPayload | null {
  const col = frame.byName.get(column);
  if (!col) return null;
  const total = frame.height;
  const nulls = nullCount(col);
  const measured = Math.max(0, total - nulls);
  if (measured <= 0) return null;

  const freq = new Map<FrameValue, number>();
  for (const v of col.present) freq.set(v, (freq.get(v) ?? 0) + 1);
  const distinct = freq.size;

  // Name breaks ties so the same data always names the same offender.
  let top: { name: string; count: number } | null = null;
  for (const [value, count] of freq) {
    if (
      !top ||
      count > top.count ||
      (count === top.count && String(value) < top.name)
    ) {
      top = { name: String(value), count };
    }
  }

  return {
    column,
    total,
    measured,
    distinct,
    duplicated: Math.max(0, measured - distinct),
    unique_rate: measured ? distinct / measured : 0,
    nulls,
    top_repeat: top && top.count > 1 ? top : null,
  };
}

const ATTRITION_REDUCERS: Record<string, string> = {
  sum: 'sum',
  average: 'average',
  mean: 'average',
  median: 'median',
  min: 'min',
  max: 'max',
};

export function computeAttrition(
  frame: StudioFrame,
  columns: string[],
  aggregation = 'sum',
): AttritionPayload | null {
  if (columns.length < 2) return null;
  const agg = (aggregation || 'sum').toLowerCase();
  const reducer = ATTRITION_REDUCERS[agg] ?? 'sum';
  const values = columns.map((c) => {
    const raw = aggregate(frame, c, reducer);
    return typeof raw === 'number' ? raw : 0;
  });

  const first = values[0];
  const stages = columns.map((name, idx) => {
    const value = values[idx];
    const previous = idx ? values[idx - 1] : null;
    return {
      name,
      value,
      // Share of the starting population: cumulative survival.
      share: first ? value / first : 0,
      // Share of the preceding stage: isolates which single step did the damage.
      step_share: idx && previous ? value / previous : null,
    };
  });

  return {
    columns: [...columns],
    aggregation: agg,
    stages,
    retained: first ? values[values.length - 1] / first : 0,
  };
}

/** Bucket label as a reader would write it, mirroring `_format_axis_label`:
 *  a date as a date, an integral float as an integer (2007, not 2007.0). */
export function formatAxisLabel(value: FrameValue, kind: string): string {
  if (value === null) return '—';
  if (kind === 'datetime') {
    const m = String(value).match(
      /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?)?/,
    );
    if (!m) return String(value);
    const [, date, hh, mm, ss, frac] = m;
    if (!hh || (hh === '00' && mm === '00' && (!ss || ss === '00') && !frac)) return date;
    return `${date} ${hh}:${mm}:${ss ?? '00'}${frac ?? ''}`;
  }
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : String(value);
  }
  return String(value);
}

/** Per-group reducers a trend bucket may use (`_TREND_REDUCERS`). Deliberately
 *  small: a per-bucket skewness is not readable off a 28px sparkline. */
function trendReduce(values: FrameValue[], aggregation: string): number {
  const agg = (aggregation || 'count').toLowerCase();
  const present = values.filter((v) => v !== null);
  const nums = present.filter((v): v is number => typeof v === 'number');
  switch (agg) {
    case 'nunique':
    case 'unique':
      // polars counts null as one of the distinct values inside an aggregation.
      return new Set(values).size;
    case 'sum':
      return nums.reduce((a, b) => a + b, 0);
    case 'average':
    case 'mean':
      return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : 0;
    case 'median': {
      const q = quantileLinear([...nums].sort((a, b) => a - b), 0.5);
      return q ?? 0;
    }
    case 'min':
      return nums.length ? Math.min(...nums) : 0;
    case 'max':
      return nums.length ? Math.max(...nums) : 0;
    default:
      return present.length;
  }
}

/** Sortable scalar for a bucket axis: epoch ms for a date, the number itself
 *  for a number. Bucket assignment is scale-invariant, so ms vs the µs polars
 *  casts to lands every row in the same bucket. */
function axisNumber(value: FrameValue, kind: string): number | null {
  if (value === null) return null;
  if (kind === 'datetime') {
    const t = Date.parse(String(value));
    return Number.isFinite(t) ? t : null;
  }
  return typeof value === 'number' ? value : null;
}

export function computeTrend(
  frame: StudioFrame,
  column: string,
  axis: string,
  aggregation = 'count',
  maxPoints = TREND_MAX_POINTS,
): TrendPayload | null {
  const valueCol = frame.byName.get(column);
  const axisCol = frame.byName.get(axis);
  if (!valueCol || !axisCol) return null;

  const temporal = axisCol.kind === 'datetime';
  const numeric = isNumericKind(axisCol.kind);
  const axisKind: TrendPayload['axis_kind'] = temporal
    ? 'temporal'
    : numeric
      ? 'numeric'
      : 'categorical';

  // Rows whose axis is null carry no position on the line.
  const idx: number[] = [];
  for (let i = 0; i < frame.height; i += 1) {
    if (axisCol.values[i] !== null) idx.push(i);
  }
  const distinct = new Set(idx.map((i) => axisCol.values[i])).size;
  if (distinct < 2) return null;

  let labels: string[];
  let values: number[];

  if (distinct > maxPoints && (temporal || numeric)) {
    const nums = idx
      .map((i) => axisNumber(axisCol.values[i], axisCol.kind))
      .filter((v): v is number => v !== null);
    const lo = Math.min(...nums);
    const hi = Math.max(...nums);
    const width = (hi - lo) / maxPoints;
    if (width <= 0) return null;
    const buckets = new Map<number, { rows: number[]; label: FrameValue }>();
    for (const i of idx) {
      const v = axisNumber(axisCol.values[i], axisCol.kind);
      if (v === null) continue;
      const b = Math.min(maxPoints - 1, Math.max(0, Math.floor((v - lo) / width)));
      const entry = buckets.get(b);
      if (entry) {
        entry.rows.push(i);
        // Label each bucket with its own earliest value: a real value from the
        // data is one the user can find again, unlike a computed edge.
        if (
          axisNumber(entry.label, axisCol.kind)! > v
        ) {
          entry.label = axisCol.values[i];
        }
      } else {
        buckets.set(b, { rows: [i], label: axisCol.values[i] });
      }
    }
    const ordered = [...buckets.entries()].sort((a, b) => a[0] - b[0]);
    labels = ordered.map(([, e]) => formatAxisLabel(e.label, axisCol.kind));
    values = ordered.map(([, e]) =>
      trendReduce(e.rows.map((i) => valueCol.values[i]), aggregation),
    );
  } else {
    const groups = new Map<FrameValue, number[]>();
    for (const i of idx) {
      const key = axisCol.values[i];
      const rows = groups.get(key);
      if (rows) rows.push(i);
      else groups.set(key, [i]);
    }
    let ordered = [...groups.entries()].sort((a, b) => {
      if (temporal || numeric) {
        const av = axisNumber(a[0], axisCol.kind) ?? 0;
        const bv = axisNumber(b[0], axisCol.kind) ?? 0;
        return av - bv;
      }
      return String(a[0]) < String(b[0]) ? -1 : String(a[0]) > String(b[0]) ? 1 : 0;
    });
    if (ordered.length > maxPoints) ordered = ordered.slice(-maxPoints);
    labels = ordered.map(([key]) => formatAxisLabel(key, axisCol.kind));
    values = ordered.map(([, rows]) =>
      trendReduce(rows.map((i) => valueCol.values[i]), aggregation),
    );
  }

  if (values.length < 2) return null;
  const first = values[0];
  const last = values[values.length - 1];
  return {
    column,
    axis,
    axis_kind: axisKind,
    aggregation: (aggregation || 'count').toLowerCase(),
    points: values.map((value, i) => ({ label: labels[i], value })),
    first,
    last,
    // A percentage change off a zero baseline is undefined, not infinite.
    change: first ? last / first - 1 : null,
    min: Math.min(...values),
    max: Math.max(...values),
  };
}

/** Stage list for `attrition` (`_attrition_columns`): the card's own column is
 *  the first stage unless the user already listed it. */
function attritionColumns(card: Record<string, unknown>, column: string): string[] {
  const raw = (card.attrition_cols as unknown[] | undefined) ?? [];
  const stages = raw.filter(Boolean).map(String);
  if (column && !stages.includes(column)) return [column, ...stages];
  return stages;
}

/** Layouts backed by a numeric payload keyed `__<layout>__` (`NUMERIC_LAYOUTS`). */
export function numericLayoutPayload(
  frame: StudioFrame,
  card: Record<string, unknown>,
  column: string,
  layout: string,
): Record<string, unknown> | null {
  const has = (name: string) => frame.byName.has(name);

  if (layout === 'histogram') {
    return has(column) ? (computeHistogram(frame, column) as never) : null;
  }
  if (layout === 'threshold') {
    const threshold = card.threshold_value;
    if (threshold === null || threshold === undefined || !has(column)) return null;
    const warn = card.threshold_warn;
    return computeThreshold(
      frame,
      column,
      Number(threshold),
      String(card.threshold_direction || 'min'),
      warn === null || warn === undefined ? null : Number(warn),
    ) as never;
  }
  if (layout === 'completeness') {
    return has(column) ? (computeCompleteness(frame, column) as never) : null;
  }
  if (layout === 'uniqueness') {
    return has(column) ? (computeUniqueness(frame, column) as never) : null;
  }
  if (layout === 'trend') {
    const axis = card.trend_col;
    if (!axis || !has(String(axis)) || !has(column)) return null;
    return computeTrend(
      frame,
      column,
      String(axis),
      String(card.aggregation || 'count'),
    ) as never;
  }
  if (layout === 'attrition') {
    const stages = attritionColumns(card, column).filter(has);
    if (stages.length < 2) return null;
    return computeAttrition(frame, stages, String(card.aggregation || 'sum')) as never;
  }
  return null;
}

/** Pielou's evenness of a category distribution, in [0, 1]. Null below two
 *  present categories, where the measure is degenerate rather than meaningful. */
export function evenness(counts: number[], total: number): number | null {
  const present = counts.filter((c) => c > 0);
  if (total <= 0 || present.length < 2) return null;
  let entropy = 0;
  for (const count of present) {
    const p = count / total;
    entropy -= p * Math.log(p);
  }
  return Math.max(0, Math.min(1, entropy / Math.log(present.length)));
}

/**
 * The `__breakdown__` payload the categorical layouts read.
 *
 * The per-group reduction mirrors the card's hero metric (`group_expr`), so a
 * "distinct POS" card broken down by GENE counts distinct POS per gene — the
 * percentages have to read against the number printed above them.
 */
export function computeBreakdown(
  frame: StudioFrame,
  column: string,
  breakdownCol: string,
  aggregation: string,
  topNCount = 3,
): BreakdownPayload | null {
  const groupCol = frame.byName.get(breakdownCol);
  const valueCol = frame.byName.get(column);
  if (!groupCol || !valueCol) return null;
  const topN = Math.max(1, Math.min(Math.trunc(topNCount || 3), MAX_TOP_N));
  const hero = (aggregation || 'count').toLowerCase();

  const groups = new Map<FrameValue, number[]>();
  for (let i = 0; i < frame.height; i += 1) {
    const key = groupCol.values[i];
    const rows = groups.get(key);
    if (rows) rows.push(i);
    else groups.set(key, [i]);
  }

  const reduce = (rows: number[]): number => {
    if (column === breakdownCol) return rows.length;
    if (hero === 'nunique' || hero === 'unique') {
      return new Set(rows.map((i) => valueCol.values[i])).size;
    }
    if (hero === 'sum') {
      let total = 0;
      for (const i of rows) {
        const v = valueCol.values[i];
        if (typeof v === 'number') total += v;
      }
      return total;
    }
    return rows.length;
  };

  const entries = [...groups.entries()].map(([key, rows]) => ({
    key,
    count: reduce(rows),
  }));
  // group_by promises no order, so the name is the tie-break — without it the
  // preview and the saved card could rank the same data differently.
  entries.sort((a, b) => {
    if (b.count !== a.count) return b.count - a.count;
    if (a.key === null) return 1;
    if (b.key === null) return -1;
    if (typeof a.key === 'number' && typeof b.key === 'number') return a.key - b.key;
    return String(a.key) < String(b.key) ? -1 : String(a.key) > String(b.key) ? 1 : 0;
  });

  // The server truncates each group to an int (a strip counts things) but takes
  // the total from the untruncated sum, so a `sum` breakdown's segments need
  // not add up to its total. Mirrored rather than tidied: the percentages the
  // renderer draws are computed from exactly these numbers.
  const total = Math.trunc(entries.reduce((sum, e) => sum + e.count, 0));
  const counts = entries.map((e) => ({ ...e, count: Math.trunc(e.count) }));
  const top = counts.slice(0, topN);
  const topCount = top.reduce((sum, e) => sum + e.count, 0);

  return {
    column: breakdownCol,
    total,
    top: top.map((e) => ({
      // Nulls are a real category: a 40%-unfilled column is exactly what the
      // composition bar should show.
      name: e.key === null ? '(null)' : String(e.key),
      count: e.count,
      percent: total > 0 ? e.count / total : 0,
    })),
    top_share: total > 0 ? topCount / total : 0,
    unique_values: entries.length,
    breakdown_kind: hero,
    evenness: evenness(counts.map((e) => e.count), total),
  };
}
