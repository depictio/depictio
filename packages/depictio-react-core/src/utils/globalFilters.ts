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
  /** Synthetic interactive-component StoredMetadata entries to splice into the
   *  rail. One per global filter whose source component isn't on this tab AND
   *  which has at least one link targeting a DC present on this tab. */
  synthetic: StoredMetadata[];
  /** def.id → tabComponent.index for global filters whose source DOES live on
   *  this tab (native promotion). The rail uses this to decorate the existing
   *  card rather than emit a synthetic copy. */
  promotedIndexByDefId: Map<string, string>;
}

/**
 * Compute the inline-promotion view model for the left rail.
 *
 * For each `def` in `definitions`:
 *   - If a component in `tabComponents` has `index === def.source_component_index`,
 *     record `promotedIndexByDefId.set(def.id, comp.index)` — the rail keeps
 *     that component as-is and decorates it (blue stripe + globe badge).
 *   - Otherwise, if any of `def.links[].dc_id` is in `dcIdsOnTab`, emit one
 *     synthetic StoredMetadata using the first matching link's
 *     `(wf_id, dc_id, column_name)`. The synthetic shares the def's
 *     `interactive_component_type`, `column_type`, and `default_state` so the
 *     existing ComponentRenderer pipeline can render it identically to a
 *     native filter card.
 *   - Otherwise (no source component AND no matching DC on this tab), skip
 *     — the filter still applies via mergeWithGlobal but has no UI here.
 */
export function buildSyntheticInteractiveComponents(
  definitions: GlobalFilterDef[],
  tabComponents: StoredMetadata[],
  dcIdsOnTab: Iterable<string>,
): SyntheticBuildResult {
  const tabDcSet = new Set<string>();
  for (const d of dcIdsOnTab) tabDcSet.add(d);
  const componentsByIndex = new Map<string, StoredMetadata>();
  for (const c of tabComponents) componentsByIndex.set(c.index, c);

  const synthetic: StoredMetadata[] = [];
  const promotedIndexByDefId = new Map<string, string>();

  for (const def of definitions) {
    const native = componentsByIndex.get(def.source_component_index);
    if (native) {
      promotedIndexByDefId.set(def.id, native.index);
      continue;
    }
    const link = def.links.find((l) => tabDcSet.has(l.dc_id));
    if (!link) continue;
    synthetic.push({
      index: syntheticComponentIndex(def.id),
      component_type: 'interactive',
      interactive_component_type: def.interactive_component_type,
      column_name: link.column_name,
      column_type: def.column_type,
      wf_id: link.wf_id,
      dc_id: link.dc_id,
      default_state: def.default_state,
      // `title` is rendered by ComponentRenderer's chrome; the def.label is
      // the user-facing name picked at promotion time.
      title: def.label,
    } as unknown as StoredMetadata);
  }

  return { synthetic, promotedIndexByDefId };
}

/**
 * `__global_<filterId>__<dcId>` — unique per (definition, target DC) so two
 * links from the same global filter don't collide in `mergeFiltersBySource`'s
 * index dedup.
 */
function syntheticIndex(filterId: string, dcId: string): string {
  return `__global_${filterId}__${dcId}`;
}

function isEmptyValue(v: unknown): boolean {
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
  const tabDcSet = new Set<string>();
  for (const d of dcIdsOnTab) tabDcSet.add(d);

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
    if (isEmptyValue(value)) continue;
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
