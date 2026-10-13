import React, { useCallback, useMemo, useState } from 'react';
import { notifications } from '@mantine/notifications';

import {
  reorderTabs,
  sameTabGroup,
  tabGroupNames,
  tabGroupOf,
  tabIdsInGroup,
  tabOrderAfterGroupMove,
  tabOrderAfterRegroup,
  tabOrderEntries,
  updateTab,
} from 'depictio-react-core';
import type { DashboardSummary } from 'depictio-react-core';

import { NewGroupModal, RenameGroupModal, type NewGroupResult } from './TabGroupModals';

/**
 * The editor's tab-group actions, behind the sidebar's group and tab menus.
 *
 * A group is only the `tab_group` its tabs share, so every action is some
 * `updateTab` patches plus, where the sidebar order changes, one
 * `reorderTabs` with the family's full child order (computed by the pure
 * helpers in react-core's `tabGroups.ts`). The sidebar is refreshed after.
 */
export function useTabGroupActions({
  tabs,
  refresh,
  openCreateTab,
}: {
  /** The dashboard family, in sidebar order (main tab first). */
  tabs: DashboardSummary[];
  /** Reloads the family so the sidebar redraws. */
  refresh: () => Promise<void>;
  /** Opens the create-tab modal with its Group prefilled. */
  openCreateTab: (group: string) => void;
}) {
  const [renaming, setRenaming] = useState<string | null>(null);
  const [newGroup, setNewGroup] = useState<{ open: boolean; tabIds: string[] }>({
    open: false,
    tabIds: [],
  });
  const [submitting, setSubmitting] = useState(false);

  const groupNames = useMemo(() => tabGroupNames(tabs), [tabs]);
  const parentId = useMemo(
    () =>
      tabs.find((t) => !t.parent_dashboard_id)?.dashboard_id ??
      tabs.find((t) => t.parent_dashboard_id)?.parent_dashboard_id ??
      null,
    [tabs],
  );

  /** Patch `tab_group` on `ids`, then (optionally) renumber the family. */
  const apply = useCallback(
    async (
      ids: string[],
      group: string | null,
      order: string[] | null,
      done: { title: string; message: string },
    ): Promise<boolean> => {
      setSubmitting(true);
      try {
        await Promise.all(ids.map((id) => updateTab(id, { tab_group: group })));
        if (order && parentId) await reorderTabs(parentId, tabOrderEntries(order));
        notifications.show({ color: 'teal', autoClose: 2000, ...done });
        await refresh();
        return true;
      } catch (err) {
        console.error('[tab groups] update failed:', err);
        notifications.show({
          color: 'red',
          title: 'Group update failed',
          message: err instanceof Error ? err.message : String(err),
          autoClose: 4000,
        });
        // Some patches may have landed before the failure.
        await refresh();
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [parentId, refresh],
  );

  const moveGroup = useCallback(
    async (group: string, direction: 'up' | 'down') => {
      const order = tabOrderAfterGroupMove(tabs, group, direction);
      if (!order || !parentId) return;
      try {
        await reorderTabs(parentId, tabOrderEntries(order));
        await refresh();
      } catch (err) {
        notifications.show({
          color: 'red',
          title: 'Reorder failed',
          message: err instanceof Error ? err.message : String(err),
          autoClose: 4000,
        });
      }
    },
    [tabs, parentId, refresh],
  );

  const ungroup = useCallback(
    (group: string) => {
      const ids = tabIdsInGroup(tabs, group);
      void apply(ids, null, tabOrderAfterRegroup(tabs, ids, null), {
        title: 'Group removed',
        message: `${ids.length} tab${ids.length === 1 ? '' : 's'} no longer grouped`,
      });
    },
    [tabs, apply],
  );

  const moveTabToGroup = useCallback(
    (tab: DashboardSummary, group: string | null) => {
      if (sameTabGroup(tabGroupOf(tab), group)) return;
      void apply(
        [tab.dashboard_id],
        group,
        tabOrderAfterRegroup(tabs, [tab.dashboard_id], group),
        {
          title: group ? `Moved to ${group}` : 'Removed from its group',
          message: tab.title || tab.dashboard_id,
        },
      );
    },
    [tabs, apply],
  );

  const submitRename = useCallback(
    async (name: string) => {
      if (renaming === null) return;
      const ids = tabIdsInGroup(tabs, renaming);
      // Merging into another group gathers both blocks where that group sits;
      // a plain rename keeps the order as it is.
      const merges = groupNames.some(
        (g) => !sameTabGroup(g, renaming) && sameTabGroup(g, name),
      );
      const ok = await apply(ids, name, merges ? tabOrderAfterRegroup(tabs, ids, name) : null, {
        title: merges ? 'Groups merged' : 'Group renamed',
        message: name,
      });
      if (ok) setRenaming(null);
    },
    [renaming, tabs, groupNames, apply],
  );

  const submitNewGroup = useCallback(
    async (result: NewGroupResult) => {
      if (result.kind === 'create-tab') {
        setNewGroup({ open: false, tabIds: [] });
        openCreateTab(result.name);
        return;
      }
      const ok = await apply(
        result.tabIds,
        result.name,
        tabOrderAfterRegroup(tabs, result.tabIds, result.name),
        { title: 'Group created', message: result.name },
      );
      if (ok) setNewGroup({ open: false, tabIds: [] });
    },
    [tabs, apply, openCreateTab],
  );

  const modals = (
    <>
      <RenameGroupModal
        group={renaming}
        groupNames={groupNames}
        submitting={submitting}
        onClose={() => setRenaming(null)}
        onSubmit={submitRename}
      />
      <NewGroupModal
        opened={newGroup.open}
        tabs={tabs}
        groupNames={groupNames}
        initialTabIds={newGroup.tabIds}
        submitting={submitting}
        onClose={() => setNewGroup({ open: false, tabIds: [] })}
        onSubmit={submitNewGroup}
      />
    </>
  );

  return {
    /** Sidebar handlers. */
    onRenameGroup: setRenaming as (group: string) => void,
    onMoveGroup: moveGroup,
    onAddTabToGroup: openCreateTab,
    onUngroup: ungroup,
    onNewGroup: (tabIds?: string[]) => setNewGroup({ open: true, tabIds: tabIds ?? [] }),
    onMoveTabToGroup: moveTabToGroup,
    /** The two dialogs; render once, anywhere in the editor tree. */
    modals,
  };
}
