import React, { useEffect, useRef, useState } from 'react';
import { Button, Group, Modal, MultiSelect, Stack, Text, TextInput } from '@mantine/core';

import { Z_LAYERS, sameTabGroup, tabDisplayName, tabGroupOf } from 'depictio-react-core';
import type { DashboardSummary } from 'depictio-react-core';

/**
 * Dialogs for the sidebar's tab groups (edit mode).
 *
 * A group has no document of its own — it is the `tab_group` its tabs share —
 * so both dialogs only collect a name (and, for a new group, which tabs go in
 * it); `useTabGroupActions` turns that into tab patches and a reorder.
 */

/** Rename a group. Typing another group's name merges the two. */
export const RenameGroupModal: React.FC<{
  /** The group being renamed; null keeps the modal closed. */
  group: string | null;
  /** Every group in the family, to say when a rename is a merge. */
  groupNames: string[];
  submitting?: boolean;
  onClose: () => void;
  onSubmit: (name: string) => void;
}> = ({ group, groupNames, submitting = false, onClose, onSubmit }) => {
  const [name, setName] = useState('');
  useEffect(() => {
    if (group !== null) setName(group);
  }, [group]);

  const trimmed = name.trim();
  const mergeInto =
    trimmed && !sameTabGroup(trimmed, group)
      ? groupNames.find((g) => sameTabGroup(g, trimmed))
      : undefined;
  const unchanged = trimmed === (group ?? '').trim();

  return (
    <Modal
      opened={group !== null}
      onClose={onClose}
      title={<Text fw={600}>Rename group</Text>}
      size="sm"
      zIndex={Z_LAYERS.overlay}
      data-testid="rename-group-modal"
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (trimmed && !unchanged) onSubmit(trimmed);
        }}
      >
        <Stack gap="sm">
          <TextInput
            label="Group name"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            data-autofocus
            data-testid="rename-group-input"
          />
          {mergeInto && (
            <Text size="xs" c="dimmed">
              &ldquo;{mergeInto}&rdquo; already exists: its tabs and these will form one group.
            </Text>
          )}
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button
              type="submit"
              loading={submitting}
              disabled={!trimmed || unchanged}
              data-testid="rename-group-submit"
            >
              {mergeInto ? 'Merge' : 'Rename'}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
};

/** What the New group dialog was asked to do. */
export type NewGroupResult =
  | { kind: 'move'; name: string; tabIds: string[] }
  | { kind: 'create-tab'; name: string };

/**
 * Start a group: a name, then either tabs to move into it or — with none
 * picked — a first tab to create in it. One primary button whose label says
 * which, so the dialog never asks the author to choose a mode up front.
 */
export const NewGroupModal: React.FC<{
  opened: boolean;
  /** The family's tabs; the child tabs are offered for moving. */
  tabs: DashboardSummary[];
  groupNames: string[];
  /** Tabs ticked when the dialog opens (a tab's "Move to group → New group…"). */
  initialTabIds?: string[];
  submitting?: boolean;
  onClose: () => void;
  onSubmit: (result: NewGroupResult) => void;
}> = ({ opened, tabs, groupNames, initialTabIds, submitting = false, onClose, onSubmit }) => {
  const [name, setName] = useState('');
  const [tabIds, setTabIds] = useState<string[]>([]);
  // Reset only when the dialog opens: a fresh `initialTabIds` array from a
  // parent re-render must not wipe what the author is typing.
  const initialRef = useRef(initialTabIds);
  initialRef.current = initialTabIds;
  useEffect(() => {
    if (!opened) return;
    setName('');
    setTabIds(initialRef.current ?? []);
  }, [opened]);

  const trimmed = name.trim();
  const existing = trimmed ? groupNames.find((g) => sameTabGroup(g, trimmed)) : undefined;
  const options = tabs
    .filter((t) => t.parent_dashboard_id)
    .map((t) => {
      const group = tabGroupOf(t);
      return {
        value: t.dashboard_id,
        label: group ? `${tabDisplayName(t)} (${group})` : tabDisplayName(t),
      };
    });

  const submit = () => {
    if (!trimmed) return;
    onSubmit(
      tabIds.length
        ? { kind: 'move', name: trimmed, tabIds }
        : { kind: 'create-tab', name: trimmed },
    );
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={<Text fw={600}>New group</Text>}
      size="md"
      zIndex={Z_LAYERS.overlay}
      data-testid="new-group-modal"
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            Groups gather tabs under a heading in the sidebar. A group exists as long as at
            least one tab is in it.
          </Text>
          <TextInput
            label="Group name"
            placeholder="e.g. Quality control"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            data-autofocus
            data-testid="new-group-name"
          />
          {existing && (
            <Text size="xs" c="dimmed">
              &ldquo;{existing}&rdquo; already exists: the tabs will join it.
            </Text>
          )}
          <MultiSelect
            label="Move existing tabs into it"
            description="Optional. Leave empty to start the group with a new tab."
            placeholder={tabIds.length ? undefined : 'Pick tabs…'}
            data={options}
            value={tabIds}
            onChange={setTabIds}
            searchable
            clearable
            comboboxProps={{ zIndex: Z_LAYERS.tooltip }}
            data-testid="new-group-tabs"
          />
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button
              type="submit"
              loading={submitting}
              disabled={!trimmed}
              data-testid="new-group-submit"
            >
              {tabIds.length
                ? `Move ${tabIds.length} tab${tabIds.length === 1 ? '' : 's'}`
                : 'Create first tab…'}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
};
