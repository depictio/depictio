/**
 * Shared role-mapping → per-kind Pydantic config-blob translator.
 *
 * Both the live preview (AdvancedVizPreview) and the persisted save path
 * (buildMetadata.buildAdvancedViz) build the exact same shape from the
 * builder's `column_mapping`. Keeping a single helper avoids drift where
 * one path serialises a new role differently from the other.
 *
 * Mirrors depictio/models/components/advanced_viz/configs.py: most roles
 * serialise as `<role>_col`; sunburst's hierarchical `ranks` and sankey's
 * ordered `steps` are list-typed (→ `rank_cols` / `step_cols`); embedding's
 * `compute_method` is a scalar pick (pca/umap/tsne/pcoa), not a column reference.
 */
export function buildAdvancedVizConfigBlob(
  vizKind: string | undefined,
  columnMapping: Record<string, string | string[]>,
  presetConfig?: Record<string, unknown> | null,
): Record<string, unknown> {
  const blob: Record<string, unknown> = { viz_kind: vizKind };
  for (const [role, value] of Object.entries(columnMapping)) {
    if (vizKind === 'sunburst' && role === 'ranks') {
      blob.rank_cols = value;
    } else if (vizKind === 'sankey' && role === 'steps') {
      blob.step_cols = value;
    } else if (vizKind === 'complex_heatmap' && role === 'index') {
      // ComplexHeatmapConfig's row-id field is `index_column`, NOT the generic
      // `<role>_col` — emitting `index_col` would be dropped and the compute
      // task would fall back to its "sample_id" default and fail the select.
      blob.index_column = value;
    } else if (role === 'value_columns' || role === 'row_annotation_cols') {
      // List-typed config fields whose key already matches the model field.
      blob[role] = value;
    } else if (role === 'compute_method') {
      blob.compute_method = value;
    } else {
      blob[`${role}_col`] = value;
    }
  }
  // Persist a sensible default view_mode so the renderer never has to
  // auto-detect from live data (which may differ from the catalog fixture).
  // Multi-sample (sample role bound) → aggregate; single-sample → overlay.
  if (vizKind === 'coverage_track') {
    blob.view_mode = columnMapping.sample ? 'aggregate' : 'overlay';
  }
  // Overlay the catalog/live viz-control extras (e.g. manhattan score_threshold,
  // top_n_labels, marker sizes) the preview rendered with — but never let them
  // override the role bindings derived from the *current* column_mapping, which
  // reflect any edits made in the builder. See extractVizControlExtras.
  return { ...blob, ...extractVizControlExtras(presetConfig) };
}

/** Role-derived / structural keys that `buildAdvancedVizConfigBlob` owns from
 *  the column_mapping. Everything else in a preset config is a viz-control
 *  extra (threshold, top-N, marker size…) worth carrying through verbatim. */
function isRoleDerivedKey(key: string): boolean {
  return (
    key.endsWith('_col') ||
    key === 'viz_kind' ||
    key === 'rank_cols' ||
    key === 'compute_method' ||
    key === 'view_mode'
  );
}

/** Pick the non-role viz-control keys out of a catalog/live preset config so
 *  they can be overlaid on a freshly-built blob without clobbering bindings. */
export function extractVizControlExtras(
  presetConfig?: Record<string, unknown> | null,
): Record<string, unknown> {
  if (!presetConfig) return {};
  const extras: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(presetConfig)) {
    if (!isRoleDerivedKey(k)) extras[k] = v;
  }
  return extras;
}
