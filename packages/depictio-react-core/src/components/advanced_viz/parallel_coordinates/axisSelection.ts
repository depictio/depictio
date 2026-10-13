/**
 * Which columns of the bound collection become axes.
 *
 * A QC table is the case this kind exists for, and a QC table is mostly
 * numbers: naming its twenty metric columns in every dashboard's YAML would
 * be a copy of the schema that goes stale on the next pipeline release. So
 * `metric_cols` is optional, and with nothing declared the axes are inferred
 * from the collection's precomputed column specs, in the collection's own
 * order so two readers of the same tile see the axes in the same places.
 *
 * The cap is on the inferred set only. A declared list is the author saying
 * exactly what to draw, and silently dropping its tail would be the tile
 * disagreeing with the dashboard it was configured by.
 */

/** Type names `/deltatables/specs` records for a measurement. Both the polars
 *  names (`int64`, `float32`) and the legacy ones (`int64`, `float64`) land in
 *  the same shape, so one prefix test covers the pair. */
const NUMERIC_SPEC_TYPE = /^(u?int\d*|float\d*|decimal|number)/i;

export function isNumericSpecType(type?: string | null): boolean {
  return Boolean(type && NUMERIC_SPEC_TYPE.test(type.trim()));
}

/** One column as the specs describe it. */
export interface AxisCandidate {
  name?: string;
  type?: string | null;
}

export interface AxisChoice {
  /** Columns to draw, in axis order. */
  columns: string[];
  /** Numeric columns the cap left out, so the controls can say the picture is
   *  not the whole table. Always 0 when the axes were declared. */
  truncated: number;
}

export function chooseAxisColumns(input: {
  candidates: readonly AxisCandidate[];
  /** `metric_cols`, when the dashboard names the axes itself. */
  declared?: readonly string[] | null;
  sampleCol: string;
  groupCol?: string | null;
  maxAxes: number;
}): AxisChoice {
  const known = new Set(
    input.candidates.map((candidate) => candidate.name).filter((name): name is string => !!name),
  );

  if (input.declared && input.declared.length) {
    // Columns the collection does not carry drop out: the axis would be a
    // blank strip and every polyline would break at it. When the specs are
    // unavailable nothing is known, so the author's list is taken as given.
    const columns = input.declared.filter(
      (column) => Boolean(column) && (known.size === 0 || known.has(column)),
    );
    return { columns: Array.from(new Set(columns)), truncated: 0 };
  }

  const roles = new Set([input.sampleCol, input.groupCol].filter(Boolean) as string[]);
  const numeric = input.candidates
    .filter((candidate) => candidate.name && !roles.has(candidate.name))
    .filter((candidate) => isNumericSpecType(candidate.type))
    .map((candidate) => candidate.name as string);
  const cap = Math.max(1, Math.floor(input.maxAxes) || 1);
  return {
    columns: numeric.slice(0, cap),
    truncated: Math.max(0, numeric.length - cap),
  };
}
