/**
 * Shared role-mapping → per-kind Pydantic config-blob translator.
 *
 * Both the live preview (AdvancedVizPreview) and the persisted save path
 * (buildMetadata.buildAdvancedViz) build the exact same shape from the
 * builder's `column_mapping`. Keeping a single helper avoids drift where
 * one path serialises a new role differently from the other.
 *
 * Mirrors depictio/models/components/advanced_viz/configs.py: most roles
 * serialise as `<role>_col`, and the exceptions are listed in one table below.
 */
/** Bindings whose config key is not the generic `<role>_col`.
 *
 *  One table, read by all three directions below: building a blob, inverting a
 *  blob, and deciding whether a preset key is a binding or a viz control. They
 *  were three parallel lists, and two of them had already drifted apart, which
 *  is most of what this module now exists to prevent.
 *
 *  `kind` scopes a rule to one viz kind where the same role name means
 *  different things elsewhere. */
const IRREGULAR_BINDINGS: readonly { kind?: string; role: string; key: string }[] = [
  { kind: 'sunburst', role: 'ranks', key: 'rank_cols' },
  { kind: 'sankey', role: 'steps', key: 'step_cols' },
  // ComplexHeatmapConfig's row-id field is `index_column`, NOT the generic
  // `<role>_col` — emitting `index_col` would be dropped and the compute task
  // would fall back to its "sample_id" default and fail the select.
  { kind: 'complex_heatmap', role: 'index', key: 'index_column' },
  // List-typed config fields whose key already matches the model field.
  { role: 'value_columns', key: 'value_columns' },
  { role: 'row_annotation_cols', key: 'row_annotation_cols' },
  // Not a column reference at all: a scalar pick (pca/umap/tsne/pcoa).
  { role: 'compute_method', key: 'compute_method' },
];

const scoped = (b: { kind?: string }, vizKind: string | undefined) => !b.kind || b.kind === vizKind;

export function buildAdvancedVizConfigBlob(
  vizKind: string | undefined,
  columnMapping: Record<string, string | string[]>,
  presetConfig?: Record<string, unknown> | null,
): Record<string, unknown> {
  const blob: Record<string, unknown> = { viz_kind: vizKind };
  for (const [role, value] of Object.entries(columnMapping)) {
    const irregular = IRREGULAR_BINDINGS.find((b) => b.role === role && scoped(b, vizKind));
    blob[irregular ? irregular.key : `${role}_col`] = value;
  }
  // Persist a sensible default view_mode so the renderer never has to
  // auto-detect from live data (which may differ from the catalog fixture).
  // Multi-sample (sample role bound) → aggregate; single-sample → overlay.
  //
  // Only a *default*: a preset that already carries a view_mode is a choice
  // someone made, so leave the key unset here and let the fallback layer below
  // supply theirs instead of recomputing over the top of it.
  if (vizKind === 'coverage_track' && !(presetConfig && 'view_mode' in presetConfig)) {
    blob.view_mode = columnMapping.sample ? 'aggregate' : 'overlay';
  }
  // Three layers, lowest first:
  //  - role-derived keys the preset carries that this mapping cannot produce
  //    (see extractRoleDerivedFallbacks),
  //  - the bindings just derived from `column_mapping`, which reflect any edits
  //    made in the builder and therefore win,
  //  - the viz-control extras (manhattan score_threshold, top_n_labels, marker
  //    sizes...) the preview rendered with.
  return {
    ...extractRoleDerivedFallbacks(presetConfig, blob),
    ...blob,
    ...extractVizControlExtras(presetConfig),
  };
}

const IRREGULAR_BINDING_KEYS: readonly string[] = IRREGULAR_BINDINGS.map((b) => b.key);

/** Role-derived / structural keys that `buildAdvancedVizConfigBlob` owns from
 *  the column_mapping. Everything else in a preset config is a viz-control
 *  extra (threshold, top-N, marker size…) worth carrying through verbatim.
 *
 *  The irregular keys must be consulted, not just `endsWith('_col')`: they all
 *  fail that test, so treating it as the whole rule filed them as viz-control
 *  extras, and extras are overlaid *last*. A preset's copy of a binding then
 *  won over the one the user had just edited, inverting the layer order above. */
function isRoleDerivedKey(key: string): boolean {
  return (
    key.endsWith('_col') ||
    key === 'viz_kind' ||
    key === 'view_mode' ||
    IRREGULAR_BINDING_KEYS.includes(key)
  );
}

/** The inverse of `buildAdvancedVizConfigBlob`'s binding mapping: a grounded
 *  config blob back to the builder's flat `role → column` map.
 *
 *  Needed because a catalog render's `roles` is only what the YAML declared,
 *  while the blob the backend ships alongside it is fully grounded against the
 *  data. A sunburst declares `roles: {abundance: …}` and nothing else; its
 *  hierarchy is inferred server-side and arrives *only* as `rank_cols`. Without
 *  this inverse the builder's binding form never learns the hierarchy exists,
 *  so an offer that previews correctly reports "needs at least 2 rank columns"
 *  the moment you open it for editing. */
export function rolesFromConfigBlob(
  vizKind: string | undefined,
  blob: Record<string, unknown> | null | undefined,
): Record<string, string | string[]> {
  if (!blob) return {};
  const roles: Record<string, string | string[]> = {};
  for (const [key, value] of Object.entries(blob)) {
    if (value == null) continue;
    // Structural, not a binding: viz_kind names the kind and view_mode is a
    // display choice that happens to be classified role-derived above.
    if (key === 'viz_kind' || key === 'view_mode') continue;

    const irregular = IRREGULAR_BINDINGS.find((b) => b.key === key && scoped(b, vizKind));
    if (irregular) {
      roles[irregular.role] = value as string | string[];
    } else if (key.endsWith('_col')) {
      roles[key.slice(0, -'_col'.length)] = value as string | string[];
    }
    // Anything else is a viz-control extra, not a binding.
  }
  return roles;
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

/** Role-derived keys a preset config carries that the current `column_mapping`
 *  has no way to produce.
 *
 *  The catalog's `roles` is a flat role→column map, so a list-typed binding has
 *  no role to travel in: a sunburst's `rank_cols` is derived from the data by
 *  the catalog and arrives *only* in the preset. Dropping it — which is what
 *  treating every role-derived key as "the mapping owns this" used to do — left
 *  the added component with an abundance column and no hierarchy, and it
 *  rendered "missing data binding".
 *
 *  Only keys absent from `blob` are filled in, so an actual binding from the
 *  mapping is never overridden. */
function extractRoleDerivedFallbacks(
  presetConfig: Record<string, unknown> | null | undefined,
  blob: Record<string, unknown>,
): Record<string, unknown> {
  if (!presetConfig) return {};
  const fallbacks: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(presetConfig)) {
    if (!isRoleDerivedKey(k)) continue; // already carried by the extras layer
    if (k in blob) continue; // the mapping produced it — that one wins
    fallbacks[k] = v;
  }
  return fallbacks;
}


/** The config a component actually renders with: the catalog or previously
 *  saved preset underneath, the author's own Tier-2 edits on top.
 *
 *  The live preview and the save path have to layer these identically or the
 *  component lands on the dashboard looking unlike the preview that sold it, so
 *  both call this rather than each spelling the merge out. */
export function mergedPresetConfig(c: {
  preset_config?: Record<string, unknown> | null;
  config?: Record<string, unknown> | null;
  viz_overrides?: Record<string, unknown> | null;
}): Record<string, unknown> | null {
  const inherited = c.preset_config ?? c.config ?? null;
  const overrides = c.viz_overrides ?? null;
  if (!inherited && !overrides) return null;
  return { ...(inherited ?? {}), ...(overrides ?? {}) };
}
