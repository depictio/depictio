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
  contactMapProjection,
  contactMapWindow,
  resolveResolutionColumn,
  BREAKDOWN_LAYOUTS,
  bindFilters,
  computeBreakdown,
  followsRegion,
  needsLayoutPayload,
  numericLayoutPayload,
  parseWallClockMicros,
  scopeRegionFilters,
  comparePolars,
  extendFiltersViaLinks,
  limitsOf,
  needsTranslation,
  reduceFrame,
  refillFigure,
  resolveUri,
  computeReferenceRequests,
  parseReferenceRequests,
  roundReference,
  roundSigFigs,
  runPrologue,
  sankeyFromColumns,
  sortSlice,
  translateViaTable,
  type AdvancedVizTailSpec,
  type AggFn,
  type BindingTable,
  type BoundFilter,
  type ContactMapRequest,
  type ColumnTable,
  type DCLinkLike,
  type DataRef,
  type FilterLike,
  type PrologueOp,
  type QueryEngine,
  type ResolveHop,
  type SankeyRequest,
  type SortSpec,
  type TableHandle,
} from 'depictio-static-core';
import type { InteractiveFilter } from '../../../../packages/depictio-react-core/src/api';
import { bundle, familyMetadata } from './bundle';

const engine: QueryEngine = new HyparquetEngine();

/** The one engine every live path shares (its column caches included). */
export function liveEngine(): QueryEngine {
  return engine;
}
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

/** Re-exported for the callers that parse picker bounds themselves. */
export { parseWallClockMicros };

/** filter_expr source text → its `__fe__<sha8>` companion, across every
 *  bundled DataRef (the name is a hash of the text, so one map serves all). */
let feCompanionCache: Map<string, string> | null = null;
export function filterExprCompanions(): Map<string, string> {
  if (feCompanionCache) return feCompanionCache;
  const out = new Map<string, string>();
  for (const ref of Object.values(bundle().data_refs ?? {})) {
    for (const [name, source] of Object.entries(ref.companions ?? {})) {
      if (name.startsWith('__fe__')) out.set(source, name);
    }
  }
  feCompanionCache = out;
  return out;
}

/** React filter payloads → engine BoundFilters — `clean_filter_payload` +
 *  `process_metadata_and_filter` + `add_filter`, ported in
 *  depictio-static-core's `bindFilters` (pinned there against the server's
 *  own functions). The bundle supplies the `__fe__` companions a component's
 *  filter_expr is ANDed through. */
export function toBoundFilters(filters: InteractiveFilter[]): BoundFilter[] {
  return bindFilters(filters as unknown as FilterLike[], {
    filterExprCompanions: filterExprCompanions(),
    onUnsupported: (type) => console.warn(`static bundle: unsupported filter type "${type}" skipped`),
  });
}

/** The `flag` filter for a component's own filter_expr (a card's row
 *  scoping), or null when the bundle carries no companion for it. */
export function filterExprFlag(expr: string | null | undefined): BoundFilter | null {
  if (!expr) return null;
  const column = filterExprCompanions().get(expr);
  return column ? { kind: 'flag', column } : null;
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

/** Server aggregation-name aliases (`_agg_expr`, dashboards routes.py) →
 *  engine AggFn. `range` is derived from minMax; `box_plot_stats` maps
 *  straight through — the kernel resolves it to the same compound object the
 *  server returns, which the card's BoxPlot renderer type-guards on. */
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
    q1: 'q1',
    q3: 'q3',
    percentile: 'percentile',
    skewness: 'skewness',
    kurtosis: 'kurtosis',
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
  secondary_layout?: string | null;
  breakdown_col?: string | null;
  weight?: string | null;
  values?: unknown;
  run_params?: unknown;
  trend_col?: string | null;
  top_n_count?: number | null;
  filter_expr?: string | null;
  follow_region_filter?: boolean;
  config?: Record<string, unknown>;
  [k: string]: unknown;
}

/** `_top_category_expr`: the category of `values` holding the most weight
 *  (summed `weight`, a missing weight counting 0; else the row count). Null
 *  categories never win; ties go to the alphabetically first category (its
 *  text form). `share` returns that weight over the total of every selected
 *  row (null categories included), null when no row has a category or the
 *  total is 0. `top` comes back as text (`_coerce_agg_result`). */
export function topCategory(
  values: ArrayLike<unknown>,
  weight: ArrayLike<unknown> | null,
  mask: Uint8Array | null,
  share: boolean,
): string | number | null {
  const totals = new Map<string, { text: string; w: number }>();
  let total = 0;
  for (let i = 0; i < values.length; i++) {
    if (mask && mask[i] !== 1) continue;
    let w = 1;
    if (weight) {
      const raw = weight[i];
      const n = typeof raw === 'bigint' ? Number(raw) : typeof raw === 'number' ? raw : Number(raw);
      w = raw === null || raw === undefined || Number.isNaN(n) ? 0 : n;
    }
    total += w;
    const v = values[i];
    if (v === null || v === undefined) continue;
    const text = typeof v === 'boolean' ? (v ? 'true' : 'false') : String(v);
    const e = totals.get(text);
    if (e) e.w += w;
    else totals.set(text, { text, w });
  }
  let best: { text: string; w: number } | null = null;
  for (const e of totals.values()) {
    if (!best || e.w > best.w || (e.w === best.w && e.text < best.text)) best = e;
  }
  if (!share) return best ? best.text : null;
  if (!best || !(total > 0)) return null;
  return best.w / total;
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
  const requested = componentIds ? new Set(componentIds) : null;
  // Family-wide: a persistent section draws its owner tab's cards on every tab.
  const cards: CardMeta[] = (familyMetadata() as CardMeta[]).filter(
    (m) =>
      m.component_type === 'card' &&
      m.index &&
      manifest.tiers[m.index]?.tier === 'live' &&
      (!requested || requested.has(String(m.index))),
  );

  // A text tile's live values ride along as cards of their own
  // (`_text_value_cards`: `<text index>::<name>`), on the card path — same
  // filters, links, filter_expr — and are folded back under the tile's index
  // with its `{{param:KEY}}` run constants at the end.
  const texts = (familyMetadata() as CardMeta[]).filter(
    (m) =>
      m.component_type === 'text' &&
      m.index &&
      manifest.tiers[m.index]?.tier !== 'omitted' &&
      (m.values || m.run_params) &&
      (!requested || requested.has(String(m.index))),
  );
  for (const t of texts) {
    for (const [name, spec] of Object.entries((t.values ?? {}) as Record<string, Record<string, unknown>>)) {
      if (!spec || typeof spec !== 'object') continue;
      cards.push({
        index: `${t.index}::${name}`,
        component_type: 'card',
        dc_id: (spec.dc_id as string) ?? null,
        column_name: spec.column as string,
        aggregation: spec.aggregation as string,
        weight: (spec.weight as string) ?? null,
        filter_expr: (spec.filter_expr as string) ?? null,
      });
    }
  }

  const bound = toBoundFilters(filters);
  const values: Record<string, unknown> = {};
  const secondary_values: Record<string, Record<string, unknown>> = {};
  const aggregations: Record<string, string[]> = {};

  // One bound filter set + mask per (dc, region scope, card filter_expr):
  //   - a genome region / residue pick is a place to look, not a subset to
  //     summarise, so a card drops it unless it opts in with
  //     `follow_region_filter` (`scope_region_filters(…, "card")`), BEFORE
  //     link resolution so a region link cannot bring it back;
  //   - the link-resolved synthetics are per TARGET dc;
  //   - a card's own `filter_expr` narrows its rows through the `__fe__`
  //     companion (the server compiles it into the card's frame).
  const maskCache = new Map<string, Promise<Uint8Array | null>>();
  const maskFor = (card: CardMeta, dcId: string) => {
    const follows = followsRegion(card);
    const expr = card.filter_expr ?? null;
    const key = `${dcId} ${follows ? 1 : 0} ${expr ?? ''}`;
    let m = maskCache.get(key);
    if (!m) {
      m = (async () => {
        const scoped = scopeRegionFilters(filters, 'card', card);
        const dcBound = toBoundFilters(await resolveLinkFilters(dcId, scoped));
        const flag = filterExprFlag(expr);
        if (expr && !flag) {
          console.warn(`static bundle: card filter_expr ${JSON.stringify(expr)} has no companion`);
        }
        if (flag) dcBound.push(flag);
        if (dcBound.length === 0) return null;
        const { handle } = await tableFor(dcId);
        return (await engine.mask(handle, dcBound)).mask;
      })();
      maskCache.set(key, m);
    }
    return m;
  };

  const aggOne = async (card: CardMeta, dcId: string, column: string, aggregation: string) => {
    const { handle } = await tableFor(dcId);
    const mask = await maskFor(card, dcId);
    const agg = (aggregation || '').toLowerCase();
    if (agg === 'top' || agg === 'top_share') {
      const names = [column, card.weight].filter((c): c is string => Boolean(c));
      const cols = await engine.columns(handle, names);
      return topCategory(cols[column], card.weight ? cols[card.weight] : null, mask, agg === 'top_share');
    }
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

  // A card's secondary layout (breakdown strip, histogram, threshold, trend,
  // …) is a reduction of the same masked rows as its hero value
  // (`compute_breakdown` / `numeric_layout_payload`, depictio-static-core's
  // cardLayouts) — recomputed here, never the export-time snapshot.
  const layoutPayload = async (card: CardMeta, dcId: string, column: string) => {
    if (!needsLayoutPayload(card)) return null;
    const { ref, handle } = await tableFor(dcId);
    const layout = String(card.secondary_layout || 'vertical');
    const names = [
      column,
      card.breakdown_col,
      card.trend_col,
      ...((card.attrition_cols as unknown[] | undefined) ?? []),
    ].filter((c): c is string => typeof c === 'string' && c.length > 0);
    const schema = new Map(userColumns(ref).map((c) => [c.name, c.dtype]));
    const present = [...new Set(names)].filter((c) => schema.has(c));
    const cols = await engine.columns(handle, present);
    const get = (name: string) =>
      cols[name] ? { values: cols[name], dtype: schema.get(name) ?? '' } : undefined;
    const mask = await maskFor(card, dcId);
    if ((BREAKDOWN_LAYOUTS as readonly string[]).includes(layout)) {
      const by = card.breakdown_col ? String(card.breakdown_col) : '';
      if (!by || !get(by)) return null;
      const payload = computeBreakdown(
        get,
        mask,
        ref.rows,
        column,
        by,
        String(card.aggregation || 'count'),
        Number(card.top_n_count ?? 3),
      );
      return payload ? (['__breakdown__', payload] as const) : null;
    }
    const payload = numericLayoutPayload(get, mask, ref.rows, card, column, layout);
    return payload ? ([`__${layout}__`, payload] as const) : null;
  };

  await Promise.all(
    cards.map(async (card) => {
      const idx = String(card.index);
      const dcId = String(card.dc_id ?? '');
      const column = card.column_name;
      if (!dcId || !column || !card.aggregation) return;
      try {
        values[idx] = await aggOne(card, dcId, column, card.aggregation);
        const secondary = card.aggregations ?? [];
        const sec: Record<string, unknown> = {};
        if (secondary.length) {
          aggregations[idx] = [...secondary];
          const entries = await Promise.all(
            secondary.map(async (agg) => [agg, await aggOne(card, dcId, column, agg)] as const),
          );
          Object.assign(sec, Object.fromEntries(entries));
        }
        try {
          const extra = await layoutPayload(card, dcId, column);
          if (extra) sec[extra[0]] = extra[1];
        } catch (e) {
          console.warn(`static bundle: card ${idx} secondary layout failed`, e);
        }
        // Always written for a live card, so the shim never lets a frozen
        // strip from the export survive under live hero numbers.
        secondary_values[idx] = sec;
      } catch (e) {
        console.error(`static bundle: card ${idx} computation failed`, e);
        values[idx] = null;
      }
    }),
  );

  for (const t of texts) {
    const idx = String(t.index);
    const folded: Record<string, unknown> = {};
    for (const name of Object.keys((t.values ?? {}) as Record<string, unknown>)) {
      const key = `${idx}::${name}`;
      folded[name] = key in values ? values[key] : null;
      delete values[key];
      delete secondary_values[key];
    }
    for (const [key, value] of Object.entries((t.run_params ?? {}) as Record<string, unknown>)) {
      folded[`param:${key}`] = value ?? null;
    }
    values[idx] = folded;
  }

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
  /** `{group_by, sum}`: sum per distinct key tuple AFTER the reduction
   *  (routes.py `_aggregate_frame`), for renderers that only add rows up. */
  aggregate?: { group_by: string[]; sum: string } | null;
  /** `{config field: {column, stat}}`; answered in `reference_stats`, taken
   *  on the filtered rows before any reduction (routes.py `_load_reduced`). */
  referenceStats?: Record<string, { column: string; stat: string }>;
}

/** `_aggregate_frame`: `df.group_by(group_by, maintain_order=True)
 *  .agg(pl.col(sum).sum())` — first-seen key order, a null key is a group of
 *  its own, nulls are skipped by the sum and an all-null group sums to 0. */
export function aggregateRows(
  rows: Record<string, unknown[]>,
  groupBy: string[],
  sumCol: string,
): Record<string, unknown[]> {
  for (const c of [...groupBy, sumCol]) {
    if (!(c in rows)) throw new Error(`aggregate names columns not in the frame: ${c}`);
  }
  const n = (rows[sumCol] ?? []).length;
  const order: string[] = [];
  const groups = new Map<string, { keys: unknown[]; sum: number }>();
  for (let i = 0; i < n; i++) {
    const keys = groupBy.map((c) => rows[c][i] ?? null);
    const key = JSON.stringify(keys.map((k) => (typeof k === 'bigint' ? `${k}n` : k)));
    let g = groups.get(key);
    if (!g) {
      g = { keys, sum: 0 };
      groups.set(key, g);
      order.push(key);
    }
    const raw = rows[sumCol][i];
    const v = typeof raw === 'bigint' ? Number(raw) : raw;
    if (typeof v === 'number') g.sum += v;
  }
  const out: Record<string, unknown[]> = {};
  groupBy.forEach((c, j) => {
    out[c] = order.map((k) => groups.get(k)!.keys[j]);
  });
  out[sumCol] = order.map((k) => groups.get(k)!.sum);
  return out;
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
  /** Only when the request asked for statistics, like the server. */
  reference_stats?: Record<string, number | null>;
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

  // References are taken before `aggregate` sums rows away: on the explicit
  // cap's prefix for a `limitRows` read, else on the whole filtered frame
  // (the reduction never sees them, so a sampled plot keeps an unbiased line).
  const referenceRequests = parseReferenceRequests(req.referenceStats);
  const referenceSource = typeof req.limitRows === 'number' ? rows : data;
  const referenceValues = computeReferenceRequests(referenceSource, referenceRequests);

  // `aggregate` runs after the counts and before the column build, so
  // `total_rows` still says how many rows the table held (routes.py).
  if (req.aggregate && Array.isArray(req.aggregate.group_by) && req.aggregate.sum) {
    rows = aggregateRows(rows, req.aggregate.group_by, req.aggregate.sum);
    rowCount = (rows[req.aggregate.sum] ?? []).length;
  }

  // Serialise only the requested columns that survived projection, in request
  // order, rounding the floats — the server's response-assembly step.
  const present = req.columns.filter((c) => schema.has(c) && c in rows);
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
    ...(Object.keys(referenceRequests).length > 0
      ? {
          reference_stats: Object.fromEntries(
            Object.entries(referenceValues).map(([k, v]) => [k, roundReference(v)]),
          ),
        }
      : {}),
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

// ---- contact_map windows (compute_live) -------------------------------------

/** `ContactMapPayload` as the renderer dispatches it. */
export interface ContactMapLiveRequest extends ContactMapRequest {
  dc_id: string;
  filter_metadata?: InteractiveFilter[];
}

/**
 * `compute_contact_map` (celery_tasks.py) over the bundled Parquet: the
 * dashboard filters (links resolved) are the load's row mask, the projection
 * is the task's, and the rest is `contact_map_window` — ported as
 * static-core's `contactMapWindow` and pinned against the Python function by
 * fixtures/contact-map-expected.json.
 */
export async function contactMapLive(req: ContactMapLiveRequest): Promise<Record<string, unknown>> {
  const startedAt = performance.now();
  const ref = dataRefFor(req.dc_id);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${req.dc_id}"`);
  if (!(req.chrom1_col && req.start1_col && req.chrom2_col && req.start2_col && req.count_col)) {
    throw new Error(
      'compute_contact_map: chrom1_col, start1_col, chrom2_col, start2_col and count_col are required',
    );
  }
  const { handle } = await tableFor(req.dc_id);
  const schemaNames = userColumns(ref).map((c) => c.name);
  const schema = new Set(schemaNames);
  const resolutionCol = resolveResolutionColumn(schemaNames, req.resolution_col);
  const projection = [...new Set(contactMapProjection(req, resolutionCol))].filter((c) => schema.has(c));
  const bound = toBoundFilters(await resolveLinkFilters(req.dc_id, req.filter_metadata ?? []));
  const mask = bound.length ? (await engine.mask(handle, bound)).mask : null;
  const cols = await engine.columns(handle, projection);
  const out = contactMapWindow(cols, ref.rows, mask, req, resolutionCol);
  return { ...out, compute_ms: Math.round(performance.now() - startedAt) };
}

/** `SankeyPayload` (api.ts) minus `wf_id`: there is one workflow in a bundle
 *  and the DC id alone keys the bundled table. */
export interface SankeyLiveRequest extends SankeyRequest {
  dc_id: string;
  filter_metadata?: InteractiveFilter[];
}

/**
 * `compute_sankey` (celery_tasks.py) over the bundled Parquet: the dashboard
 * filters (links resolved) are the load's row mask, the projection is the
 * task's (`step_cols` + `option_cols`, then `value_col`), and the rest is
 * `_sankey_result_from_frame` — ported as static-core's `sankeyFromColumns`
 * and pinned against the Python function by fixtures/sankey-expected.json.
 */
export async function sankeyLive(req: SankeyLiveRequest): Promise<Record<string, unknown>> {
  const startedAt = performance.now();
  const ref = dataRefFor(req.dc_id);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${req.dc_id}"`);
  const stepCols = req.step_cols ?? [];
  // Endpoint request validation (celery_tasks.py): ≥2 steps, no duplicates —
  // duplicate steps would land in the same ambiguous group_by the task rejects.
  if (stepCols.length < 2) {
    throw new Error('compute_sankey: step_cols must have ≥2 columns');
  }
  if (new Set(stepCols).size !== stepCols.length) {
    throw new Error('compute_sankey: step_cols must not contain duplicates');
  }
  const { handle } = await tableFor(req.dc_id);
  // Projection = the task's `project_cols`, schema-guarded: pruning put
  // exactly these columns in the bundle, but a stale bundle must degrade to a
  // readable error inside the compute rather than throw inside the engine.
  const schema = new Set(userColumns(ref).map((c) => c.name));
  const projectCols = [...new Set([...stepCols, ...(req.option_cols ?? [])])];
  if (req.value_col && !projectCols.includes(req.value_col)) projectCols.push(req.value_col);
  const projection = projectCols.filter((c) => schema.has(c));
  const bound = toBoundFilters(await resolveLinkFilters(req.dc_id, req.filter_metadata ?? []));
  const mask = bound.length ? (await engine.mask(handle, bound)).mask : null;
  const cols = await engine.columns(handle, projection);
  const out = sankeyFromColumns(cols, ref.rows, mask, req);
  return { ...out, compute_ms: Math.round(performance.now() - startedAt) };
}

/** The distinct values of `column` among the rows `filters` keep (links
 *  resolved), as strings; `null` when no filter applies. */
export async function keptValues(
  dcId: string,
  column: string,
  filters: InteractiveFilter[],
): Promise<Set<string> | null> {
  const { ref, handle } = await tableFor(dcId);
  const bound = toBoundFilters(await resolveLinkFilters(dcId, filters));
  if (!bound.length) return null;
  const mask = (await engine.mask(handle, bound)).mask;
  const values = (await engine.columns(handle, [column]))[column];
  const keep = new Set<string>();
  for (let i = 0; i < ref.rows; i++) {
    if (mask[i] === 1 && values[i] !== null && values[i] !== undefined) {
      keep.add(String(jsonNumber(values[i])));
    }
  }
  return keep;
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

/** What `fetchDataCollectionPreview` answers for a bundled table: its first
 *  `limit` rows in file order (the server's preview reads the Delta table's
 *  head, unsorted and unfiltered), over the columns the file carries. */
export async function previewLive(
  dcId: string,
  limit: number,
): Promise<{ columns: string[]; rows: Record<string, unknown>[]; total_rows: number; total_columns: number }> {
  const { ref, handle } = await tableFor(dcId);
  const companions = new Set(Object.keys(ref.companions ?? {}));
  const names = (ref.columns ?? [])
    .map((c) => c.name)
    .filter((name) => !companions.has(name) && !name.startsWith('__'));
  const cols = await engine.columns(handle, names);
  const { rows } = sortSlice(cols, null, [], 0, Math.max(1, Math.floor(limit) || 100));
  return {
    columns: names,
    rows: rows.map((row) => {
      const out: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(row)) out[key] = jsonNumber(value);
      return out;
    }),
    total_rows: ref.rows,
    total_columns: names.length,
  };
}
