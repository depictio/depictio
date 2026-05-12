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

import type { GlobalFilterDef, InteractiveFilter } from '../api';

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
