/**
 * The selection groups store of a static bundle: in memory, seeded from the
 * manifest.
 *
 * The viewer keeps a dashboard's groups, colour-by and split in localStorage
 * (`depictio:selection-groups:<family>`), so they outlive a reload and are
 * shared with the editor. A file has neither: a group a reader makes is theirs
 * for as long as the page is open, not written anywhere (`localStorage` is also
 * blocked on a file opened from disk in some browsers). This module replaces
 * the two storage functions of `selectionGroups.ts` and re-exports the rest
 * untouched, so `useSelectionGroups` and the panel run as in the live app.
 *
 * The store opens on the export's own state (`manifest.initial_grouping`): the
 * groups the exporter had, with the colour-by and split on. Reloading the page
 * goes back to it.
 */
import { rawBundle } from './bundle';
import {
  COLOR_BY_NONE,
  type ColorByState,
  type GroupingDisplay,
  type SelectionGroup,
  type SelectionGroupsPayload,
} from '../../../../packages/depictio-react-core/src/selectionGroups';

export * from '../../../../packages/depictio-react-core/src/selectionGroups';

/** The state the page opens on, from the manifest; null when it carries none. */
export function initialSelectionGroups(): SelectionGroupsPayload | null {
  const grouping = rawBundle().initial_grouping;
  if (!grouping) return null;
  const groups: SelectionGroup[] = grouping.groups.map((g) => ({
    id: g.id,
    name: g.name,
    color: g.color,
    dcId: g.dc_id ?? undefined,
    columnName: g.column_name,
    values: [...g.values],
    createdAt: g.created_at,
    filterActive: g.filter_active,
  }));
  let colorBy: ColorByState = COLOR_BY_NONE;
  if (grouping.color_by.kind === 'groups') colorBy = { kind: 'groups' };
  else if (grouping.color_by.kind === 'column' && grouping.color_by.column_name) {
    colorBy = { kind: 'column', columnName: grouping.color_by.column_name };
  }
  return {
    version: 2,
    groups,
    colorBy,
    compareInCards: false,
    displayMode: grouping.display_mode,
    showOther: grouping.show_other,
    showOverall: grouping.show_overall,
    // The analysis panel opens beside a view that is already grouped.
    analysisArmed: groups.length > 0 || colorBy.kind !== 'none',
  };
}

/** `undefined`: not read yet. The manifest is only loaded once the page boots. */
let memory: SelectionGroupsPayload | null | undefined;

export function readSelectionGroups(_dashboardId: string): SelectionGroupsPayload | null {
  if (memory === undefined) memory = initialSelectionGroups();
  return memory;
}

export function writeSelectionGroups(
  _dashboardId: string,
  groups: SelectionGroup[],
  colorBy: ColorByState,
  compareInCards: boolean,
  displayMode: GroupingDisplay = 'color',
  showOther = true,
  showOverall = true,
  analysisArmed = false,
): void {
  memory = {
    version: 2,
    groups,
    colorBy,
    compareInCards,
    displayMode,
    showOther,
    showOverall,
    analysisArmed,
  };
}
