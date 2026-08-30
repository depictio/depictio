/**
 * Where a numeric slider is allowed to stop, and which stops it names.
 *
 * Both sliders used to divide their range into a hundred steps and label five
 * evenly spaced positions, whatever the column held. On a whole-number column
 * spanning a handful of values — a year, a run index, a replicate number — that
 * yields a fractional step, so the thumb lands between two values the column
 * never takes and the values it does take are reachable only by luck or by
 * dragging to an end.
 *
 * Such a column is therefore laid out from its own values: one step per value,
 * one mark per value, and the slider restricted to those marks. Everything
 * wider or fractional keeps the continuous treatment, which is the right one
 * for a measurement.
 */

/** Above this many stops, one mark per value stops being a scale and turns into
 *  a row of overlapping labels — a wide column is better served by a few evenly
 *  spaced anchors. */
const MAX_DISCRETE_STOPS = 12;

/** Marks drawn on a continuous scale when the author has not asked for a
 *  specific number. */
const DEFAULT_MARKS = 5;

export interface SliderMark {
  value: number;
  /** Omitted for a mark that should sit on the track without a caption. */
  label?: string;
}

/** Column facts the layout is derived from. `dtype` and `unique` come from the
 *  DC specs; both are optional so a caller with bounds alone still gets a
 *  sensible scale. */
export interface ColumnScaleStats {
  min: number;
  max: number;
  dtype?: string | null;
  unique?: number | null;
}

export interface NumericScale {
  step: number;
  marks: SliderMark[];
  /** True when every stop is a value the column actually takes. The slider can
   *  then be restricted to the marks without hiding anything from the user. */
  discrete: boolean;
}

/**
 * Slider value as a reader would write it: an integer bare, a fraction with
 * enough decimals to tell neighbouring stops apart and no more.
 *
 * Three decimals is the ceiling whatever the magnitude. Below 1 this used to
 * spell out four, which on a sub-unit column turned every mark and every drag
 * readout into a wall of digits nobody was reading; a fourth decimal has never
 * been what tells two stops apart at a width the Filters panel can offer.
 */
export function formatSliderValue(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (Number.isInteger(v)) return String(v);
  const abs = Math.abs(v);
  const decimals = abs >= 100 ? 1 : abs >= 1 ? 2 : 3;
  return String(Number(v.toFixed(decimals)));
}

export interface NumericScaleOptions {
  /** Marks on a continuous scale. Ignored by a discrete one, which marks every
   *  value it has. */
  marksNumber?: number;
  /** Force the continuous treatment — a log10 slider works on transformed
   *  bounds, where whole numbers mean nothing about the underlying column. */
  continuous?: boolean;
  format?: (value: number) => string;
}

export function buildNumericScale(
  stats: ColumnScaleStats,
  options: NumericScaleOptions = {},
): NumericScale {
  const format = options.format ?? formatSliderValue;
  const { min, max } = stats;
  const span = max - min;

  // A constant column: one stop, and a step that is merely legal (Mantine
  // rejects 0) since there is nowhere to move.
  if (!Number.isFinite(span) || span <= 0) {
    return { step: 1, marks: [{ value: min, label: format(min) }], discrete: false };
  }

  // The dtype is the reliable signal; bounds are the fallback for callers that
  // do not carry specs (the catalog preview's mock API, say). A float column
  // whose min and max happen to be whole is then treated as whole-number too,
  // which costs nothing: its stops are still values it could hold.
  const integral = stats.dtype
    ? /^u?int/i.test(stats.dtype)
    : Number.isInteger(min) && Number.isInteger(max);

  const stops = span + 1;
  // `unique` short of `stops` means the integers are not contiguous — the
  // column skips some of the values between its bounds. Marking every integer
  // would then offer values it never takes, so that case falls through to the
  // continuous branch (which still steps by 1, so it never offers a fraction
  // either).
  const contiguous = stats.unique == null || stats.unique === stops;
  if (integral && !options.continuous && stops <= MAX_DISCRETE_STOPS && contiguous) {
    return {
      step: 1,
      marks: Array.from({ length: stops }, (_, i) => ({
        value: min + i,
        label: format(min + i),
      })),
      discrete: true,
    };
  }

  const count = Math.max(2, options.marksNumber ?? DEFAULT_MARKS);
  const seen = new Set<number>();
  const marks: SliderMark[] = [];
  for (let i = 0; i < count; i += 1) {
    const raw = min + (span / (count - 1)) * i;
    // Rounding keeps a whole-number column's anchors on whole numbers, and
    // keeps the label formatter off fractions it would have to spell out.
    const value = integral ? Math.round(raw) : raw;
    if (seen.has(value)) continue;
    seen.add(value);
    marks.push({ value, label: format(value) });
  }

  return { step: integral ? 1 : span / 100, marks, discrete: false };
}
