import React, { useEffect, useRef, useState } from 'react';
import { Button, Group, Modal, MultiSelect, Stack, Text, TextInput, Title } from '@mantine/core';
import { Icon } from '@iconify/react';

import { Z_LAYERS, sameTabGroup, tabDisplayName, tabGroupOf } from 'depictio-react-core';
import type { DashboardSummary } from 'depictio-react-core';

/**
 * Dialogs for the sidebar's tab groups (edit mode).
 *
 * A group has no document of its own — it is the `tab_group` its tabs share —
 * so both dialogs only collect a name (and, for a new group, which tabs go in
 * it); `useTabGroupActions` turns that into tab patches and a reorder.
 */

/**
 * The look the tab and group dialogs share, so adding a tab and adding a
 * group read as the same kind of step: a centred orange icon and title (as
 * the dashboard create/edit dialogs), then the form, then Cancel and an
 * orange primary action.
 */
export const SidebarModalHeader: React.FC<{ icon: string; title: string }> = ({
  icon,
  title,
}) => (
  <Group justify="center" gap="sm" mb="xs">
    <Icon icon={icon} width={28} height={28} color="var(--mantine-color-orange-6)" />
    <Title order={3} c="orange" m={0}>
      {title}
    </Title>
  </Group>
);

export const SidebarModalActions: React.FC<{
  submitIcon: string;
  submitLabel: string;
  submitting: boolean;
  disabled: boolean;
  onCancel: () => void;
  /** Without it the primary button submits its form. */
  onSubmit?: () => void;
  testId?: string;
}> = ({ submitIcon, submitLabel, submitting, disabled, onCancel, onSubmit, testId }) => (
  <Group justify="flex-end" gap="md" mt="sm">
    <Button variant="outline" color="gray" radius="md" onClick={onCancel} disabled={submitting}>
      Cancel
    </Button>
    <Button
      type={onSubmit ? 'button' : 'submit'}
      color="orange"
      radius="md"
      leftSection={<Icon icon={submitIcon} width={16} />}
      onClick={onSubmit}
      loading={submitting}
      disabled={disabled}
      data-testid={testId}
    >
      {submitLabel}
    </Button>
  </Group>
);

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
      withCloseButton
      size="md"
      centered
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
          <SidebarModalHeader icon="mdi:folder-edit-outline" title="Edit Group" />
          <TextInput
            label="Group name"
            required
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
          <SidebarModalActions
            submitIcon={mergeInto ? 'mdi:call-merge' : 'mdi:content-save'}
            submitLabel={mergeInto ? 'Merge Groups' : 'Save Changes'}
            submitting={submitting}
            disabled={!trimmed || unchanged}
            onCancel={onClose}
            testId="rename-group-submit"
          />
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
      withCloseButton
      size="md"
      centered
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
          <SidebarModalHeader icon="mdi:folder-plus-outline" title="Add Group" />
          <TextInput
            label="Group name"
            description="A heading in the sidebar that gathers tabs. It stays as long as one tab is in it."
            required
            placeholder="Quality control"
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
            description="Optional. Leave empty and the group starts with a new tab, added next."
            placeholder={tabIds.length ? undefined : 'Pick tabs…'}
            data={options}
            value={tabIds}
            onChange={setTabIds}
            searchable
            clearable
            comboboxProps={{ zIndex: Z_LAYERS.tooltip }}
            data-testid="new-group-tabs"
          />
          <SidebarModalActions
            submitIcon={tabIds.length ? 'mdi:folder-move-outline' : 'mdi:plus'}
            submitLabel={
              tabIds.length
                ? `Move ${tabIds.length} Tab${tabIds.length === 1 ? '' : 's'}`
                : 'Add Group'
            }
            submitting={submitting}
            disabled={!trimmed}
            onCancel={onClose}
            testId="new-group-submit"
          />
        </Stack>
      </form>
    </Modal>
  );
};
