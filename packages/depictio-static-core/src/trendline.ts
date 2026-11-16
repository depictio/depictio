/**
 * Plotly-Express trendlines, refit in the browser (RFC §4 refill, trendlines).
 *
 * A bundle ships each trendline as a scaffold trace with its x/y stripped; the
 * refill recomputes it over the rows its raw trace keeps under the current
 * filter. This module is the recomputation, and it is a port of exactly what
 * plotly express does (plotly 6.9, `express/_core.py` + `trendline_functions`),
 * not an approximation of it:
 *
 * 1. px skips the fit (the trace keeps no x/y) unless at least 2 rows have
 *    both x and y non-null. Here: `null` → the caller hides the trace.
 * 2. px sorts the trace's rows by x, nulls last (a polars sort, stable in
 *    practice, and every parity fixture asserts it), converts a temporal x to
 *    unix epoch seconds, and keeps `non_missing = x and y both non-null`.
 * 3. The output x is the raw x of the non-missing rows in that order, and the
 *    output y comes from the kind's function, one value per output x:
 *    - `ols`: statsmodels OLS on the non-missing pairs (`add_constant`,
 *      `log_x`, `log_y` honoured). The fitted values of a 1-predictor OLS are
 *      closed-form; a degenerate x (zero variance) gets what statsmodels'
 *      pinv solve gives, the mean of y.
 *    - `lowess`: statsmodels `lowess(y, x, frac, it=3, delta=0.0,
 *      missing="drop")`, the Cython kernel ported line for line.
 *    - `rolling` / `expanding` / `ewm`: a pandas Series over ALL the sorted
 *      rows (a null y is NaN and still occupies its window slot, rows with a
 *      null x sit at the end), aggregated with pandas' own kernels
 *      (`pandas/_libs/window/aggregations.pyx`, pandas 3.0), then sliced to
 *      `non_missing`.
 *
 * Which kinds and options are refit is decided at BUILD time by the binder
 * (`depictio/serverless/binding.py`, `trendline_refit_miss`), which freezes
 * every figure whose trendline this module does not implement. The checks
 * here are the same list, as a guard: a binding that reaches this module with
 * an option it does not know is a contract violation, and throws.
 *
 * Parity is pinned by `fixtures/trendline-expected.json`, generated with the
 * real `create_figure_from_data` + px + statsmodels + pandas by
 * `scripts/generate_trendline_fixture.py`.
 */

export type TrendlineKind = 'ols' | 'lowess' | 'rolling' | 'expanding' | 'ewm';

export const TRENDLINE_KINDS: readonly TrendlineKind[] = [
  'ols',
  'lowess',
  'rolling',
  'expanding',
  'ewm',
];

/** px's `lowess` default (`trendline_options.get("frac", 0.6666666)`). */
export const PX_LOWESS_FRAC = 0.6666666;

export interface TrendlineFit {
  /** Raw x values of the fitted rows, sorted by x (what px writes to the trace). */
  x: unknown[];
  /** Fitted values, one per x; NaN where pandas yields NaN (a gap). */
  y: number[];
}

/**
 * Refit one trendline over `sel` (row indices of its raw trace, in source
 * order). Returns `null` where px would leave the trace empty.
 */
export function fitTrendline(
  kind: TrendlineKind,
  options: Record<string, unknown>,
  xs: ArrayLike<unknown>,
  ys: ArrayLike<unknown>,
  sel: readonly number[],
): TrendlineFit | null {
  const n = sel.length;
  const xKey: (number | null)[] = new Array(n);
  const yVal: (number | null)[] = new Array(n);
  let usable = 0;
  for (let k = 0; k < n; k++) {
    xKey[k] = xNumber(xs[sel[k]]);
    yVal[k] = yNumber(ys[sel[k]]);
    if (xKey[k] !== null && yVal[k] !== null) usable++;
  }
  if (usable < 2) return null;

  // Stable sort by x, nulls last — the order px fits and draws in.
  const order = Array.from({ length: n }, (_, k) => k);
  order.sort((a, b) => {
    const xa = xKey[a];
    const xb = xKey[b];
    if (xa === null) return xb === null ? a - b : 1;
    if (xb === null) return -1;
    return xa - xb || a - b;
  });

  const outX: unknown[] = [];
  const fitX: number[] = [];
  const fitY: number[] = [];
  const nonMissing: boolean[] = new Array(n);
  const seriesY: number[] = new Array(n);
  for (let k = 0; k < n; k++) {
    const r = order[k];
    const x = xKey[r];
    const y = yVal[r];
    seriesY[k] = y === null ? NaN : y;
    nonMissing[k] = x !== null && y !== null;
    if (nonMissing[k]) {
      const raw = xs[sel[r]];
      outX.push(typeof raw === 'bigint' ? Number(raw) : raw);
      fitX.push(x as number);
      fitY.push(y as number);
    }
  }

  let y: number[] | null;
  switch (kind) {
    case 'ols':
      y = olsFit(options, fitX, fitY);
      break;
    case 'lowess':
      y = lowessFit(options, fitX, fitY);
      break;
    case 'rolling':
    case 'expanding':
    case 'ewm': {
      const full = pandasWindow(kind, options, seriesY);
      y = full.filter((_, k) => nonMissing[k]);
      break;
    }
    default:
      throw new Error(`trendline: unsupported kind "${String(kind)}"`);
  }
  if (y === null) return null;
  return { x: outX, y };
}

// ---------------------------------------------------------------------------
// input coercion
// ---------------------------------------------------------------------------

/** px fits a temporal x in unix epoch SECONDS; numbers pass through. */
function xNumber(v: unknown): number | null {
  if (v instanceof Date) {
    const t = v.getTime();
    return Number.isFinite(t) ? t / 1000 : null;
  }
  return yNumber(v);
}

function yNumber(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'bigint') return Number(v);
  return null;
}

function checkKeys(kind: string, options: Record<string, unknown>, allowed: string[]): void {
  for (const key of Object.keys(options)) {
    if (!allowed.includes(key)) {
      throw new Error(`trendline: ${kind} option "${key}" cannot be refit in the browser`);
    }
  }
}

// ---------------------------------------------------------------------------
// ols — px.trendline_functions.ols over statsmodels OLS
// ---------------------------------------------------------------------------

function olsFit(options: Record<string, unknown>, xIn: number[], yIn: number[]): number[] | null {
  checkKeys('ols', options, ['add_constant', 'log_x', 'log_y']);
  const addConstant = options.add_constant === undefined ? true : Boolean(options.add_constant);
  const logX = Boolean(options.log_x);
  const logY = Boolean(options.log_y);
  // px raises on a non-positive value under a log option; a filtered subset of
  // a frame that passed cannot hold one, but never draw a fit px would refuse.
  if (logY && yIn.some((v) => v <= 0)) return null;
  if (logX && xIn.some((v) => v <= 0)) return null;
  const x = logX ? xIn.map(Math.log10) : xIn;
  const y = logY ? yIn.map(Math.log10) : yIn;
  const n = x.length;

  let fitted: number[];
  if (addConstant) {
    let sx = 0;
    let sy = 0;
    for (let k = 0; k < n; k++) {
      sx += x[k];
      sy += y[k];
    }
    const xbar = sx / n;
    const ybar = sy / n;
    let sxx = 0;
    let sxy = 0;
    for (let k = 0; k < n; k++) {
      sxx += (x[k] - xbar) * (x[k] - xbar);
      sxy += (x[k] - xbar) * (y[k] - ybar);
    }
    if (sxx === 0) {
      // A constant x: [1, x] is rank 1 and statsmodels' pinv solve projects y
      // onto the constant — every fitted value is the mean.
      fitted = y.map(() => ybar);
    } else {
      const slope = sxy / sxx;
      const intercept = ybar - slope * xbar;
      fitted = x.map((v) => intercept + slope * v);
    }
  } else {
    // Through the origin: y = b·x, b = Σxy / Σx² (pinv gives 0 for an all-zero x).
    let sxx = 0;
    let sxy = 0;
    for (let k = 0; k < n; k++) {
      sxx += x[k] * x[k];
      sxy += x[k] * y[k];
    }
    const slope = sxx === 0 ? 0 : sxy / sxx;
    fitted = x.map((v) => slope * v);
  }
  return logY ? fitted.map((v) => Math.pow(10, v)) : fitted;
}

// ---------------------------------------------------------------------------
// lowess — statsmodels.nonparametric.lowess (0.14, _smoothers_lowess.pyx)
// ---------------------------------------------------------------------------

function lowessFit(options: Record<string, unknown>, x: number[], y: number[]): number[] {
  checkKeys('lowess', options, ['frac']);
  const frac = options.frac === undefined ? PX_LOWESS_FRAC : Number(options.frac);
  if (!(frac >= 0 && frac <= 1)) {
    throw new Error('trendline: lowess `frac` must be in the range [0,1]');
  }
  // `x` is already sorted ascending (statsmodels argsorts it again; on sorted
  // input that is the identity), and `missing="drop"` already happened.
  return lowess(x, y, frac, 3, 0.0);
}

/** The statsmodels kernel with xvals = exog (no `given_xvals`). */
export function lowess(x: number[], y: number[], frac: number, it: number, delta: number): number[] {
  const n = x.length;
  let k = Math.trunc(frac * n + 1e-10);
  if (k < 2) k = 2;
  if (k > n) k = n;
  const yFit = new Array<number>(n).fill(0);
  const weights = new Array<number>(n).fill(0);
  const residWeights = new Array<number>(n).fill(1);

  for (let robiter = 0; robiter < it + 1; robiter++) {
    let i = 0;
    let lastFit = -1;
    let left = 0;
    let right = k;
    yFit.fill(0);
    for (;;) {
      const xval = x[i];
      weights.fill(0);
      // update_neighborhood
      while (right < n && xval > (x[left] + x[right]) / 2.0) {
        left++;
        right++;
      }
      const radius = Math.max(xval - x[left], x[right - 1] - xval);
      // calculate_weights
      let sumWeights = 0;
      for (let j = left; j < right; j++) {
        const d = Math.abs(x[j] - xval) / radius;
        const c = d * d * d;
        const t = 1.0 - c;
        weights[j] = t * t * t * residWeights[j];
        sumWeights += weights[j];
      }
      let nonzero = 0;
      for (let j = left; j < right; j++) if (weights[j] > 1e-12) nonzero++;
      const regOk = nonzero >= 2;
      // calculate_y_fit
      if (!regOk) {
        yFit[i] = y[i];
      } else {
        for (let j = left; j < right; j++) weights[j] /= sumWeights;
        let sumWeightedX = 0;
        for (let j = left; j < right; j++) sumWeightedX += weights[j] * x[j];
        let weightedSqdevX = 0;
        for (let j = left; j < right; j++) {
          weightedSqdevX += weights[j] * (x[j] - sumWeightedX) ** 2;
        }
        weightedSqdevX = Math.max(weightedSqdevX, 1e-12);
        for (let j = left; j < right; j++) {
          const p = weights[j] * (1.0 + ((xval - sumWeightedX) * (x[j] - sumWeightedX)) / weightedSqdevX);
          yFit[i] += p * y[j];
        }
      }
      // interpolate_skipped_fits
      if (lastFit < i - 1) {
        const denom = x[i] - x[lastFit];
        for (let j = lastFit + 1; j < i; j++) {
          const a = (x[j] - x[lastFit]) / denom;
          yFit[j] = a * yFit[i] + (1.0 - a) * yFit[lastFit];
        }
      }
      // update_indices
      lastFit = i;
      const cutpoint = x[lastFit] + delta;
      let kk = lastFit;
      for (kk = lastFit + 1; kk < n; kk++) {
        if (x[kk] > cutpoint) break;
        if (x[kk] === x[lastFit]) {
          yFit[kk] = yFit[lastFit];
          lastFit = kk;
        }
      }
      // Cython leaves the loop variable on the last value it took (n - 1 when
      // the range ran out), not one past it.
      if (kk === n) kk = n - 1;
      i = Math.max(kk - 1, lastFit + 1);
      if (lastFit >= n - 1) break;
    }
    // calculate_residual_weights
    const resid = new Array<number>(n);
    for (let j = 0; j < n; j++) resid[j] = Math.abs(y[j] - yFit[j]);
    const median = npMedian(resid);
    for (let j = 0; j < n; j++) {
      let v = median === 0 ? (resid[j] > 0 ? 1 : 0) : resid[j] / (6.0 * median);
      if (v > 1) v = 1.0;
      const t = 1.0 - v * v;
      residWeights[j] = t * t;
    }
  }
  return yFit;
}

function npMedian(values: number[]): number {
  const s = values.slice().sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// ---------------------------------------------------------------------------
// rolling / expanding / ewm — pandas Series window aggregations
// ---------------------------------------------------------------------------

const WINDOW_FUNCTIONS = ['mean', 'sum', 'min', 'max', 'median', 'std', 'var', 'count'];
const EWM_FUNCTIONS = ['mean', 'sum', 'std', 'var'];

function pandasWindow(
  kind: 'rolling' | 'expanding' | 'ewm',
  options: Record<string, unknown>,
  values: number[],
): number[] {
  const opts = { ...options };
  const fn = opts.function === undefined ? 'mean' : String(opts.function);
  const fnArgs = (opts.function_args ?? {}) as Record<string, unknown>;
  delete opts.function;
  delete opts.function_args;
  if (kind === 'ewm') return ewmApply(opts, fn, fnArgs, values);

  const allowedFns = WINDOW_FUNCTIONS;
  if (!allowedFns.includes(fn)) {
    throw new Error(`trendline: ${kind} function "${fn}" cannot be refit in the browser`);
  }
  checkKeys(`${kind} ${fn}`, fnArgs, fn === 'std' || fn === 'var' ? ['ddof'] : []);
  const ddof = fnArgs.ddof === undefined ? 1 : Number(fnArgs.ddof);

  const n = values.length;
  let start: number[];
  let end: number[];
  let minp: number;
  if (kind === 'rolling') {
    checkKeys('rolling', opts, ['window', 'min_periods', 'center', 'closed']);
    const window = Number(opts.window);
    if (!Number.isInteger(window) || window < 0) {
      throw new Error('trendline: rolling `window` must be an integer 0 or greater');
    }
    minp = opts.min_periods === undefined || opts.min_periods === null ? window : Number(opts.min_periods);
    // FixedWindowIndexer.get_window_bounds
    const offset = opts.center || window === 0 ? Math.floor((window - 1) / 2) : 0;
    const closed = opts.closed ?? null;
    start = [];
    end = [];
    for (let i = 0; i < n; i++) {
      let e = i + 1 + offset;
      let s = e - window;
      if (closed === 'left' || closed === 'both') s -= 1;
      if (closed === 'left' || closed === 'neither') e -= 1;
      end.push(Math.min(Math.max(e, 0), n));
      start.push(Math.min(Math.max(s, 0), n));
    }
  } else {
    checkKeys('expanding', opts, ['min_periods']);
    minp = opts.min_periods === undefined || opts.min_periods === null ? 1 : Number(opts.min_periods);
    start = values.map(() => 0);
    end = values.map((_, i) => i + 1);
  }

  switch (fn) {
    case 'mean':
      return rollMean(values, start, end, minp);
    case 'sum':
      return rollSum(values, start, end, minp);
    case 'count':
      return rollSum(
        values.map((v) => (Number.isNaN(v) ? 0 : 1)),
        start,
        end,
        minp,
      );
    case 'min':
      return rollMinMax(values, start, end, minp, false);
    case 'max':
      return rollMinMax(values, start, end, minp, true);
    case 'median':
      return rollMedian(values, start, end, minp);
    case 'var':
      return rollVar(values, start, end, minp, ddof);
    case 'std':
      return rollVar(values, start, end, minp, ddof).map(zsqrt);
    default:
      throw new Error(`trendline: ${kind} function "${fn}" cannot be refit in the browser`);
  }
}

function zsqrt(v: number): number {
  return v < 0 ? 0 : Math.sqrt(v);
}

function isMonotonicBounds(start: number[], end: number[]): boolean {
  for (let i = 1; i < start.length; i++) {
    if (start[i] < start[i - 1] || end[i] < end[i - 1]) return false;
  }
  return true;
}

/** roll_sum: Kahan add/remove, `num_consecutive_same_value` exactness. */
function rollSum(values: number[], start: number[], end: number[], minp: number): number[] {
  const N = start.length;
  const out = new Array<number>(N);
  const mono = isMonotonicBounds(start, end);
  let nobs = 0;
  let sumX = 0;
  let compAdd = 0;
  let compRemove = 0;
  let same = 0;
  let prev = 0;
  const add = (val: number) => {
    if (val !== val) return;
    nobs++;
    const y = val - compAdd;
    const t = sumX + y;
    compAdd = t - sumX - y;
    sumX = t;
    if (val === prev) same++;
    else same = 1;
    prev = val;
  };
  const remove = (val: number) => {
    if (val !== val) return;
    nobs--;
    const y = -val - compRemove;
    const t = sumX + y;
    compRemove = t - sumX - y;
    sumX = t;
  };
  for (let i = 0; i < N; i++) {
    const s = start[i];
    const e = end[i];
    if (i === 0 || !mono || s >= end[i - 1]) {
      prev = values[s];
      same = 0;
      sumX = compAdd = compRemove = 0;
      nobs = 0;
      for (let j = s; j < e; j++) add(values[j]);
    } else {
      for (let j = start[i - 1]; j < s; j++) remove(values[j]);
      for (let j = end[i - 1]; j < e; j++) add(values[j]);
    }
    if (nobs === 0 && minp === 0) out[i] = 0;
    else if (nobs >= minp) out[i] = same >= nobs ? prev * nobs : sumX;
    else out[i] = NaN;
    if (!mono) {
      nobs = 0;
      sumX = 0;
      compRemove = 0;
    }
  }
  return out;
}

/** roll_mean: Kahan add/remove plus pandas' sign and constant-run corrections. */
function rollMean(values: number[], start: number[], end: number[], minp: number): number[] {
  const N = start.length;
  const out = new Array<number>(N);
  const mono = isMonotonicBounds(start, end);
  let nobs = 0;
  let negCt = 0;
  let sumX = 0;
  let compAdd = 0;
  let compRemove = 0;
  let same = 0;
  let prev = 0;
  const add = (val: number) => {
    if (val !== val) return;
    nobs++;
    const y = val - compAdd;
    const t = sumX + y;
    compAdd = t - sumX - y;
    sumX = t;
    if (signbit(val)) negCt++;
    if (val === prev) same++;
    else same = 1;
    prev = val;
  };
  const remove = (val: number) => {
    if (val !== val) return;
    nobs--;
    const y = -val - compRemove;
    const t = sumX + y;
    compRemove = t - sumX - y;
    sumX = t;
    if (signbit(val)) negCt--;
  };
  for (let i = 0; i < N; i++) {
    const s = start[i];
    const e = end[i];
    if (i === 0 || !mono || s >= end[i - 1]) {
      compAdd = compRemove = sumX = 0;
      nobs = negCt = 0;
      prev = values[s];
      same = 0;
      for (let j = s; j < e; j++) add(values[j]);
    } else {
      for (let j = start[i - 1]; j < s; j++) remove(values[j]);
      for (let j = end[i - 1]; j < e; j++) add(values[j]);
    }
    if (nobs >= minp && nobs > 0) {
      let result = sumX / nobs;
      if (same >= nobs) result = prev;
      else if (negCt === 0 && result < 0) result = 0;
      else if (negCt === nobs && result > 0) result = 0;
      out[i] = result;
    } else {
      out[i] = NaN;
    }
    if (!mono) {
      nobs = 0;
      negCt = 0;
      sumX = 0;
      compRemove = 0;
    }
  }
  return out;
}

function signbit(v: number): boolean {
  return v < 0 || Object.is(v, -0);
}

const INV_COND_TOL = Number.EPSILON * 1e3;

/** roll_var: Welford with Kahan compensation and the cancellation recompute. */
function rollVar(
  values: number[],
  start: number[],
  end: number[],
  minpIn: number,
  ddof: number,
): number[] {
  const minp = Math.max(minpIn, 1);
  const N = start.length;
  const out = new Array<number>(N);
  const mono = isMonotonicBounds(start, end);
  let nobs = 0;
  let meanX = 0;
  let ssqdm = 0;
  let compAdd = 0;
  let compRemove = 0;
  let unstable = false;
  const add = (val: number) => {
    const prevM2 = ssqdm;
    if (val !== val) return;
    nobs++;
    const prevMean = meanX - compAdd;
    const y = val - compAdd;
    const t = y - meanX;
    compAdd = t + meanX - y;
    const delta = t;
    meanX = nobs ? meanX + delta / nobs : 0;
    ssqdm = ssqdm + (val - prevMean) * (val - meanX);
    if (prevM2 * INV_COND_TOL > ssqdm) unstable = true;
  };
  const remove = (val: number) => {
    const prevM2 = ssqdm;
    if (val !== val) return;
    nobs--;
    if (nobs) {
      const prevMean = meanX - compRemove;
      const y = val - compRemove;
      const t = y - meanX;
      compRemove = t + meanX - y;
      const delta = t;
      meanX = meanX - delta / nobs;
      ssqdm = ssqdm - (val - prevMean) * (val - meanX);
      if (prevM2 * INV_COND_TOL > ssqdm) unstable = true;
    } else {
      meanX = 0;
      ssqdm = 0;
      unstable = false;
    }
  };
  for (let i = 0; i < N; i++) {
    const s = start[i];
    const e = end[i];
    const recompute = i === 0 || !mono || s >= end[i - 1];
    if (!recompute) {
      for (let j = start[i - 1]; j < s; j++) remove(values[j]);
      for (let j = end[i - 1]; j < e; j++) add(values[j]);
    }
    if (recompute || unstable) {
      meanX = ssqdm = nobs = compAdd = compRemove = 0;
      for (let j = s; j < e; j++) add(values[j]);
      unstable = false;
    }
    out[i] = nobs >= minp && nobs > ddof ? ssqdm / (nobs - ddof) : NaN;
    if (!mono) {
      nobs = 0;
      meanX = 0;
      ssqdm = 0;
      compRemove = 0;
    }
  }
  return out;
}

/** roll_min / roll_max: the extremum of the window's non-NaN values, when
 *  there are at least max(minp, 1) of them. */
function rollMinMax(
  values: number[],
  start: number[],
  end: number[],
  minpIn: number,
  isMax: boolean,
): number[] {
  const minp = Math.max(minpIn, 1);
  return start.map((s, i) => {
    let nobs = 0;
    let best = NaN;
    for (let j = s; j < end[i]; j++) {
      const v = values[j];
      if (v !== v) continue;
      nobs++;
      if (nobs === 1 || (isMax ? v > best : v < best)) best = v;
    }
    return nobs >= minp ? best : NaN;
  });
}

/** roll_median_c: the skiplist median of the window's non-NaN values. */
function rollMedian(values: number[], start: number[], end: number[], minp: number): number[] {
  return start.map((s, i) => {
    const w: number[] = [];
    for (let j = s; j < end[i]; j++) if (values[j] === values[j]) w.push(values[j]);
    if (w.length < minp || w.length === 0) return NaN;
    w.sort((a, b) => a - b);
    const mid = w.length >> 1;
    return w.length % 2 ? w[mid] : (w[mid] + w[mid - 1]) / 2;
  });
}

/** pandas.core.window.ewm.get_center_of_mass */
function centerOfMass(opts: Record<string, unknown>): number {
  const given = ['com', 'span', 'halflife', 'alpha'].filter(
    (k) => opts[k] !== undefined && opts[k] !== null,
  );
  if (given.length > 1) {
    throw new Error('trendline: comass, span, halflife, and alpha are mutually exclusive');
  }
  if (opts.com !== undefined && opts.com !== null) return Number(opts.com);
  if (opts.span !== undefined && opts.span !== null) return (Number(opts.span) - 1) / 2;
  if (opts.halflife !== undefined && opts.halflife !== null) {
    const decay = 1 - Math.exp(Math.log(0.5) / Number(opts.halflife));
    return 1 / decay - 1;
  }
  if (opts.alpha !== undefined && opts.alpha !== null) {
    const alpha = Number(opts.alpha);
    return (1 - alpha) / alpha;
  }
  throw new Error('trendline: ewm needs one of com, span, halflife or alpha');
}

function ewmApply(
  opts: Record<string, unknown>,
  fn: string,
  fnArgs: Record<string, unknown>,
  values: number[],
): number[] {
  if (!EWM_FUNCTIONS.includes(fn)) {
    throw new Error(`trendline: ewm function "${fn}" cannot be refit in the browser`);
  }
  checkKeys('ewm', opts, ['com', 'span', 'halflife', 'alpha', 'min_periods', 'adjust', 'ignore_na']);
  checkKeys(`ewm ${fn}`, fnArgs, fn === 'std' || fn === 'var' ? ['bias'] : []);
  const com = centerOfMass(opts);
  const adjust = opts.adjust === undefined ? true : Boolean(opts.adjust);
  const ignoreNa = Boolean(opts.ignore_na);
  const mp = opts.min_periods;
  const minp = mp === undefined || mp === null ? 1 : Math.max(Math.trunc(Number(mp)), 1);
  if (fn === 'mean') return ewm(values, minp, com, adjust, ignoreNa, true);
  if (fn === 'sum') {
    if (!adjust) throw new Error('trendline: ewm sum is not implemented with adjust=False');
    return ewm(values, minp, com, adjust, ignoreNa, false);
  }
  const bias = Boolean(fnArgs.bias);
  const variance = ewmcov(values, minp, values, com, adjust, ignoreNa, bias);
  return fn === 'std' ? variance.map(zsqrt) : variance;
}

/** aggregations.ewm over one window [0, N), no `times` deltas. */
function ewm(
  vals: number[],
  minp: number,
  com: number,
  adjust: boolean,
  ignoreNa: boolean,
  normalize: boolean,
): number[] {
  const N = vals.length;
  const out = new Array<number>(N);
  if (N === 0) return out;
  const alpha = 1 / (1 + com);
  const oldWtFactor = 1 - alpha;
  let newWt = adjust ? 1 : alpha;
  let weighted = vals[0];
  let nobs = weighted === weighted ? 1 : 0;
  out[0] = nobs >= minp ? weighted : NaN;
  let oldWt = 1;
  for (let i = 1; i < N; i++) {
    const cur = vals[i];
    const isObs = cur === cur;
    if (isObs) nobs++;
    if (weighted === weighted) {
      if (isObs || !ignoreNa) {
        if (normalize) oldWt *= oldWtFactor;
        else weighted = oldWtFactor * weighted;
        if (isObs) {
          if (normalize) {
            if (weighted !== cur) {
              if (!adjust && com === 1) newWt = 1 - oldWt;
              weighted = oldWt * weighted + newWt * cur;
              weighted /= oldWt + newWt;
            }
            if (adjust) oldWt += newWt;
            else oldWt = 1;
          } else {
            weighted += cur;
          }
        }
      }
    } else if (isObs) {
      weighted = cur;
    }
    out[i] = nobs >= minp ? weighted : NaN;
  }
  return out;
}

/** aggregations.ewmcov over one window [0, N). */
function ewmcov(
  inputX: number[],
  minp: number,
  inputY: number[],
  com: number,
  adjust: boolean,
  ignoreNa: boolean,
  bias: boolean,
): number[] {
  const N = inputX.length;
  const out = new Array<number>(N);
  if (N === 0) return out;
  const alpha = 1 / (1 + com);
  const oldWtFactor = 1 - alpha;
  const newWt = adjust ? 1 : alpha;
  let meanX = inputX[0];
  let meanY = inputY[0];
  let isObs = meanX === meanX && meanY === meanY;
  let nobs = isObs ? 1 : 0;
  if (!isObs) {
    meanX = NaN;
    meanY = NaN;
  }
  out[0] = nobs >= minp ? (bias ? 0 : NaN) : NaN;
  let cov = 0;
  let sumWt = 1;
  let sumWt2 = 1;
  let oldWt = 1;
  for (let i = 1; i < N; i++) {
    const curX = inputX[i];
    const curY = inputY[i];
    isObs = curX === curX && curY === curY;
    if (isObs) nobs++;
    if (meanX === meanX) {
      if (isObs || !ignoreNa) {
        sumWt *= oldWtFactor;
        sumWt2 *= oldWtFactor * oldWtFactor;
        oldWt *= oldWtFactor;
        if (isObs) {
          const oldMeanX = meanX;
          const oldMeanY = meanY;
          if (meanX !== curX) meanX = (oldWt * oldMeanX + newWt * curX) / (oldWt + newWt);
          if (meanY !== curY) meanY = (oldWt * oldMeanY + newWt * curY) / (oldWt + newWt);
          cov =
            (oldWt * (cov + (oldMeanX - meanX) * (oldMeanY - meanY)) +
              newWt * ((curX - meanX) * (curY - meanY))) /
            (oldWt + newWt);
          sumWt += newWt;
          sumWt2 += newWt * newWt;
          oldWt += newWt;
          if (!adjust) {
            sumWt /= oldWt;
            sumWt2 /= oldWt * oldWt;
            oldWt = 1;
          }
        }
      }
    } else if (isObs) {
      meanX = curX;
      meanY = curY;
    }
    if (nobs >= minp) {
      if (!bias) {
        const numerator = sumWt * sumWt;
        const denominator = numerator - sumWt2;
        out[i] = denominator > 0 ? (numerator / denominator) * cov : NaN;
      } else {
        out[i] = cov;
      }
    } else {
      out[i] = NaN;
    }
  }
  return out;
}
