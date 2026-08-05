import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { InteractiveFilter } from '../api';
import {
  groupFromSelectionFilter,
  groupsRenderPayload,
  groupsToFilters,
  nextGroupColor,
  readSelectionGroups,
  writeSelectionGroups,
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
  colorByGroup: boolean;
  /** Snapshot a selection filter into a new group. Returns the created group,
   *  or null when the filter isn't usable (empty, oversized, no column). */
  createGroupFromFilter: (
    filter: InteractiveFilter,
    name: string,
    color?: string,
  ) => SelectionGroup | null;
  renameGroup: (id: string, name: string) => void;
  deleteGroup: (id: string) => void;
  toggleGroupFilter: (id: string) => void;
  setColorByGroup: (on: boolean) => void;
  /** Projection of filter-active groups into dashboard filters (memoised). */
  groupFilters: InteractiveFilter[];
  /** Render-payload shape for the figure endpoint (memoised). */
  renderGroups: GroupRenderDef[];
}

export function useSelectionGroups(dashboardId: string | undefined): SelectionGroupsApi {
  const [groups, setGroups] = useState<SelectionGroup[]>(() =>
    dashboardId ? (readSelectionGroups(dashboardId)?.groups ?? []) : [],
  );
  const [colorByGroup, setColorByGroupState] = useState<boolean>(() =>
    dashboardId ? (readSelectionGroups(dashboardId)?.colorByGroup ?? false) : false,
  );

  // Re-hydrate when the mounted app switches dashboards under us.
  const idRef = useRef(dashboardId);
  useEffect(() => {
    if (idRef.current === dashboardId) return;
    idRef.current = dashboardId;
    const stored = dashboardId ? readSelectionGroups(dashboardId) : null;
    setGroups(stored?.groups ?? []);
    setColorByGroupState(stored?.colorByGroup ?? false);
  }, [dashboardId]);

  // Write-through: any state change lands in storage so a reload (or the
  // sibling viewer/editor app) picks it up.
  useEffect(() => {
    if (!dashboardId) return;
    writeSelectionGroups(dashboardId, groups, colorByGroup);
  }, [dashboardId, groups, colorByGroup]);

  // Mirror of `groups` so `createGroupFromFilter` can build the group outside
  // the state updater (updaters are double-invoked under StrictMode and must
  // stay pure — id generation isn't).
  const groupsRef = useRef(groups);
  groupsRef.current = groups;

  const createGroupFromFilter = useCallback(
    (filter: InteractiveFilter, name: string, color?: string): SelectionGroup | null => {
      const created = groupFromSelectionFilter(
        filter,
        name,
        color ?? nextGroupColor(groupsRef.current),
      );
      if (created) setGroups((prev) => [...prev, created]);
      return created;
    },
    [],
  );

  const renameGroup = useCallback((id: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setGroups((prev) => prev.map((g) => (g.id === id ? { ...g, name: trimmed } : g)));
  }, []);

  const deleteGroup = useCallback((id: string) => {
    setGroups((prev) => prev.filter((g) => g.id !== id));
  }, []);

  const toggleGroupFilter = useCallback((id: string) => {
    setGroups((prev) =>
      prev.map((g) => (g.id === id ? { ...g, filterActive: !g.filterActive } : g)),
    );
  }, []);

  const setColorByGroup = useCallback((on: boolean) => {
    setColorByGroupState(on);
  }, []);

  const groupFilters = useMemo(() => groupsToFilters(groups), [groups]);
  const renderGroups = useMemo(() => groupsRenderPayload(groups), [groups]);

  return useMemo(
    () => ({
      groups,
      colorByGroup,
      createGroupFromFilter,
      renameGroup,
      deleteGroup,
      toggleGroupFilter,
      setColorByGroup,
      groupFilters,
      renderGroups,
    }),
    [
      groups,
      colorByGroup,
      createGroupFromFilter,
      renameGroup,
      deleteGroup,
      toggleGroupFilter,
      setColorByGroup,
      groupFilters,
      renderGroups,
    ],
  );
}

export default useSelectionGroups;
