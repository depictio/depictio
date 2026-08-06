/** Layout names and the payload shapes each one reads.
 *
 *  Every payload here is a field-for-field mirror of what the server returns —
 *  `card_breakdown.py` for the categorical one, `card_metrics.py` for the rest.
 */

export type SecondaryLayout =
  // Plain stats out of the card's own `aggregations` list.
  | 'vertical'
  | 'compact'
  | 'grid'
  // Distribution of one numeric column.
  | 'box_plot'
  | 'histogram'
  // Progress towards a target.
  | 'coverage'
  | 'gauge'
  | 'threshold'
  // Data quality.
  | 'completeness'
  | 'uniqueness'
  // Change along an axis.
  | 'attrition'
  | 'trend'
  // Make-up of one categorical column.
  | 'top_n'
  | 'concentration'
  | 'composition'
  | 'donut';

/** Layouts that draw the server-computed ``__breakdown__`` payload, i.e. the
 *  ones whose config requires a ``breakdown_col``.
 *
 *  Mirrors ``BREAKDOWN_LAYOUTS`` in ``depictio/api/v1/services/card_breakdown.py``.
 *  The builder gates its required-field UI and its preview fetch on this, so a
 *  layout added to the union but forgotten here silently renders no strip —
 *  which is precisely how ``composition`` nearly shipped broken. */
export const BREAKDOWN_LAYOUTS = [
  'top_n',
  'concentration',
  'composition',
  'donut',
] as const satisfies readonly SecondaryLayout[];

export const isBreakdownLayout = (layout: SecondaryLayout | undefined | null): boolean =>
  !!layout && (BREAKDOWN_LAYOUTS as readonly string[]).includes(layout);

/** Layouts backed by a server-computed *numeric* payload, keyed in ``rows`` as
 *  ``__<layout>__``.
 *
 *  Mirrors ``NUMERIC_LAYOUTS`` in ``depictio/api/v1/services/card_metrics.py``;
 *  a test asserts the two lists are equal. */
export const NUMERIC_LAYOUTS = [
  'histogram',
  'threshold',
  'completeness',
  'attrition',
  'trend',
  'uniqueness',
] as const satisfies readonly SecondaryLayout[];

export const isNumericLayout = (layout: SecondaryLayout | undefined | null): boolean =>
  !!layout && (NUMERIC_LAYOUTS as readonly string[]).includes(layout);

/** Layouts drawn from the card's own `aggregations` list, with no server-side
 *  payload of their own. */
export const STAT_LIST_LAYOUTS = ['vertical', 'compact', 'grid'] as const;

export interface HistogramPayload {
  bins: number[];
  breakpoints: number[];
  min: number;
  max: number;
  median: number | null;
  total: number;
  nulls: number;
}

export interface ThresholdPayload {
  column: string;
  threshold: number;
  warn_threshold: number | null;
  direction: 'min' | 'max';
  total: number;
  measured: number;
  nulls: number;
  passing: number;
  warning: number;
  failing: number;
  pass_rate: number;
  min: number | null;
  max: number | null;
  median: number | null;
}

export interface CompletenessPayload {
  column: string;
  total: number;
  filled: number;
  nulls: number;
  fill_rate: number;
}

export interface AttritionPayload {
  columns: string[];
  aggregation: string;
  stages: { name: string; value: number; share: number; step_share: number | null }[];
  retained: number;
}

/** ``trend`` — the hero aggregation recomputed per bucket of an ordered
 *  column, oldest bucket first. */
export interface TrendPayload {
  column: string;
  /** Column the buckets were cut on (a date, or any sortable numeric). */
  axis: string;
  axis_kind: 'temporal' | 'numeric' | 'categorical';
  aggregation: string;
  points: { label: string; value: number }[];
  first: number;
  last: number;
  /** ``last / first - 1``. Null when the first bucket is zero, where a
   *  percentage change has no meaning. */
  change: number | null;
  min: number;
  max: number;
}

/** ``uniqueness`` — how much of the column repeats itself. */
export interface UniquenessPayload {
  column: string;
  total: number;
  /** Non-null values considered. */
  measured: number;
  distinct: number;
  /** ``measured - distinct``: rows that repeat a value already seen. */
  duplicated: number;
  /** ``distinct / measured``, i.e. 1.0 when the column is a key. */
  unique_rate: number;
  nulls: number;
  /** Most-repeated value and its count, or null when nothing repeats. */
  top_repeat: { name: string; count: number } | null;
}

/** Server-computed payload for the breakdown layouts. Lives in ``rows`` under
 *  the synthetic name ``__breakdown__`` — populated by the
 *  ``bulk_compute_cards`` endpoint when ``breakdown_col`` is bound. */
export interface BreakdownPayload {
  column: string;
  total: number;
  top: { name: string; count: number; percent: number }[];
  top_share: number;
  unique_values: number;
  /** Hero aggregation the per-group counts mirror ('count' / 'nunique' / 'sum'). */
  breakdown_kind?: string;
  /** Pielou evenness of the whole distribution, 0–1. Null below two
   *  categories, where the measure is degenerate rather than meaningful. */
  evenness?: number | null;
}

export const isBreakdownPayload = (v: unknown): v is BreakdownPayload => {
  if (!v || typeof v !== 'object') return false;
  const o = v as Record<string, unknown>;
  return Array.isArray(o.top) && typeof o.total === 'number';
};

/** One secondary aggregation as the card hands it to the strip. */
export interface MetricRow {
  name: string;
  value: unknown;
}
