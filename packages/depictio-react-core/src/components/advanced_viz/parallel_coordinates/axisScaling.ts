/**
 * How one axis is scaled, and how it keeps telling the truth once it is.
 *
 * Axes in different units cannot share a picture: a read count of 40 million
 * and a duplication rate of 0.12 on raw axes leave the rate a flat line at the
 * bottom of its strip. Normalising per axis is what makes the polylines
 * comparable, and it is also what makes the numbers on the axis meaningless,
 * since nobody reads a genome in z-scores.
 *
 * So the values are rescaled and the ticks are not: `tickvals` sit at the
 * rescaled positions while `ticktext` keeps printing the column's own units.
 * `toOriginal` is the same inversion, for a brush that has to leave the tile
 * as a filter on the real column.
 */

export type AxisScaleMode = 'raw' | 'zscore' | 'minmax';

export interface AxisScale {
  /** Values as the axis plots them, nulls preserved so a gap stays a gap. */
  values: (number | null)[];
  /** Axis bounds in plotted space. */
  range: [number, number];
  /** Tick positions in plotted space, with the original values they stand
   *  for. Undefined for `raw`, where plotly's own ticks already read right. */
  tickvals?: number[];
  ticktext?: string[];
  /** A plotted coordinate back in the column's own units. */
  toOriginal: (value: number) => number;
  /** A value in the column's own units, where the axis draws it. The brush
   *  state is kept in the column's units, so this is what puts it back on the
   *  axis after a scale change, a refetch or a remount. */
  toPlotted: (value: number) => number;
}

/** Ticks per normalised axis: enough to read the span, few enough to fit in a
 *  strip a few dozen pixels wide. */
const DEFAULT_TICKS = 5;

/** Values as numbers, with everything unparseable read as a gap. */
export function toNumbers(values: readonly unknown[]): (number | null)[] {
  return values.map((value) => {
    if (value === null || value === undefined || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  });
}

/** One axis tick, in as few characters as still separate two of them. */
export function formatAxisTick(value: number): string {
  if (!Number.isFinite(value)) return '';
  const magnitude = Math.abs(value);
  if (magnitude !== 0 && (magnitude < 1e-3 || magnitude >= 1e6)) return value.toExponential(1);
  if (Number.isInteger(value)) return value.toLocaleString('en-US');
  const digits = magnitude >= 100 ? 0 : magnitude >= 1 ? 2 : 3;
  return value.toLocaleString('en-US', { maximumFractionDigits: digits });
}

export function buildAxisScale(
  raw: readonly unknown[],
  mode: AxisScaleMode,
  tickCount: number = DEFAULT_TICKS,
): AxisScale {
  const values = toNumbers(raw);
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  let sum = 0;
  let count = 0;
  for (const value of values) {
    if (value === null) continue;
    if (value < min) min = value;
    if (value > max) max = value;
    sum += value;
    count += 1;
  }

  // An axis with nothing on it still has to have bounds, or plotly draws the
  // dimension at NaN and takes the whole trace with it.
  if (count === 0) {
    return { values, range: [0, 1], toOriginal: (value) => value, toPlotted: (value) => value };
  }

  if (mode === 'raw') {
    return {
      values,
      range: min === max ? [min - 0.5, max + 0.5] : [min, max],
      toOriginal: (value) => value,
      toPlotted: (value) => value,
    };
  }

  const mean = sum / count;
  let variance = 0;
  for (const value of values) {
    if (value === null) continue;
    variance += (value - mean) ** 2;
  }
  const sd = Math.sqrt(variance / count);

  const scaled = mode === 'zscore' ? sd : max - min;
  if (scaled === 0) {
    // Every row carries the same value. A flat line down the middle of the
    // strip says that; a divide by zero says NaN.
    const centre = mode === 'zscore' ? 0 : 0.5;
    const range: [number, number] = mode === 'zscore' ? [-1, 1] : [0, 1];
    return {
      values: values.map((value) => (value === null ? null : centre)),
      range,
      tickvals: [centre],
      ticktext: [formatAxisTick(min)],
      toOriginal: () => min,
      toPlotted: () => centre,
    };
  }

  const project =
    mode === 'zscore'
      ? (value: number) => (value - mean) / sd
      : (value: number) => (value - min) / scaled;
  const invert =
    mode === 'zscore'
      ? (value: number) => mean + value * sd
      : (value: number) => min + value * scaled;

  const ticks = Math.max(2, Math.floor(tickCount) || DEFAULT_TICKS);
  const tickvals: number[] = [];
  const ticktext: string[] = [];
  for (let i = 0; i < ticks; i += 1) {
    const original = min + ((max - min) * i) / (ticks - 1);
    tickvals.push(project(original));
    ticktext.push(formatAxisTick(original));
  }

  return {
    values: values.map((value) => (value === null ? null : project(value))),
    range: [project(min), project(max)],
    tickvals,
    ticktext,
    toOriginal: invert,
    toPlotted: project,
  };
}
