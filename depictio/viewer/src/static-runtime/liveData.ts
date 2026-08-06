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
 * Every render path starts by resolving cross-DC links for ITS target data
 * collection ({@link resolveLinkFilters}, RFC §8) — a filter set is only
 * complete relative to the collection it is about to mask.
 *
 * Manifests without `data_refs` (the phase-0 fixture) take none of these
 * paths — the apiShim falls back to frozen payloads, so old bundles keep
 * rendering.
 */
import {
  HyparquetEngine,
  applyResolver,
  comparePolars,
  extendFiltersViaLinks,
  limitsOf,
  needsTranslation,
  reduceFrame,
  refillFigure,
  resolveUri,
  roundSigFigs,
  runPrologue,
  sortSlice,
  translateViaTable,
  type AdvancedVizTailSpec,
  type AggFn,
  type BindingTable,
  type BoundFilter,
  type ColumnTable,
  type DCLinkLike,
  type DataRef,
  type PrologueOp,
  type QueryEngine,
  type ResolveHop,
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

/** JSON-serialisable form of one engine cell.
 *
 *  hyparquet decodes Int64/UInt64 as BigInt, which no renderer expects: the
 *  server ships plain JSON numbers, and arithmetic on a BigInt throws
 *  ("Cannot convert a BigInt value to a number") — one such throw in a
 *  renderer's useMemo unmounts the whole app, not just its tile. Widening to
 *  Number matches the wire format; values beyond 2^53 lose precision exactly
 *  as they would in the server's own JSON. */
function jsonNumber(value: unknown): unknown {
  return typeof value === 'bigint' ? Number(value) : value;
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

// ---------------------------------------------------------------------------
// cross-DC links (RFC §8, phase 7)
// ---------------------------------------------------------------------------

/** Polars dtype strings the server treats as date-typed in a link translation
 *  (`schema[filter_column] in [pl.Date, pl.Datetime]`, links routes.py:225):
 *  'Date' and 'Datetime(time_unit=…, time_zone=…)'. */
const DATE_DTYPE_RE = /^date/i;

/**
 * The BoundFilter one hop's translation query runs on the SOURCE table —
 * mirror of the predicate `_translate_filter_values` builds
 * (links routes.py:222–241) before its `SELECT DISTINCT link_col`:
 *
 *   - a 2-element value list on a Date/Datetime column is a BETWEEN, both
 *     bounds inclusive (the server's DateRangePicker special case, parsing the
 *     bounds with '%Y-%m-%d'); `parseWallClockMicros` reads the same strings
 *     into the epoch-µs space the `__ts__` companion lives in.
 *   - everything else is `is_in`.
 *
 * Returns null when the engine would have nothing to read: a `ts_range` needs
 * the `__ts__` companion, and without it the mask kernel's per-filter skip
 * would silently drop the predicate and translate the WHOLE column — an
 * over-match that would widen the filter instead of narrowing it. An unusable
 * hop is the honest answer (the caller returns null → the chain is dropped).
 */
function translationFilter(
  ref: DataRef,
  column: string,
  dtype: string,
  values: unknown[],
): BoundFilter | null {
  if (values.length === 2 && DATE_DTYPE_RE.test(dtype)) {
    const min = parseWallClockMicros(values[0]);
    const max = parseWallClockMicros(values[1]);
    if (min !== undefined && max !== undefined) {
      const hasCompanion = (ref.columns ?? []).some((c) => c.name === `__ts__${column}`);
      return hasCompanion ? { kind: 'ts_range', column, min, max } : null;
    }
  }
  return { kind: 'in', column, values };
}

/**
 * One link hop, resolved offline — the runtime half of depictio-static-core's
 * {@link ResolveHop} contract (the data-touching step the pure graph walk
 * delegates).
 *
 * Tier A — the hop's SOURCE data collection ships in the bundle: run the
 * server's own translation query against the bundled Parquet
 * (`SELECT DISTINCT source_column WHERE filter_col …`, links routes.py:243–256)
 * when the filter column differs from the join column, then apply the pure
 * resolver. A filter or join column absent from the source schema returns null
 * — the server answers those with a 400 (routes.py:196–207), and a null here
 * is the walk's "unusable hop", which claims nothing rather than filtering
 * wrongly.
 *
 * Tier B — the source DC is NOT bundled (producer A, when the source is a
 * link-only collection): the precomputed `manifest.links.tables[link_id]` IS
 * the full answer of that query, but only for the join column it was keyed on
 * — a hop that would need a different column's translation has no table to
 * read and is unusable. The precomputed values already went through the real
 * server resolver at build time, so `applyResolver` must NOT run again.
 */
const resolveHop: ResolveHop = async (link, column, values) => {
  const sourceDcId = String(link.source_dc_id ?? '');
  const linkColumn = String(link.source_column ?? '');
  if (!sourceDcId || !linkColumn) return null;

  const ref = dataRefFor(sourceDcId);
  if (!ref) {
    const table = bundle().links?.tables?.[String(link.id ?? '')];
    if (!table || needsTranslation(column, link)) return null;
    return { resolved_values: translateViaTable(table, values) };
  }

  // The source DC's schema as the SERVER sees it: build-time companions are
  // physical columns of the bundled Parquet but never part of a link's
  // contract (the engine reaches them itself, through `column`).
  const schema = new Map(userColumns(ref).map((c) => [c.name, c.dtype]));
  if (!schema.has(column) || !schema.has(linkColumn)) return null;

  let translated: unknown[] = values;
  if (needsTranslation(column, link)) {
    const filter = translationFilter(ref, column, schema.get(column) ?? '', values);
    if (!filter) return null;
    const { handle } = await tableFor(sourceDcId);
    const { mask } = await engine.mask(handle, [filter]);
    translated = await engine.unique(handle, mask, linkColumn);
  }
  return { resolved_values: applyResolver(link.link_config, translated).resolved };
};

/**
 * Extend a render's filter list with the cross-DC filters the project's links
 * imply for ONE target data collection — the offline equivalent of
 * `_filters_with_links` (dashboards routes.py:1390–1466) wrapping
 * `extend_filters_via_links`.
 *
 * Grouping is strictly by `metadata.dc_id`, like the server: a filter without
 * one (a selection the SPA could not attribute) is left out of the walk
 * entirely — it already binds to every DC by column name, and feeding it in
 * would invent an origin it does not have. The synthetic filters come back in
 * the flattened shape the viewer's `InteractiveFilter` uses (top-level
 * column_name/interactive_component_type plus metadata), and are APPENDED —
 * for this target DC only, which is why every live path resolves its own.
 *
 * Fast path: a bundle with no links (every pre-phase-7 bundle, and every
 * single-DC one) returns the caller's array untouched, so linkless renders pay
 * nothing.
 */
export async function resolveLinkFilters(
  targetDcId: string,
  filters: InteractiveFilter[],
): Promise<InteractiveFilter[]> {
  const configs = (bundle().links?.configs ?? []) as DCLinkLike[];
  if (configs.length === 0 || !targetDcId) return filters;

  const filtersByDc: Record<string, InteractiveFilter[]> = {};
  for (const f of filters ?? []) {
    const dcId = String(f.metadata?.dc_id ?? '');
    if (!dcId) continue;
    (filtersByDc[dcId] ??= []).push(f);
  }
  if (Object.keys(filtersByDc).length === 0) return filters;

  const synthetic = await extendFiltersViaLinks(targetDcId, filtersByDc, configs, resolveHop);
  if (synthetic.length === 0) return filters;
  return [...filters, ...(synthetic as unknown as InteractiveFilter[])];
}

/** Server aggregation-name aliases (`_agg_expr`, dashboards routes.py:1242)
 *  → engine AggFn. Returns undefined for aggregations the engine doesn't cover
 *  (q1/q3); `range` is derived from minMax. `box_plot_stats` maps straight
 *  through — the kernel resolves it to the same compound object the server
 *  returns, which the card's BoxPlot renderer type-guards on. */
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
    box_plot_stats: 'box_plot_stats',
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

  // One bound filter set per dc: the user's filters are global (per-filter
  // column skip is the engine's job, matching apply_runtime_filters), but the
  // link-resolved synthetics are per TARGET dc, so each dc resolves its own.
  const boundCache = new Map<string, Promise<BoundFilter[]>>();
  const boundFor = (dcId: string) => {
    let b = boundCache.get(dcId);
    if (!b) {
      b = resolveLinkFilters(dcId, filters).then(toBoundFilters);
      boundCache.set(dcId, b);
    }
    return b;
  };

  // One mask per dc, over that dc's own bound filters.
  const maskCache = new Map<string, Promise<Uint8Array>>();
  const maskFor = (dcId: string) => {
    let m = maskCache.get(dcId);
    if (!m) {
      m = Promise.all([tableFor(dcId), boundFor(dcId)]).then(([{ handle }, dcBound]) =>
        engine.mask(handle, dcBound).then((r) => r.mask),
      );
      maskCache.set(dcId, m);
    }
    return m;
  };

  const aggOne = async (dcId: string, column: string, aggregation: string) => {
    const { handle } = await tableFor(dcId);
    const mask = (await boundFor(dcId)).length ? await maskFor(dcId) : null;
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
    return jsonNumber(value);
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

  // Reported from the USER's filters, not any dc's link-extended set: the
  // server's own count is of the filter entries the client sent
  // (`bulk_compute_cards`), and a synthetic link filter is not a filter the
  // user set — counting it would make the badge disagree per card.
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
  const bound = toBoundFilters(await resolveLinkFilters(dcId, filters));
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
  const bound = toBoundFilters(await resolveLinkFilters(dcId, filters));
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

/** The DataRef's user-visible columns: its schema minus the build-time
 *  companions (companion-map keys plus `__code__*` codebook codes, `__ts__*`
 *  epoch-µs datetimes, `__fe__*` filter_expr booleans — companions.py). Those
 *  exist only for the filter kernels; the live server's schema never has them,
 *  so neither a projection nor a schema response may mention them. */
export function userColumns(ref: DataRef): { name: string; dtype: string }[] {
  const companions = new Set(Object.keys(ref.companions ?? {}));
  return (ref.columns ?? []).filter(
    (c) =>
      !companions.has(c.name) &&
      !c.name.startsWith('__code__') &&
      !c.name.startsWith('__ts__') &&
      !c.name.startsWith('__fe__'),
  );
}

/** The dtypes the server rounds before serialising: `df.schema[c] in
 *  (pl.Float32, pl.Float64)` (advanced_viz routes.py:838). Ints and decimals
 *  are left alone there and here. */
const FLOAT_DTYPE_RE = /^float(32|64)$/i;

/** Request shape of the real `fetchAdvancedVizData` (api.ts:625–648) minus
 *  `wfId`: there is one workflow in a bundle and the DC id alone keys the
 *  bundled table. */
export interface AdvancedVizLiveRequest {
  dcId: string;
  columns: string[];
  filters?: InteractiveFilter[];
  limitRows?: number;
  fullLoad?: boolean;
  vizKind?: string | null;
  roles?: Record<string, string>;
  tail?: AdvancedVizTailSpec | null;
}

/** `AdvancedVizDataResponse` (api.ts:593–609) with the optional fields the
 *  live path always populates. */
export interface AdvancedVizLiveResponse {
  columns: string[];
  rows: Record<string, unknown[]>;
  row_count: number;
  total_rows: number;
  sampled: boolean;
  sampling: { policy: string; exact: boolean; degraded: boolean };
  filter_applied: boolean;
}

/**
 * Live equivalent of `POST /advanced_viz/data`
 * (advanced_viz_endpoints/routes.py:560–867) over the bundled Parquet.
 *
 * The server does mask + projection + reduction in one lazy scan; here the
 * engine masks and materialises, and depictio-static-core's `reduceFrame` —
 * the port of `_load_reduced` — makes the reduction decision. Everything
 * `reduceFrame`'s doc leaves to the caller happens in this function: the
 * explicit `limit_rows` / `full_load` request shapes (which never reach
 * `_load_reduced`, routes.py:656–666), the projection, and the float
 * rounding.
 *
 * Faithfulness notes, all pinned to the server's own lines:
 *   projection  — requested ∪ filter columns, first occurrence wins, then
 *     intersected with the DC's schema (routes.py:725–762). Filter columns
 *     ride along because the reduction hashes the WHOLE projection
 *     (`_hash_sample`, :289), so dropping them would change which rows a
 *     sample keeps.
 *   response `columns` — NOT the projection: `present = [c for c in columns
 *     if c in df.columns]` (:826) echoes the REQUESTED columns that survived,
 *     in request order, so a filter-only column is projected and hashed but
 *     never serialised. `rows` carries exactly those columns.
 *   rounding    — every Float column to 6 significant figures (:836–842),
 *     after the reduction, so live values are byte-comparable with the
 *     server's.
 */
export async function fetchAdvancedVizDataLive(
  req: AdvancedVizLiveRequest,
): Promise<AdvancedVizLiveResponse> {
  const ref = dataRefFor(req.dcId);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${req.dcId}"`);
  const { handle } = await tableFor(req.dcId);

  // Cross-DC links first: the server resolves them before it projects, and the
  // synthetic filters are part of both steps below.
  const filters = await resolveLinkFilters(req.dcId, req.filters ?? []);

  // Projection: requested columns first, then any column a filter names —
  // deduped first-occurrence, then intersected with the DC's actual schema
  // (the server's `available_cols` guard, which exists because link-resolved
  // filters can name columns this DC doesn't have).
  const schema = new Map(userColumns(ref).map((c) => [c.name, c.dtype]));
  const filterCols = filters
    .map((f) => f.column_name ?? f.metadata?.column_name)
    .filter((c): c is string => Boolean(c));
  const projection = [...new Set([...req.columns, ...filterCols])].filter((c) => schema.has(c));

  // Mask exactly like every other live path (no filters → null mask = all
  // rows), then materialise the projection over the surviving rows: the
  // reduction kernels take plain arrays, not a scan.
  const bound = toBoundFilters(filters);
  const mask = bound.length ? (await engine.mask(handle, bound)).mask : null;
  const cols = await engine.columns(handle, projection);
  const sel: number[] = [];
  for (let i = 0; i < ref.rows; i++) {
    if (mask === null || mask[i] === 1) sel.push(i);
  }
  const data: Record<string, unknown[]> = {};
  for (const name of projection) {
    const src = cols[name];
    const out: unknown[] = new Array(sel.length);
    for (let k = 0; k < sel.length; k++) {
      const v = src[sel[k]];
      out[k] = v === undefined ? null : v;
    }
    data[name] = out;
  }
  // `total_rows` is always the count BEFORE any reduction — the "of M" half of
  // the renderer's badge (routes.py:808–810). Taken from the mask rather than
  // from `reduceFrame` so it stays right even when the projection came back
  // empty (no requested column exists on this DC).
  const total = sel.length;

  let rows: Record<string, unknown[]>;
  let rowCount: number;
  let sampled: boolean;
  let sampling: { policy: string; exact: boolean; degraded: boolean };

  if (typeof req.limitRows === 'number') {
    // Explicit cap (heatmap/upset previews): the server pushes it into the
    // scan, so it is a PREFIX of the filtered frame, never a sample
    // (routes.py:815–826). `exact` is false as soon as the frame reaches the
    // cap — including when it lands exactly on it, which is what
    // `df.height >= limit_rows` says.
    const n = Math.max(0, Math.min(Math.floor(req.limitRows), total));
    rows = {};
    for (const name of projection) rows[name] = data[name].slice(0, n);
    rowCount = n;
    sampled = false;
    sampling = { policy: 'explicit', exact: total < req.limitRows, degraded: false };
  } else if (req.fullLoad) {
    // Load-All. DELIBERATE DEVIATION: the server still caps a full load, at
    // `figure_max_load_rows` (500k) — a transport bound on a Delta scan it has
    // to serialise over HTTP — and therefore reports policy 'explicit' with
    // `exact` false past that ceiling. The bundle's rows are already in the
    // browser, so there is nothing to transport and no reason to truncate:
    // Load-All here is genuinely the whole filtered frame, which is what
    // policy 'full' + `exact: true` means (the same pair the server sends when
    // its reduction bails to the unbounded row loader, routes.py:818–824).
    rows = data;
    rowCount = total;
    sampled = false;
    sampling = { policy: 'full', exact: true, degraded: false };
  } else {
    // Default path: the kind's policy decides (uniform / tail-preserving /
    // none), against the building instance's ceilings pinned into the
    // manifest.
    const reduced = reduceFrame({
      columns: projection,
      data,
      vizKind: req.vizKind,
      roles: req.roles,
      tail: req.tail,
      limits: limitsOf(bundle()),
    });
    rows = reduced.rows;
    rowCount = reduced.row_count;
    sampled = reduced.sampled;
    sampling = reduced.sampling;
  }

  // Serialise only the requested columns that survived projection, in request
  // order, rounding the floats — the server's response-assembly step.
  const present = req.columns.filter((c) => schema.has(c));
  const payload: Record<string, unknown[]> = {};
  for (const name of present) {
    const values = rows[name] ?? [];
    payload[name] = FLOAT_DTYPE_RE.test(schema.get(name) ?? '')
      ? values.map(roundSigFigs)
      : values.map(jsonNumber);
  }

  return {
    columns: present,
    rows: payload,
    row_count: rowCount,
    total_rows: total,
    sampled,
    sampling,
    // `bound`, not `req.filters`: an interactive component sitting at its empty
    // value contributes a filter entry that selects nothing, and the other
    // live paths (table/figure) already report those as "no filter applied".
    // The server counts filter *entries* (`bool(filter_metadata)`, :854) — the
    // two agree for every payload the viewer actually sends.
    filter_applied: bound.length > 0,
  };
}

/** Request shape of the real `dispatchCoverageTrack` payload
 *  (`CoverageTrackPayload`, api.ts:1031–1045) minus `wf_id`: there is one
 *  workflow in a bundle and the DC id alone keys the bundled table. */
export interface CoverageTrackLiveRequest {
  dc_id: string;
  chromosome_col: string;
  position_col: string;
  value_col: string;
  end_col?: string | null;
  sample_col?: string | null;
  category_col?: string | null;
  chromosomes_filter?: string[] | null;
  samples_filter?: string[] | null;
  smoothing_window?: number;
  max_rows?: number | null;
  filter_metadata?: InteractiveFilter[];
}

/** `CoverageTrackResult` (api.ts:1047–1068), every field the renderer reads. */
export interface CoverageTrackLiveResult {
  rows: Record<string, unknown[]>;
  columns: {
    chromosome: string;
    position: string;
    value: string;
    end?: string | null;
    sample?: string | null;
    category?: string | null;
  };
  summary: {
    row_count: number;
    chromosomes: string[];
    samples: string[];
    n_samples: number;
    mean_value: number | null;
    max_value: number | null;
  };
  row_count: number;
  compute_ms: number;
}

/** `int(payload.get("max_rows") or 200_000)` — the task's own ceiling; the
 *  renderer never sends one (CoverageTrackRenderer.tsx:116–129). */
const COVERAGE_MAX_ROWS = 200_000;

/**
 * Live equivalent of the `compute_coverage_track` Celery task
 * (celery_tasks.py:1340–1495) over the bundled Parquet.
 *
 * Unlike its four siblings in `CELERY_VIZ_KINDS`, this task is not a compute
 * the browser has no answer for: it projects six bound columns, masks rows on
 * two whitelists, sorts, takes a rolling mean partitioned by (chromosome,
 * sample) and decimates. Every step is row-wise or partitioned by columns a
 * dashboard filter itself masks on, so the filter commutes with the whole
 * chain — which is why the component ships its DATA rather than a frozen
 * payload and this function replays the task at every filter state.
 *
 * Faithfulness notes, pinned to the task's own lines:
 *   whitelists  — applied AFTER the dashboard filters, and the summaries the
 *     MultiSelects read are computed from the post-whitelist frame, so the
 *     option lists narrow with the selection exactly as they do live (:1418).
 *   sort        — `df.sort([sample, chromosome, position])`, whose Polars
 *     defaults are nulls FIRST (unlike the table path's `nulls_last=True`)
 *     (:1430). Ties keep input order: `maintain_order` is not set, so the
 *     server's tie order is unspecified and a stable one cannot disagree.
 *   rolling mean — trailing window of `smoothing_window` rows within each
 *     (chromosome, sample) group in the SORTED order, `min_periods=1`. Nulls
 *     occupy a slot but are excluded from both numerator and denominator
 *     (verified on Polars 1.42.1), and a window with no non-null value yields
 *     null (:1435).
 *   decimation  — every `floor(height / max_rows)`-th row of the sorted frame,
 *     which is what `with_row_index` + modulo does (:1444).
 *
 * BigInt: genomic positions are Int64, which hyparquet decodes as BigInt — so
 * every value that reaches arithmetic (the sort comparator, the rolling mean,
 * the summary reductions) goes through {@link jsonNumber} first.
 */
export async function coverageTrackLive(
  req: CoverageTrackLiveRequest,
): Promise<CoverageTrackLiveResult> {
  const startedAt = performance.now();
  const ref = dataRefFor(req.dc_id);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${req.dc_id}"`);
  const { handle } = await tableFor(req.dc_id);

  const chromCol = req.chromosome_col;
  const posCol = req.position_col;
  const valCol = req.value_col;
  const endCol = req.end_col || null;
  const sampleCol = req.sample_col || null;
  const catCol = req.category_col || null;
  if (!chromCol || !posCol || !valCol) {
    throw new Error('coverage track: chromosome_col, position_col, value_col are required');
  }

  // Projection = the task's `project_cols` (:1400), schema-guarded: pruning
  // put exactly these columns in the bundle, but a stale bundle must degrade
  // to a missing series rather than throw inside the engine.
  const schema = new Set(userColumns(ref).map((c) => c.name));
  const projection = [...new Set([chromCol, posCol, valCol, endCol, sampleCol, catCol])].filter(
    (c): c is string => Boolean(c) && schema.has(c as string),
  );

  // The dashboard filters are the task's `metadata=filter_metadata` load
  // argument; cross-DC links resolve first, like every other live path.
  const bound = toBoundFilters(await resolveLinkFilters(req.dc_id, req.filter_metadata ?? []));
  const mask = bound.length ? (await engine.mask(handle, bound)).mask : null;
  const cols = await engine.columns(handle, projection);

  // Per-setting whitelists on top of the mask (:1418–1421). Compared as
  // strings: the option lists the MultiSelects feed back are this function's
  // own `summary`, which the wire type declares as `string[]`.
  const chromWhitelist = req.chromosomes_filter?.length ? new Set(req.chromosomes_filter) : null;
  const sampleWhitelist =
    sampleCol && req.samples_filter?.length ? new Set(req.samples_filter) : null;
  const chromValues = cols[chromCol];
  const sampleValues = sampleCol ? cols[sampleCol] : undefined;
  let sel: number[] = [];
  for (let i = 0; i < ref.rows; i++) {
    if (mask !== null && mask[i] !== 1) continue;
    if (chromWhitelist && !chromWhitelist.has(String(chromValues?.[i]))) continue;
    if (sampleWhitelist && !sampleWhitelist.has(String(sampleValues?.[i]))) continue;
    sel.push(i);
  }

  // Universe summaries from the post-filter frame, so the MultiSelects reflect
  // what is actually showing (:1423). `sorted()` on a Python str list is
  // code-point order — `comparePolars`' string branch. Nulls are skipped: the
  // server's `sorted()` would raise on a mixed None/str list, and a crash is
  // not a behaviour worth mirroring.
  const universe = (values: ArrayLike<unknown> | undefined): string[] => {
    if (!values) return [];
    const seen = new Set<string>();
    for (const i of sel) {
      const v = values[i];
      if (v === null || v === undefined) continue;
      seen.add(String(v));
    }
    return [...seen].sort(comparePolars);
  };
  const chromosomes = universe(chromValues);
  const samples = universe(sampleValues);

  // Sort keys (:1430), schema-guarded the same way the projection is.
  const sortKeys = (sampleCol ? [sampleCol, chromCol, posCol] : [chromCol, posCol]).filter((c) =>
    projection.includes(c),
  );
  const sortValues = sortKeys.map((c) => cols[c]);
  sel.sort((a, b) => {
    for (const values of sortValues) {
      const va = jsonNumber(values[a] ?? null);
      const vb = jsonNumber(values[b] ?? null);
      // Nulls FIRST in both directions: `df.sort(...)` leaves `nulls_last` at
      // its Polars default of False.
      if (va === null || vb === null) {
        if (va === null && vb === null) continue;
        return va === null ? -1 : 1;
      }
      const c = comparePolars(va, vb);
      if (c !== 0) return c;
    }
    return a - b;
  });

  // Rolling mean over the sorted order, partitioned by (chromosome, sample)
  // (:1435). Written as a per-group trailing window with a running sum rather
  // than assuming the groups came out contiguous — they do for these sort
  // keys, but the grouping is a separate contract from the ordering.
  const window = Math.max(0, Math.min(200, Math.floor(req.smoothing_window || 0)));
  const rawValues = cols[valCol];
  let smoothed: (number | null)[] | null = null;
  if (window > 1 && rawValues) {
    const groups = new Map<string, { queue: (number | null)[]; sum: number; n: number }>();
    smoothed = new Array(sel.length);
    for (let k = 0; k < sel.length; k++) {
      const i = sel[k];
      const key = `${String(chromValues?.[i])} ${sampleCol ? String(sampleValues?.[i]) : ''}`;
      let g = groups.get(key);
      if (!g) {
        g = { queue: [], sum: 0, n: 0 };
        groups.set(key, g);
      }
      const raw = jsonNumber(rawValues[i]);
      const v = typeof raw === 'number' ? raw : null;
      g.queue.push(v);
      if (v !== null) {
        g.sum += v;
        g.n += 1;
      }
      if (g.queue.length > window) {
        const gone = g.queue.shift()!;
        if (gone !== null) {
          g.sum -= gone;
          g.n -= 1;
        }
      }
      smoothed[k] = g.n > 0 ? g.sum / g.n : null;
    }
  }

  // Last-ditch decimation for runaway DCs (:1444): every Nth row of the
  // sorted frame, which keeps each track continuous.
  const maxRows = Math.floor(req.max_rows || COVERAGE_MAX_ROWS);
  if (sel.length > maxRows) {
    const keepEvery = Math.max(1, Math.floor(sel.length / maxRows));
    const kept: number[] = [];
    const keptSmoothed: (number | null)[] = [];
    for (let k = 0; k < sel.length; k++) {
      if (k % keepEvery !== 0) continue;
      kept.push(sel[k]);
      if (smoothed) keptSmoothed.push(smoothed[k]);
    }
    sel = kept;
    if (smoothed) smoothed = keptSmoothed;
  }

  // Column-oriented output in the task's own key order, deduplicated (:1450).
  const rows: Record<string, unknown[]> = {};
  for (const name of [chromCol, posCol, valCol, endCol, sampleCol, catCol]) {
    if (!name || name in rows || !projection.includes(name)) continue;
    if (name === valCol && smoothed) {
      rows[name] = smoothed;
      continue;
    }
    const src = cols[name];
    rows[name] = sel.map((i) => jsonNumber(src[i] ?? null));
  }

  // `Series.cast(Float64).mean()/.max()` over the final frame, nulls ignored
  // (:1455). NaN is left to propagate through the mean exactly as Polars does.
  const finalValues = (rows[valCol] ?? []) as (number | null)[];
  let sum = 0;
  let n = 0;
  let max: number | null = null;
  for (const v of finalValues) {
    if (typeof v !== 'number') continue;
    sum += v;
    n += 1;
    if (max === null || v > max) max = v;
  }

  return {
    rows,
    columns: {
      chromosome: chromCol,
      position: posCol,
      value: valCol,
      end: endCol,
      sample: sampleCol,
      category: catCol,
    },
    summary: {
      row_count: sel.length,
      chromosomes,
      samples,
      n_samples: samples.length,
      mean_value: n > 0 ? sum / n : null,
      max_value: max,
    },
    row_count: sel.length,
    compute_ms: Math.round(performance.now() - startedAt),
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
  const bound = toBoundFilters(await resolveLinkFilters(dcId, filters));
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
    rows: rows.map((row) => {
      const out: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(row)) out[key] = jsonNumber(value);
      return out;
    }),
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
  return { min: jsonNumber(min) as number | null, max: jsonNumber(max) as number | null };
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
      return { name: c.name, type: c.dtype, specs: { min: jsonNumber(min), max: jsonNumber(max) } };
    }),
  );
  return entries as unknown as Record<string, unknown>;
}
