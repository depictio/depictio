/**
 * depictio-static-core's QueryEngine over the Studio's in-memory fixture.
 *
 * The exported serverless dashboard computes every card, table page and filter
 * mask through depictio-static-core (`HyparquetEngine` + the shared kernels in
 * `engine/aggregate.ts`, `engine/sortSlice.ts`, `cardLayouts.ts`), each pinned
 * against the server. The Studio has the same data, but as a parsed CSV rather
 * than Parquet bytes — so instead of re-deriving the filter predicates, this
 * module hands the fixture to that very engine, pre-decoded.
 *
 * How: `HyparquetEngine` keeps every decoded column in a per-table cache and
 * only touches the Parquet file for a column that is not cached yet. A table
 * whose cache already holds every column — which is what `openFrame` builds —
 * therefore never reads a file, and `mask` / `aggregate` / `unique` / `minMax`
 * run the exact code the bundle runs (codebook translation, BigInt `__ts__`
 * ranges, null-never-matches, per-filter skip on a missing column).
 * `src/test/frameEngine.test.ts` pins that this stays true.
 *
 * Columns are typed the way hyparquet decodes them: a null-free numeric column
 * is a `Float64Array`, a numeric column with nulls a plain array with `null`
 * entries, strings and booleans plain arrays. Two companions are synthesised
 * the way the bundle producer writes them (`depictio/serverless/companions.py`):
 *   - `__ts__<col>` for a Datetime column: wall-clock epoch-µs as BigInt, which
 *     is what a DateRangePicker filter compares against;
 *   - `__code__<col>` + codebook for a Boolean column, so a Select on
 *     `true`/`false` matches the way the bundle (and the server's Utf8
 *     fallback) does.
 */
import {
  HyparquetEngine,
  parseWallClockMicros,
  type AggSpec,
  type Bitmask,
  type ColumnBatch,
  type ColumnGetter,
  type DataRef,
  type MaskResult,
  type QueryEngine,
  type TableHandle,
  type BoundFilter,
} from 'depictio-static-core';
import type { ColumnKind, StudioFrame } from './frame';

/** depictio's column-type name → the polars dtype the kernels key on. */
export function polarsDtype(kind: ColumnKind): string {
  switch (kind) {
    case 'int64':
      return 'Int64';
    case 'float64':
      return 'Float64';
    case 'bool':
      return 'Boolean';
    case 'datetime':
      return 'Datetime';
    default:
      return 'String';
  }
}

/** The fixture as one opened engine table. */
export interface FrameTable {
  readonly handle: TableHandle;
  readonly ref: DataRef;
  readonly rows: number;
  /** User columns (no companions), typed as described above. */
  readonly columns: Record<string, ArrayLike<unknown>>;
  /** Column → polars dtype. */
  readonly dtypes: Map<string, string>;
}

function typedValues(kind: ColumnKind, values: readonly unknown[]): ArrayLike<unknown> {
  if ((kind === 'int64' || kind === 'float64') && values.every((v) => typeof v === 'number')) {
    return Float64Array.from(values as number[]);
  }
  return values.slice();
}

/** The shape `HyparquetEngine` reads off its handle. Every column is cached,
 *  so `file` and `metadata` are never reached; they throw if that changes. */
function preDecodedHandle(
  ref: DataRef,
  rows: number,
  cache: Map<string, ArrayLike<unknown>>,
): TableHandle {
  const unreachable = () => {
    throw new Error('frameEngine: the fixture table has no Parquet file to read');
  };
  return {
    engine: 'hyparquet',
    ref,
    rows,
    columnNames: [...cache.keys()],
    cache,
    file: { byteLength: 0, slice: unreachable },
    metadata: new Proxy({}, { get: unreachable }),
  } as unknown as TableHandle;
}

const tables = new WeakMap<StudioFrame, FrameTable>();

/** Build (once per frame) the engine table for a Studio frame. */
export function frameTable(frame: StudioFrame): FrameTable {
  const hit = tables.get(frame);
  if (hit) return hit;

  const cache = new Map<string, ArrayLike<unknown>>();
  const columns: Record<string, ArrayLike<unknown>> = {};
  const dtypes = new Map<string, string>();
  const companions: Record<string, string> = {};
  const codebooks: Record<string, Record<string, number>> = {};

  for (const col of frame.columns) {
    const values = typedValues(col.kind, col.values);
    columns[col.name] = values;
    cache.set(col.name, values);
    dtypes.set(col.name, polarsDtype(col.kind));
  }
  for (const col of frame.columns) {
    if (col.kind === 'datetime') {
      const name = `__ts__${col.name}`;
      if (cache.has(name)) continue;
      cache.set(
        name,
        col.values.map((v) => (v === null ? null : (parseWallClockMicros(String(v)) ?? null))),
      );
      companions[name] = col.name;
    } else if (col.kind === 'bool') {
      const name = `__code__${col.name}`;
      if (cache.has(name)) continue;
      codebooks[col.name] = { false: 0, true: 1 };
      cache.set(name, col.values.map((v) => (v === null ? null : v ? 1 : 0)));
      companions[name] = col.name;
    }
  }

  const ref: DataRef = {
    uri: 'studio:fixture',
    rows: frame.height,
    size_bytes: 0,
    columns: frame.columns.map((c) => ({ name: c.name, dtype: polarsDtype(c.kind) })) as DataRef['columns'],
    companions,
    codebooks,
  };
  const table: FrameTable = {
    handle: preDecodedHandle(ref, frame.height, cache),
    ref,
    rows: frame.height,
    columns,
    dtypes,
  };
  tables.set(frame, table);
  return table;
}

/** The column getter `cardLayouts` reads: values plus polars dtype, with a
 *  Datetime column's ISO strings turned into the `Date`s hyparquet decodes. */
export function layoutGetter(frame: StudioFrame): ColumnGetter {
  const table = frameTable(frame);
  const dates = new Map<string, ArrayLike<unknown>>();
  return (name) => {
    const values = table.columns[name];
    if (!values) return undefined;
    const dtype = table.dtypes.get(name) ?? '';
    if (dtype !== 'Datetime') return { values, dtype };
    let parsed = dates.get(name);
    if (!parsed) {
      parsed = Array.from(values, (v) => {
        if (v === null || v === undefined) return null;
        const t = Date.parse(String(v));
        return Number.isFinite(t) ? new Date(t) : null;
      });
      dates.set(name, parsed);
    }
    return { values: parsed, dtype };
  };
}

/**
 * A `QueryEngine` whose tables are Studio frames. `open` (Parquet bytes) is not
 * supported — a fixture is opened with `openFrame`; everything else is the
 * bundle's own `HyparquetEngine`.
 */
export class FrameEngine implements QueryEngine {
  private readonly inner = new HyparquetEngine();

  async open(): Promise<TableHandle> {
    throw new Error('frameEngine: open a Studio frame with openFrame()');
  }

  openFrame(frame: StudioFrame): TableHandle {
    return frameTable(frame).handle;
  }

  columns(h: TableHandle, names: string[]): Promise<ColumnBatch> {
    return this.inner.columns(h, names);
  }

  mask(h: TableHandle, filters: BoundFilter[]): Promise<MaskResult> {
    return this.inner.mask(h, filters);
  }

  aggregate(h: TableHandle, mask: Bitmask | null, specs: AggSpec[]): Promise<unknown[]> {
    return this.inner.aggregate(h, mask, specs);
  }

  unique(h: TableHandle, mask: Bitmask | null, col: string): Promise<unknown[]> {
    return this.inner.unique(h, mask, col);
  }

  minMax(h: TableHandle, mask: Bitmask | null, col: string): Promise<[number | null, number | null]> {
    return this.inner.minMax(h, mask, col);
  }
}

/** The one engine the shim shares. */
export const frameEngine = new FrameEngine();

/** Row indices a mask keeps (all rows for a null mask). */
export function maskedRows(mask: Bitmask | null, rows: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < rows; i += 1) if (mask === null || mask[i] === 1) out.push(i);
  return out;
}
