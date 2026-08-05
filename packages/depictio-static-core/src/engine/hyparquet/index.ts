/**
 * HyparquetEngine — the phase-1 QueryEngine implementation.
 *
 * Engine decision + measured patterns: `docs/design/serverless-engine-spike.md`
 * (hyparquet primary for all three modes; kernels on decoded typed arrays;
 * `__ts__` comparisons in BigInt space; plain-Array fallback for chunks that
 * are not ArrayBuffer views — string columns, and any column containing nulls,
 * decode as plain arrays with `null` entries).
 *
 * Server-semantics contract (file:line evidence) lives on BoundFilter
 * (../filters.ts) and QueryEngine (../QueryEngine.ts).
 */

import {
  parquetMetadata,
  parquetRead,
  parquetSchema,
  type AsyncBuffer,
  type ColumnData,
  type DecodedArray,
  type FileMetaData,
} from 'hyparquet';
import { compressors } from 'hyparquet-compressors';

import type { DataRef } from '../../manifest';
import type { BoundFilter } from '../filters';
import { serializeOption } from '../filters';
import type {
  AggSpec,
  Bitmask,
  ColumnBatch,
  MaskResult,
  QueryEngine,
  TableHandle,
} from '../QueryEngine';

type ColumnValues = ArrayLike<unknown>;

interface HyTable extends TableHandle {
  readonly engine: 'hyparquet';
  readonly ref: DataRef;
  readonly file: AsyncBuffer;
  readonly metadata: FileMetaData;
  readonly rows: number;
  /** Physical column names present in the file, in schema order. */
  readonly columnNames: string[];
  /** Decoded-column cache: decode on first use, keep for the session. */
  readonly cache: Map<string, ColumnValues>;
}

const NUMERIC_DTYPE = /^(U?Int|Float)/;

export class HyparquetEngine implements QueryEngine {
  async open(ref: DataRef, bytes: Uint8Array): Promise<TableHandle> {
    // hyparquet slices an ArrayBuffer; a Uint8Array may be a view into a
    // larger (or shared) buffer — re-anchor onto a plain ArrayBuffer of
    // exactly these bytes when needed.
    let ab: ArrayBuffer;
    const buf = bytes.buffer;
    if (buf instanceof ArrayBuffer && bytes.byteOffset === 0 && bytes.byteLength === buf.byteLength) {
      ab = buf;
    } else {
      ab = new ArrayBuffer(bytes.byteLength);
      new Uint8Array(ab).set(bytes);
    }
    const file: AsyncBuffer = {
      byteLength: ab.byteLength,
      slice: (start: number, end?: number) => ab.slice(start, end),
    };
    const metadata = parquetMetadata(ab);
    const rows = Number(metadata.num_rows);
    const columnNames = parquetSchema(metadata).children.map((c) => c.element.name);
    const handle: HyTable = {
      engine: 'hyparquet',
      ref,
      file,
      metadata,
      rows,
      columnNames,
      cache: new Map(),
    };
    return handle;
  }

  async columns(h: TableHandle, names: string[]): Promise<ColumnBatch> {
    const t = asHyTable(h);
    const missing = names.filter((n) => !t.cache.has(n));
    for (const name of missing) {
      if (!t.columnNames.includes(name)) {
        throw new Error(`hyparquet engine: column "${name}" not in table`);
      }
    }
    if (missing.length > 0) {
      const chunksByColumn = new Map<string, ColumnData[]>();
      await parquetRead({
        file: t.file,
        metadata: t.metadata,
        columns: missing,
        compressors,
        utf8: true,
        onChunk: (chunk) => {
          let list = chunksByColumn.get(chunk.columnName);
          if (!list) {
            list = [];
            chunksByColumn.set(chunk.columnName, list);
          }
          list.push(chunk);
        },
      });
      for (const name of missing) {
        t.cache.set(name, assembleColumn(chunksByColumn.get(name) ?? [], t.rows, name));
      }
    }
    const out: ColumnBatch = {};
    for (const name of names) {
      out[name] = t.cache.get(name)!;
    }
    return out;
  }

  async mask(h: TableHandle, filters: BoundFilter[]): Promise<MaskResult> {
    const t = asHyTable(h);
    const mask: Bitmask = new Uint8Array(t.rows);

    // link_no_match short-circuits everything: the server appends
    // pl.lit(False) (add_filter:240-250), so the conjunction is all-false.
    if (filters.some((f) => f.kind === 'link_no_match')) {
      return { mask, matched: 0 };
    }
    mask.fill(1);

    // Decode-on-first-use: pull every physical column the filters can bind
    // to (absent ones are skipped, mirroring the server's per-filter skip).
    const needed = new Set<string>();
    for (const f of filters) {
      const physical = physicalColumn(t, f);
      if (physical !== null && t.columnNames.includes(physical)) needed.add(physical);
    }
    if (needed.size > 0) await this.columns(h, [...needed]);

    for (const filter of filters) {
      const bound = this.resolveFilter(t, filter);
      if (bound === 'skip') continue; // per-filter skip on missing column
      const { values, predicate } = bound;
      for (let i = 0; i < t.rows; i++) {
        if (mask[i] === 1 && !predicate(values[i])) mask[i] = 0;
      }
    }

    let matched = 0;
    for (let i = 0; i < t.rows; i++) matched += mask[i];
    return { mask, matched };
  }

  /**
   * Bind one filter to its physical column + row predicate, or 'skip' when
   * the column (or the companion it reads) is absent from the table —
   * mirroring the server's per-filter skip (apply_runtime_filters:1986-2010).
   * Nulls (null/undefined entries) never match any predicate.
   */
  private resolveFilter(
    t: HyTable,
    filter: BoundFilter,
  ): { values: ColumnValues; predicate: (v: unknown) => boolean } | 'skip' {
    switch (filter.kind) {
      case 'link_no_match':
        // Handled by the short-circuit in mask(); unreachable here.
        return { values: [], predicate: () => false };

      case 'in': {
        const codebook = t.ref.codebooks[filter.column];
        if (codebook !== undefined) {
          // Codebook path: translate option values -> Int32 codes via the
          // shared serializeOption convention; a value absent from the
          // codebook matches NOTHING (manifest.ts DataRef.codebooks).
          const companion = `__code__${filter.column}`;
          if (!t.columnNames.includes(companion)) return 'skip';
          const codes = new Set<number>();
          for (const v of filter.values) {
            const code = codebook[serializeOption(v)];
            if (code !== undefined) codes.add(code);
          }
          return {
            values: this.cachedColumn(t, companion),
            predicate: (v) => typeof v === 'number' && codes.has(v),
          };
        }
        if (!t.columnNames.includes(filter.column)) return 'skip';
        const values = this.cachedColumn(t, filter.column);
        const dtype = t.ref.columns.find((c) => c.name === filter.column)?.dtype;
        if (dtype === 'String' || dtype === 'Utf8' || dtype === undefined) {
          // String column: bare string set-membership over stringified values
          // (server: is_in(str_values), _categorical_predicate:184,193).
          const set = new Set(filter.values.map((v) => String(v)));
          return { values, predicate: (v) => typeof v === 'string' && set.has(v) };
        }
        // Typed column without codebook: cast the *values* to the column's
        // domain; an unconvertible value is dropped and matches nothing
        // (_categorical_predicate:199,215).
        const set = new Set<string>();
        for (const v of filter.values) {
          const key = numericKey(v);
          if (key !== null) set.add(key);
        }
        return {
          values,
          predicate: (v) => {
            if (v == null) return false;
            const key = numericKey(v);
            return key !== null && set.has(key);
          },
        };
      }

      case 'eq': {
        if (!t.columnNames.includes(filter.column)) return 'skip';
        const target = filter.value;
        return {
          values: this.cachedColumn(t, filter.column),
          predicate: (v) => {
            if (v == null || target == null) return false;
            if (typeof v === 'bigint' || typeof target === 'bigint') {
              const a = numericKey(v);
              const b = numericKey(target);
              return a !== null && a === b;
            }
            return v === target;
          },
        };
      }

      case 'range': {
        if (!t.columnNames.includes(filter.column)) return 'skip';
        const min = filter.min ?? Number.NEGATIVE_INFINITY;
        const max = filter.max ?? Number.POSITIVE_INFINITY;
        // Exact bounds for integer (BigInt) values: for integral v,
        // v >= min  ⇔  v >= ceil(min)  and  v <= max  ⇔  v <= floor(max).
        const bigMin = Number.isFinite(min) ? BigInt(Math.ceil(min)) : null;
        const bigMax = Number.isFinite(max) ? BigInt(Math.floor(max)) : null;
        return {
          values: this.cachedColumn(t, filter.column),
          predicate: (v) => {
            if (typeof v === 'number') return v >= min && v <= max;
            if (typeof v === 'bigint') {
              return (bigMin === null || v >= bigMin) && (bigMax === null || v <= bigMax);
            }
            return false; // null / non-numeric never matches
          },
        };
      }

      case 'ts_range': {
        // Reads the epoch-µs Int64 companion; comparisons stay in BigInt
        // space (number mixing silently truncates above 2^53 — spike §5).
        const companion = `__ts__${filter.column}`;
        if (!t.columnNames.includes(companion)) return 'skip';
        const min = filter.min;
        const max = filter.max;
        return {
          values: this.cachedColumn(t, companion),
          predicate: (v) => {
            if (typeof v !== 'bigint') return false;
            return (min === undefined || v >= min) && (max === undefined || v <= max);
          },
        };
      }

      case 'contains': {
        if (!t.columnNames.includes(filter.column)) return 'skip';
        // Polars str.contains(pattern): REGEX, case-sensitive, unanchored
        // (add_filter:260-262). An invalid pattern throws — the server load
        // errors too. JS RegExp and Rust regex agree on the common syntax;
        // exotic constructs (look-around works here but not in Rust) diverge.
        const regex = new RegExp(filter.pattern);
        return {
          values: this.cachedColumn(t, filter.column),
          predicate: (v) => typeof v === 'string' && regex.test(v),
        };
      }
    }
  }

  /**
   * Synchronous cache access used by resolveFilter — mask() prefetches every
   * physical column its filters bind to before binding predicates.
   */
  private cachedColumn(t: HyTable, name: string): ColumnValues {
    const cached = t.cache.get(name);
    if (cached) return cached;
    throw new Error(`hyparquet engine: column "${name}" was not prefetched before binding`);
  }

  async aggregate(h: TableHandle, mask: Bitmask | null, specs: AggSpec[]): Promise<unknown[]> {
    const t = asHyTable(h);
    const names = [...new Set(specs.map((s) => s.col))];
    const batch = await this.columns(h, names);
    return specs.map((spec) => aggregateColumn(batch[spec.col], mask, spec, t));
  }

  async unique(h: TableHandle, mask: Bitmask | null, col: string): Promise<unknown[]> {
    const batch = await this.columns(h, [col]);
    const values = batch[col];
    // Server contract (deltatables routes.py:687-689): drop nulls, stringify,
    // dedupe, sort lexicographically. ASCII/BMP sort order matches Python's.
    const set = new Set<string>();
    for (let i = 0; i < values.length; i++) {
      if (mask !== null && mask[i] === 0) continue;
      const v = values[i];
      if (v == null) continue;
      set.add(stringifyValue(v));
    }
    return [...set].sort();
  }

  async minMax(
    h: TableHandle,
    mask: Bitmask | null,
    col: string,
  ): Promise<[number | null, number | null]> {
    const batch = await this.columns(h, [col]);
    const values = batch[col];
    let min: number | null = null;
    let max: number | null = null;
    for (let i = 0; i < values.length; i++) {
      if (mask !== null && mask[i] === 0) continue;
      const raw = values[i];
      if (raw == null) continue;
      const v = typeof raw === 'bigint' ? Number(raw) : typeof raw === 'number' ? raw : NaN;
      if (Number.isNaN(v)) continue;
      if (min === null || v < min) min = v;
      if (max === null || v > max) max = v;
    }
    return [min, max];
  }

}

/**
 * The physical column a filter reads: the `__ts__`/`__code__` companion where
 * that is the read target, the named column otherwise; null for filters that
 * read nothing (link_no_match).
 */
function physicalColumn(t: HyTable, f: BoundFilter): string | null {
  if (f.kind === 'link_no_match') return null;
  if (f.kind === 'ts_range') return `__ts__${f.column}`;
  if (f.kind === 'in' && t.ref.codebooks[f.column] !== undefined) return `__code__${f.column}`;
  return f.column;
}

// ---------------------------------------------------------------------------
// column assembly
// ---------------------------------------------------------------------------

type TypedArray = Float64Array | Float32Array | Int32Array | Uint32Array | BigInt64Array | BigUint64Array | Uint8Array;

function isTypedChunk(a: DecodedArray): a is TypedArray {
  return ArrayBuffer.isView(a);
}

/**
 * Concatenate row-group chunks into one full-length column, preserving typed
 * arrays when every chunk is one (measured gotcha, spike §3: string columns
 * and null-carrying columns arrive as plain arrays — those fall back).
 * Values are placed by absolute rowStart so overlapping/re-emitted chunks
 * (hyparquet may deliver data outside the requested range) stay correct.
 */
function assembleColumn(chunks: ColumnData[], rows: number, name: string): ColumnValues {
  if (chunks.length === 0) {
    throw new Error(`hyparquet engine: no data decoded for column "${name}"`);
  }
  const sorted = [...chunks].sort((a, b) => a.rowStart - b.rowStart);
  const first = sorted[0].columnData;
  const allTypedSame =
    isTypedChunk(first) &&
    sorted.every(
      (c) => isTypedChunk(c.columnData) && c.columnData.constructor === first.constructor,
    );
  if (allTypedSame) {
    const ctor = first.constructor as new (n: number) => TypedArray;
    const out = new ctor(rows);
    for (const chunk of sorted) {
      // TS can't relate the union members; runtime constructor equality does.
      (out as Float64Array).set(chunk.columnData as Float64Array, chunk.rowStart);
    }
    return out;
  }
  const out: unknown[] = new Array(rows).fill(null);
  for (const chunk of sorted) {
    const data = chunk.columnData;
    for (let j = 0; j < data.length; j++) {
      const v = (data as ArrayLike<unknown>)[j];
      out[chunk.rowStart + j] = v === undefined ? null : v;
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// aggregate kernel — mirrors _agg_value (dashboards routes.py:1290)
// ---------------------------------------------------------------------------

function aggregateColumn(
  values: ColumnValues,
  mask: Bitmask | null,
  spec: AggSpec,
  t: HyTable,
): unknown {
  const dtype = t.ref.columns.find((c) => c.name === spec.col)?.dtype ?? '';
  const numericColumn = NUMERIC_DTYPE.test(dtype);

  switch (spec.fn) {
    case 'count': {
      // Server: col.drop_nulls().len() — NON-null count (routes.py:1299-1300).
      let n = 0;
      forEachMasked(values, mask, (v) => {
        if (v != null) n++;
      });
      return n;
    }
    case 'sum': {
      // Polars sum skips nulls and returns 0 for an empty/all-null NUMERIC
      // series (verified, Polars 1.42.1); on a non-numeric column col.sum()
      // raises and _agg_value's catch returns None (routes.py:1384-1386).
      if (!numericColumn) return null;
      let sum = 0;
      let big = 0n;
      forEachMasked(values, mask, (v) => {
        if (typeof v === 'number') sum += v;
        else if (typeof v === 'bigint') big += v;
      });
      return sum + (big === 0n ? 0 : Number(big));
    }
    case 'mean': {
      if (!numericColumn) return null;
      let sum = 0;
      let big = 0n;
      let n = 0;
      forEachMasked(values, mask, (v) => {
        if (typeof v === 'number') {
          sum += v;
          n++;
        } else if (typeof v === 'bigint') {
          big += v;
          n++;
        }
      });
      return n === 0 ? null : (sum + (big === 0n ? 0 : Number(big))) / n;
    }
    case 'median': {
      // Polars default: linear interpolation between the two middle values on
      // even counts (verified: median([1,2,3,10]) == 2.5).
      const nums = collectNumbers(values, mask);
      if (nums.length === 0) return null;
      nums.sort((a, b) => a - b);
      const pos = (nums.length - 1) / 2;
      const lo = Math.floor(pos);
      const frac = pos - lo;
      return frac === 0 ? nums[lo] : nums[lo] + frac * (nums[lo + 1] - nums[lo]);
    }
    case 'min':
    case 'max': {
      // Numeric -> float; non-numeric -> str (routes.py:1310-1319).
      const wantMin = spec.fn === 'min';
      let bestNum: number | null = null;
      let bestStr: string | null = null;
      forEachMasked(values, mask, (v) => {
        if (v == null) return;
        if (typeof v === 'number' || typeof v === 'bigint') {
          const cur = typeof v === 'bigint' ? Number(v) : v;
          if (Number.isNaN(cur)) return;
          if (bestNum === null || (wantMin ? cur < bestNum : cur > bestNum)) bestNum = cur;
        } else {
          const cur = stringifyValue(v);
          if (bestStr === null || (wantMin ? cur < bestStr : cur > bestStr)) bestStr = cur;
        }
      });
      return bestNum !== null ? bestNum : bestStr;
    }
    case 'std':
    case 'var': {
      // ddof=1 (sample), Polars default; n < 2 -> null (verified: std of a
      // single value is None, not NaN).
      const nums = collectNumbers(values, mask);
      const n = nums.length;
      if (n < 2) return null;
      let sum = 0;
      for (const v of nums) sum += v;
      const mean = sum / n;
      let ssd = 0;
      for (const v of nums) ssd += (v - mean) * (v - mean);
      const variance = ssd / (n - 1);
      return spec.fn === 'var' ? variance : Math.sqrt(variance);
    }
    case 'nunique': {
      // Polars n_unique counts null as a distinct value (verified:
      // n_unique([1,2,None,2]) == 3, n_unique([None,None]) == 1).
      const seen = new Set<string>();
      let sawNull = false;
      forEachMasked(values, mask, (v) => {
        if (v == null) sawNull = true;
        else seen.add(typeof v + ':' + stringifyValue(v));
      });
      return seen.size + (sawNull ? 1 : 0);
    }
    case 'mode': {
      // Server (_agg_value routes.py:1377-1383): m[0] of col.mode(). Two
      // measured traps, both matched here:
      // - Polars mode() counts NULL as a candidate value (verified on 1.42.1:
      //   mode of a null-heavy Int64 column is [None]) — and str(None) makes
      //   the server literally return the string "None" for it.
      // - Polars' order among TIED modes is nondeterministic (neither sorted
      //   nor first-encountered), so the server is arbitrary there. We pin
      //   the deterministic first-encountered winner; identical whenever the
      //   mode is unique.
      // Empty selection -> null (routes.py:1379-1381).
      const NULL_KEY = ' null';
      const counts = new Map<string, { value: unknown; count: number; firstIdx: number }>();
      let idx = 0;
      forEachMasked(values, mask, (v) => {
        const i = idx++;
        const key = v == null ? NULL_KEY : typeof v + ':' + stringifyValue(v);
        const entry = counts.get(key);
        if (entry) entry.count++;
        else counts.set(key, { value: v ?? null, count: 1, firstIdx: i });
      });
      let best: { value: unknown; count: number; firstIdx: number } | null = null;
      for (const entry of counts.values()) {
        if (
          best === null ||
          entry.count > best.count ||
          (entry.count === best.count && entry.firstIdx < best.firstIdx)
        ) {
          best = entry;
        }
      }
      if (best === null) return null;
      const v = best.value;
      if (v === null) return 'None'; // str(None) — the server's exact artifact
      return typeof v === 'number' ? v : typeof v === 'bigint' ? Number(v) : stringifyValue(v);
    }
    case 'first':
    case 'last': {
      // Polars Series.first()/last(): the positional first/last element,
      // nulls INCLUDED (first([None,1]) is None — verified).
      let result: unknown = null;
      let found = false;
      forEachMasked(values, mask, (v) => {
        if (spec.fn === 'first') {
          if (!found) {
            result = v ?? null;
            found = true;
          }
        } else {
          result = v ?? null;
          found = true;
        }
      });
      if (!found || result == null) return null;
      return typeof result === 'number'
        ? result
        : typeof result === 'bigint'
          ? Number(result)
          : stringifyValue(result);
    }
  }
}

function forEachMasked(
  values: ColumnValues,
  mask: Bitmask | null,
  fn: (v: unknown) => void,
): void {
  for (let i = 0; i < values.length; i++) {
    if (mask !== null && mask[i] === 0) continue;
    fn(values[i]);
  }
}

function collectNumbers(values: ColumnValues, mask: Bitmask | null): number[] {
  const out: number[] = [];
  forEachMasked(values, mask, (v) => {
    if (typeof v === 'number') {
      if (!Number.isNaN(v)) out.push(v);
    } else if (typeof v === 'bigint') {
      out.push(Number(v));
    }
  });
  return out;
}

/**
 * Canonical numeric key for cross-representation set-membership ('in' on a
 * typed column, 'eq' with bigint on either side): exact for integers of any
 * size (BigInt canonical form), Number string form otherwise; null when the
 * value doesn't convert (server drops those — _categorical_predicate:215).
 */
function numericKey(v: unknown): string | null {
  if (typeof v === 'bigint') return v.toString();
  if (typeof v === 'number') {
    if (Number.isNaN(v)) return null;
    return Number.isInteger(v) ? BigInt(v).toString() : String(v);
  }
  if (typeof v === 'string') {
    const s = v.trim();
    if (/^-?\d+$/.test(s)) return BigInt(s).toString();
    const n = Number(s);
    return Number.isNaN(n) || s === '' ? null : String(n);
  }
  if (typeof v === 'boolean') return v ? '1' : '0';
  return null;
}

/** String form for unique()/string aggregates; ISO for Dates. */
function stringifyValue(v: unknown): string {
  if (v instanceof Date) return v.toISOString();
  return String(v);
}

function asHyTable(h: TableHandle): HyTable {
  if (h.engine !== 'hyparquet') {
    throw new Error(`HyparquetEngine received a "${h.engine}" table handle`);
  }
  return h as HyTable;
}
