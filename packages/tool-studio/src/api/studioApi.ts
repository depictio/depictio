/**
 * Offline api shim for Tool Studio.
 *
 * Vite redirects every `depictio-react-core` import of the real `api.ts` to
 * this module (see the `api-shim` plugin in `vite.config.ts`, shared with the
 * catalog-preview bundle). It re-exports the real api unchanged and overrides
 * ONLY the data-fetching functions, so depictio's own builders and renderers —
 * `CardBuilder`/`CardPreview`, `InteractiveBuilder` and the interactive
 * renderers, `AdvancedVizBuilder` and the 18 advanced-viz renderers,
 * `TableRenderer`, `ComponentRenderer` — run here unmodified, against the
 * fixture in the browser instead of FastAPI.
 *
 * This is the same seam `depictio/viewer/src/catalog-preview/mockApi.ts` uses,
 * with one difference: that shim *looks payloads up* (Python precomputed them
 * into the bundle), while this one *computes them*, because the Studio's
 * fixture is whatever the user just dropped.
 *
 * What is deliberately NOT served, and says so rather than spinning:
 *   - the five Celery-computed advanced-viz kinds (embedding in live mode,
 *     complex_heatmap, upset_plot, coverage_track, sankey);
 *   - a phylogenetic tree's newick, which is a second file the Studio has not
 *     been given;
 *   - figures, which are approximated client-side (`src/viz/figureBuilder.ts`)
 *     because the authoritative figure is built by Python plotly-express.
 *
 * Filter arguments are accepted and ignored throughout: a Studio preview has no
 * dashboard, so there is never an active filter to apply.
 */
export * from 'depictio-react-core/api';

import type {
  AdvancedVizDataRequest,
  AuthStatusResponse,
  DashboardData,
  AdvancedVizDataResponse,
  AdvancedVizKindDescriptor,
  BreakdownPayloadDTO,
  BulkComputeResponse,
  ColumnRange,
  FigurePreviewRequest,
  FigureResponse,
  PreviewResult,
  TableResponse,
  VizKindSuggestion,
  VizSuggestionsResponse,
} from 'depictio-react-core/api';

import { fixtureToColumnSpecs } from '../builder/columnSpecs';
import { buildPreview, isUnavailable } from '../viz/figureBuilder';
import { applyPlotlyTheme } from '../viz/plotlyTheme';
import type { RenderSpec } from '../types';
import { aggregate } from './aggregations';
import { computeBreakdown, numericLayoutPayload } from './cardMetrics';
import type { FrameValue, StudioFrame } from './frame';
import { frameRows, isNumericKind } from './frame';
import type { ComponentMetadata } from './fixtureRegistry';
import {
  allComponents,
  cardComponents,
  getActiveFixture,
  getActiveFrame,
  getComponent,
} from './fixtureRegistry';

/** Raised when a preview needs data the Studio genuinely does not have. The
 *  message is what the renderer puts on screen, so it is written for the user. */
class StudioPreviewError extends Error {}

/** Answer a request the way a network call would: on a later task, and never
 *  after the caller has abandoned it.
 *
 *  Both halves matter. depictio's builder previews have no request-id guard —
 *  their only staleness protection is aborting the previous fetch and relying
 *  on it rejecting (`useNumericPreview` in CardPreview). A shim that computes
 *  synchronously and ignores the signal hands a superseded payload to a live
 *  renderer: switching a card from `threshold` to `completeness` fed the
 *  completeness strip a threshold payload, and it crashed the whole builder on
 *  a missing field. */
function settle<T>(compute: () => T, signal?: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const abort = () =>
      reject(new DOMException('The operation was aborted.', 'AbortError'));
    if (signal?.aborted) {
      abort();
      return;
    }
    setTimeout(() => {
      if (signal?.aborted) {
        abort();
        return;
      }
      try {
        resolve(compute());
      } catch (err) {
        reject(err);
      }
    }, 0);
  });
}

function requireFrame(): StudioFrame {
  const frame = getActiveFrame();
  if (!frame) throw new StudioPreviewError('Drop a fixture to preview this component.');
  return frame;
}

// ---- data collection: specs, schema, unique values -------------------------

export async function fetchSpecs(_dcId: string): Promise<Record<string, unknown>> {
  const fixture = getActiveFixture();
  if (!fixture) return {} as Record<string, unknown>;
  // The list shape `[{name, type, specs}]` — one of the two `fetchColumnRange`
  // accepts, and the one the builder store already speaks.
  return fixtureToColumnSpecs(fixture) as unknown as Record<string, unknown>;
}

export async function fetchColumnRange(
  _dcId: string,
  columnName: string,
): Promise<ColumnRange> {
  const frame = getActiveFrame();
  const col = frame?.byName.get(columnName);
  if (!col) return { min: null, max: null, dtype: null, unique: null };
  const min = aggregate(frame!, columnName, 'min');
  const max = aggregate(frame!, columnName, 'max');
  return {
    min: typeof min === 'number' ? min : null,
    max: typeof max === 'number' ? max : null,
    // The dtype and the distinct count are what tell a three-year survey column
    // apart from a continuous measurement, so the slider stops on 2008 rather
    // than 2007.34 (see `buildNumericScale`).
    dtype: col.kind,
    unique: new Set(col.present).size,
  };
}

/** Column → POLARS dtype name (`Float64`, `String`, …), which is the
 *  vocabulary `/datacollections/polars_schema` speaks and the advanced-viz
 *  builder matches role dtypes against. Not the lowercase precompute names the
 *  card/interactive forms use — those come from `fetchSpecs`. Getting these two
 *  the wrong way round leaves every advanced-viz role saying "no column with a
 *  compatible dtype" over a fixture full of them. */
export async function fetchPolarsSchema(_dcId: string): Promise<Record<string, string>> {
  const fixture = getActiveFixture();
  if (!fixture) return {};
  return Object.fromEntries(fixture.columns.map((c) => [c.name, c.dtype]));
}

export async function fetchUniqueValues(
  _dcId: string,
  columnName: string,
): Promise<string[]> {
  const frame = getActiveFrame();
  const col = frame?.byName.get(columnName);
  if (!col) return [];
  const seen = new Set(col.present.map(String));
  return [...seen].sort();
}

// ---- cards -----------------------------------------------------------------

function cardConfig(metadata: ComponentMetadata): Record<string, unknown> {
  return metadata as Record<string, unknown>;
}

/** One card's secondary strip: the plain aggregations it declares, plus the
 *  synthetic `__breakdown__` / `__<layout>__` payload its layout reads. */
function secondaryValues(
  frame: StudioFrame,
  card: Record<string, unknown>,
  column: string,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const aggregations = (card.aggregations as string[] | undefined) ?? [];
  for (const agg of aggregations) out[agg] = aggregate(frame, column, agg);

  const layout = String(card.secondary_layout || 'vertical');
  const breakdownCol = card.breakdown_col as string | undefined;
  if (breakdownCol && frame.byName.has(breakdownCol)) {
    const payload = computeBreakdown(
      frame,
      column,
      breakdownCol,
      String(card.aggregation || 'count'),
      Number(card.top_n_count || 3),
    );
    if (payload) out.__breakdown__ = payload;
  }
  const numeric = numericLayoutPayload(frame, card, column, layout);
  if (numeric) out[`__${layout}__`] = numeric;
  return out;
}

export function fetchCardMetric(
  _dcId: string,
  layout: string,
  column: string,
  config: Record<string, unknown> = {},
  signal?: AbortSignal,
): Promise<Record<string, unknown> | null> {
  return settle(() => {
    const frame = requireFrame();
    if (layout === 'hero') {
      return { value: aggregate(frame, column, String(config.aggregation || 'count')) };
    }
    return numericLayoutPayload(frame, config, column, layout);
  }, signal);
}

export function fetchCardHeroValue(
  _dcId: string,
  column: string,
  aggregation: string,
  _filters?: unknown,
  signal?: AbortSignal,
): Promise<unknown> {
  return settle(() => aggregate(requireFrame(), column, aggregation), signal);
}

export function fetchBreakdown(
  _dcId: string,
  column: string,
  breakdownCol: string,
  aggregation = 'count',
  topNCount = 3,
  signal?: AbortSignal,
): Promise<BreakdownPayloadDTO> {
  return settle(() => {
    const payload = computeBreakdown(
      requireFrame(),
      column,
      breakdownCol,
      aggregation,
      topNCount,
    );
    if (!payload) throw new StudioPreviewError('That column is not in the fixture.');
    return payload as BreakdownPayloadDTO;
  }, signal);
}

export async function bulkComputeCards(
  _dashboardId: string,
  _filters: unknown,
  componentIds?: string[],
): Promise<BulkComputeResponse> {
  const frame = getActiveFrame();
  const values: Record<string, unknown> = {};
  const secondary: Record<string, Record<string, unknown>> = {};
  const aggregations: Record<string, string[]> = {};
  if (frame) {
    const cards = componentIds
      ? (componentIds.map(getComponent).filter(Boolean) as ComponentMetadata[])
      : cardComponents();
    for (const card of cards) {
      const cfg = cardConfig(card);
      const column = String(cfg.column_name || '');
      if (!column) continue;
      values[card.index] = aggregate(frame, column, String(cfg.aggregation || 'count'));
      const sec = secondaryValues(frame, cfg, column);
      if (Object.keys(sec).length) secondary[card.index] = sec;
      const declared = cfg.aggregations as string[] | undefined;
      if (declared?.length) aggregations[card.index] = declared;
    }
  }
  return {
    values,
    secondary_values: secondary,
    aggregations,
    filter_applied: false,
    filter_count: 0,
  };
}

// ---- figures ---------------------------------------------------------------

/** depictio metadata → the Studio's own render spec, so one figure builder
 *  serves the builder preview, the render list and the recognised-tool
 *  previews. */
function figureSpecFrom(metadata: Record<string, unknown>): RenderSpec {
  return {
    uid: String(metadata.index ?? 'preview'),
    component: 'figure',
    visu_type: (metadata.visu_type as RenderSpec extends { visu_type: infer T } ? T : never) ?? 'scatter',
    dict_kwargs: (metadata.dict_kwargs as Record<string, string>) ?? {},
  } as RenderSpec;
}

/** depictio's server builds a figure with the mantine template already
 *  applied, so `FigureRenderer` themes nothing itself — the shim has to. */
function themed(
  figure: { data?: unknown[]; layout?: Record<string, unknown> },
  theme: 'light' | 'dark',
): FigureResponse['figure'] {
  return { data: figure.data ?? [], layout: applyPlotlyTheme(figure.layout ?? {}, theme) };
}

async function figureFrom(
  metadata: Record<string, unknown>,
  theme: 'light' | 'dark' = 'light',
): Promise<FigureResponse> {
  const fixture = getActiveFixture();
  if (!fixture) throw new StudioPreviewError('Drop a fixture to preview this figure.');

  if (metadata.mode === 'code' || metadata.code_content) {
    const code = String(metadata.code_content ?? '').trim();
    // A render already executed once carries its figure, so the render list can
    // redraw it without paying for the interpreter again.
    const cached = metadata._previewFigure as FigureResponse['figure'] | undefined;
    if (!code) {
      if (cached) {
        return {
          figure: themed(cached, theme),
          metadata: { visu_type: 'code', filter_applied: false },
        };
      }
      throw new StudioPreviewError('Write some code, then press Execute.');
    }
    // depictio executes Code Mode on the server; here it runs in the browser
    // under Pyodide, which is why this is the one preview that is not instant.
    const { runCodeToFigure } = await import('../builder/pyodideRunner');
    const result = await runCodeToFigure(code, fixture);
    if (result.error) throw new StudioPreviewError(result.error);
    return {
      figure: themed(result.figure!, theme),
      metadata: { visu_type: 'code', filter_applied: false },
    };
  }

  const result = buildPreview(fixture, figureSpecFrom(metadata));
  if (isUnavailable(result)) throw new StudioPreviewError(result.reason);
  return {
    figure: themed(result, theme),
    metadata: {
      visu_type: String(metadata.visu_type ?? ''),
      filter_applied: false,
      was_sampled: false,
      full_data_loaded: true,
    },
  };
}

export async function previewFigure(body: FigurePreviewRequest): Promise<FigureResponse> {
  return figureFrom(body.metadata, body.theme ?? 'light');
}

export async function renderFigure(
  _dashboardId: string,
  componentId: string,
  _filters: unknown,
  theme: 'light' | 'dark' = 'light',
): Promise<FigureResponse> {
  const metadata = getComponent(componentId);
  if (!metadata) throw new StudioPreviewError('This figure is no longer on screen.');
  return figureFrom(metadata as Record<string, unknown>, theme);
}

// ---- tables ----------------------------------------------------------------

function visibleColumns(frame: StudioFrame, metadata?: ComponentMetadata): string[] {
  const cols = (metadata?.cols_json ?? {}) as Record<string, { hide?: boolean }>;
  return frame.columns.map((c) => c.name).filter((name) => cols[name]?.hide !== true);
}

export async function fetchDataCollectionPreview(
  _dcId: string,
  limit = 100,
): Promise<PreviewResult> {
  const frame = getActiveFrame();
  if (!frame) return { columns: [], rows: [], total_rows: 0, total_columns: 0 };
  return {
    columns: frame.columns.map((c) => c.name),
    rows: frameRows(frame).slice(0, limit) as Record<string, unknown>[],
    total_rows: frame.height,
    total_columns: frame.columns.length,
  };
}

export async function renderTable(
  _dashboardId: string,
  componentId: string,
  _filters: unknown,
  start = 0,
  limit = 100,
  sortBy?: string | null,
  sortDir: 'asc' | 'desc' = 'desc',
): Promise<TableResponse> {
  const frame = requireFrame();
  const metadata = getComponent(componentId);
  const names = visibleColumns(frame, metadata);
  let rows = frameRows(frame) as Record<string, unknown>[];
  if (sortBy && frame.byName.has(sortBy)) {
    const dir = sortDir === 'asc' ? 1 : -1;
    rows = [...rows].sort((a, b) => {
      const av = a[sortBy] as FrameValue;
      const bv = b[sortBy] as FrameValue;
      if (av === null) return 1;
      if (bv === null) return -1;
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
      return String(av) < String(bv) ? -dir : String(av) > String(bv) ? dir : 0;
    });
  }
  return {
    columns: names.map((name) => ({
      field: name,
      headerName: name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      type: isNumericKind(frame.byName.get(name)!.kind) ? 'numericColumn' : 'text',
    })),
    rows: rows.slice(start, start + limit),
    total: frame.height,
    sort_by: sortBy ?? null,
    sort_dir: sortDir,
  };
}

// ---- advanced viz ----------------------------------------------------------

export function fetchAdvancedVizData(
  req: AdvancedVizDataRequest,
  signal?: AbortSignal,
): Promise<AdvancedVizDataResponse> {
  return settle(() => {
    const frame = requireFrame();
  // A Studio fixture is capped at a few thousand rows, so there is nothing to
  // sample: every renderer gets the whole frame and its aggregates are exact.
    const present = req.columns.filter((c) => frame.byName.has(c));
    const rows: Record<string, unknown[]> = {};
    for (const name of present) rows[name] = frame.byName.get(name)!.values;
    return {
      columns: present,
      rows,
      row_count: frame.height,
      total_rows: frame.height,
      sampled: false,
      sampling: { policy: 'none', exact: true, degraded: false },
      filter_applied: false,
    };
  }, signal);
}

let kindsPromise: Promise<AdvancedVizKindDescriptor[]> | null = null;

/** The kind descriptors depictio serves from `/advanced_viz/kinds`, read from
 *  the committed `public/kinds.json` snapshot instead (regenerated by
 *  `scripts/genKinds.ts`, drift-checked in CI). */
export async function fetchAdvancedVizKinds(): Promise<AdvancedVizKindDescriptor[]> {
  if (!kindsPromise) {
    kindsPromise = fetch(`${import.meta.env.BASE_URL}kinds.json`)
      .then((r) => r.json())
      .then((payload: unknown) =>
        Array.isArray(payload)
          ? (payload as AdvancedVizKindDescriptor[])
          : ((payload as { kinds?: AdvancedVizKindDescriptor[] }).kinds ?? []),
      )
      .catch(() => {
        kindsPromise = null;
        return [];
      });
  }
  return kindsPromise;
}

/** How well each kind fits the fixture, ranked the way depictio ranks a data
 *  collection server-side (`suggest_viz_kinds`): per required role, the best
 *  column scores `dtype × (0.5 + 0.5 × name)`, and the kind scores the mean.
 *
 *  Both halves matter. Dtype alone puts every kind at 100% — a fixture with one
 *  text and one float column "fits" volcano, MA, lollipop and a dozen others
 *  equally — so the name signal (the aliases each role is known by, snapshotted
 *  into `kinds.json` as `role_names`) is what makes the ranking say anything.
 *
 *  Not ported: the optional-role nudge and the structural gates (a heatmap
 *  wants a wide float matrix, sankey wants several categoricals). They refine
 *  an order that is advisory in the first place — the picker shows every kind
 *  and disables none — and the authoritative check is `grounding.ts` here and
 *  `dev catalog validate` in CI. */
const FLOAT_DTYPES = new Set(['Float32', 'Float64']);
const INT_DTYPES = new Set([
  'Int8',
  'Int16',
  'Int32',
  'Int64',
  'UInt8',
  'UInt16',
  'UInt32',
  'UInt64',
]);
const STRING_DTYPES = new Set(['String', 'Utf8']);

/** `_dtype_score`: exact, then the two cast tiers the renderers tolerate. */
function dtypeScore(dtype: string, accepted: string[]): number {
  if (accepted.includes(dtype)) return 1;
  if (accepted.length > 0 && accepted.every((d) => FLOAT_DTYPES.has(d)) && INT_DTYPES.has(dtype)) {
    return 0.6;
  }
  if (dtype === 'Categorical' && accepted.some((d) => STRING_DTYPES.has(d))) return 0.8;
  return 0;
}

const normaliseName = (name: string): string => name.toLowerCase().replace(/[^a-z0-9]/g, '');

/** `_name_score`: an exact alias scores 1, a near miss scores in [0.6, 0.9].
 *  The near-miss measure is a longest-common-subsequence ratio rather than
 *  Python's difflib, so the two agree on "same"/"unrelated" and can differ by a
 *  little in between — which only ever reorders neighbours in an advisory list. */
function nameScore(column: string, aliases: string[]): number {
  const col = normaliseName(column);
  let best = 0;
  for (const alias of aliases) {
    const a = normaliseName(alias);
    if (!a) continue;
    if (col === a) return 1;
    const ratio = similarity(col, a);
    if (ratio >= 0.8) best = Math.max(best, 0.6 + (ratio - 0.8));
  }
  return Math.min(best, 0.9);
}

function similarity(a: string, b: string): number {
  if (!a.length || !b.length) return 0;
  // Longest common subsequence, doubled over the combined length — the same
  // shape as difflib's ratio.
  const prev = new Array<number>(b.length + 1).fill(0);
  const row = new Array<number>(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i += 1) {
    row.fill(0);
    for (let j = 1; j <= b.length; j += 1) {
      row[j] = a[i - 1] === b[j - 1] ? prev[j - 1] + 1 : Math.max(prev[j], row[j - 1]);
    }
    prev.splice(0, prev.length, ...row);
  }
  return (2 * prev[b.length]) / (a.length + b.length);
}

export async function fetchVizSuggestions(dcId: string): Promise<VizSuggestionsResponse> {
  const fixture = getActiveFixture();
  const kinds = await fetchAdvancedVizKinds();
  const schema: Record<string, string> = fixture
    ? Object.fromEntries(fixture.columns.map((c) => [c.name, c.dtype as string]))
    : {};

  const vizKinds: VizKindSuggestion[] = kinds.map((kind) => {
    const roles = kind.roles ?? {};
    const aliases = (kind as unknown as { role_names?: Record<string, string[]> }).role_names ?? {};
    const candidates: Record<string, string[]> = {};
    const unmet: string[] = [];
    const weak: string[] = [];
    let total = 0;
    let required = 0;

    for (const [role, spec] of Object.entries(roles)) {
      const scored = Object.entries(schema)
        .map(([column, dtype]) => ({
          column,
          score: dtypeScore(dtype, spec.dtypes ?? []) *
            (0.5 + 0.5 * nameScore(column, aliases[role] ?? [role])),
        }))
        .filter((c) => c.score > 0)
        .sort((a, b) => b.score - a.score || a.column.localeCompare(b.column));
      candidates[role] = scored.map((c) => c.column);
      if (!spec.required) continue;
      required += 1;
      const best = scored[0]?.score ?? 0;
      total += best;
      if (best === 0) unmet.push(role);
      // `_STRONG_ROLE_SCORE` — bound but not convincingly.
      else if (best < 0.75) weak.push(role);
    }

    return {
      viz_kind: kind.viz_kind,
      score: required ? Number((total / required).toFixed(4)) : 0,
      role_candidates: candidates,
      unmet_roles: unmet,
      weak_roles: weak,
    };
  });
  vizKinds.sort((a, b) => b.score - a.score || a.viz_kind.localeCompare(b.viz_kind));
  return { data_collection_id: dcId, schema, viz_kinds: vizKinds };
}

export async function fetchPhylogenyNewick(): Promise<string> {
  throw new StudioPreviewError(
    'A phylogenetic tree needs its newick file, which the Studio has not been given. ' +
      'The render exports correctly and previews in depictio.',
  );
}

// ---- the Celery-computed kinds --------------------------------------------

/** The five kinds depictio computes in a worker. They export correctly and
 *  render once the tool is imported; here they resolve to a finished-but-failed
 *  job so the renderer shows its own message instead of polling forever. */
function serverComputed(kind: string) {
  return {
    job_id: `studio::${kind}`,
    status: 'failed' as const,
    result: null,
    error: `${kind} is computed by depictio's workers — this render exports correctly and previews once the tool is imported.`,
    from_cache: false,
  };
}

export async function dispatchComputeEmbedding() {
  return serverComputed('Embedding') as never;
}
export async function pollComputeEmbedding() {
  return serverComputed('Embedding') as never;
}
export async function dispatchComplexHeatmap() {
  return serverComputed('ComplexHeatmap') as never;
}
export async function pollComplexHeatmap() {
  return serverComputed('ComplexHeatmap') as never;
}
export async function dispatchUpset() {
  return serverComputed('UpSet') as never;
}
export async function pollUpset() {
  return serverComputed('UpSet') as never;
}
export async function dispatchCoverageTrack() {
  return serverComputed('Coverage track') as never;
}
export async function pollCoverageTrack() {
  return serverComputed('Coverage track') as never;
}
export async function dispatchSankey() {
  return serverComputed('Sankey') as never;
}
export async function pollSankey() {
  return serverComputed('Sankey') as never;
}

// ---- session + dashboard ---------------------------------------------------

/** The Studio has one user: whoever is at the keyboard. The builders ask who
 *  that is only to gate affordances — figure Code Mode is owner-only and off in
 *  public/demo deployments — so the answer is a signed-in owner of an ordinary
 *  deployment. */
const STUDIO_USER = { id: 'tool-studio', email: 'you@tool-studio', is_admin: false };

export async function fetchAuthStatus(): Promise<AuthStatusResponse> {
  return {
    auth_mode: 'standard',
    user: STUDIO_USER,
    is_public_mode: false,
    is_single_user_mode: false,
    is_demo_mode: false,
    google_oauth_enabled: false,
  };
}

/** There is no dashboard, but the builders read two things off one: who owns it
 *  (Code Mode gating) and what else is on it (`InteractiveBuilder` suggests a
 *  panel group from sibling filters). Both are answerable from the registry. */
export async function fetchDashboard(dashboardId: string): Promise<DashboardData> {
  return {
    _id: dashboardId,
    title: 'Tool Studio',
    permissions: { owners: [STUDIO_USER] },
    stored_metadata: allComponents() as never,
    filter_sections: [],
  };
}

/** The real api navigates to `/auth` when a request 401s. There is no session
 *  here and no route to navigate to, and doing so would throw away an unsaved
 *  draft — so it is a no-op. */
export function redirectToAuth(): void {}
