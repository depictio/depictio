/**
 * Engine-agnostic query interface (serverless plan, phase 1).
 *
 * The decided implementation is `engine/hyparquet/` (see
 * `docs/design/serverless-engine-spike.md`); the interface stays
 * engine-agnostic so DuckDB-WASM (or any SQL engine) remains pluggable for
 * `static-dir`/`remote` should a later feature warrant it.
 *
 * LATER PHASES — deliberately absent from this interface for now:
 *   - sortSlice (sorted table pages)
 *   - groupByAgg (grouped figure aggregation)
 *   - unpivot (prologue ops)
 * Do not add them piecemeal; they arrive with their own phases.
 */

import type { DataRef } from '../manifest';
import type { BoundFilter } from './filters';

/**
 * Opaque per-engine handle for an opened table. Engines brand it with their
 * own private shape; callers only pass it back.
 */
export interface TableHandle {
  /** Engine identifier, e.g. 'hyparquet' — for error messages only. */
  readonly engine: string;
}

/**
 * One decoded column batch: column name → values, full table length.
 * Typed arrays wherever the decoder can produce them (Float64Array /
 * Int32Array / BigInt64Array); a plain array otherwise (strings, and any
 * column containing nulls — nulls surface as `null`/`undefined` entries).
 */
export interface ColumnBatch {
  [col: string]: ArrayLike<unknown>;
}

/**
 * Row-match mask, one byte per row: 1 = row matches, 0 = row filtered out.
 * (A byte per row, not a bit — the kernels trade 8x memory for branch-free
 * indexing; masks are transient per interaction.)
 */
export type Bitmask = Uint8Array;

/** Aggregations mirroring the server's `_agg_value` (dashboards routes.py:1290). */
export type AggFn =
  | 'sum'
  | 'mean'
  | 'median'
  | 'min'
  | 'max'
  | 'count'
  | 'nunique'
  | 'std'
  | 'var'
  | 'mode'
  | 'first'
  | 'last';

export interface AggSpec {
  col: string;
  fn: AggFn;
}

export interface MaskResult {
  mask: Bitmask;
  /** Number of 1-bytes in `mask`. */
  matched: number;
}

export interface QueryEngine {
  /**
   * Open a table from raw Parquet bytes (already resolved via resolveUri).
   * `ref` supplies the schema-side contract: companions and codebooks.
   */
  open(ref: DataRef, bytes: Uint8Array): Promise<TableHandle>;

  /** Decode (and cache) the named columns; full table length each. */
  columns(h: TableHandle, names: string[]): Promise<ColumnBatch>;

  /**
   * Evaluate `filters` (ANDed) into a row mask. Server-mirroring rules —
   * per-filter skip on missing columns, codebook translation, null-never-
   * matches, link_no_match short-circuit — are documented on BoundFilter.
   */
  mask(h: TableHandle, filters: BoundFilter[]): Promise<MaskResult>;

  /**
   * Compute each AggSpec over the rows selected by `mask` (null = all rows).
   * Result order matches `specs`. Return values mirror `_agg_value`: numbers
   * (or strings for non-numeric min/max/mode/first/last), `null` when the
   * aggregation has no answer, with the empty-selection cases pinned as:
   * sum → 0 on numeric columns, count/nunique → 0, everything else → null.
   */
  aggregate(h: TableHandle, mask: Bitmask | null, specs: AggSpec[]): Promise<unknown[]>;

  /**
   * Distinct non-null values of `col` under `mask`, stringified and sorted
   * lexicographically — exactly the server's unique_values endpoint contract
   * (deltatables routes.py:687-689: drop_nulls, `str(v)` dedupe, `sorted`).
   */
  unique(h: TableHandle, mask: Bitmask | null, col: string): Promise<unknown[]>;

  /**
   * Numeric [min, max] of `col` under `mask`, ignoring nulls (and NaN);
   * [null, null] when no numeric values survive.
   */
  minMax(h: TableHandle, mask: Bitmask | null, col: string): Promise<[number | null, number | null]>;
}
