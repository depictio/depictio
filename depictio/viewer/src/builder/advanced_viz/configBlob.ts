/**
 * Shared role-mapping → per-kind Pydantic config-blob translator.
 *
 * Both the live preview (AdvancedVizPreview) and the persisted save path
 * (buildMetadata.buildAdvancedViz) build the exact same shape from the
 * builder's `column_mapping`. Keeping a single helper avoids drift where
 * one path serialises a new role differently from the other.
 *
 * Mirrors depictio/models/components/advanced_viz/configs.py: most roles
 * serialise as `<role>_col`; sunburst's hierarchical `ranks` is list-typed
 * (→ `rank_cols`); embedding's `compute_method` is a scalar pick
 * (pca/umap/tsne/pcoa), not a column reference.
 */
export function buildAdvancedVizConfigBlob(
  vizKind: string | undefined,
  columnMapping: Record<string, string | string[]>,
): Record<string, unknown> {
  const blob: Record<string, unknown> = { viz_kind: vizKind };
  for (const [role, value] of Object.entries(columnMapping)) {
    if (vizKind === 'sunburst' && role === 'ranks') {
      blob.rank_cols = value;
    } else if (role === 'compute_method') {
      blob.compute_method = value;
    } else {
      blob[`${role}_col`] = value;
    }
  }
  return blob;
}
