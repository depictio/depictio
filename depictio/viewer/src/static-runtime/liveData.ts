/**
 * Live data path for the static runtime (serverless phase 1).
 *
 * Bridges the viewer's filter/card contracts onto depictio-static-core's
 * QueryEngine: opens each bundled DataRef once (inline snappy Parquet →
 * HyparquetEngine), translates the React `InteractiveFilter[]` payloads into
 * engine `BoundFilter[]` exactly as the server's `add_filter`
 * (depictio/api/v1/deltatables_utils.py:225) would, and computes card values /
 * unique options / column ranges offline.
 *
 * Manifests without `data_refs` (the phase-0 fixture) take none of these
 * paths — the apiShim falls back to frozen payloads, so old bundles keep
 * rendering.
 */
import {
  HyparquetEngine,
  refillFigure,
  resolveUri,
  runPrologue,
  sortSlice,
  type AggFn,
  type BindingTable,
  type BoundFilter,
  type ColumnTable,
  type DataRef,
  type PrologueOp,
  type QueryEngine,
  type SortSpec,
  type TableHandle,
} from 'depictio-static-core';
import type { InteractiveFilter } from '../../../../packages/depictio-react-core/src/api';
import { bundle } from './bundle';

const LINK_NO_MATCH = '__link_no_match__';

const engine: QueryEngine = new HyparquetEngine();
const tableCache = new Map<string, Promise<{ ref: DataRef; handle: TableHandle }>>();

export function dataRefFor(dcId: string): DataRef | undefined {
  return bundle().data_refs?.[dcId];
}

/** Open (once) the bundled table for a data collection. */
export function tableFor(dcId: string): Promise<{ ref: DataRef; handle: TableHandle }> {
  let entry = tableCache.get(dcId);
  if (!entry) {
    entry = (async () => {
      const ref = dataRefFor(dcId);
      if (!ref) throw new Error(`static bundle: no data_ref for dc "${dcId}"`);
      const resolved = resolveUri(bundle(), ref.uri);
      if (resolved.kind !== 'inline') {
        // static-dir / remote fetching is phase 9.
        throw new Error(`static bundle: non-inline data uri "${ref.uri}" not supported yet`);
      }
      const handle = await engine.open(ref, resolved.bytes);
      return { ref, handle };
    })();
    tableCache.set(dcId, entry);
  }
  return entry;
}

/** Parse the ISO-ish strings the date pickers emit into epoch-microseconds,
 *  as WALL-CLOCK time — the server parses them into naive datetimes
 *  (add_filter:290-306) and the `__ts__` companions epoch wall-clock too, so
 *  local-timezone parsing (what `Date.parse` does for datetime strings) would
 *  shift the boundary. */
export function parseWallClockMicros(raw: unknown): bigint | undefined {
  if (typeof raw !== 'string') {
    if (raw instanceof Date) return BigInt(raw.getTime()) * 1000n;
    return undefined;
  }
  const m = raw.match(
    /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?/,
  );
  if (!m) return undefined;
  const [, y, mo, d, h = '0', mi = '0', s = '0', frac = ''] = m;
  const ms = Date.UTC(+y, +mo - 1, +d, +h, +mi, +s);
  const fracUs = Math.round(Number(`0.${frac || '0'}`) * 1e6);
  return BigInt(ms) * 1000n + BigInt(fracUs);
}

/** React filter payloads → engine BoundFilters, mirroring `add_filter`'s
 *  branches and its empty-value guards (`_build_filter_metadata`,
 *  dashboards routes.py:1606: entries without a column or with value in
 *  (None, [], "") never reach the predicate builder). */
export function toBoundFilters(filters: InteractiveFilter[]): BoundFilter[] {
  const out: BoundFilter[] = [];
  for (const f of filters ?? []) {
    const meta = f.metadata ?? {};
    const type = f.interactive_component_type ?? meta.interactive_component_type;
    if (type === LINK_NO_MATCH) {
      out.push({ kind: 'link_no_match' });
      continue;
    }
    const column = f.column_name ?? meta.column_name;
    const v = f.value;
    if (!column || v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0)) {
      continue;
    }
    switch (type) {
      case 'Select':
      case 'MultiSelect':
      case 'SegmentedControl':
        out.push({ kind: 'in', column, values: Array.isArray(v) ? v : [v] });
        break;
      case 'TextInput':
        out.push({ kind: 'contains', column, pattern: String(v) });
        break;
      case 'Slider':
        out.push({ kind: 'eq', column, value: v });
        break;
      case 'RangeSlider':
        if (Array.isArray(v) && v.length === 2) {
          out.push({ kind: 'range', column, min: Number(v[0]), max: Number(v[1]) });
        }
        break;
      case 'DateRangePicker':
      case 'Timeline':
        if (Array.isArray(v) && v.length === 2) {
          const min = parseWallClockMicros(v[0]);
          const max = parseWallClockMicros(v[1]);
          if (min !== undefined && max !== undefined) {
            out.push({ kind: 'ts_range', column, min, max });
          }
        }
        break;
      default:
        // Selection-sourced filters with filter_expr scoping are phase 6.
        console.warn(`static bundle: unsupported filter type "${type}" skipped`);
    }
  }
  return out;
}

/** Server aggregation-name aliases (`_agg_expr`, dashboards routes.py:1242)
 *  → engine AggFn. Returns undefined for aggregations the phase-1 engine
 *  doesn't cover (box_plot_stats, q1/q3); `range` is derived from minMax. */
function toAggFn(aggregation: string): AggFn | 'range' | undefined {
  const agg = (aggregation || '').toLowerCase();
  const direct: Record<string, AggFn> = {
    sum: 'sum',
    mean: 'mean',
    average: 'mean',
    median: 'median',
    min: 'min',
    max: 'max',
    count: 'count',
    nunique: 'nunique',
    unique: 'nunique',
    std: 'std',
    std_dev: 'std',
    var: 'var',
    variance: 'var',
    mode: 'mode',
    first: 'first',
    last: 'last',
  };
  if (agg in direct) return direct[agg];
  if (agg === 'range') return 'range';
  return undefined;
}

interface CardMeta {
  index?: string;
  component_type?: string;
  dc_id?: string | null;
  column_name?: string;
  aggregation?: string;
  aggregations?: string[];
}

/** Live equivalent of the server's bulk_compute_cards body. */
export async function computeCardsLive(
  filters: InteractiveFilter[],
  componentIds?: string[],
): Promise<{
  values: Record<string, unknown>;
  secondary_values: Record<string, Record<string, unknown>>;
  aggregations: Record<string, string[]>;
  filter_applied: boolean;
  filter_count: number;
}> {
  const manifest = bundle();
  const doc = manifest.dashboard.doc as { stored_metadata?: CardMeta[] };
  const requested = componentIds ? new Set(componentIds) : null;
  const cards = (doc.stored_metadata ?? []).filter(
    (m) =>
      m.component_type === 'card' &&
      m.index &&
      manifest.tiers[m.index]?.tier === 'live' &&
      (!requested || requested.has(String(m.index))),
  );

  const bound = toBoundFilters(filters);
  const values: Record<string, unknown> = {};
  const secondary_values: Record<string, Record<string, unknown>> = {};
  const aggregations: Record<string, string[]> = {};

  // One mask per dc (filters are global; per-filter column skip is the
  // engine's job, matching apply_runtime_filters).
  const maskCache = new Map<string, Promise<Uint8Array>>();
  const maskFor = (dcId: string) => {
    let m = maskCache.get(dcId);
    if (!m) {
      m = tableFor(dcId).then(({ handle }) =>
        engine.mask(handle, bound).then((r) => r.mask),
      );
      maskCache.set(dcId, m);
    }
    return m;
  };

  const aggOne = async (dcId: string, column: string, aggregation: string) => {
    const { handle } = await tableFor(dcId);
    const mask = bound.length ? await maskFor(dcId) : null;
    const fn = toAggFn(aggregation);
    if (fn === undefined) {
      console.warn(`static bundle: aggregation "${aggregation}" not supported offline`);
      return null;
    }
    if (fn === 'range') {
      const [min, max] = await engine.minMax(handle, mask, column);
      return min === null || max === null ? null : max - min;
    }
    const [value] = await engine.aggregate(handle, mask, [{ col: column, fn }]);
    return value;
  };

  await Promise.all(
    cards.map(async (card) => {
      const idx = String(card.index);
      const dcId = String(card.dc_id ?? '');
      const column = card.column_name;
      if (!dcId || !column || !card.aggregation) return;
      try {
        values[idx] = await aggOne(dcId, column, card.aggregation);
        const secondary = card.aggregations ?? [];
        if (secondary.length) {
          aggregations[idx] = [...secondary];
          const entries = await Promise.all(
            secondary.map(async (agg) => [agg, await aggOne(dcId, column, agg)] as const),
          );
          secondary_values[idx] = Object.fromEntries(entries);
        }
      } catch (e) {
        console.error(`static bundle: card ${idx} computation failed`, e);
        values[idx] = null;
      }
    }),
  );

  return {
    values,
    secondary_values,
    aggregations,
    filter_applied: bound.length > 0,
    filter_count: bound.length,
  };
}

/** Live equivalent of the server's render_figure body for a bound ui-mode
 *  figure (RFC §4 bind-and-refill): mask the dc's table with the current
 *  filters (no filters → null mask = all rows), then refill the binding's
 *  scaffold from the projected columns. Theme templating stays in the api
 *  shim — this helper is theme-agnostic, like the engine. */
export async function renderFigureLive(
  binding: BindingTable,
  dcId: string,
  filters: InteractiveFilter[],
): Promise<{
  figure: { data: unknown[]; layout: Record<string, unknown> };
  displayed: number;
  total: number;
  filterApplied: boolean;
}> {
  const { handle } = await tableFor(dcId);
  const bound = toBoundFilters(filters);
  const mask = bound.length ? (await engine.mask(handle, bound)).mask : null;
  const result = await refillFigure({
    binding,
    columns: (names) => engine.columns(handle, names),
    mask,
  });
  return { ...result, filterApplied: bound.length > 0 };
}

/** Live path for a code-mode figure with a transpiled prologue (phase 6):
 *  mask the BASE table with the current filters exactly like the ui-mode
 *  figure path, replay the prologue IR over the mask-selected base rows to
 *  rebuild the code's derived frame, then refill the binding's scaffold from
 *  that frame. `mask: null` on the refill is deliberate — the mask was
 *  already applied while materializing the base rows, so refill operates on
 *  the reshaped frame unchanged. Any throw (missing column, malformed op,
 *  unbound scaffold trace) is structural degradation — the api shim catches
 *  it, same as the ui-mode path. */
export async function renderPrologueFigureLive(
  binding: BindingTable,
  ops: PrologueOp[],
  dcId: string,
  filters: InteractiveFilter[],
): Promise<{
  figure: { data: unknown[]; layout: Record<string, unknown> };
  displayed: number;
  total: number;
  filterApplied: boolean;
}> {
  const { ref, handle } = await tableFor(dcId);
  const bound = toBoundFilters(filters);
  const mask = bound.length ? (await engine.mask(handle, bound)).mask : null;

  // Base frame = the DataRef's schema minus build-time companions
  // (companion-map keys plus `__code__*`/`__ts__*`/`__fe__*` — the same
  // exclusion rule as renderTableLive): the prologue re-derives the code's
  // DataFrame from the user-visible columns, which the producer bundles
  // keep-all for prologue figures.
  const companions = new Set(Object.keys(ref.companions ?? {}));
  const baseNames = (ref.columns ?? [])
    .map((c) => c.name)
    .filter(
      (n) =>
        !companions.has(n) &&
        !n.startsWith('__code__') &&
        !n.startsWith('__ts__') &&
        !n.startsWith('__fe__'),
    );
  const cols = await engine.columns(handle, baseNames);

  // Materialize the mask-selected base rows into a plain ColumnTable.
  const sel: number[] = [];
  for (let i = 0; i < ref.rows; i++) {
    if (mask === null || mask[i] === 1) sel.push(i);
  }
  const columns: Record<string, unknown[]> = {};
  for (const name of baseNames) {
    const src = cols[name];
    const out: unknown[] = new Array(sel.length);
    for (let k = 0; k < sel.length; k++) {
      const v = src[sel[k]];
      out[k] = v === undefined ? null : v;
    }
    columns[name] = out;
  }
  const base: ColumnTable = { columns, length: sel.length };

  const derived = runPrologue(ops, base);

  const result = await refillFigure({
    binding,
    // The mask is already baked into `derived`; the binding's fields/group
    // reference DERIVED column names, served straight from the frame.
    mask: null,
    columns: async (names) => {
      const out: Record<string, ArrayLike<unknown>> = {};
      for (const name of names) {
        const values = derived.columns[name];
        if (values === undefined) {
          throw new Error(`prologue figure: derived frame has no column "${name}"`);
        }
        out[name] = values;
      }
      return out;
    },
  });

  // Metadata counts DERIVED rows (post-reshape) — that is what the figure
  // actually plots: `total` is the derived frame's height, `displayed` the
  // points refill wrote across raw traces.
  return {
    figure: result.figure,
    displayed: result.displayed,
    total: derived.length,
    filterApplied: bound.length > 0,
  };
}

/** Numeric Polars dtypes → AG Grid's numericColumn, matching the dtype set
 *  Polars' `DataType.is_numeric()` covers (ints, uints, floats, decimals). */
const NUMERIC_DTYPE_RE = /^(u?int|float|decimal)/i;

/** `name.replace("_", " ").title()` — the header naming the frozen table
 *  payloads used, kept byte-identical so live and frozen tables agree. */
function titleCaseHeader(name: string): string {
  return name
    .replace(/_/g, ' ')
    .replace(/[A-Za-z]+/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());
}

/** Live equivalent of the server's `render_table_endpoint` body
 *  (dashboards routes.py:2429): filter → sort → slice over the bundled
 *  Parquet, in the exact TableResponse shape the real `renderTable` returns.
 *  Sorting itself is the shared `sortSlice` kernel (depictio-static-core),
 *  which pins the Polars semantics (single sort key, nulls last both
 *  directions, stable, NaN above +inf, code-point string compare). */
export async function renderTableLive(
  dcId: string,
  filters: InteractiveFilter[],
  start: number,
  limit: number,
  sortBy?: string | null,
  sortDir: 'asc' | 'desc' = 'desc',
): Promise<{
  columns: { field: string; headerName: string; type: string }[];
  rows: Record<string, unknown>[];
  total: number;
  sort_by: string | null;
  sort_dir: 'asc' | 'desc';
  sort_disabled: boolean;
  data_version: string | null;
}> {
  const { ref, handle } = await tableFor(dcId);

  // Display columns = the DataRef's schema minus build-time companions
  // (`__code__*` codebook codes, `__ts__*` epoch-µs — companions.py): those
  // exist only for the filter kernels and the live server never serves them.
  const companions = new Set(Object.keys(ref.companions ?? {}));
  const display = (ref.columns ?? []).filter(
    (c) =>
      !companions.has(c.name) &&
      !c.name.startsWith('__code__') &&
      !c.name.startsWith('__ts__'),
  );

  // Endpoint request validation (routes.py:2467-2473): limit clamped 1..500,
  // sort_dir anything but "asc" collapses to the default "desc".
  const s = Math.max(0, Math.floor(start) || 0);
  const l = Math.max(1, Math.min(Math.floor(limit) || 100, 500));
  const dir: 'asc' | 'desc' = sortDir === 'asc' ? 'asc' : 'desc';

  // Default sort pick + unknown-column drop (routes.py:2544-2555): no client
  // sort → first acquisition-timestamp-looking column (realtime "newest
  // first"); a sort key absent from the schema is silently dropped, never an
  // error (stale client caches must not 500).
  let chosen = sortBy ?? null;
  if (!chosen) {
    chosen =
      display.find((c) => {
        const n = c.name.toLowerCase();
        return (
          n.includes('acquisition') &&
          (n.includes('time') || n.includes('date') || n.includes('stamp'))
        );
      })?.name ?? null;
  }
  if (chosen && !display.some((c) => c.name === chosen)) chosen = null;

  // Filters apply BEFORE sorting, exactly like the server threads
  // filter_metadata into the load (routes.py:2612-2621); `total` is the
  // filtered count, independent of the page window (routes.py:2577-2579).
  const bound = toBoundFilters(filters);
  const mask = bound.length ? (await engine.mask(handle, bound)).mask : null;
  const cols = await engine.columns(
    handle,
    display.map((c) => c.name),
  );
  const sort: SortSpec[] = chosen ? [{ column: chosen, desc: dir === 'desc' }] : [];
  const { rows, total } = sortSlice(cols, mask, sort, s, l);

  return {
    columns: display.map((c) => ({
      field: c.name,
      headerName: titleCaseHeader(c.name),
      type: NUMERIC_DTYPE_RE.test(c.dtype) ? 'numericColumn' : 'text',
    })),
    rows,
    total,
    sort_by: chosen,
    sort_dir: dir,
    // A bundled table is always small enough to sort in the browser — the
    // server's table_sort_max_rows guard protects multi-million-row Delta
    // scans, not an inlined Parquet.
    sort_disabled: false,
    // The bundle's data never changes under the grid; a stable version means
    // the infinite row model never purges its block cache mid-scroll.
    data_version: ref.aggregation_hash ?? null,
  };
}

/** MultiSelect options: codebook keys are the server's exact option strings
 *  (sorted str(v), see companions.py) — no decode needed; String columns
 *  compute unique() from the table. */
export async function uniqueValuesLive(dcId: string, columnName: string): Promise<string[]> {
  const ref = dataRefFor(dcId);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${dcId}"`);
  const codebook = ref.codebooks?.[columnName];
  if (codebook) return Object.keys(codebook).sort();
  const { handle } = await tableFor(dcId);
  const vals = await engine.unique(handle, null, columnName);
  return vals.map((v) => String(v));
}

export async function columnRangeLive(
  dcId: string,
  columnName: string,
): Promise<{ min: number | null; max: number | null }> {
  const { handle } = await tableFor(dcId);
  const [min, max] = await engine.minMax(handle, null, columnName);
  return { min, max };
}

/** Specs in the list shape fetchColumnRange's real implementation expects —
 *  built lazily from the DataRef's column list with engine min/max. */
export async function specsLive(dcId: string): Promise<Record<string, unknown>> {
  const ref = dataRefFor(dcId);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${dcId}"`);
  const { handle } = await tableFor(dcId);
  const entries = await Promise.all(
    (ref.columns ?? []).map(async (c) => {
      const [min, max] = await engine.minMax(handle, null, c.name);
      return { name: c.name, type: c.dtype, specs: { min, max } };
    }),
  );
  return entries as unknown as Record<string, unknown>;
}
