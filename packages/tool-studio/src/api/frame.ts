/**
 * A typed, column-oriented view of the parsed fixture — the in-browser stand-in
 * for the Polars frame depictio's API computes against.
 *
 * `parseFixture` hands back rows of strings (that is what a CSV holds), but
 * every reduction downstream is dtype-dependent: polars returns a float for
 * `min` on a numeric column and a string on a text one, and counts an empty
 * cell as null rather than as the empty string. Coercing once, here, is what
 * lets `aggregations.ts` and `cardMetrics.ts` be faithful ports of the Python
 * rather than approximations that happen to agree on the easy cases.
 *
 * `type` uses depictio's own column-type vocabulary (`int64` / `float64` /
 * `bool` / `datetime` / `object`), NOT polars' — those are the names
 * `_polars_type_name` records in the precomputed specs, and the names every
 * frontend consumer compares against (`ColumnSelect`'s categorical set,
 * `aggFunctions.normalizeType`, `CardBuilder`'s trend/attrition pickers).
 */
import type { Dtype, FixtureColumn, ParsedFixture } from '../types';

/** Column-type names as depictio's precompute records them. */
export type ColumnKind = 'int64' | 'float64' | 'bool' | 'datetime' | 'object';

/** One cell, coerced to the type its column declares. `null` covers both a
 *  missing cell and one that could not be coerced. */
export type FrameValue = number | string | boolean | null;

export interface FrameColumn {
  name: string;
  kind: ColumnKind;
  values: FrameValue[];
  /** Values with nulls dropped — every reduction starts from this. */
  present: FrameValue[];
}

export interface StudioFrame {
  height: number;
  columns: FrameColumn[];
  byName: Map<string, FrameColumn>;
}

/** The fixture's polars-style dtype → depictio's column-type name. */
export function columnKind(dtype: Dtype): ColumnKind {
  switch (dtype) {
    case 'Int64':
      return 'int64';
    case 'Float64':
      return 'float64';
    case 'Boolean':
      return 'bool';
    case 'Datetime':
      return 'datetime';
    default:
      return 'object';
  }
}

export const isNumericKind = (kind: ColumnKind): boolean =>
  kind === 'int64' || kind === 'float64';

function coerce(raw: unknown, kind: ColumnKind): FrameValue {
  if (raw === null || raw === undefined) return null;
  if (typeof raw === 'string' && raw.trim() === '') return null;
  switch (kind) {
    case 'int64':
    case 'float64': {
      const n = typeof raw === 'number' ? raw : Number(String(raw).trim());
      return Number.isFinite(n) ? n : null;
    }
    case 'bool': {
      if (typeof raw === 'boolean') return raw;
      const t = String(raw).trim().toLowerCase();
      if (t === 'true') return true;
      if (t === 'false') return false;
      return null;
    }
    default:
      return String(raw);
  }
}

function buildColumn(rows: Record<string, unknown>[], col: FixtureColumn): FrameColumn {
  const kind = columnKind(col.dtype);
  const values = rows.map((r) => coerce(r[col.name], kind));
  return {
    name: col.name,
    kind,
    values,
    present: values.filter((v) => v !== null),
  };
}

/** Coercion is O(rows × columns) and the fixture is re-read by every preview,
 *  so the frame is memoised on the fixture object it was built from. */
const cache = new WeakMap<ParsedFixture, StudioFrame>();

export function buildFrame(fixture: ParsedFixture): StudioFrame {
  const hit = cache.get(fixture);
  if (hit) return hit;
  const columns = fixture.columns.map((c) => buildColumn(fixture.rows, c));
  const frame: StudioFrame = {
    height: fixture.rows.length,
    columns,
    byName: new Map(columns.map((c) => [c.name, c])),
  };
  cache.set(fixture, frame);
  return frame;
}

/** Numeric view of a column, nulls dropped. Empty for a non-numeric column:
 *  the Python side reduces on the declared dtype, so a text column that happens
 *  to hold digits must not silently become numeric here. */
export function numericValues(col: FrameColumn | undefined): number[] {
  if (!col || !isNumericKind(col.kind)) return [];
  return col.present as number[];
}

/** Row objects with every cell coerced — what the table/figure previews and
 *  the advanced-viz data endpoint hand to the renderers. */
export function frameRows(frame: StudioFrame): Record<string, FrameValue>[] {
  const out: Record<string, FrameValue>[] = [];
  for (let i = 0; i < frame.height; i += 1) {
    const row: Record<string, FrameValue> = {};
    for (const col of frame.columns) row[col.name] = col.values[i];
    out.push(row);
  }
  return out;
}
