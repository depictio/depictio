/**
 * sortSlice — sorted table pages over decoded columns (serverless plan, phase 3).
 *
 * Standalone kernel, deliberately NOT part of the QueryEngine interface (see
 * QueryEngine.ts:9-13 — later-phase ops arrive as free functions). Operates on
 * full-length decoded columns as returned by `QueryEngine.columns()` plus an
 * optional row mask from `QueryEngine.mask()`.
 *
 * Server contract being mirrored — `render_table_endpoint`
 * (depictio/api/v1/endpoints/dashboards_endpoints/routes.py:2429-2687):
 *
 *   - Request: single `sort_by` column + `sort_dir` ("asc"|"desc", default
 *     "desc"; routes.py:2470-2473), `start`/`limit` pagination
 *     (routes.py:2467-2469 — the *endpoint* clamps limit to 1..500; that is
 *     request validation, not sort semantics, so this kernel takes the page
 *     window verbatim and only floors negatives to 0). Filters are applied
 *     BEFORE sorting (`metadata=filter_metadata`, routes.py:2612-2621) — here
 *     that is the `mask` argument.
 *   - Sort call (deltatables_utils.py:1591-1592, and identically on the lazy
 *     page path at 1568-1577):
 *         df.sort(sort_by, descending=..., nulls_last=True, maintain_order=True)
 *     so: NULLS LAST in BOTH directions (nulls_last=True is the function
 *     default at deltatables_utils.py:1468 and the endpoint never overrides
 *     it), and the sort is STABLE (maintain_order=True — ties preserve input
 *     order).
 *   - An unknown sort column is silently dropped, not an error
 *     (routes.py:2552-2555) — same here, per SortSpec.
 *   - No sort → natural order, page window pushed down as a plain slice
 *     (routes.py:2622-2633 `_load_natural_page`).
 *   - `total` is the FILTERED row count (routes.py:2577-2579), independent of
 *     the page window.
 *   - Rows: `sliced.to_dicts()` (routes.py:2642) serialized by FastAPI — the
 *     browser observes JSON scalars: Int64 arrives as a JS number (lossy above
 *     2^53 via JSON.parse, exactly like `Number(bigint)`), so BigInt cells are
 *     converted to numbers here. Dates are left as the decoder produced them
 *     (Date objects) — display formatting is a renderer concern; the server's
 *     ISO string vs JS `toISOString()` differ in trailing-zero/timezone
 *     cosmetics, so pinning one here would mirror neither faithfully.
 *
 * The server accepts a single sort key (AG Grid's infinite row model sends
 * one sortBy/sortDir pair — react-core api.ts:1004-1031). The kernel
 * generalizes to `SortSpec[]` because the server itself uses the list form
 * elsewhere with the same semantics (routes.py:2838-2847:
 * `df.sort(sort_cols, descending=sort_desc, nulls_last=True)` — per-key
 * direction, nulls last on every key); `[]` = natural order.
 *
 * Per-dtype comparison semantics, verified empirically on Polars 1.42.1 (the
 * repo venv's pin — see also scripts/generate_fixture.py "sort_slice" cases):
 *   - numbers: numeric; NaN sorts GREATER than every float including +inf
 *     (asc: [-inf, 1, inf, NaN, null], desc: [NaN, inf, 1, -inf, null] — NaN
 *     participates in direction reversal, nulls do not).
 *   - Int64: exact BigInt comparison (no float round-trip).
 *   - strings: Polars compares UTF-8 bytes, and UTF-8 byte order equals code
 *     POINT order — which JS's default UTF-16 code-UNIT `<` violates for
 *     supplementary-plane characters vs U+E000..U+FFFF. Compared by code
 *     point here, never localeCompare (locale-dependent, not byte order).
 *   - booleans: false < true.
 *   - Date: by epoch millis (µs-precision datetime sorts should go through
 *     the `__ts__` BigInt companion column instead when sub-ms order matters).
 */

/** One sort key: column name + direction (desc mirrors sort_dir="desc"). */
export interface SortSpec {
  column: string;
  desc: boolean;
}

export interface SortSliceResult {
  /** Page rows, one object per row, keys = every column passed in. */
  rows: Record<string, unknown>[];
  /** Filtered (mask-selected) row count — NOT the page length. */
  total: number;
}

/**
 * Compare two non-null cells of the same column, ascending, mirroring Polars'
 * per-dtype ordering (see module doc). Exported for reuse by later kernels.
 */
export function comparePolars(a: unknown, b: unknown): number {
  if (typeof a === 'number' && typeof b === 'number') {
    // NaN is the greatest float (above +inf) — verified on Polars 1.42.1.
    const na = Number.isNaN(a);
    const nb = Number.isNaN(b);
    if (na || nb) return na === nb ? 0 : na ? 1 : -1;
    return a < b ? -1 : a > b ? 1 : 0;
  }
  if (typeof a === 'bigint' && typeof b === 'bigint') {
    return a < b ? -1 : a > b ? 1 : 0;
  }
  if (typeof a === 'bigint' || typeof b === 'bigint') {
    // Mixed bigint/number cannot occur within one homogeneous column; guard
    // via float space anyway so a malformed column cannot throw mid-sort.
    const fa = typeof a === 'bigint' ? Number(a) : (a as number);
    const fb = typeof b === 'bigint' ? Number(b) : (b as number);
    return fa < fb ? -1 : fa > fb ? 1 : 0;
  }
  if (typeof a === 'string' && typeof b === 'string') return compareCodePoints(a, b);
  if (typeof a === 'boolean' && typeof b === 'boolean') {
    return a === b ? 0 : a ? 1 : -1; // false < true (Polars Boolean order)
  }
  if (a instanceof Date && b instanceof Date) {
    const ta = a.getTime();
    const tb = b.getTime();
    return ta < tb ? -1 : ta > tb ? 1 : 0;
  }
  // Heterogeneous leftovers (shouldn't happen for real columns): stable
  // best-effort via stringified code-point order.
  return compareCodePoints(String(a), String(b));
}

/**
 * Sort the mask-selected rows by `sort` (stable, Polars semantics), then
 * return the `[start, start + limit)` page as row objects plus the total
 * selected count. `sort: []` keeps natural (input) order — the server's
 * unsorted slice-pushdown branch.
 *
 * `columns` must all share one length (the full table length); `mask` (when
 * non-null) must be that same length, 1 = row selected.
 */
export function sortSlice(
  columns: Record<string, ArrayLike<unknown>>,
  mask: Uint8Array | null,
  sort: SortSpec[],
  start: number,
  limit: number,
): SortSliceResult {
  const names = Object.keys(columns);
  const rowCount =
    mask !== null ? mask.length : names.length > 0 ? columns[names[0]].length : 0;

  // Selected row indices, in input order (natural order when unsorted, and
  // the stable-sort baseline otherwise).
  const idx: number[] = [];
  if (mask === null) {
    for (let i = 0; i < rowCount; i++) idx.push(i);
  } else {
    for (let i = 0; i < rowCount; i++) if (mask[i] === 1) idx.push(i);
  }
  const total = idx.length;

  // Bind sort keys; a SortSpec naming an absent column is silently dropped
  // (routes.py:2552-2555 — stale client caches must not error).
  const keys: { values: ArrayLike<unknown>; desc: boolean }[] = [];
  for (const spec of sort) {
    const values = columns[spec.column];
    if (values !== undefined) keys.push({ values, desc: spec.desc });
  }

  if (keys.length > 0) {
    idx.sort((a, b) => {
      for (const key of keys) {
        const va = key.values[a] ?? null;
        const vb = key.values[b] ?? null;
        // Nulls last in BOTH directions (nulls_last=True) — null placement
        // is NOT reversed by desc, so it sits outside the negation below.
        if (va === null || vb === null) {
          if (va === null && vb === null) continue; // tie on this key
          return va === null ? 1 : -1;
        }
        const c = comparePolars(va, vb);
        if (c !== 0) return key.desc ? -c : c;
      }
      // Full tie: preserve input order (maintain_order=True). Array.sort is
      // spec-stable since ES2019; the explicit tiebreak keeps it airtight.
      return a - b;
    });
  }

  const s = Math.max(0, Math.floor(start));
  const l = Math.max(0, Math.floor(limit));
  const page = idx.slice(s, s + l);

  const rows: Record<string, unknown>[] = [];
  for (const i of page) {
    const row: Record<string, unknown> = {};
    for (const name of names) row[name] = normalizeCell(columns[name][i]);
    rows.push(row);
  }
  return { rows, total };
}

/**
 * Cell value → what the browser observes in the server's JSON rows:
 * undefined → null, BigInt → number (Int64 arrives as a JSON number; above
 * 2^53 JSON.parse loses the same precision Number(bigint) does). Everything
 * else passes through as decoded.
 */
function normalizeCell(v: unknown): unknown {
  if (v === undefined || v === null) return null;
  if (typeof v === 'bigint') return Number(v);
  return v;
}

/**
 * Code-point string comparison — Polars sorts strings as UTF-8 bytes, and
 * UTF-8 byte order equals Unicode code-point order. JS's default `<` compares
 * UTF-16 code units, which mis-orders supplementary-plane characters
 * (U+10000+, surrogate pairs starting 0xD800) below U+E000..U+FFFF.
 */
function compareCodePoints(a: string, b: string): number {
  const la = a.length;
  const lb = b.length;
  let i = 0;
  while (i < la && i < lb) {
    const ca = a.codePointAt(i)!;
    const cb = b.codePointAt(i)!;
    if (ca !== cb) return ca < cb ? -1 : 1;
    i += ca > 0xffff ? 2 : 1;
  }
  return la === lb ? 0 : la < lb ? -1 : 1;
}
