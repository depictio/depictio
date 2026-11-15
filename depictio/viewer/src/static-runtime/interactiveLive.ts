/**
 * Offline equivalents of the interactive-component endpoints the static App
 * calls besides the option list itself (serverless audit §3 item 6):
 *
 *   fetchUniqueValues(dc, col, filterExpr, orderBy) — `/deltatables/unique_values`
 *   fetchFunnelValues                — `POST /dashboards/funnel_values`
 *   fetchRankedValues                — `/deltatables/ranked_values` (`rank_values`)
 *   fetchRowValues                   — `/deltatables/row_values` (`row_values`)
 *   fetchTextFilterMatches           — `POST /dashboards/text_filter_matches`
 *   fetchResolvedGroups              — `POST /dashboards/resolve_groups`
 *
 * Each reads the bundled Parquet through the shared engine and follows the
 * server function line for line (cited per function). A component's own
 * `filter_expr` is the `__fe__` companion the producer evaluated.
 */
import {
  orderValues,
  scopeRegionFilters,
  textFilterPattern,
  type BoundFilter,
} from 'depictio-static-core';

import type {
  FunnelStageColumn,
  FunnelValuesResponse,
  InteractiveFilter,
  ResolvedGroupsResult,
  TextFilterMatchesResult,
} from '../../../../packages/depictio-react-core/src/api';

import { bundle, familyMetadata } from './bundle';
import {
  dataRefFor,
  filterExprFlag,
  liveEngine,
  resolveLinkFilters,
  tableFor,
  toBoundFilters,
  userColumns,
} from './liveData';

const FUNNEL_MAX_TARGETS = 32;
const FUNNEL_MAX_VALUES = 1000;
const FUNNEL_MAX_STAGES = 12;
const FILTER_OPTIONS_LIMIT = 1000;
const TEXT_MATCHES_LIMIT = 100;
const MAX_VALUES_PER_GROUP = 50_000;

/** The column's cells as the server's `str(v)` renders them (null kept).
 *  A typed categorical column reads its codebook keys — Python-produced
 *  strings — through the `__code__` companion, so `3.0` stays `"3.0"`. */
async function textCells(dcId: string, column: string): Promise<(string | null)[]> {
  const { ref, handle } = await tableFor(dcId);
  const codebook = ref.codebooks?.[column];
  const engine = liveEngine();
  if (codebook && (ref.columns ?? []).some((c) => c.name === `__code__${column}`)) {
    const byCode = new Map(Object.entries(codebook).map(([k, code]) => [code, k]));
    const codes = (await engine.columns(handle, [`__code__${column}`]))[`__code__${column}`];
    return Array.from({ length: ref.rows }, (_, i) => {
      const c = codes[i];
      return c === null || c === undefined ? null : (byCode.get(Number(c)) ?? null);
    });
  }
  const values = (await engine.columns(handle, [column]))[column];
  return Array.from({ length: ref.rows }, (_, i) => {
    const v = values[i];
    if (v === null || v === undefined) return null;
    if (typeof v === 'boolean') return v ? 'True' : 'False';
    if (v instanceof Date) return v.toISOString();
    return String(v);
  });
}

async function maskWith(dcId: string, bound: BoundFilter[]): Promise<Uint8Array | null> {
  if (bound.length === 0) return null;
  const { handle } = await tableFor(dcId);
  return (await liveEngine().mask(handle, bound)).mask;
}

/** Distinct non-null strings of a column under a mask, as `sorted({str(v)})`. */
async function distinctUnder(dcId: string, column: string, mask: Uint8Array | null): Promise<string[]> {
  const cells = await textCells(dcId, column);
  const seen = new Set<string>();
  for (let i = 0; i < cells.length; i++) {
    if (mask && mask[i] !== 1) continue;
    const v = cells[i];
    if (v !== null) seen.add(v);
  }
  return [...seen].sort();
}

function flagFor(filterExpr: string | null | undefined): BoundFilter[] {
  if (!filterExpr) return [];
  const flag = filterExprFlag(filterExpr);
  if (!flag) console.warn(`static bundle: filter_expr ${JSON.stringify(filterExpr)} has no companion`);
  return flag ? [flag] : [];
}

/** `get_unique_values`: the component's filter_expr first, then an
 *  `order_by` companion column (each value keyed by its smallest), then
 *  `order_values`. */
export async function uniqueValuesLive(
  dcId: string,
  column: string,
  filterExpr?: string | null,
  orderBy?: string | null,
): Promise<string[]> {
  const ref = dataRefFor(dcId);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${dcId}"`);
  const mask = await maskWith(dcId, flagFor(filterExpr));
  if (orderBy && orderBy !== column && userColumns(ref).some((c) => c.name === orderBy)) {
    const cells = await textCells(dcId, column);
    const { handle } = await tableFor(dcId);
    const keysCol = (await liveEngine().columns(handle, [orderBy]))[orderBy];
    const keys = new Map<string, unknown>();
    const less = (a: unknown, b: unknown) => {
      const x = typeof a === 'bigint' ? Number(a) : a;
      const y = typeof b === 'bigint' ? Number(b) : b;
      return (x as number | string) < (y as number | string);
    };
    for (let i = 0; i < cells.length; i++) {
      if (mask && mask[i] !== 1) continue;
      const v = cells[i];
      if (v === null) continue;
      const k = keysCol[i];
      if (!keys.has(v)) keys.set(v, k ?? null);
      else if (k !== null && k !== undefined && (keys.get(v) == null || less(k, keys.get(v)))) keys.set(v, k);
    }
    const values = [...keys.keys()].slice(0, FILTER_OPTIONS_LIMIT);
    const stringKeys = new Map<string, unknown>();
    for (const [v, k] of keys) {
      stringKeys.set(v, typeof k === 'bigint' ? Number(k) : k);
    }
    return orderValues(values, stringKeys);
  }
  const values = (await distinctUnder(dcId, column, mask)).slice(0, FILTER_OPTIONS_LIMIT);
  return orderValues(values);
}

// ---------------------------------------------------------------------------
// funnel (`funnel_values_endpoint`)
// ---------------------------------------------------------------------------

/** `_funnel_filter_is_active`: a reset range control ([null, null]) is not. */
function funnelActive(f: InteractiveFilter): boolean {
  const v = f.value as unknown;
  if (v === null || v === undefined || v === '') return false;
  if (Array.isArray(v)) return v.some((x) => x !== null && x !== undefined);
  return true;
}

/** Filters a load on `dcId` applies: the link-extended set narrowed to the
 *  entries addressed to that DC, as `_funnel_target_values` /
 *  `_funnel_stage_counts` do before `_build_filter_metadata`. */
async function dcScopedBound(dcId: string, filters: InteractiveFilter[]): Promise<BoundFilter[]> {
  const merged = await resolveLinkFilters(dcId, filters);
  const own = merged.filter((f) => String(f.metadata?.dc_id ?? '') === dcId);
  return toBoundFilters(own);
}

export async function funnelValuesLive(
  filters: InteractiveFilter[],
  targetIndexes: string[],
  includeStages: boolean,
  stageColumn?: FunnelStageColumn | null,
): Promise<FunnelValuesResponse> {
  const active = (filters ?? []).filter(funnelActive);
  const index = new Map<string, Record<string, unknown>>();
  for (const m of familyMetadata()) {
    const i = String(m.index ?? '');
    if (i && !index.has(i)) index.set(i, m);
  }

  const targets: FunnelValuesResponse['targets'] = {};
  for (const idx of targetIndexes.slice(0, FUNNEL_MAX_TARGETS).map(String)) {
    const meta = index.get(idx);
    if (!meta || meta.component_type !== 'interactive') {
      targets[idx] = { status: 'unsupported' } as never;
      continue;
    }
    const dcId = String(meta.dc_id ?? '');
    const column = String(meta.column_name ?? '');
    if (!dcId || !column || !dataRefFor(dcId)) {
      targets[idx] = { status: 'unsupported' } as never;
      continue;
    }
    const remaining = scopeRegionFilters(
      active.filter((f) => String(f.index ?? '') !== idx),
      'interactive',
      meta,
    );
    try {
      const bound = await dcScopedBound(dcId, remaining);
      if (bound.length === 0) {
        targets[idx] = { status: 'unrestricted', column, dc_id: dcId } as never;
        continue;
      }
      const values = await distinctUnder(dcId, column, await maskWith(dcId, bound));
      targets[idx] = {
        status: 'ok',
        column,
        dc_id: dcId,
        values: values.slice(0, FUNNEL_MAX_VALUES),
        truncated: values.length > FUNNEL_MAX_VALUES,
      } as never;
    } catch (e) {
      console.warn(`static bundle: funnel values failed for ${dcId}:${column}`, e);
      targets[idx] = { status: 'error', column, dc_id: dcId } as never;
    }
  }

  let stages: FunnelValuesResponse['stages'] = null;
  let initial: Record<string, number | null> | null = null;
  const extra: Partial<FunnelValuesResponse> = {};
  if (stageColumn !== undefined && stageColumn !== null) {
    extra.stage_column_status = 'unsupported';
    extra.stage_column = null;
    extra.initial_values = null;
    extra.stage_dcs = [];
  }
  if (includeStages) {
    const doc = bundle().dashboard.doc as { stored_metadata?: Record<string, unknown>[] };
    const dataTypes = new Set(['figure', 'table', 'map', 'image', 'card', 'interactive']);
    const stageDcs: string[] = [];
    for (const m of doc.stored_metadata ?? []) {
      const dc = String(m.dc_id ?? '');
      if (!dc || stageDcs.includes(dc) || !dataTypes.has(String(m.component_type))) continue;
      if (m.component_type === 'multiqc') continue;
      stageDcs.push(dc);
    }
    const countStages = async (dcs: string[], col: string | null) => {
      const rows = async (dc: string, cumulative: InteractiveFilter[]) => {
        if (!dataRefFor(dc)) return { rows: null as number | null, values: null };
        const mask = await maskWith(dc, await dcScopedBound(dc, cumulative));
        const n = mask ? mask.reduce((a, b) => a + b, 0) : (dataRefFor(dc)?.rows ?? 0);
        let values = null;
        if (col) {
          const distinct = await distinctUnder(dc, col, mask);
          values = {
            count: distinct.length,
            values: distinct.slice(0, FUNNEL_MAX_VALUES),
            truncated: distinct.length > FUNNEL_MAX_VALUES,
          };
        }
        return { rows: n, values };
      };
      const init: Record<string, number | null> = {};
      let initValues = null;
      for (const dc of dcs) {
        const r = await rows(dc, []);
        init[dc] = r.rows;
        if (col) initValues = r.values;
      }
      const out = [];
      for (let k = 0; k < Math.min(active.length, FUNNEL_MAX_STAGES); k++) {
        const f = active[k];
        const cumulative = active.slice(0, k + 1);
        const meta = index.get(String(f.index ?? '')) ?? {};
        const rowsByDc: Record<string, number | null> = {};
        let stageValues = null;
        for (const dc of dcs) {
          const r = await rows(dc, cumulative);
          rowsByDc[dc] = r.rows;
          if (col) stageValues = r.values;
        }
        out.push({
          index: f.index,
          label: (meta.title as string) || (meta.column_name as string) || f.column_name,
          column_name: f.column_name || (meta.column_name as string),
          dc_id: String(meta.dc_id ?? f.metadata?.dc_id ?? ''),
          value: f.value,
          rows_by_dc: rowsByDc,
          ...(col ? { values: stageValues } : {}),
        });
      }
      return { init, out, initValues };
    };
    let counted: Awaited<ReturnType<typeof countStages>> | null = null;
    if (stageColumn) {
      extra.stage_dcs = stageDcs;
      const dc = String(stageColumn.dc_id ?? '');
      const col = stageColumn.column_name;
      const ref = dataRefFor(dc);
      if (stageDcs.includes(dc) && col && ref && userColumns(ref).some((c) => c.name === col)) {
        counted = await countStages([dc], col);
        extra.stage_column_status = 'ok';
        extra.stage_column = { dc_id: dc, column_name: col };
        extra.initial_values = counted.initValues as never;
      }
    }
    counted ??= await countStages(stageDcs, null);
    initial = counted.init;
    stages = counted.out as never;
  }

  return {
    targets,
    stages,
    initial_rows_by_dc: initial,
    dc_labels: {},
    filter_count: active.length,
    ...extra,
  };
}

// ---------------------------------------------------------------------------
// always_selected defaults and scope banners
// ---------------------------------------------------------------------------

function cmpNative(a: unknown, b: unknown): number {
  const x = typeof a === 'bigint' ? Number(a) : a;
  const y = typeof b === 'bigint' ? Number(b) : b;
  if (typeof x === 'number' && typeof y === 'number') return x - y;
  const sx = String(x);
  const sy = String(y);
  return sx < sy ? -1 : sx > sy ? 1 : 0;
}

/** `rank_values`: distinct non-null values of `column`, ranked by the largest
 *  `by` each carries; null ranks last; ties on the value itself. */
export async function rankedValuesLive(
  dcId: string,
  column: string,
  by: string,
  order: 'asc' | 'desc' = 'desc',
  limit = 1000,
): Promise<string[]> {
  const ref = dataRefFor(dcId);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${dcId}"`);
  for (const name of [column, by]) {
    if (!userColumns(ref).some((c) => c.name === name)) {
      throw new Error(`Column '${name}' not found in data collection ${dcId}.`);
    }
  }
  const { handle } = await tableFor(dcId);
  const cols = await liveEngine().columns(handle, [column, by]);
  const text = await textCells(dcId, column);
  const groups = new Map<string, { raw: unknown; rank: unknown }>();
  for (let i = 0; i < ref.rows; i++) {
    const raw = cols[column][i];
    if (raw === null || raw === undefined) continue;
    const key = text[i] ?? String(raw);
    const r = cols[by][i];
    const g = groups.get(key);
    const rank = r === undefined || (typeof r === 'number' && Number.isNaN(r)) ? null : r;
    if (!g) groups.set(key, { raw, rank });
    else if (rank !== null && (g.rank === null || cmpNative(rank, g.rank) > 0)) g.rank = rank;
  }
  const desc = order === 'desc';
  return [...groups.entries()]
    .sort(([, a], [, b]) => {
      if (a.rank === null || b.rank === null) {
        if (a.rank === null && b.rank !== null) return 1;
        if (b.rank === null && a.rank !== null) return -1;
      } else {
        const c = cmpNative(a.rank, b.rank);
        if (c !== 0) return desc ? -c : c;
      }
      return cmpNative(a.raw, b.raw);
    })
    .slice(0, limit)
    .map(([key]) => key);
}

function jsonSafe(v: unknown): unknown {
  if (typeof v === 'bigint') return Number(v);
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (v instanceof Date) return v.toISOString();
  return v ?? null;
}

/** `row_values`: the `columns` of the first row whose `column` (as text)
 *  equals `value`, after the component's filter_expr; null when none. */
export async function rowValuesLive(
  dcId: string,
  column: string,
  value: string,
  columns: readonly string[],
  filterExpr?: string | null,
): Promise<Record<string, unknown> | null> {
  const ref = dataRefFor(dcId);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${dcId}"`);
  const wanted = [...new Set(columns)];
  for (const name of [column, ...wanted]) {
    if (!userColumns(ref).some((c) => c.name === name)) {
      throw new Error(`Column '${name}' not found in data collection ${dcId}.`);
    }
  }
  const mask = await maskWith(dcId, flagFor(filterExpr));
  const text = await textCells(dcId, column);
  const { handle } = await tableFor(dcId);
  const cols = await liveEngine().columns(handle, wanted);
  for (let i = 0; i < text.length; i++) {
    if (mask && mask[i] !== 1) continue;
    if (text[i] !== value) continue;
    return Object.fromEntries(wanted.map((c) => [c, jsonSafe(cols[c][i])]));
  }
  return null;
}

/** `_text_filter_matches`: the column's distinct values (its filter_expr
 *  applied, no other filter) and the ones the TextInput pattern keeps, with
 *  the filter's own predicate (`text_filter_pattern`). */
export async function textFilterMatchesLive(request: {
  dc_id: string;
  column: string;
  value: string;
  case_sensitive?: boolean;
  match_mode?: string;
  filter_expr?: string | null;
  limit?: number;
}): Promise<TextFilterMatchesResult> {
  const { dc_id: dcId, column } = request;
  const ref = dataRefFor(dcId);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${dcId}"`);
  if (!userColumns(ref).some((c) => c.name === column)) {
    throw new Error(`Column '${column}' not found in data collection ${dcId}.`);
  }
  const limit =
    typeof request.limit === 'number' && Number.isInteger(request.limit)
      ? Math.min(Math.max(request.limit, 1), FILTER_OPTIONS_LIMIT)
      : TEXT_MATCHES_LIMIT;
  const distinct = await distinctUnder(dcId, column, await maskWith(dcId, flagFor(request.filter_expr)));
  const compiled = textFilterPattern(request.value, request.case_sensitive, request.match_mode);
  let matching = distinct;
  if (compiled) {
    const re = compiled.literal ? null : new RegExp(compiled.pattern, compiled.flags);
    matching = distinct.filter((v) => (re ? re.test(v) : v.includes(compiled.pattern)));
  }
  const text = request.value === null || request.value === undefined ? '' : String(request.value).trim();
  const literal = (request.match_mode ?? 'regex').toLowerCase() === 'contains';
  let invalid = text.length > 512;
  if (!invalid && !literal && text) {
    try {
      new RegExp(text);
    } catch {
      invalid = true;
    }
  }
  const values = matching.slice(0, limit);
  return {
    column,
    total: distinct.length,
    matching: matching.length,
    values,
    truncated: matching.length > values.length,
    invalid,
  };
}

// ---------------------------------------------------------------------------
// selection groups (`resolve_group_defs_for_dc`)
// ---------------------------------------------------------------------------

type GroupDef = { name: string; column_name: string; values: string[]; color: string; dc_id?: string };

/** One group pointed at `dcId`'s column — kept when the column is there,
 *  translated through the bundled links when it was captured on another
 *  collection (the shortest route, as `resolve_values_via_links`). */
export async function resolvedGroupsLive(dcId: string, groups: GroupDef[]): Promise<ResolvedGroupsResult> {
  const ref = dataRefFor(dcId);
  const available = ref ? new Set(userColumns(ref).map((c) => c.name)) : null;
  const resolved: GroupDef[] = [];
  const status: ResolvedGroupsResult['status'] = [];
  for (const g of groups ?? []) {
    const origin = String(g.dc_id ?? '');
    const verdict = (code: string, column: string = g.column_name, matched = 0) => ({
      name: g.name,
      status: code,
      applied: code === 'applied' || code === 'linked' || code === 'unknown',
      column_name: column,
      source_dc_id: origin,
      source_column: g.column_name,
      matched_values: matched,
    });
    if (available === null) {
      resolved.push(g);
      status.push(verdict('unknown', g.column_name, g.values.length));
      continue;
    }
    if (available.has(g.column_name)) {
      resolved.push(g);
      status.push(verdict('applied', g.column_name, g.values.length));
      continue;
    }
    if (!origin || origin === dcId) {
      status.push(verdict('column_absent'));
      continue;
    }
    const probe: InteractiveFilter = {
      index: `group:${g.name}`,
      value: g.values,
      column_name: g.column_name,
      interactive_component_type: 'MultiSelect',
      metadata: { dc_id: origin, column_name: g.column_name, interactive_component_type: 'MultiSelect' },
    } as unknown as InteractiveFilter;
    let synthetic: InteractiveFilter[];
    try {
      synthetic = (await resolveLinkFilters(dcId, [probe])).slice(1);
    } catch {
      status.push(verdict('link_failed'));
      continue;
    }
    if (synthetic.length === 0) {
      status.push(verdict('no_link'));
      continue;
    }
    const hops = (f: InteractiveFilter) => String(f.index ?? '').split('_').length;
    const best = [...synthetic].sort((a, b) => hops(a) - hops(b))[0];
    const target = String(best.column_name ?? best.metadata?.column_name ?? '');
    const values = (Array.isArray(best.value) ? best.value : []) as unknown[];
    if (values.length === 0) {
      status.push(verdict('link_no_match', target));
      continue;
    }
    if (!available.has(target)) {
      status.push(verdict('column_absent', target));
      continue;
    }
    const kept = values.slice(0, MAX_VALUES_PER_GROUP).map(String);
    resolved.push({ ...g, column_name: target, values: kept, dc_id: dcId });
    status.push(verdict('linked', target, kept.length));
  }
  return { groups: resolved, status };
}
