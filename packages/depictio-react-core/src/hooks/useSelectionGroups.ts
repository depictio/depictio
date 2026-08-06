import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { BulkComputeOptions, InteractiveFilter } from '../api';
import type { GroupSummaryRow } from '../components/interactive/ActiveFilterSummary';
import {
  COLOR_BY_NONE,
  groupFromSelectionFilter,
  groupsRenderPayload,
  groupsToFilters,
  nextGroupColor,
  readSelectionGroups,
  uniqueGroupName,
  writeSelectionGroups,
  type ColorByState,
  type GroupingDisplay,
  type GroupRenderDef,
  type SelectionGroup,
} from '../selectionGroups';

/**
 * Per-dashboard selection-group state, shared verbatim by the viewer and
 * editor roots so both apps see the same groups (they share the localStorage
 * key). Groups are annotation state: they sit *next to* the filter list, and
 * the roots compose `groupFilters` into the fetch-bound list themselves.
 */
export interface SelectionGroupsApi {
  groups: SelectionGroup[];
  /** Dashboard-global "Color by": nothing, the saved groups, or a column. */
  colorBy: ColorByState;
  /** Global "compare groups in cards" toggle. */
  compareInCards: boolean;
  /** Overlay ("color") vs small-multiples ("facet") display of the override. */
  displayMode: GroupingDisplay;
  /** Whether ungrouped rows render as gray "Other" in groups mode. */
  showOther: boolean;
  /** Whether card comparisons include the "All rows" reference entry. */
  showOverall: boolean;
  /** Snapshot a selection filter into a new group. Returns the created group,
   *  or null when the filter isn't usable (empty, oversized, no column). */
  createGroupFromFilter: (
    filter: InteractiveFilter,
    name: string,
    color?: string,
  ) => SelectionGroup | null;
  /** Patch a group's name and/or color (empty/absent fields are ignored). */
  updateGroup: (id: string, patch: { name?: string; color?: string }) => void;
  deleteGroup: (id: string) => void;
  toggleGroupFilter: (id: string) => void;
  /** Turn off every group's filter participation (dashboard "Reset all"). */
  deactivateAllGroupFilters: () => void;
  setColorBy: (next: ColorByState) => void;
  setCompareInCards: (on: boolean) => void;
  setDisplayMode: (mode: GroupingDisplay) => void;
  setShowOther: (on: boolean) => void;
  setShowOverall: (on: boolean) => void;
  /** Projection of filter-active groups into dashboard filters (memoised). */
  groupFilters: InteractiveFilter[];
  /** Render-payload shape for the figure endpoint (memoised). */
  renderGroups: GroupRenderDef[];
  /** Filter-active groups as removable rows for the active-filter summary
   *  (they narrow the data like any filter but live outside the filter list,
   *  so they get their own rows instead of riding onFilterChange). */
  summaryRows: GroupSummaryRow[];
  /** ``bulkComputeCards`` options while "Compare groups in cards" is live,
   *  ``undefined`` otherwise — so effects keyed on it don't refire on group
   *  edits while the comparison is off. */
  bulkOptions: BulkComputeOptions | undefined;
}

export function useSelectionGroups(dashboardId: string | undefined): SelectionGroupsApi {
  // One storage read shared by all six initialisers (per-state lazy
  // initialisers would each re-parse the same localStorage payload).
  const [stored] = useState(() => (dashboardId ? readSelectionGroups(dashboardId) : null));
  const [groups, setGroups] = useState<SelectionGroup[]>(stored?.groups ?? []);
  const [colorBy, setColorByState] = useState<ColorByState>(stored?.colorBy ?? COLOR_BY_NONE);
  const [compareInCards, setCompareInCardsState] = useState<boolean>(
    stored?.compareInCards ?? false,
  );
  const [displayMode, setDisplayModeState] = useState<GroupingDisplay>(
    stored?.displayMode ?? 'color',
  );
  const [showOther, setShowOtherState] = useState<boolean>(stored?.showOther ?? true);
  const [showOverall, setShowOverallState] = useState<boolean>(stored?.showOverall ?? true);

  // Re-hydrate when the mounted app switches dashboards under us.
  const idRef = useRef(dashboardId);
  useEffect(() => {
    if (idRef.current === dashboardId) return;
    idRef.current = dashboardId;
    const stored = dashboardId ? readSelectionGroups(dashboardId) : null;
    setGroups(stored?.groups ?? []);
    setColorByState(stored?.colorBy ?? COLOR_BY_NONE);
    setCompareInCardsState(stored?.compareInCards ?? false);
    setDisplayModeState(stored?.displayMode ?? 'color');
    setShowOtherState(stored?.showOther ?? true);
    setShowOverallState(stored?.showOverall ?? true);
  }, [dashboardId]);

  // Write-through: any state change lands in storage so a reload (or the
  // sibling viewer/editor app) picks it up.
  useEffect(() => {
    if (!dashboardId) return;
    writeSelectionGroups(
      dashboardId,
      groups,
      colorBy,
      compareInCards,
      displayMode,
      showOther,
      showOverall,
    );
  }, [dashboardId, groups, colorBy, compareInCards, displayMode, showOther, showOverall]);

  // Mirror of `groups` so `createGroupFromFilter` can build the group outside
  // the state updater (updaters are double-invoked under StrictMode and must
  // stay pure — id generation isn't).
  const groupsRef = useRef(groups);
  groupsRef.current = groups;

  const createGroupFromFilter = useCallback(
    (filter: InteractiveFilter, name: string, color?: string): SelectionGroup | null => {
      const created = groupFromSelectionFilter(
        filter,
        // Names are identity on the wire (server dedups by name) — suffix
        // rather than let a duplicate silently vanish from coloring/compare.
        uniqueGroupName(name, groupsRef.current),
        color ?? nextGroupColor(groupsRef.current),
      );
      if (created) setGroups((prev) => [...prev, created]);
      return created;
    },
    [],
  );

  const updateGroup = useCallback((id: string, patch: { name?: string; color?: string }) => {
    // Renames go through the same uniqueness rule as creation (see above).
    const name = patch.name?.trim()
      ? uniqueGroupName(patch.name, groupsRef.current, id)
      : undefined;
    const color = patch.color;
    if (!name && !color) return;
    setGroups((prev) =>
      prev.map((g) =>
        g.id === id ? { ...g, ...(name ? { name } : {}), ...(color ? { color } : {}) } : g,
      ),
    );
  }, []);

  const deleteGroup = useCallback((id: string) => {
    // Deleting the last group while coloring/comparing by groups leaves a
    // dangling mode; degrade rather than keep a stale toggle. The decision
    // reads the ref (updaters must stay pure under StrictMode); the removal
    // itself is a functional update so rapid deletes compose.
    if (groupsRef.current.filter((g) => g.id !== id).length === 0) {
      setColorByState((cb) => (cb.kind === 'groups' ? COLOR_BY_NONE : cb));
      setCompareInCardsState(false);
    }
    setGroups((prev) => prev.filter((g) => g.id !== id));
  }, []);

  const toggleGroupFilter = useCallback((id: string) => {
    setGroups((prev) =>
      prev.map((g) => (g.id === id ? { ...g, filterActive: !g.filterActive } : g)),
    );
  }, []);

  const deactivateAllGroupFilters = useCallback(() => {
    setGroups((prev) =>
      prev.some((g) => g.filterActive) ? prev.map((g) => ({ ...g, filterActive: false })) : prev,
    );
  }, []);

  const groupFilters = useMemo(() => groupsToFilters(groups), [groups]);
  const renderGroups = useMemo(() => groupsRenderPayload(groups), [groups]);

  const summaryRows = useMemo<GroupSummaryRow[]>(
    () =>
      groups
        .filter((g) => g.filterActive)
        .map((g) => ({
          id: g.id,
          name: g.name,
          color: g.color,
          count: g.values.length,
          onClear: () => toggleGroupFilter(g.id),
        })),
    [groups, toggleGroupFilter],
  );

  const bulkOptions = useMemo<BulkComputeOptions | undefined>(
    () =>
      compareInCards && renderGroups.length > 0
        ? { groups: renderGroups, compareGroups: true, showOther, showOverall }
        : undefined,
    [compareInCards, renderGroups, showOther, showOverall],
  );

  return useMemo(
    () => ({
      groups,
      colorBy,
      compareInCards,
      displayMode,
      showOther,
      showOverall,
      createGroupFromFilter,
      updateGroup,
      deleteGroup,
      toggleGroupFilter,
      deactivateAllGroupFilters,
      // React state setters are identity-stable — expose them directly.
      setColorBy: setColorByState,
      setCompareInCards: setCompareInCardsState,
      setDisplayMode: setDisplayModeState,
      setShowOther: setShowOtherState,
      setShowOverall: setShowOverallState,
      groupFilters,
      renderGroups,
      summaryRows,
      bulkOptions,
    }),
    [
      groups,
      colorBy,
      compareInCards,
      displayMode,
      showOther,
      showOverall,
      createGroupFromFilter,
      updateGroup,
      deleteGroup,
      toggleGroupFilter,
      deactivateAllGroupFilters,
      groupFilters,
      renderGroups,
      summaryRows,
      bulkOptions,
    ],
  );
}

export default useSelectionGroups;
