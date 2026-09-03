/**
 * Catalog render -> builder-store config.
 *
 * Two surfaces hand a catalog render to the builder: the Catalog tab of the
 * Add-component page and the "From the catalog" offers of the AI Describe
 * step's Suggestions mode. Both go through this one translation so a render
 * lands in the builder the same way wherever it was picked from.
 */
import type { CatalogRender } from 'depictio-react-core';
import { fetchMultiQCBuilderOptions } from 'depictio-react-core';
import { advancedVizConfig } from '../store/applyLiteComponent';

/** Translate one catalog render into the builder-store config the component
 *  type expects.
 *
 *  Async because a MultiQC render names a module but not a plot, and only the
 *  collection itself knows which plots its report carries. */
export async function buildConfigFromRender(
  render: CatalogRender,
  dcId: string,
): Promise<Record<string, unknown>> {
  if (render.component === 'advanced_viz') {
    // Same mapping the AI answers go through (see applyLiteComponent):
    // `preset_config` carries the catalog preview's computed config (role
    // bindings + data-derived viz-control defaults), and buildMetadata overlays
    // its non-role extras so the added component renders exactly like its
    // preview. The bindings are seeded from that grounded config *and* the
    // declared roles, declared last so they win. A list-typed binding has no
    // role to travel in (a sunburst declares only `abundance` and gets its
    // hierarchy inferred server-side), so reading the roles alone left the
    // binding form short of a requirement the offer actually satisfies, and
    // "Edit" rejected an offer whose preview had just rendered.
    return advancedVizConfig(render.kind, render.config, render.roles);
  }
  if (render.component === 'figure') {
    return {
      visu_type: render.visu_type ?? 'scatter',
      dict_kwargs: render.dict_kwargs ?? {},
      ...(render.code ? { code_content: render.code, mode: 'code' } : { mode: 'ui' }),
    };
  }
  if (render.component === 'card') {
    // CardBuilder reads column_name (not column) from config. Everything after
    // the first two lines is the secondary strip: the catalog can declare it and
    // the preview renders it, so dropping it here made Add produce a plain
    // number where the preview had just shown a box plot / histogram / top-N.
    return {
      column_name: render.column ?? null,
      aggregation: render.aggregation ?? null,
      ...(render.aggregations?.length ? { aggregations: render.aggregations } : {}),
      ...(render.secondary_layout ? { secondary_layout: render.secondary_layout } : {}),
      ...(render.breakdown_col ? { breakdown_col: render.breakdown_col } : {}),
      ...(render.top_n_count != null ? { top_n_count: render.top_n_count } : {}),
      ...(render.coverage_max != null ? { coverage_max: render.coverage_max } : {}),
      ...(render.threshold_value != null ? { threshold_value: render.threshold_value } : {}),
      ...(render.threshold_direction
        ? { threshold_direction: render.threshold_direction }
        : {}),
      ...(render.threshold_warn != null ? { threshold_warn: render.threshold_warn } : {}),
      ...(render.attrition_cols?.length ? { attrition_cols: render.attrition_cols } : {}),
      ...(render.trend_col ? { trend_col: render.trend_col } : {}),
      ...(render.filter_expr ? { filter_expr: render.filter_expr } : {}),
    };
  }
  if (render.component === 'interactive') {
    return {
      interactive_component_type: render.interactive_type ?? null,
      column_name: render.column_name ?? null,
    };
  }
  if (render.component === 'table') {
    // The builder keeps per-column visibility as a bag; the catalog states the
    // visible list, so anything it doesn't name is hidden.
    const colsJson = render.columns?.length
      ? Object.fromEntries(
          (render.columns ?? []).map((name) => [name, { hide: false }]),
        )
      : undefined;
    return {
      ...(colsJson ? { cols_json: colsJson } : {}),
      ...(render.page_size != null ? { page_size: render.page_size } : {}),
      ...(render.row_selection_enabled != null
        ? { row_selection_enabled: render.row_selection_enabled }
        : {}),
      ...(render.row_selection_column
        ? { row_selection_column: render.row_selection_column }
        : {}),
    };
  }
  if (render.component === 'multiqc') {
    return multiqcConfigForSection(dcId, render.section);
  }
  return {};
}

/** Resolve a catalog `section` (a MultiQC *module*) to the concrete
 *  `selected_module` / `selected_plot` pair the renderer needs.
 *
 *  The catalog cannot name a plot: which plots exist depends on the report the
 *  pipeline actually produced. So ask the collection, through the same endpoint
 *  MultiQCBuilder uses, and take the module's first plot, which is also the one
 *  the catalog preview renders.
 *
 *  Report anchors are module-prefixed (`samtools_bowtie2`, `ivar_variants`)
 *  while the catalog names the module (`samtools`, `ivar`), so an exact match is
 *  tried first and a prefix match second, the same normalisation the compose
 *  endpoint applies when it decides which sections a report carries. Matching is
 *  case-insensitive on both arms: a report anchor can carry its tool's own casing
 *  (`iVar`) while the catalog always names the section lowercase (`ivar`), and the
 *  compose endpoint already lowercases both sides the same way.
 *
 *  A module can be present without a plot (a custom-content *table*, e.g.
 *  `summary_conformance_metrics`); the compose endpoint excludes those from what
 *  it offers (see `_multiqc_sections` in catalog_endpoints/routes.py), so this
 *  should not see one under normal operation. Prefer a plottable candidate
 *  anyway as defense in depth, rather than persisting a null `selected_plot`
 *  that only surfaces as a render-time failure. */
export async function multiqcConfigForSection(
  dcId: string,
  section: string | undefined,
): Promise<Record<string, unknown>> {
  const opts = await fetchMultiQCBuilderOptions(dcId);
  const modulePrefix = (anchor: string) => anchor.split(/[-_]/)[0];
  const norm = (s: string) => s.toLowerCase();
  const hasPlot = (m: string) => m === 'general_stats' || (opts.plots[m]?.length ?? 0) > 0;

  const candidates = section
    ? opts.modules.filter(
        (m) => norm(m) === norm(section) || norm(modulePrefix(m)) === norm(section),
      )
    : [];
  const anchor = candidates.find(hasPlot) ?? candidates[0] ?? opts.modules.find(hasPlot) ?? opts.modules[0];

  return {
    selected_module: anchor ?? null,
    selected_plot: (anchor && opts.plots[anchor]?.[0]) ?? null,
    selected_dataset: null,
    s3_locations: opts.s3_locations ?? [],
    is_general_stats: anchor === 'general_stats',
  };
}
