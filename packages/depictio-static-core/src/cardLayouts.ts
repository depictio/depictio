/**
 * Card secondary layouts in the browser — ports of the server's
 * `services/card_breakdown.compute_breakdown` (the `__breakdown__` payload of
 * top_n / concentration / composition / donut) and
 * `services/card_metrics.numeric_layout_payload` (the `__<layout>__` payloads
 * of histogram / threshold / completeness / uniqueness / trend / attrition).
 *
 * The bundle used to ship these strips as the export-time snapshot (producer
 * A — stale under any filter, and unbadged) or not at all (producer B). They
 * are reductions of the card's own filtered rows, so they recompute here from
 * the same mask as the hero value. Pinned against the server functions by the
 * engine fixture's `card_layouts` cases (test/engine/cardLayouts.test.ts).
 *
 * Polars semantics carried over: `n_unique` counts null as a value; sums skip
 * nulls; group sorts are `nulls_last` on every key; `int()` truncation of the
 * breakdown counts; `hist(bin_count)` bins are (a, b] with the first closed;
 * `cast(Utf8)` renders an integral float with `.0`.
 */

import type { Bitmask } from './engine/QueryEngine';

/** One column as the layouts read it: decoded values plus the Polars dtype. */
export interface LayoutColumn {
  values: ArrayLike<unknown>;
  dtype: string;
}

export type ColumnGetter = (name: string) => LayoutColumn | undefined;

export const BREAKDOWN_LAYOUTS = ['top_n', 'concentration', 'composition', 'donut'] as const;
export const NUMERIC_LAYOUTS = [
  'histogram',
  'threshold',
  'completeness',
  'attrition',
  'trend',
  'uniqueness',
] as const;
const MAX_TOP_N = 5;
const HISTOGRAM_BINS = 20;
const TREND_MAX_POINTS = 24;

const FLOAT_RE = /^Float/i;
const NUMERIC_RE = /^(U?Int|Float|Decimal)/i;
const TEMPORAL_RE = /^(Date|Datetime)/i;

function num(v: unknown): number | null {
  if (typeof v === 'bigint') return Number(v);
  if (typeof v === 'number') return Number.isNaN(v) ? null : v;
  return null;
}

function selected(mask: Bitmask | null, n: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < n; i++) if (mask === null || mask[i] === 1) out.push(i);
  return out;
}

/** Polars `cast(Utf8)` of one cell. */
export function polarsUtf8(v: unknown, dtype: string): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'bigint') return v.toString();
  if (typeof v === 'number') {
    if (FLOAT_RE.test(dtype) && Number.isInteger(v) && Math.abs(v) < 1e16) return `${v}.0`;
    return String(v);
  }
  if (v instanceof Date) {
    const iso = v.toISOString();
    return /^Date$/i.test(dtype) ? iso.slice(0, 10) : iso.replace('T', ' ').replace(/Z$/, '');
  }
  return String(v);
}

function keyOf(v: unknown): string {
  if (v === null || v === undefined) return '\u0000null';
  if (typeof v === 'bigint') return `n:${v}`;
  if (typeof v === 'number') return `n:${v}`;
  if (v instanceof Date) return `d:${v.getTime()}`;
  return `${typeof v}:${String(v)}`;
}

/** Native ascending compare of two non-null cells (numbers numerically). */
function cmpNative(a: unknown, b: unknown): number {
  const x = num(a);
  const y = num(b);
  if (x !== null && y !== null) return x - y;
  if (a instanceof Date && b instanceof Date) return a.getTime() - b.getTime();
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b);
  const sa = String(a);
  const sb = String(b);
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}

/** Sort comparator over (value, key) pairs: nulls last on BOTH keys. */
function nullsLast(a: unknown, b: unknown, desc: boolean): number {
  const an = a === null || a === undefined;
  const bn = b === null || b === undefined;
  if (an || bn) return an === bn ? 0 : an ? 1 : -1;
  const c = cmpNative(a, b);
  return desc ? -c : c;
}

function numbersOf(values: ArrayLike<unknown>, rows: number[]): number[] {
  const out: number[] = [];
  for (const i of rows) {
    const v = num(values[i]);
    if (v !== null) out.push(v);
  }
  return out;
}

function quantileLinear(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const frac = pos - lo;
  return frac === 0 ? sorted[lo] : sorted[lo] + frac * (sorted[lo + 1] - sorted[lo]);
}

function median(nums: number[]): number | null {
  if (nums.length === 0) return null;
  return quantileLinear([...nums].sort((a, b) => a - b), 0.5);
}

function variance(nums: number[]): number | null {
  if (nums.length < 2) return null;
  const mean = nums.reduce((a, b) => a + b, 0) / nums.length;
  return nums.reduce((a, b) => a + (b - mean) * (b - mean), 0) / (nums.length - 1);
}

function nUnique(values: ArrayLike<unknown>, rows: number[]): number {
  const seen = new Set<string>();
  for (const i of rows) seen.add(keyOf(values[i]));
  return seen.size;
}

/** The value reductions of `_VALUE_REDUCTIONS` / `_TREND_REDUCERS`. */
function reduce(agg: string, values: ArrayLike<unknown>, rows: number[], numeric: boolean): number | null {
  const nums = numbersOf(values, rows);
  switch (agg) {
    case 'average':
    case 'mean':
      return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
    case 'median':
      return median(nums);
    case 'min':
      return nums.length ? Math.min(...nums) : null;
    case 'max':
      return nums.length ? Math.max(...nums) : null;
    case 'range':
      return nums.length ? Math.max(...nums) - Math.min(...nums) : null;
    case 'variance':
      return variance(nums);
    case 'std_dev':
    case 'std': {
      const v = variance(nums);
      return v === null ? null : Math.sqrt(v);
    }
    case 'sum':
      return numeric ? nums.reduce((a, b) => a + b, 0) : null;
    case 'count': {
      let n = 0;
      for (const i of rows) if (values[i] !== null && values[i] !== undefined) n++;
      return n;
    }
    case 'nunique':
    case 'unique':
      return nUnique(values, rows);
    default:
      return null;
  }
}

const VALUE_REDUCTIONS = new Set(['average', 'mean', 'median', 'min', 'max', 'range', 'variance', 'std_dev', 'std']);

/** `evenness`: Pielou's evenness, null below two categories. */
export function evenness(counts: number[], total: number): number | null {
  const present = counts.filter((c) => c > 0);
  if (total <= 0 || present.length < 2) return null;
  let entropy = 0;
  for (const c of present) {
    const p = c / total;
    entropy -= p * Math.log(p);
  }
  return Math.max(0, Math.min(1, entropy / Math.log(present.length)));
}

function plainNumber(v: number | null): number | null {
  if (v === null || !Number.isFinite(v)) return null;
  return v;
}

/** `compute_breakdown`. */
export function computeBreakdown(
  get: ColumnGetter,
  mask: Bitmask | null,
  rowCount: number,
  column: string,
  breakdownCol: string,
  aggregation: string,
  topNCount = 3,
): Record<string, unknown> | null {
  const by = get(breakdownCol);
  const hero = get(column);
  if (!by || !hero) return null;
  const n = Math.max(1, Math.min(Math.trunc(Number(topNCount) || 3), MAX_TOP_N));
  const agg = (aggregation || 'count').toLowerCase();
  const rows = selected(mask, rowCount);
  const groups = new Map<string, { value: unknown; rows: number[] }>();
  for (const i of rows) {
    const v = by.values[i] ?? null;
    const k = keyOf(v);
    let g = groups.get(k);
    if (!g) {
      g = { value: v, rows: [] };
      groups.set(k, g);
    }
    g.rows.push(i);
  }
  const isValue = column !== breakdownCol && VALUE_REDUCTIONS.has(agg);
  const heroNumeric = NUMERIC_RE.test(hero.dtype);
  const reduceGroup = (g: { rows: number[] }): number | null => {
    if (column === breakdownCol) return g.rows.length;
    if (agg === 'nunique' || agg === 'unique') return nUnique(hero.values, g.rows);
    if (agg === 'sum') return reduce('sum', hero.values, g.rows, heroNumeric);
    if (VALUE_REDUCTIONS.has(agg)) return reduce(agg, hero.values, g.rows, heroNumeric);
    return g.rows.length;
  };
  const grouped = [...groups.values()].map((g) => ({ value: g.value, rows: g.rows.length, count: reduceGroup(g) }));
  const name = (v: unknown) => polarsUtf8(v, by.dtype) ?? '(null)';

  if (isValue) {
    const desc = agg !== 'min';
    grouped.sort((a, b) => nullsLast(a.count, b.count, desc) || nullsLast(a.value, b.value, false));
    const top = grouped.slice(0, n);
    return {
      column: breakdownCol,
      total: grouped.reduce((s, g) => s + g.rows, 0),
      top: top.map((g) => ({ name: name(g.value), count: plainNumber(g.count), percent: null })),
      top_share: null,
      unique_values: grouped.length,
      breakdown_kind: agg,
      evenness: null,
    };
  }
  grouped.sort((a, b) => nullsLast(a.count, b.count, true) || nullsLast(a.value, b.value, false));
  const totalRaw = grouped.reduce((s, g) => s + (g.count ?? 0), 0);
  const total = Math.trunc(totalRaw || 0);
  const top = grouped.slice(0, n);
  const counts = top.map((g) => Math.trunc(g.count ?? 0));
  const share = total > 0 ? counts.reduce((a, b) => a + b, 0) / total : 0;
  return {
    column: breakdownCol,
    total,
    top: top.map((g, i) => ({ name: name(g.value), count: counts[i], percent: total > 0 ? counts[i] / total : 0 })),
    top_share: share,
    unique_values: grouped.length,
    breakdown_kind: agg,
    evenness: evenness(
      grouped.map((g) => Math.trunc(g.count ?? 0)),
      total,
    ),
  };
}

// ---------------------------------------------------------------------------
// numeric / QC layouts (card_metrics.py)
// ---------------------------------------------------------------------------

function nullCount(values: ArrayLike<unknown>, rows: number[]): number {
  let n = 0;
  for (const i of rows) if (values[i] === null || values[i] === undefined) n++;
  return n;
}

/** `compute_histogram` (no domain): Polars `hist(bin_count)` over the column. */
export function computeHistogram(col: LayoutColumn, rows: number[], bins = HISTOGRAM_BINS): Record<string, unknown> | null {
  if (rows.length === 0) return null;
  const nums = numbersOf(col.values, rows);
  const total = rows.length;
  const nulls = nullCount(col.values, rows);
  if (nums.length === 0) return null;
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of nums) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (total - nulls <= 1 || lo === hi) return null;
  const width = (hi - lo) / bins;
  const counts = new Array<number>(bins).fill(0);
  for (const v of nums) {
    let idx = Math.ceil((v - lo) / width) - 1;
    if (idx < 0) idx = 0;
    if (idx > bins - 1) idx = bins - 1;
    counts[idx] += 1;
  }
  const breakpoints = Array.from({ length: bins }, (_, i) => lo + width * (i + 1));
  return { bins: counts, breakpoints, min: lo, max: hi, median: median(nums), total, nulls };
}

/** `compute_threshold`. */
export function computeThreshold(
  col: LayoutColumn,
  rows: number[],
  column: string,
  threshold: number,
  direction = 'min',
  warnThreshold: number | null = null,
): Record<string, unknown> | null {
  if (rows.length === 0) return null;
  const higher = direction !== 'max';
  const warnValid = warnThreshold !== null && (higher ? warnThreshold < threshold : warnThreshold > threshold);
  let passing = 0;
  let warning = 0;
  for (const i of rows) {
    const v = num(col.values[i]);
    if (v === null) continue;
    const passes = higher ? v >= threshold : v <= threshold;
    if (passes) passing++;
    else if (warnValid && (higher ? v >= (warnThreshold as number) : v <= (warnThreshold as number))) warning++;
  }
  const total = rows.length;
  const nulls = nullCount(col.values, rows);
  const measured = total - nulls;
  const nums = numbersOf(col.values, rows);
  return {
    column,
    threshold,
    warn_threshold: warnValid ? warnThreshold : null,
    direction: higher ? 'min' : 'max',
    total,
    measured,
    nulls,
    passing,
    warning: warnValid ? warning : 0,
    failing: Math.max(0, measured - passing - (warnValid ? warning : 0)),
    pass_rate: measured > 0 ? passing / measured : 0,
    min: nums.length ? Math.min(...nums) : null,
    max: nums.length ? Math.max(...nums) : null,
    median: median(nums),
  };
}

/** `compute_completeness`. */
export function computeCompleteness(col: LayoutColumn, rows: number[], column: string): Record<string, unknown> | null {
  const total = rows.length;
  const nulls = nullCount(col.values, rows);
  const filled = Math.max(0, total - nulls);
  return { column, total, filled, nulls, fill_rate: total > 0 ? filled / total : 0 };
}

/** `compute_uniqueness`. */
export function computeUniqueness(col: LayoutColumn, rows: number[], column: string): Record<string, unknown> | null {
  const total = rows.length;
  const nulls = nullCount(col.values, rows);
  const measured = Math.max(0, total - nulls);
  if (measured <= 0) return null;
  const counts = new Map<string, { value: unknown; count: number }>();
  for (const i of rows) {
    const v = col.values[i];
    if (v === null || v === undefined) continue;
    const k = keyOf(v);
    const e = counts.get(k);
    if (e) e.count++;
    else counts.set(k, { value: v, count: 1 });
  }
  const distinct = counts.size;
  const ranked = [...counts.values()].sort((a, b) => b.count - a.count || cmpNative(a.value, b.value));
  const top = ranked[0];
  return {
    column,
    total,
    measured,
    distinct,
    duplicated: Math.max(0, measured - distinct),
    unique_rate: measured ? distinct / measured : 0,
    nulls,
    top_repeat: top && top.count > 1 ? { name: polarsUtf8(top.value, col.dtype), count: top.count } : null,
  };
}

/** `compute_attrition`. */
export function computeAttrition(get: ColumnGetter, rows: number[], columns: string[], aggregation = 'sum'): Record<string, unknown> | null {
  if (columns.length < 2) return null;
  const agg = (aggregation || 'sum').toLowerCase();
  const op = ['sum', 'average', 'mean', 'median', 'min', 'max'].includes(agg) ? agg : 'sum';
  const values = columns.map((c) => {
    const col = get(c);
    if (!col) return 0;
    const v = reduce(op, col.values, rows, NUMERIC_RE.test(col.dtype));
    return v === null ? 0 : v;
  });
  const first = values[0];
  return {
    columns: [...columns],
    aggregation: agg,
    stages: columns.map((name, i) => ({
      name,
      value: values[i],
      share: first ? values[i] / first : 0,
      step_share: i && values[i - 1] ? values[i] / values[i - 1] : null,
    })),
    retained: first ? values[values.length - 1] / first : 0,
  };
}

/** Integer representation Polars `cast(Int64)` gives a temporal cell. */
function temporalInt(v: unknown, dtype: string): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === 'bigint') return Number(v);
  if (typeof v === 'number') return v;
  if (v instanceof Date) {
    if (/^Date$/i.test(dtype)) return Math.floor(v.getTime() / 86_400_000);
    const unit = /\bns\b|"ns"|'ns'/.test(dtype) ? 1e6 : /\bms\b|"ms"|'ms'/.test(dtype) ? 1 : 1e3;
    return v.getTime() * unit;
  }
  return null;
}

/** `_format_axis_label`. */
function axisLabel(v: unknown, dtype: string): string {
  if (v === null || v === undefined) return '—';
  if (v instanceof Date) {
    const iso = v.toISOString();
    if (/^Date$/i.test(dtype) || iso.slice(11, 23) === '00:00:00.000') return iso.slice(0, 10);
    const ms = v.getUTCMilliseconds();
    return `${iso.slice(0, 10)} ${iso.slice(11, 19)}${ms ? `.${String(ms * 1000).padStart(6, '0')}` : ''}`;
  }
  if (typeof v === 'bigint') return v.toString();
  if (typeof v === 'number' && Number.isInteger(v)) return String(v);
  return String(v);
}

/** `compute_trend`. */
export function computeTrend(
  get: ColumnGetter,
  rows: number[],
  column: string,
  axis: string,
  aggregation = 'count',
  maxPoints = TREND_MAX_POINTS,
): Record<string, unknown> | null {
  const col = get(column);
  const ax = get(axis);
  if (!col || !ax) return null;
  const temporal = TEMPORAL_RE.test(ax.dtype);
  const numeric = NUMERIC_RE.test(ax.dtype);
  const axisKind = temporal ? 'temporal' : numeric ? 'numeric' : 'categorical';
  const agg = (aggregation || 'count').toLowerCase();
  const op = ['count', 'nunique', 'unique', 'sum', 'average', 'mean', 'median', 'min', 'max'].includes(agg) ? agg : 'count';
  const colNumeric = NUMERIC_RE.test(col.dtype);
  const base = rows.filter((i) => ax.values[i] !== null && ax.values[i] !== undefined);
  const distinctAxis = new Map<string, unknown>();
  for (const i of base) distinctAxis.set(keyOf(ax.values[i]), ax.values[i]);
  if (distinctAxis.size < 2) return null;

  let points: { label: string; value: number }[];
  if (distinctAxis.size > maxPoints && (temporal || numeric)) {
    const asNum = (i: number) => (temporal ? temporalInt(ax.values[i], ax.dtype) : num(ax.values[i])) as number;
    let lo = Infinity;
    let hi = -Infinity;
    for (const i of base) {
      const v = asNum(i);
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    const width = (hi - lo) / maxPoints;
    if (width <= 0) return null;
    const buckets = new Map<number, { rows: number[]; label: unknown }>();
    for (const i of base) {
      let b = Math.floor((asNum(i) - lo) / width);
      if (b < 0) b = 0;
      if (b > maxPoints - 1) b = maxPoints - 1;
      let e = buckets.get(b);
      if (!e) {
        e = { rows: [], label: ax.values[i] };
        buckets.set(b, e);
      }
      e.rows.push(i);
      if (cmpNative(ax.values[i], e.label) < 0) e.label = ax.values[i];
    }
    points = [...buckets.entries()]
      .sort(([a], [b]) => a - b)
      .map(([, e]) => ({ label: axisLabel(e.label, ax.dtype), value: reduce(op, col.values, e.rows, colNumeric) ?? 0 }));
  } else {
    const groups = new Map<string, { value: unknown; rows: number[] }>();
    for (const i of base) {
      const k = keyOf(ax.values[i]);
      let g = groups.get(k);
      if (!g) {
        g = { value: ax.values[i], rows: [] };
        groups.set(k, g);
      }
      g.rows.push(i);
    }
    let sorted = [...groups.values()].sort((a, b) => cmpNative(a.value, b.value));
    if (sorted.length > maxPoints) sorted = sorted.slice(sorted.length - maxPoints);
    points = sorted.map((g) => ({ label: axisLabel(g.value, ax.dtype), value: reduce(op, col.values, g.rows, colNumeric) ?? 0 }));
  }
  if (points.length < 2) return null;
  const values = points.map((p) => p.value);
  const first = values[0];
  const last = values[values.length - 1];
  return {
    column,
    axis,
    axis_kind: axisKind,
    aggregation: agg,
    points,
    first,
    last,
    change: first ? last / first - 1 : null,
    min: Math.min(...values),
    max: Math.max(...values),
  };
}

/** `numeric_layout_payload`: dispatch a card's config to the layout above. */
export function numericLayoutPayload(
  get: ColumnGetter,
  mask: Bitmask | null,
  rowCount: number,
  card: Record<string, unknown>,
  column: string,
  layout: string,
): Record<string, unknown> | null {
  const rows = selected(mask, rowCount);
  const col = get(column);
  switch (layout) {
    case 'histogram':
      return col ? computeHistogram(col, rows) : null;
    case 'threshold': {
      const t = card.threshold_value;
      if (t === null || t === undefined || !col) return null;
      const warn = card.threshold_warn;
      return computeThreshold(
        col,
        rows,
        column,
        Number(t),
        String(card.threshold_direction || 'min'),
        warn === null || warn === undefined ? null : Number(warn),
      );
    }
    case 'completeness':
      return col ? computeCompleteness(col, rows, column) : null;
    case 'uniqueness':
      return col ? computeUniqueness(col, rows, column) : null;
    case 'trend': {
      const axis = card.trend_col ? String(card.trend_col) : '';
      if (!axis || !get(axis) || !col) return null;
      return computeTrend(get, rows, column, axis, String(card.aggregation || 'count'));
    }
    case 'attrition': {
      const raw = ((card.attrition_cols as unknown[]) ?? []).filter(Boolean).map(String);
      const stages = column && !raw.includes(column) ? [column, ...raw] : raw;
      const present = stages.filter((c) => get(c));
      if (present.length < 2) return null;
      return computeAttrition(get, rows, present, String(card.aggregation || 'sum'));
    }
    default:
      return null;
  }
}

/** True when a card's secondary layout needs a payload computed from rows. */
export function needsLayoutPayload(card: Record<string, unknown>): boolean {
  const layout = String(card.secondary_layout || 'vertical');
  if ((BREAKDOWN_LAYOUTS as readonly string[]).includes(layout)) return Boolean(card.breakdown_col);
  return (NUMERIC_LAYOUTS as readonly string[]).includes(layout);
}
