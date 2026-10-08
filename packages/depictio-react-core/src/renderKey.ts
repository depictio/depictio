/**
 * When does a renderer have to fetch again?
 *
 * Every server-rendered component keys its fetch effect on `metadata.index`,
 * which is the component's *identity* and by design does not move. That is
 * correct for the normal edit flow, where changing a chart navigates away and
 * back, but wrong for anything that swaps a component's definition underneath
 * a mounted renderer:
 *
 *   - restoring one component from a past version;
 *   - a dashboard-wide restore;
 *   - any future in-place edit.
 *
 * In all of those the id is unchanged and the definition is not, so the
 * renderer keeps showing the old chart until the page is reloaded. Cards do
 * not have the problem: their values come from the dashboard's bulk-compute
 * pass, which re-runs when the document changes.
 *
 * A fingerprint of the fields that decide *what is drawn* closes it. Deriving
 * it from the metadata rather than bumping a counter means it works no matter
 * who changed the component, including code that does not know this mechanism
 * exists.
 */

import type { StoredMetadata } from './api';

/**
 * Fields that change what a component renders.
 *
 * Presentation-only fields (position, size, colour of the title) are excluded:
 * they change often and none of them require a round trip, so including them
 * would refetch on every drag.
 *
 * `dc_id` and `wf_id` are included because a component repointed at another
 * collection must certainly reload.
 */
const RENDER_DEFINING_FIELDS = [
  'dc_id',
  'wf_id',
  'visu_type',
  'dict_kwargs',
  'mode',
  'code_content',
  'column_name',
  'aggregation',
  'aggregations',
  'breakdown_col',
  'columns',
  'visible_columns',
  'column_order',
  'selected_module',
  'selected_plot',
  'last_updated',
] as const;

/**
 * A stable string that changes exactly when the component's rendered output
 * should change.
 *
 * `last_updated` is in the list and does most of the work in practice, since
 * the save path stamps it. The explicit fields are what make this correct when
 * a write forgets to, which a restore writing a stored snapshot verbatim
 * plausibly could.
 */
export function renderDefinitionKey(metadata: StoredMetadata | null | undefined): string {
  if (!metadata) return '';
  const source = metadata as unknown as Record<string, unknown>;
  const parts: unknown[] = [];
  for (const field of RENDER_DEFINING_FIELDS) {
    parts.push(source[field] ?? null);
  }
  return JSON.stringify(parts);
}
