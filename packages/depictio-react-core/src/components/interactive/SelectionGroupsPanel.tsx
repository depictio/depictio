import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  ColorSwatch,
  Group,
  Popover,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { InteractiveFilter, StoredMetadata } from '../../api';
import { filterDisplayLabel } from '../../activeFilters';
import { TAB10_PALETTE } from '../../colors';
import {
  nextGroupColor,
  selectableSelectionFilters,
  type SelectionGroup,
} from '../../selectionGroups';

export interface SelectionGroupsPanelProps {
  /** The dashboard's *user* filters — scanned for active selections to save.
   *  Group-derived filters never appear here; the apps compose those at the
   *  fetch boundary. */
  filters: InteractiveFilter[];
  /** Full stored_metadata, to label the source selection in the picker. */
  components: StoredMetadata[];
  groups: SelectionGroup[];
  colorByGroup: boolean;
  onCreateGroup: (filter: InteractiveFilter, name: string, color: string) => void;
  /** Called with the source selection filter after a group is saved; the app
   *  routes it to its normal filter-change handler with an empty value so the
   *  `(index, source)` slot frees up for the next selection. */
  onClearSelection: (filter: InteractiveFilter) => void;
  onRenameGroup: (id: string, name: string) => void;
  onDeleteGroup: (id: string) => void;
  onToggleGroupFilter: (id: string) => void;
  onColorByGroupChange: (on: boolean) => void;
}

/**
 * "Select & compare" panel: turns the current chart/table/map selection into a
 * named, colored group and lists the saved groups.
 *
 * Groups are annotation state, not filters — each row's funnel toggles whether
 * the group narrows the dashboard, and the header switch asks the server to
 * color figures by group membership. Saving a group clears the selection it
 * came from, which is what lets a user lasso the next cohort while keeping the
 * first: the dashboard's selection protocol only holds one live selection per
 * component.
 */
const SelectionGroupsPanel: React.FC<SelectionGroupsPanelProps> = ({
  filters,
  components,
  groups,
  colorByGroup,
  onCreateGroup,
  onClearSelection,
  onRenameGroup,
  onDeleteGroup,
  onToggleGroupFilter,
  onColorByGroupChange,
}) => {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [name, setName] = useState('');
  const [color, setColor] = useState<string | null>(null);
  const [sourceIndex, setSourceIndex] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');

  const candidates = useMemo(() => selectableSelectionFilters(filters), [filters]);

  // Nothing to save from and nothing saved: stay out of the panel entirely
  // rather than pinning a permanently disabled button above the filters.
  if (candidates.length === 0 && groups.length === 0) return null;

  const defaultColor = nextGroupColor(groups);
  const selectedCandidate =
    candidates.find((f) => `${f.index}:${f.source}` === sourceIndex) ?? candidates[0];

  const openPopover = () => {
    setName(`Group ${groups.length + 1}`);
    setColor(null);
    setSourceIndex(null);
    setPopoverOpen(true);
  };

  const confirmCreate = () => {
    if (!selectedCandidate) return;
    const finalName = name.trim() || `Group ${groups.length + 1}`;
    onCreateGroup(selectedCandidate, finalName, color ?? defaultColor);
    // Free the (index, source) selection slot so the next lasso starts clean.
    onClearSelection({ ...selectedCandidate, value: [] });
    setPopoverOpen(false);
  };

  return (
    <Box mt={6}>
      <Group gap={6} wrap="nowrap" justify="space-between">
        <Group gap={6} wrap="nowrap">
          <Text size="xs" fw={600}>
            Groups
          </Text>
          {groups.length > 0 && (
            <Badge size="sm" variant="light" circle>
              {groups.length}
            </Badge>
          )}
        </Group>
        {groups.length > 0 && (
          <Tooltip
            label="Color figures by group membership (rows in no group show as gray “Other”)"
            withArrow
            openDelay={400}
          >
            <span style={{ display: 'flex' }}>
              <Switch
                size="xs"
                label="Color by group"
                labelPosition="left"
                checked={colorByGroup}
                onChange={(e) => onColorByGroupChange(e.currentTarget.checked)}
                styles={{ label: { fontSize: 11, paddingRight: 6 } }}
              />
            </span>
          </Tooltip>
        )}
      </Group>

      <Popover
        opened={popoverOpen}
        onChange={setPopoverOpen}
        width={260}
        position="bottom-start"
        withArrow
        shadow="md"
        trapFocus
      >
        <Popover.Target>
          <Tooltip
            label={
              candidates.length === 0
                ? 'Make a selection on a chart, table or map first'
                : 'Save the current selection as a named group'
            }
            withArrow
            openDelay={400}
          >
            <span style={{ display: 'inline-flex', width: '100%' }}>
              <Button
                mt={4}
                size="xs"
                variant="light"
                fullWidth
                leftSection={<Icon icon="mdi:selection-drag" width={14} height={14} />}
                disabled={candidates.length === 0}
                onClick={openPopover}
              >
                Save selection as group
              </Button>
            </span>
          </Tooltip>
        </Popover.Target>
        <Popover.Dropdown>
          <Stack gap="xs">
            {candidates.length > 1 && (
              <Select
                size="xs"
                label="Selection"
                data={candidates.map((f) => ({
                  value: `${f.index}:${f.source}`,
                  label: `${filterDisplayLabel(f, components)} (${
                    Array.isArray(f.value) ? f.value.length : 0
                  })`,
                }))}
                value={sourceIndex ?? `${candidates[0].index}:${candidates[0].source}`}
                onChange={setSourceIndex}
                allowDeselect={false}
              />
            )}
            <TextInput
              size="xs"
              label="Group name"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') confirmCreate();
              }}
              data-autofocus
            />
            <Group gap={4}>
              {TAB10_PALETTE.map((c) => (
                <ColorSwatch
                  key={c}
                  color={c}
                  size={16}
                  style={{
                    cursor: 'pointer',
                    outline:
                      (color ?? defaultColor) === c
                        ? '2px solid var(--mantine-color-blue-5)'
                        : 'none',
                    outlineOffset: 1,
                  }}
                  onClick={() => setColor(c)}
                />
              ))}
            </Group>
            {selectedCandidate && Array.isArray(selectedCandidate.value) && (
              <Text size="xs" c="dimmed">
                {selectedCandidate.value.length} selected item
                {selectedCandidate.value.length === 1 ? '' : 's'}
              </Text>
            )}
            <Button size="xs" onClick={confirmCreate} disabled={!selectedCandidate}>
              Save group
            </Button>
          </Stack>
        </Popover.Dropdown>
      </Popover>

      {groups.length > 0 && (
        <Stack gap={2} mt={6} mah={160} style={{ overflowY: 'auto' }}>
          {groups.map((g) => (
            <Group key={g.id} gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
              <ColorSwatch color={g.color} size={12} style={{ flexShrink: 0 }} />
              {renamingId === g.id ? (
                <TextInput
                  size="xs"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.currentTarget.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      onRenameGroup(g.id, renameValue);
                      setRenamingId(null);
                    }
                    if (e.key === 'Escape') setRenamingId(null);
                  }}
                  onBlur={() => {
                    onRenameGroup(g.id, renameValue);
                    setRenamingId(null);
                  }}
                  autoFocus
                  style={{ flex: '1 1 auto', minWidth: 0 }}
                />
              ) : (
                <Tooltip
                  label={`${g.values.length} items on ${g.columnName} — double-click to rename`}
                  withArrow
                  openDelay={400}
                >
                  <Text
                    size="xs"
                    fw={500}
                    truncate
                    style={{ flex: '1 1 auto', minWidth: 0, cursor: 'default' }}
                    onDoubleClick={() => {
                      setRenamingId(g.id);
                      setRenameValue(g.name);
                    }}
                  >
                    {g.name}
                  </Text>
                </Tooltip>
              )}
              <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                {g.values.length}
              </Text>
              <Tooltip
                label={g.filterActive ? 'Stop filtering by this group' : 'Filter by this group'}
                withArrow
                openDelay={400}
              >
                <ActionIcon
                  variant={g.filterActive ? 'filled' : 'subtle'}
                  color={g.filterActive ? 'blue' : 'gray'}
                  size="xs"
                  aria-label={
                    g.filterActive
                      ? `Stop filtering by group ${g.name}`
                      : `Filter by group ${g.name}`
                  }
                  onClick={() => onToggleGroupFilter(g.id)}
                  style={{ flexShrink: 0 }}
                >
                  <Icon icon="mdi:filter-variant" width={12} height={12} />
                </ActionIcon>
              </Tooltip>
              <ActionIcon
                variant="subtle"
                color="gray"
                size="xs"
                aria-label={`Delete group ${g.name}`}
                onClick={() => onDeleteGroup(g.id)}
                style={{ flexShrink: 0 }}
              >
                <Icon icon="mdi:close" width={12} height={12} />
              </ActionIcon>
            </Group>
          ))}
        </Stack>
      )}
    </Box>
  );
};

export default SelectionGroupsPanel;
