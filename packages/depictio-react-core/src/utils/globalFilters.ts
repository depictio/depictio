/**
 * Expand promoted global filters into synthetic ``InteractiveFilter`` entries
 * and merge them with the per-tab local filter array before it is sent to the
 * backend.
 *
 * A global filter may carry multiple ``GlobalFilterLink`` targets so it can
 * apply across data collections (e.g. ``sample_id`` in one DC maps to
 * ``sample`` in another). For each link whose ``dc_id`` is referenced on the
 * current tab we emit one synthetic filter; the backend already treats the
 * ``InteractiveFilter[]`` array uniformly.
 *
 * Local filters take precedence when a global filter targets the same
 * ``(dc_id, column_name)`` — typical case: a user opens a per-tab control
 * tuned for that view and wants it to override the dashboard-wide value.
 */

import type { GlobalFilterDef, InteractiveFilter, StoredMetadata } from '../api';

/**
 * Stable index for a synthetic StoredMetadata that surfaces a global filter
 * on a tab whose `stored_metadata` doesn't contain the source component.
 * Distinct from `syntheticIndex` (which keys synthetic InteractiveFilters):
 * those identify a (def, dc) pair for the backend, while this identifies a
 * single editable card for the rail.
 */
export const SYNTHETIC_COMPONENT_INDEX_PREFIX = '__global_card_';

export function syntheticComponentIndex(filterId: string): string {
  return `${SYNTHETIC_COMPONENT_INDEX_PREFIX}${filterId}`;
}

export function isSyntheticComponentIndex(index: string): boolean {
  return index.startsWith(SYNTHETIC_COMPONENT_INDEX_PREFIX);
}

export function filterIdFromSyntheticIndex(index: string): string | null {
  if (!isSyntheticComponentIndex(index)) return null;
  return index.slice(SYNTHETIC_COMPONENT_INDEX_PREFIX.length);
}

export interface SyntheticBuildResult {
  /** Synthetic interactive-component StoredMetadata entries to splice into
   *  the rail. One per active global filter that targets at least one DC on
   *  this tab — regardless of whether the source component also lives here.
   *  The rail renders these in a dedicated "Global filters" section at the
   *  top, so the visual surface for globals is uniform across tabs. */
   synthetic: StoredMetadata[];
  /** Set of native component indices that the rail should HIDE from the
   *  per-tab filter list, because an active global already covers them.
   *  Two reasons a native is hidden:
   *    - its `index` is the `source_component_index` of an active global
   *      (the original filter that was promoted), OR
   *    - its `(dc_id, column_name)` matches any active global's `links[]`
   *      on this tab — a different per-tab filter targets the same column
   *      and would shadow the global if both rendered.
   */
   hiddenNativeIndices: Set<string>;
}

/**
 * Compute the unified left-rail view model for global filters.
 *
 * For each `def` in `definitions` that targets a DC present on this tab,
 * emit ONE synthetic StoredMetadata so the rail renders a card in the
 * dedicated top "Global filters" section. The synthetic copies the def's
 * `display` styling (icon, custom color, title) so the card LOOKS like the
 * original component the user promoted — same identity across all tabs.
 *
 * Returns the synthetic cards plus the set of native indices the host
 * should suppress from the per-tab filter list to avoid duplicate UI for
 * the same logical filter.
 */
export function buildSyntheticInteractiveComponents(
  definitions: GlobalFilterDef[],
  tabComponents: StoredMetadata[],
  dcIdsOnTab: Iterable<string>,
): SyntheticBuildResult {
  const tabDcSet = new Set(dcIdsOnTab);
  const componentsByIndex = new Map(tabComponents.map((c) => [c.index, c] as const));

  const synthetic: StoredMetadata[] = [];
  const hiddenNativeIndices = new Set<string>();

  for (const def of definitions) {
    // Prefer a link whose dc_id is actually on this tab; without one, the
    // global filter has no UI here at all.
    const link = def.links.find((l) => tabDcSet.has(l.dc_id));
    if (!link) continue;

    // Native source on this tab → hide it; the synthetic above takes over.
    const nativeSource = componentsByIndex.get(def.source_component_index);
    if (nativeSource) hiddenNativeIndices.add(nativeSource.index);

    // Also hide any OTHER per-tab interactive that targets the same
    // (dc_id, column_name) as one of the def's links — those would be a
    // redundant per-tab filter for a column the global already controls.
    for (const c of tabComponents) {
      const meta = c as unknown as {
        index: string;
        component_type?: string;
        dc_id?: string;
        column_name?: string;
      };
      if (meta.component_type !== 'interactive') continue;
      if (!meta.dc_id || !meta.column_name) continue;
      if (
        def.links.some(
          (l) => l.dc_id === meta.dc_id && l.column_name === meta.column_name,
        )
      ) {
        hiddenNativeIndices.add(meta.index);
      }
    }

    const display = def.display ?? {};
    synthetic.push({
      index: syntheticComponentIndex(def.id),
      component_type: 'interactive',
      interactive_component_type: def.interactive_component_type,
      column_name: link.column_name,
      column_type: def.column_type,
      wf_id: link.wf_id,
      dc_id: link.dc_id,
      default_state: def.default_state,
      // Styling preservation: use the promotion-time display fields so the
      // card looks identical wherever it renders. Fall back to def.label
      // for the title; never let the title be empty.
      title: display.title || def.label,
      custom_color: display.custom_color,
      icon_name: display.icon_name,
      title_size: display.title_size,
    } as unknown as StoredMetadata);
  }

  return { synthetic, hiddenNativeIndices };
}

/**
 * `__global_<filterId>__<dcId>` — unique per (definition, target DC) so two
 * links from the same global filter don't collide in `mergeFiltersBySource`'s
 * index dedup.
 */
function syntheticIndex(filterId: string, dcId: string): string {
  return `__global_${filterId}__${dcId}`;
}

export function isEmptyGlobalValue(v: unknown): boolean {
  return v === null || v === undefined || (Array.isArray(v) && v.length === 0) || v === '';
}

/**
 * Combine the per-tab local filter array with the active set of global
 * filters, expanding each global definition's links into one synthetic filter
 * per (link, target-on-tab).
 *
 * @param localFilters   Filters produced by per-tab interactive components +
 *                       chart/table selections.
 * @param definitions    All currently-promoted global filters for the
 *                       dashboard family.
 * @param values         Per-user current values keyed by filter id. A missing
 *                       or empty value yields no synthetic filter for that id.
 * @param dcIdsOnTab     The set of `dc_id`s referenced by components on the
 *                       currently-rendered tab. Synthetic filters are emitted
 *                       only when a link's `dc_id` appears here.
 */
export function mergeWithGlobal(
  localFilters: InteractiveFilter[],
  definitions: GlobalFilterDef[],
  values: Record<string, unknown>,
  dcIdsOnTab: Iterable<string>,
): InteractiveFilter[] {
  const tabDcSet = new Set(dcIdsOnTab);

  // Build the precedence map from local filters: `(dc_id, column_name)` →
  // present. Synthetic globals skip entries that already collide with a local
  // filter on the same (dc, column).
  const localScopes = new Set<string>();
  for (const f of localFilters) {
    const dc = f.metadata?.dc_id;
    const col = f.metadata?.column_name ?? f.column_name;
    if (dc && col) localScopes.add(`${dc}::${col}`);
  }

  const synthetic: InteractiveFilter[] = [];
  for (const def of definitions) {
    const value = values[def.id];
    if (isEmptyGlobalValue(value)) continue;
    for (const link of def.links) {
      if (!tabDcSet.has(link.dc_id)) continue;
      if (localScopes.has(`${link.dc_id}::${link.column_name}`)) continue;
      synthetic.push({
        index: syntheticIndex(def.id, link.dc_id),
        value,
        column_name: link.column_name,
        interactive_component_type: def.interactive_component_type,
        metadata: {
          dc_id: link.dc_id,
          column_name: link.column_name,
          interactive_component_type: def.interactive_component_type,
        },
      });
    }
  }

  return [...localFilters, ...synthetic];
}
