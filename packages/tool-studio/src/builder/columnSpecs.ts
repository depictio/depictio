/**
 * Map the parsed fixture into depictio's builder `ColumnSpec[]` shape
 * ({ name, type, specs }) — the store the reused builder panels read, and what
 * the offline api shim serves from `fetchSpecs`.
 *
 * `type` is depictio's own column-type name (`int64` / `float64` / `bool` /
 * `datetime` / `object`), not the fixture's polars-style dtype. That
 * distinction is not cosmetic: `aggFunctions.normalizeType` lowercases before
 * it looks a type up, but `ColumnSelect` and `CardBuilder` compare the raw
 * string against lowercase sets, so emitting `String`/`Int64` left the card's
 * breakdown-column, attrition-stage and trend-axis pickers permanently empty —
 * silently disabling six of the sixteen secondary layouts.
 *
 * `specs` carries the per-column stats depictio precomputes at ingest time and
 * every consumer reads by aggregation name, plus the `unique_values` sample the
 * breakdown pickers offer.
 */
import type { ColumnSpec } from 'depictio-builder/store/useBuilderStore';
import type { ParsedFixture } from '../types';
import { aggregate } from '../api/aggregations';
import type { FrameColumn, StudioFrame } from '../api/frame';
import { buildFrame, isNumericKind } from '../api/frame';

/** Aggregations the ingest-time precompute records for a numeric column. */
const NUMERIC_KEYS = [
  'sum',
  'average',
  'median',
  'min',
  'max',
  'range',
  'variance',
  'std_dev',
  // Offered by `aggFunctions.NUMERIC_CARD` and legal in the catalog, so a card
  // using one has to show a value rather than an em dash.
  'percentile',
  'skewness',
  'kurtosis',
] as const;

/** Distinct values offered to the breakdown pickers. A sample, not the column:
 *  the pickers list categories, they don't enumerate a key column. */
const UNIQUE_SAMPLE = 25;

function computeSpecs(frame: StudioFrame, col: FrameColumn): Record<string, unknown> {
  const specs: Record<string, unknown> = {};
  specs.count = aggregate(frame, col.name, 'count');
  const nunique = aggregate(frame, col.name, 'nunique');
  specs.nunique = nunique;
  // `unique` is the name the ingest-time specs use; both spellings are read.
  specs.unique = nunique;
  specs.mode = aggregate(frame, col.name, 'mode');

  const seen = new Set<string>();
  for (const v of col.present) {
    seen.add(String(v));
    if (seen.size >= UNIQUE_SAMPLE) break;
  }
  specs.unique_values = [...seen];

  if (isNumericKind(col.kind)) {
    for (const key of NUMERIC_KEYS) {
      const value = aggregate(frame, col.name, key);
      if (typeof value === 'number' && Number.isFinite(value)) specs[key] = value;
    }
  } else if (col.kind === 'datetime') {
    // The date-range picker reads its bounds from the specs like every other
    // interactive control does.
    specs.min = aggregate(frame, col.name, 'min');
    specs.max = aggregate(frame, col.name, 'max');
  }
  return specs;
}

export function fixtureToColumnSpecs(fixture: ParsedFixture): ColumnSpec[] {
  const frame = buildFrame(fixture);
  return frame.columns.map((col) => ({
    name: col.name,
    type: col.kind,
    specs: computeSpecs(frame, col),
  }));
}
