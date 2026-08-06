/**
 * Offline MultiQC render path for the static-bundle runtime.
 *
 * WHY THIS EXISTS. `render_multiqc` looks like a server-side renderer, but at
 * request time it does exactly two things (dashboards routes.py:3814-4194):
 *
 *   1. FETCH a figure dict keyed on inputs that are all frozen into the
 *      component's stored_metadata — `(s3_locations, module, plot, dataset,
 *      theme)`. Every layer it consults (filter-aware Redis, bare Redis, the
 *      S3 prerender, the disk store, the Celery build) is a cache of that one
 *      value; nothing about it varies with the dashboard's filter state.
 *   2. PATCH that dict with `patch_multiqc_figures(fig, selected_samples)`
 *      (services/multiqc/patching.py:59) — a pure array filter over the figure
 *      itself: no S3, no Delta, no Mongo, ~100 lines of trace surgery.
 *
 * So the only runtime-variable inputs are the SAMPLE LIST and the theme. The
 * sample list comes from `_resolve_multiqc_sample_filter` (routes.py:3609),
 * which is the cross-DC link walk this runtime already reproduces offline in
 * `resolveLinkFilters` (RFC §8, phase 7). Step 1 is already in the bundle as
 * the frozen payload. Step 2 is ported here verbatim. Nothing is recomputed —
 * the same bytes the producer shipped are re-sliced in the browser.
 *
 * GENERAL STATISTICS is the same story with a different payload shape:
 * `build_general_stats_payload` (services/multiqc/general_stats_payload.py:797)
 * filters `df_for_display` by `Sample Name` and rebuilds the table + violin
 * from the filtered frame. Rows and violin points are reproduced here exactly;
 * the data-bar `table_styles` are NOT recomputed (they need matplotlib
 * colormaps), so shading keeps the export-time full-cohort scale while the
 * numbers themselves are the filtered truth. That single approximation is why
 * General Stats is a `partial` tier and regular figures are `live`.
 *
 * SAMPLE-NAME EXPANSION. MultiQC keys its traces by report-local variants
 * (`SRR10070130_1`, `SRR10070130 - First read: Adapter 1`) while the metadata
 * collection a filter lives on carries the canonical id (`SRR10070130`). The
 * server bridges that with the `sample_mapping` resolver fed from
 * `multiqc_collection`'s `metadata.sample_mappings`; offline, the same pure
 * resolver runs inside `extendFiltersViaLinks` — but only if the producer
 * baked `link_config.mappings` into the emitted link config (it is `null` in
 * Mongo, auto-fetched server-side at resolve time, links routes.py:716-737).
 * Without those mappings the resolver passes canonical ids through unchanged
 * and they match no trace, so {@link resolveMultiqcSamples} reports the
 * shortfall through `mappingsMissing` and the callers below decline to patch
 * rather than blanking every trace — a bundle built before the producer patch
 * behaves exactly as it does today (unfiltered) instead of showing an empty
 * plot.
 */
import type { InteractiveFilter } from '../../../../packages/depictio-react-core/src/api';
import { bundle, frozenPayload } from './bundle';
import { resolveLinkFilters } from './liveData';
import { themedFrozenFigure, type ThemeName } from './mantinePlotlyTemplate';

/** `interactive_component_type` marking a link chain that resolved to nothing
 *  (depictio-static-core `LINK_NO_MATCH`). */
const LINK_NO_MATCH = '__link_no_match__';

/** Column names `_resolve_multiqc_sample_filter` treats as "the MultiQC DC's
 *  own sample column" (routes.py:3667 uses `sample`; the sibling fallback list
 *  at routes.py:3622 names the other two). */
const SAMPLE_COLUMNS = new Set(['sample', 'sample_id', 'sample_name']);

// ---------------------------------------------------------------------------
// figure patching — port of services/multiqc/patching.py:59
// ---------------------------------------------------------------------------

type Fig = { data?: unknown[]; layout?: Record<string, unknown> };
type Trace = Record<string, unknown>;

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/**
 * Apply a sample selection to one MultiQC figure dict — line-by-line port of
 * `patch_multiqc_figures` (patching.py:59), including its quirks, because the
 * bundle's job is to reproduce the server, not to improve on it:
 *
 *   - bar/box/violin: the sample axis is `y` when `orientation === 'h'`, else
 *     `x`; both axes are rebuilt from the surviving indices. A violin whose
 *     sample axis is empty (MultiQC's "Top overrepresented sequences" ships
 *     `y: []`) therefore empties — as it does server-side.
 *   - heatmap: whichever of `x` / `y` carries samples is index-filtered, and
 *     `z` follows (rows for a `y` match, per-row columns for an `x` match).
 *   - scatter/scattergl: a NAMED trace is hidden with `visible: false` rather
 *     than emptied; an unnamed one filters its `x` / `y` pairs, and the
 *     server's `if filtered_x:` guard means a trace that matches nothing is
 *     left untouched.
 *
 * Returns a new figure; the manifest object is never mutated (a later filter
 * change re-patches from the pristine snapshot).
 */
export function patchMultiqcFigure(figure: Fig, selectedSamples: string[]): Fig {
  if (!figure || selectedSamples.length === 0) return figure;
  const selected = new Set(selectedSamples.map(String));
  const data = asArray(figure.data).map((raw) => {
    const trace = { ...(raw as Trace) };
    const traceType = String(trace.type ?? '').toLowerCase();
    const traceName = trace.name;

    const originalX = asArray(trace.x);
    const originalY = asArray(trace.y);
    const originalZ = asArray(trace.z);
    const orientation = trace.orientation;

    if (traceType === 'bar' || traceType === 'box' || traceType === 'violin') {
      const horizontal = orientation === 'h';
      const sampleAxis = horizontal ? originalY : originalX;
      const valueAxis = horizontal ? originalX : originalY;
      const sampleKey = horizontal ? 'y' : 'x';
      const valueKey = horizontal ? 'x' : 'y';

      const filteredSamples: unknown[] = [];
      const filteredValues: unknown[] = [];
      sampleAxis.forEach((sample, j) => {
        if (!selected.has(String(sample))) return;
        filteredSamples.push(sample);
        if (j < valueAxis.length) filteredValues.push(valueAxis[j]);
      });
      trace[sampleKey] = filteredSamples;
      trace[valueKey] = filteredValues;
      return trace;
    }

    if (traceType === 'heatmap') {
      if (originalX.length > 0 && originalZ.length > 0) {
        const xIndices = originalX.flatMap((x, j) => (selected.has(String(x)) ? [j] : []));
        const yIndices = originalY.length
          ? originalY.flatMap((y, j) => (selected.has(String(y)) ? [j] : []))
          : [];

        if (yIndices.length > 0 && yIndices.length >= xIndices.length) {
          trace.y = yIndices.map((j) => originalY[j]);
          trace.z = yIndices.filter((j) => j < originalZ.length).map((j) => originalZ[j]);
        } else if (xIndices.length > 0) {
          trace.x = xIndices.map((j) => originalX[j]);
          trace.z = originalZ.map((row) =>
            xIndices.filter((j) => j < asArray(row).length).map((j) => asArray(row)[j]),
          );
        }
      }
      return trace;
    }

    if (traceType === 'scatter' || traceType === 'scattergl') {
      if (traceName) {
        trace.visible = selected.has(String(traceName));
        return trace;
      }
      const filteredX: unknown[] = [];
      const filteredY: unknown[] = [];
      originalX.forEach((xVal, j) => {
        const yVal = j < originalY.length ? originalY[j] : '';
        if (!selected.has(String(xVal)) && !selected.has(String(yVal))) return;
        filteredX.push(xVal);
        if (j < originalY.length) filteredY.push(originalY[j]);
      });
      if (filteredX.length > 0) {
        trace.x = filteredX;
        trace.y = filteredY;
      }
      return trace;
    }

    return trace;
  });

  return { ...figure, data };
}

// ---------------------------------------------------------------------------
// sample resolution — offline `_resolve_multiqc_sample_filter` (routes.py:3609)
// ---------------------------------------------------------------------------

interface ComponentMeta {
  index?: string;
  component_type?: string;
  dc_id?: string | null;
  data_collection_id?: string | null;
}

/** Every component of the tab family (a filter authored on one tab drives the
 *  MultiQC tiles of another, exactly as it does server-side). */
function familyComponents(): ComponentMeta[] {
  const raw = bundle();
  const tabs = raw.tabs ?? [];
  const docs = tabs.length
    ? tabs.map((t) => t.doc)
    : [raw.dashboard.doc];
  const out: ComponentMeta[] = [];
  for (const doc of docs) {
    const meta = (doc as { stored_metadata?: ComponentMeta[] }).stored_metadata ?? [];
    out.push(...meta);
  }
  return out;
}

/** The data collection a MultiQC component reads, from the bundled document. */
export function multiqcDcIdFor(componentId: string): string {
  const meta = familyComponents().find(
    (c) => c.component_type === 'multiqc' && String(c.index ?? '') === componentId,
  );
  return String(meta?.dc_id ?? meta?.data_collection_id ?? '');
}

export interface MultiqcSampleSelection {
  /** Sample names to keep; empty means "no resolvable filter" (server parity:
   *  `patch_multiqc_figures` no-ops on an empty list, so the full figure shows). */
  samples: string[];
  /** True when a link into this DC declares the `sample_mapping` resolver but
   *  carries no `mappings` — the canonical ids it produced cannot be trusted to
   *  name real traces, so callers skip patching instead of emptying the plot. */
  mappingsMissing: boolean;
}

/**
 * Resolve the dashboard's filter state into a MultiQC sample list.
 *
 * Two sources, mirroring the server (routes.py:3658-3811):
 *   - DIRECT — a filter that lives on the MultiQC DC itself and names a sample
 *     column; its values are used as-is.
 *   - LINKED — everything else goes through `resolveLinkFilters`, the offline
 *     mirror of `_filters_with_links`. The synthetics it appends for this
 *     target DC ARE the resolved sample list (the `sample_mapping` resolver
 *     already ran inside the walk), so no second expansion happens here.
 *
 * A chain that resolved to nothing (`LINK_NO_MATCH`) contributes no samples,
 * which lands on the server's own behaviour: `_resolve_multiqc_sample_filter`
 * returns `[]` when the metadata frame comes back empty, and an empty list
 * makes `patch_multiqc_figures` return the figure unpatched.
 */
export async function resolveMultiqcSamples(
  dcId: string,
  filters: InteractiveFilter[],
): Promise<MultiqcSampleSelection> {
  const empty: MultiqcSampleSelection = { samples: [], mappingsMissing: false };
  if (!dcId || !filters || filters.length === 0) return empty;

  const direct: string[] = [];
  for (const f of filters) {
    const meta = f.metadata ?? {};
    if (String(meta.dc_id ?? '') !== dcId) continue;
    const column = f.column_name ?? meta.column_name;
    if (!column || !SAMPLE_COLUMNS.has(String(column))) continue;
    const value = f.value;
    if (value === null || value === undefined || value === '') continue;
    for (const v of Array.isArray(value) ? value : [value]) direct.push(String(v));
  }

  const extended = await resolveLinkFilters(dcId, filters);
  const linked: string[] = [];
  for (const f of extended) {
    if (filters.includes(f)) continue; // user filter, already handled above
    if (String(f.metadata?.dc_id ?? '') !== dcId) continue;
    if (f.interactive_component_type === LINK_NO_MATCH) continue;
    for (const v of Array.isArray(f.value) ? f.value : [f.value]) {
      if (v !== null && v !== undefined && v !== '') linked.push(String(v));
    }
  }

  // A `sample_mapping` link with no baked mappings resolved canonical ids to
  // themselves. They will not match MultiQC's variant-keyed traces, and
  // patching with them would blank the figure — worse than not filtering.
  const mappingsMissing =
    linked.length > 0 &&
    (bundle().links?.configs ?? []).some(
      (link) =>
        String((link as { target_dc_id?: string }).target_dc_id ?? '') === dcId &&
        (link as { link_config?: { resolver?: string; mappings?: unknown } }).link_config
          ?.resolver === 'sample_mapping' &&
        !(link as { link_config?: { mappings?: unknown } }).link_config?.mappings,
    );

  return {
    samples: [...new Set([...direct, ...linked])],
    mappingsMissing,
  };
}

// ---------------------------------------------------------------------------
// render entry points (called by apiShim)
// ---------------------------------------------------------------------------

interface MultiqcFigurePayload {
  figure: Fig;
  metadata?: Record<string, unknown>;
}

/**
 * Offline `renderMultiQC`. Serves the frozen figure, re-themed like every other
 * frozen figure (`themedFrozenFigure`, so MultiQC follows the color-scheme flip
 * the renderer re-requests on), and sample-patched under the current filters.
 *
 * Never throws for a filtering reason: a link walk that fails degrades to the
 * unpatched figure (RFC §4 structural degradation) rather than an error tile.
 */
export async function renderMultiQCStatic(
  componentId: string,
  filters: InteractiveFilter[] = [],
  theme: ThemeName = 'light',
): Promise<MultiqcFigurePayload & { status: 'ready' }> {
  const payload = frozenPayload<MultiqcFigurePayload>(componentId, 'multiqc');

  let selection: MultiqcSampleSelection = { samples: [], mappingsMissing: false };
  try {
    selection = await resolveMultiqcSamples(multiqcDcIdFor(componentId), filters);
  } catch (e) {
    console.error(
      `static bundle: MultiQC sample resolution failed for "${componentId}" — serving unfiltered`,
      e,
    );
  }

  if (selection.samples.length === 0 || selection.mappingsMissing) {
    return { ...themedFrozenFigure(payload, theme), status: 'ready' };
  }

  const patched = patchMultiqcFigure(payload.figure, selection.samples);
  return {
    ...themedFrozenFigure(
      {
        figure: {
          ...patched,
          layout: { ...(patched.layout ?? {}), _depictio_filter_applied: true },
        },
        metadata: {
          ...(payload.metadata ?? {}),
          filter_applied: true,
          selected_sample_count: selection.samples.length,
        },
      },
      theme,
    ),
    status: 'ready',
  };
}

interface GeneralStatsMode {
  table_data: Record<string, unknown>[];
  table_columns: unknown[];
  table_styles: unknown[];
  violin_figure?: Fig;
}

interface GeneralStatsPayloadLike {
  is_paired_end: boolean;
  all_samples: string[];
  modes: Record<string, GeneralStatsMode | undefined>;
  filter_applied?: boolean;
  selected_sample_count?: number;
}

/**
 * Filter one General Statistics read mode to a sample selection.
 *
 * Rows are matched on `Sample Name`, which the payload carries as the CANONICAL
 * id while a link-resolved selection is a list of report variants — so a row
 * survives if its name is selected outright OR if a selected variant is that
 * name followed by a separator (`SRR10070130` kept by `SRR10070130_1` or by
 * `SRR10070130 - First read: Adapter 1`). That is the table-side counterpart of
 * the variant expansion, not an extra guess: a MultiQC variant IS the sample
 * name plus a suffix, which is how `sample_mappings` buckets them. Requiring a
 * `_` or whitespace after the prefix keeps `SRR1007013` from being kept by
 * `SRR10070130_1`, which a bare `startsWith` would do.
 *
 * The violin is filtered through each trace's `text` array — `_create_violin_plot`
 * (general_stats_payload.py:445) puts the sample names there, with the metric
 * values in `x` — so the surviving points are exactly those of the filtered
 * frame and Plotly recomputes the KDE from them.
 *
 * `table_styles` are passed through unchanged: the server regenerates its data
 * bars over the filtered range, which needs the matplotlib colormaps that
 * produced them. Cells keep the full-cohort shading; the numbers are exact.
 */
export function filterGeneralStatsMode(
  mode: GeneralStatsMode,
  selectedSamples: string[],
): GeneralStatsMode {
  const selected = new Set(selectedSamples.map(String));
  const keep = (name: unknown): boolean => {
    const n = String(name ?? '');
    if (!n) return false;
    if (selected.has(n)) return true;
    for (const s of selected) {
      if (s.length > n.length && s.startsWith(n) && /^[_\s]/.test(s.slice(n.length))) return true;
    }
    return false;
  };

  const rows = mode.table_data.filter((row) => keep(row['Sample Name']));
  const violin = mode.violin_figure;
  const violinFiltered = violin
    ? {
        ...violin,
        data: asArray(violin.data).map((raw) => {
          const trace = { ...(raw as Trace) };
          const text = asArray(trace.text);
          if (text.length === 0) return trace;
          const indices = text.flatMap((t, i) => (keep(t) ? [i] : []));
          for (const key of ['x', 'y', 'text', 'hovertext', 'customdata'] as const) {
            const arr = trace[key];
            if (Array.isArray(arr) && arr.length === text.length) {
              trace[key] = indices.map((i) => arr[i]);
            }
          }
          return trace;
        }),
      }
    : violin;

  return { ...mode, table_data: rows, violin_figure: violinFiltered };
}

/**
 * Offline `renderMultiQCGeneralStats`. Every read mode is filtered, because the
 * Mean / R1 / R2 / All pills switch between them client-side without a refetch —
 * a mode left unfiltered would silently show the whole cohort one click away.
 *
 * `mappingsMissing` is deliberately NOT a bail-out here, unlike the figure path:
 * this table is keyed by canonical sample id, which is precisely what an
 * unexpanded `sample_mapping` resolution yields, so General Statistics filters
 * correctly in bundles built before the producer bakes the mappings in.
 */
export async function renderMultiQCGeneralStatsStatic(
  componentId: string,
  filters: InteractiveFilter[] = [],
): Promise<GeneralStatsPayloadLike> {
  const payload = frozenPayload<GeneralStatsPayloadLike>(componentId, 'multiqc-general-stats');

  let selection: MultiqcSampleSelection = { samples: [], mappingsMissing: false };
  try {
    selection = await resolveMultiqcSamples(multiqcDcIdFor(componentId), filters);
  } catch (e) {
    console.error(
      `static bundle: MultiQC General Stats sample resolution failed for "${componentId}" — serving unfiltered`,
      e,
    );
  }
  if (selection.samples.length === 0) return payload;

  const modes: Record<string, GeneralStatsMode | undefined> = {};
  for (const [name, mode] of Object.entries(payload.modes ?? {})) {
    modes[name] = mode ? filterGeneralStatsMode(mode, selection.samples) : mode;
  }
  return {
    ...payload,
    modes,
    filter_applied: true,
    selected_sample_count: selection.samples.length,
  };
}
