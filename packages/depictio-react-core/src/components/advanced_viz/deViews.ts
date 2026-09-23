/**
 * The three ways one differential-expression table is read.
 *
 * A volcano, an MA plot and a QQ plot are not three visualisations. They are
 * three projections of the same rows, with the same thresholds, the same hits
 * and the same selection: effect against significance, effect against
 * abundance, and observed significance against the uniform null. Keeping them
 * in one tile means one fetch and one set of thresholds; keeping the maths here
 * means it can be tested without a browser.
 *
 * `VolcanoRenderer` owns the fetch, the controls and the theming; this module
 * owns the arithmetic and the trace assembly for the MA and QQ views.
 */

export type DeTier = 'UP' | 'DN' | 'NS';

/** Which of the three projections the tile is showing. */
export type DeView = 'volcano' | 'ma' | 'qq';

export const DE_VIEWS: readonly DeView[] = ['volcano', 'ma', 'qq'] as const;

/**
 * UP / DN / NS per row, from a signed effect and an optional significance.
 *
 * `significance` is already on the scale `passesSignificance` expects: for the
 * volcano that is -log10 and the test is "at or above", for the MA view it is a
 * raw p-value and the test is "below". Passing the predicate in rather than a
 * flag keeps the two callers honest about which way their column runs.
 */
export function classifyTiers(
  effects: readonly (number | null | undefined)[],
  effectThreshold: number,
  passesSignificance: (index: number) => boolean,
): DeTier[] {
  return effects.map((effect, index) => {
    if (effect == null || !Number.isFinite(effect)) return 'NS';
    if (!passesSignificance(index)) return 'NS';
    if (Math.abs(effect) < effectThreshold) return 'NS';
    return effect > 0 ? 'UP' : 'DN';
  });
}

/** Count each tier, in UP / DN / NS order so the frame's badges keep that order. */
export function tierCounts(tiers: readonly DeTier[]): Record<string, number> {
  const counts: Record<string, number> = { UP: 0, DN: 0, NS: 0 };
  for (const tier of tiers) counts[tier] += 1;
  return counts;
}

/**
 * Indices of the `topN` rows with the highest score, dropping non-finite ones.
 *
 * Both plots label by a product of the two axes rather than by either alone: a
 * feature that is only extreme in one of them is rarely the one a reader wants
 * named.
 */
export function rankTopN(scores: readonly number[], topN: number): Set<number> {
  if (topN <= 0) return new Set();
  const ranked = scores
    .map((score, index) => ({ index, score }))
    .filter((entry) => Number.isFinite(entry.score))
    .sort((a, b) => b.score - a.score);
  return new Set(ranked.slice(0, topN).map((entry) => entry.index));
}

/** Rows whose id or label contains `query`, case-insensitively. Null when the box is empty. */
export function matchSearch(
  ids: readonly (string | number | null | undefined)[],
  labels: readonly (string | number | null | undefined)[],
  query: string,
): Set<number> | null {
  const needle = query.trim().toLowerCase();
  if (!needle) return null;
  const hits = new Set<number>();
  for (let index = 0; index < ids.length; index++) {
    const id = String(ids[index] ?? '').toLowerCase();
    const label = String(labels[index] ?? '').toLowerCase();
    if (id.includes(needle) || label.includes(needle)) hits.add(index);
  }
  return hits;
}

export interface QqSeries {
  /** -log10 of the theoretical quantile, descending from the smallest p. */
  expected: number[];
  /** -log10 of the observed p-value, same order. */
  observed: number[];
  /** Feature ids in the same order, empty strings when nothing is bound. */
  ids: string[];
  /** The sorted p-values themselves, for the inflation factor. */
  ps: number[];
  n: number;
}

/**
 * Sort p-values and pair each with its expected quantile under a uniform null.
 *
 * `-log10((k + 1) / (n + 1))` is the standard plotting position; it descends
 * with k, so the maximum sits at index 0 and not at the end. Values outside
 * (0, 1] are dropped rather than clamped: a zero would plot at infinity and a
 * value above one is not a p-value.
 */
export function qqSeries(
  ps: readonly (number | null | undefined)[],
  indices: readonly number[],
  ids: readonly (string | number | null | undefined)[] | null,
): QqSeries {
  const sorted = indices
    .filter((index) => {
      const p = ps[index];
      return p != null && Number.isFinite(p) && p > 0 && p <= 1;
    })
    .map((index) => ({ index, p: ps[index] as number }))
    .sort((a, b) => a.p - b.p);
  const n = sorted.length;
  return {
    expected: sorted.map((_, k) => -Math.log10((k + 1) / (n + 1))),
    observed: sorted.map((entry) => -Math.log10(entry.p)),
    ids: sorted.map((entry) => (ids ? String(ids[entry.index] ?? '') : '')),
    ps: sorted.map((entry) => entry.p),
    n,
  };
}

/**
 * Inverse chi-square CDF for 1 degree of freedom, via the Beasley-Springer-Moro
 * normal quantile. Good to about four decimals over the range a QQ plot uses,
 * which is well inside what a reported lambda is worth.
 *
 * A two-sided p maps to the normal quantile at `1 - p / 2`, not at `1 - p`.
 * The version this replaces took the latter, which sends the median of a
 * uniform null to a chi-square of zero and so reported lambda near zero for
 * every well-behaved table. `deViews.test.ts` pins both ends of that: uniform
 * p-values now read lambda 1, and squared ones read well above it.
 */
export function chi2InvCdf1df(p: number): number {
  if (p <= 0) return Infinity;
  if (p >= 1) return 0;
  const upper = 1 - p / 2;
  const t = Math.sqrt(-2 * Math.log(Math.min(upper, 1 - upper)));
  const num = 2.515517 + 0.802853 * t + 0.010328 * t * t;
  const den = 1 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t;
  const z = (upper > 0.5 ? 1 : -1) * (t - num / den);
  return z * z;
}

/**
 * Genomic inflation factor: median observed chi-square over the median expected
 * one (0.4549 for 1 df). One above 1 says the whole distribution is shifted,
 * which is the question a QQ plot is asked.
 */
export function genomicInflation(sortedPs: readonly number[]): number {
  if (sortedPs.length === 0) return NaN;
  const median = sortedPs[Math.floor(sortedPs.length / 2)];
  return chi2InvCdf1df(median) / 0.4549;
}

/**
 * The 95% envelope of the null, as a beta-distribution normal approximation on
 * the -log10 scale. Drawn as a filled band behind the points.
 */
export function qqConfidenceBand(n: number): { x: number[]; lower: number[]; upper: number[] } {
  const x: number[] = [];
  const lower: number[] = [];
  const upper: number[] = [];
  for (let k = 1; k <= n; k++) {
    const p = k / (n + 1);
    const variance = (p * (1 - p)) / (n + 2);
    const se = Math.sqrt(variance) / (Math.log(10) * Math.max(p, 1e-12));
    const expected = -Math.log10(p);
    x.push(expected);
    lower.push(Math.max(0, expected - 1.96 * se));
    upper.push(expected + 1.96 * se);
  }
  return { x, lower, upper };
}

/**
 * Which of the three views the bindings can actually draw.
 *
 * The MA view needs somewhere to put abundance and the QQ view needs raw
 * p-values, so a tile bound to a table that has neither offers no switch at all
 * rather than a control that leads to an empty plot.
 */
export function offeredDeViews(config: {
  views?: DeView[] | null;
  avg_log_intensity_col?: string | null;
  p_value_col?: string | null;
  significance_col?: string | null;
  significance_is_neg_log10?: boolean;
}): DeView[] {
  const allowed = config.views && config.views.length > 0 ? config.views : DE_VIEWS;
  const hasMa = Boolean(config.avg_log_intensity_col);
  const hasQq = Boolean(config.p_value_col) || !config.significance_is_neg_log10;
  return DE_VIEWS.filter(
    (view) =>
      allowed.includes(view) && (view === 'volcano' || (view === 'ma' ? hasMa : hasQq)),
  );
}

/** The view to draw: the author's pick, or the first one the bindings allow. */
export function resolveDeView(view: DeView, offered: readonly DeView[]): DeView {
  if (offered.includes(view)) return view;
  return offered[0] ?? 'volcano';
}
