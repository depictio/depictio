/**
 * References computed from the data on show: which statistic a config asks
 * for, and where its line ends up.
 *
 * RULES.md §17 allows a data-defined reference only when it is called that, so
 * a `*_stat` field draws its line at the statistic the server computed on the
 * filtered, unsampled rows (`reference_stats` on the data response) and names
 * it "median of this table". Never computed here: the rows a renderer holds
 * may be a sample, and the Manhattan / genome view keep one tail whole, either
 * of which would bias a quantile.
 *
 * Twin of `depictio/api/v1/services/advanced_viz/reference_stats.py`
 * (`REFERENCE_STAT_NAMES`, `config_reference_requests`). Pure, so each kind's
 * "which value wins" rule is unit-tested without a renderer.
 */

/** Mirrors `ReferenceStat` in depictio/models/components/types.py. */
export type ReferenceStat = 'median' | 'mean' | 'p75' | 'p90' | 'p95' | 'p99';

export const REFERENCE_STAT_NAMES: Record<ReferenceStat, string> = {
  median: 'median',
  mean: 'mean',
  p75: '75th percentile',
  p90: '90th percentile',
  p95: '95th percentile',
  p99: '99th percentile',
};

/** `{config field: {column, stat}}`, the `reference_stats` a request carries. */
export type ReferenceStatRequests = Record<string, { column: string; stat: ReferenceStat }>;

/** `{config field: value}`, the `reference_stats` a response carries. */
export type ReferenceStatValues = Record<string, number | null | undefined>;

function isStat(value: unknown): value is ReferenceStat {
  return typeof value === 'string' && value in REFERENCE_STAT_NAMES;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** "median of this table", "95th percentile of this table". */
export function referenceStatLabel(stat: ReferenceStat): string {
  return `${REFERENCE_STAT_NAMES[stat] ?? stat} of this table`;
}

export interface ResolvedReference {
  /** Where the line sits, or null for no line. */
  value: number | null;
  /** The statistic it came from, when it came from one. */
  stat: ReferenceStat | null;
  /** The words to draw: the author's label, else the statistic's name, else null
   *  (the renderer writes its own `y = value`). */
  label: string | null;
}

/**
 * The rule every kind shares: an explicit value wins (an authored one, or the
 * reader's own control), else the server's statistic, else no line.
 */
export function resolveReference(args: {
  explicit: number | null | undefined;
  stat: ReferenceStat | null | undefined;
  computed: number | null | undefined;
  label?: string | null;
}): ResolvedReference {
  const label = args.label || null;
  if (isFiniteNumber(args.explicit)) return { value: args.explicit, stat: null, label };
  if (isStat(args.stat) && isFiniteNumber(args.computed)) {
    return { value: args.computed, stat: args.stat, label: label ?? referenceStatLabel(args.stat) };
  }
  return { value: null, stat: null, label };
}

/** Undefined for an empty map, so a request without stats is byte-identical
 *  to the one sent before this existed. */
function orUndefined(requests: ReferenceStatRequests): ReferenceStatRequests | undefined {
  return Object.keys(requests).length > 0 ? requests : undefined;
}

// ---- scatter_xy --------------------------------------------------------------

export interface ScatterReferenceConfig {
  x_col?: string | null;
  y_col?: string | null;
  reference_stat?: ReferenceStat | null;
  reference_label?: string | null;
}

/** A horizontal line reads its statistic off y, a vertical one off x. Only
 *  requested when no value is set, by the author or by the reader. */
export function scatterReferenceRequests(
  config: ScatterReferenceConfig,
  line: string,
  explicit: number | null | undefined,
): ReferenceStatRequests | undefined {
  const stat = config.reference_stat;
  const column = line === 'horizontal' ? config.y_col : line === 'vertical' ? config.x_col : null;
  if (!isStat(stat) || !column || isFiniteNumber(explicit)) return undefined;
  return orUndefined({ reference_value: { column, stat } });
}

export function resolveScatterReference(
  config: ScatterReferenceConfig,
  line: string,
  explicit: number | null | undefined,
  stats: ReferenceStatValues | null | undefined,
): ResolvedReference {
  if (line !== 'horizontal' && line !== 'vertical') {
    return { value: null, stat: null, label: config.reference_label || null };
  }
  return resolveReference({
    explicit,
    stat: config.reference_stat,
    computed: stats?.reference_value,
    label: config.reference_label,
  });
}

// ---- profile -----------------------------------------------------------------

export interface ProfileReferenceConfig {
  y_col?: string | null;
  reference_y?: number | null;
  reference_y_stat?: ReferenceStat | null;
  reference_y_label?: string | null;
}

export function profileReferenceRequests(
  config: ProfileReferenceConfig,
): ReferenceStatRequests | undefined {
  const stat = config.reference_y_stat;
  if (!isStat(stat) || !config.y_col || isFiniteNumber(config.reference_y)) return undefined;
  return orUndefined({ reference_y: { column: config.y_col, stat } });
}

export function resolveProfileReferenceY(
  config: ProfileReferenceConfig,
  stats: ReferenceStatValues | null | undefined,
): ResolvedReference {
  return resolveReference({
    explicit: config.reference_y,
    stat: config.reference_y_stat,
    computed: stats?.reference_y,
    label: config.reference_y_label,
  });
}

// ---- manhattan / genome_view -------------------------------------------------

export interface ScoreThresholdConfig {
  score_col?: string | null;
  score_threshold_stat?: ReferenceStat | null;
}

export function scoreThresholdRequests(
  config: ScoreThresholdConfig,
  explicit: number | null | undefined,
): ReferenceStatRequests | undefined {
  const stat = config.score_threshold_stat;
  if (!isStat(stat) || !config.score_col || isFiniteNumber(explicit)) return undefined;
  return orUndefined({ score_threshold: { column: config.score_col, stat } });
}

/** The threshold line: the reader's or author's value, else the statistic. */
export function resolveScoreThreshold(
  config: ScoreThresholdConfig,
  explicit: number | null | undefined,
  stats: ReferenceStatValues | null | undefined,
): ResolvedReference {
  return resolveReference({
    explicit,
    stat: config.score_threshold_stat,
    computed: stats?.score_threshold,
  });
}

/**
 * The tail the server must keep whole for a threshold line, or undefined.
 * A statistic travels as `threshold_stat`: its number depends on the filters,
 * and the server settles it on the unreduced rows, the same rows the line's
 * own value is computed on.
 */
export function scoreThresholdTail(
  config: ScoreThresholdConfig,
  explicit: number | null | undefined,
  direction: 'low' | 'high',
):
  | { column: string; direction: 'low' | 'high'; threshold: number }
  | { column: string; direction: 'low' | 'high'; threshold_stat: ReferenceStat }
  | undefined {
  if (!config.score_col) return undefined;
  if (isFiniteNumber(explicit)) return { column: config.score_col, direction, threshold: explicit };
  if (isStat(config.score_threshold_stat)) {
    return { column: config.score_col, direction, threshold_stat: config.score_threshold_stat };
  }
  return undefined;
}

// ---- for hosts that hold every row -------------------------------------------

const QUANTILES: Partial<Record<ReferenceStat, number>> = {
  p75: 0.75,
  p90: 0.9,
  p95: 0.95,
  p99: 0.99,
};

/**
 * `stat` over `values`, for a host that holds every row and no server: Tool
 * Studio's in-browser shim, which serves its whole fixture. Never for a
 * renderer, whose rows may be a sample. Same rules as the Python helper:
 * non-finite values and non-numbers are ignored, quantiles interpolate
 * linearly (polars' `interpolation="linear"`), and no finite value is null.
 */
export function computeReferenceStat(values: readonly unknown[], stat: ReferenceStat): number | null {
  const xs: number[] = [];
  for (const v of values) {
    const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN;
    if (Number.isFinite(n)) xs.push(n);
  }
  if (xs.length === 0) return null;
  if (stat === 'mean') return xs.reduce((a, b) => a + b, 0) / xs.length;
  xs.sort((a, b) => a - b);
  const q = stat === 'median' ? 0.5 : QUANTILES[stat];
  if (q === undefined) return null;
  const pos = (xs.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo);
}

/** Answer a request's `reference_stats` off columns held whole. */
export function computeReferenceStats(
  requests: ReferenceStatRequests | undefined,
  column: (name: string) => readonly unknown[] | undefined,
): Record<string, number | null> | undefined {
  if (!requests) return undefined;
  const out: Record<string, number | null> = {};
  for (const [field, { column: name, stat }] of Object.entries(requests)) {
    const values = column(name);
    out[field] = values ? computeReferenceStat(values, stat) : null;
  }
  return out;
}
