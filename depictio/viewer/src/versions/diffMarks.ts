/**
 * Turning a diff report into things the canvas and the drawer can show.
 *
 * The report's component ids are `stored_metadata[].index` — the same id
 * `DashboardGrid` stamps as `data-component-id` and the render endpoints match
 * on — so no translation layer is needed between "what changed" and "which
 * tile".
 */

import type { VersionComponentDiff, VersionDiff } from 'depictio-react-core';

/** How a tile is marked. `moved` is distinct from `modified` because the two
 *  mean different things to a reader: one is the same chart somewhere else, the
 *  other is a different chart in the same place. */
export type DiffMark = 'added' | 'modified' | 'moved';

export type DiffMarks = Record<string, DiffMark>;

/** Marks for one tab's components, keyed by component index. */
export function marksForTab(diff: VersionDiff | null, tabId: string | null): DiffMarks {
  if (!diff || !tabId) return {};
  const tab = diff.tabs.find((t) => t.tab_id === tabId);
  if (!tab) return {};

  const marks: DiffMarks = {};
  for (const component of tab.components) {
    if (component.change === 'added') {
      marks[component.index] = 'added';
    } else if (component.change === 'modified') {
      // A component can be both; config changes are the more consequential of
      // the two to look at, so they win the single slot.
      marks[component.index] = component.modified_config ? 'modified' : 'moved';
    }
  }
  return marks;
}

/** Components removed since the base version, with the grid box they occupied. */
export function ghostsForTab(diff: VersionDiff | null, tabId: string | null) {
  if (!diff || !tabId) return [];
  const tab = diff.tabs.find((t) => t.tab_id === tabId);
  if (!tab) return [];
  return tab.components
    .filter((c) => c.change === 'removed' && c.layout_before)
    .map((c) => ({
      index: c.index,
      title: c.title ?? c.component_type ?? 'component',
      layout: c.layout_before!,
    }));
}

/** Dotted config paths → something a person would say.
 *
 *  Deliberately partial: an unmapped path falls through to itself, which is
 *  still more useful than "reconfigured" and makes the gap visible rather than
 *  hiding it behind a generic label. */
const FIELD_LABELS: Record<string, string> = {
  'dict_kwargs.x': 'x axis',
  'dict_kwargs.y': 'y axis',
  'dict_kwargs.color': 'colour',
  'dict_kwargs.size': 'point size',
  'dict_kwargs.facet_col': 'facet column',
  'dict_kwargs.facet_row': 'facet row',
  visu_type: 'chart type',
  dc_id: 'data collection',
  wf_id: 'workflow',
  columns: 'columns',
  'columns.length': 'columns',
  column_name: 'column',
  aggregation: 'aggregation',
  aggregations: 'aggregations',
  code_content: 'code',
  title: 'title',
  cols_json: 'hidden columns',
};

export function labelForField(path: string): string {
  return FIELD_LABELS[path] ?? path;
}

/** "y axis, colour and 3 more" — the phrase the drawer row shows. */
export function describeChange(component: VersionComponentDiff): string {
  const parts: string[] = [];

  if (component.changed_fields.length) {
    const labels = component.changed_fields.map(labelForField);
    const shown = labels.slice(0, 3).join(', ');
    const hidden = labels.length - 3 + component.changed_fields_truncated;
    parts.push(hidden > 0 ? `${shown} and ${hidden} more` : shown);
  }
  if (component.moved) parts.push('moved');
  if (component.resized) parts.push('resized');

  return parts.join(' · ');
}

/** "2 added, 1 removed, 3 changed" — empty when a version changed nothing but
 *  its own metadata, which is a real and worth-stating outcome. */
export function summariseDiff(diff: VersionDiff | null): string {
  if (!diff) return '';
  const { added, removed, modified, tabs_added, tabs_removed } = diff.totals;
  const parts: string[] = [];
  if (added) parts.push(`${added} added`);
  if (removed) parts.push(`${removed} removed`);
  if (modified) parts.push(`${modified} changed`);
  if (tabs_added) parts.push(`${tabs_added} tab${tabs_added > 1 ? 's' : ''} added`);
  if (tabs_removed) parts.push(`${tabs_removed} tab${tabs_removed > 1 ? 's' : ''} removed`);
  return parts.join(', ');
}
