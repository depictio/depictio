import type { InteractiveFilter, JBrowseTrackRow } from '../../api';

/**
 * Which tracks to hide and show to move the open set towards ``desired``.
 *
 * Only tracks in ``managed`` (the manifest's tracks) are ever hidden: an
 * annotation track or one the user opened from JBrowse's own track selector
 * stays put when the dashboard filters change.
 */
export function planTrackSync(
  open: string[],
  desired: string[],
  managed: Set<string>,
): { hide: string[]; show: string[] } {
  const want = new Set(desired);
  const isOpen = new Set(open);
  return {
    hide: open.filter((id) => managed.has(id) && !want.has(id)),
    show: desired.filter((id) => !isOpen.has(id)),
  };
}

/** Distinct selection-column values of the given tracks, in track order. */
export function selectionValuesFor(trackIds: string[], rows: JBrowseTrackRow[]): string[] {
  const byId = new Map(rows.map((r) => [r.track_id, r.selection_value]));
  const out: string[] = [];
  const seen = new Set<string>();
  for (const id of trackIds) {
    const v = byId.get(id);
    if (v == null || seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

/** Add ``value`` to the selection, or take it out when already there. */
export function toggleValue(current: string[], value: string): string[] {
  return current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
}

/**
 * The dashboard filter a genome-browser selection emits. ``dc_id`` is the
 * track manifest's, so link resolution carries it to the sample tables the
 * manifest is linked to (the phylogeny tree does the same with its metadata).
 */
export function jbrowseSelectionFilter(
  index: string,
  column: string,
  tracksDcId: string,
  values: string[],
): InteractiveFilter {
  return {
    index,
    value: values,
    column_name: column,
    source: 'jbrowse_selection',
    interactive_component_type: 'MultiSelect',
    metadata: {
      dc_id: tracksDcId,
      column_name: column,
      interactive_component_type: 'MultiSelect',
    },
  };
}
