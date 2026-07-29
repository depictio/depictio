/**
 * One row in the version timeline.
 *
 * Selection is **pure**: clicking a row navigates the viewer to that version
 * and writes nothing. Every mutating action stays an explicit item in the row's
 * menu, and the two irreversible ones (restore, delete) route through a confirm
 * modal owned by the drawer. Clicking is inert entirely when the host did not
 * ask for selection — the editor, where loading a past version into editor
 * state would risk autosaving it over the present.
 */

import React from 'react';
import { ActionIcon, Badge, Group, Menu, Stack, Text, Timeline, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DashboardVersionSummary } from 'depictio-react-core';

import { absTime, dataCoverageLabel, kindMeta, relTime, saveSpanLabel, versionTitle } from './format';

/** Which mechanism reproduced each collection's data, as a badge.
 *
 *  `none` is included on purpose: "1 live" is information, and omitting it
 *  would make a partially-pinned version look fully pinned. */
const DATA_KIND_BADGES: { key: string; label: string; color: string }[] = [
  { key: 'delta', label: 'delta', color: 'blue' },
  { key: 'manifest', label: 'manifest', color: 'grape' },
  { key: 'asset', label: 'asset', color: 'teal' },
  { key: 'none', label: 'live', color: 'gray' },
];

interface VersionTimelineItemProps {
  version: DashboardVersionSummary;
  isCurrent: boolean;
  /** The version currently on screen. */
  isSelected?: boolean;
  /** Whether clicking the row selects it (viewer) or does nothing (editor). */
  selectable?: boolean;
  /** Rendered under the row when selected — the diff panel. */
  detail?: React.ReactNode;
  canEdit: boolean;
  canDelete: boolean;
  busy: boolean;
  onPreview: (version: DashboardVersionSummary) => void;
  onTogglePin: (version: DashboardVersionSummary) => void;
  onRename: (version: DashboardVersionSummary) => void;
  onRestore: (version: DashboardVersionSummary) => void;
  onDelete: (version: DashboardVersionSummary) => void;
}

const VersionTimelineItem: React.FC<VersionTimelineItemProps> = ({
  version,
  isCurrent,
  isSelected = false,
  selectable = false,
  detail = null,
  canEdit,
  canDelete,
  busy,
  onPreview,
  onTogglePin,
  onRename,
  onRestore,
  onDelete,
}) => {
  const meta = kindMeta(version.kind);
  const span = saveSpanLabel(version);
  const coverage = dataCoverageLabel(version.data_version_kinds || {});

  return (
    <Timeline.Item
      // A pin is the strongest signal in the list, so it wins the bullet.
      bullet={<Icon icon={version.pinned ? 'mdi:pin' : meta.icon} width={12} />}
      color={version.pinned ? 'yellow' : meta.color}
      title={
        <Group gap={6} wrap="nowrap" justify="space-between">
          <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
            <Text size="sm" fw={version.pinned || version.label ? 600 : 500} truncate>
              {versionTitle(version)}
            </Text>
            {version.label && (
              <Badge size="xs" variant="light" color="gray">
                v{version.seq}
              </Badge>
            )}
            {isCurrent && (
              <Badge size="xs" variant="filled" color="teal">
                Current
              </Badge>
            )}
            {version.kind === 'restore' && (
              <Badge size="xs" variant="light" color="yellow">
                Restored
              </Badge>
            )}
          </Group>

          <Menu position="bottom-end" withinPortal width={190}>
            <Menu.Target>
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                disabled={busy}
                aria-label={`Actions for version ${version.seq}`}
                data-testid="version-actions"
              >
                <Icon icon="tabler:dots-vertical" width={15} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item
                leftSection={<Icon icon="mdi:eye-outline" width={14} />}
                onClick={() => onPreview(version)}
                data-testid="version-preview"
              >
                Preview
              </Menu.Item>
              <Menu.Item
                leftSection={
                  <Icon icon={version.pinned ? 'mdi:pin-off' : 'mdi:pin'} width={14} />
                }
                onClick={() => onTogglePin(version)}
                disabled={!canEdit}
                data-testid="version-pin"
              >
                {version.pinned ? 'Unpin' : 'Pin…'}
              </Menu.Item>
              <Menu.Item
                leftSection={<Icon icon="mdi:rename-outline" width={14} />}
                onClick={() => onRename(version)}
                disabled={!canEdit}
                data-testid="version-rename"
              >
                Rename…
              </Menu.Item>
              <Menu.Divider />
              <Menu.Item
                leftSection={<Icon icon="mdi:backup-restore" width={14} />}
                onClick={() => onRestore(version)}
                disabled={!canEdit || isCurrent}
                data-testid="version-restore"
              >
                Restore…
              </Menu.Item>
              <Menu.Item
                color="red"
                leftSection={<Icon icon="mdi:delete-outline" width={14} />}
                onClick={() => onDelete(version)}
                disabled={!canDelete}
                data-testid="version-delete"
              >
                Delete…
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      }
      data-testid="version-timeline-item"
      data-selected={isSelected ? 'true' : undefined}
      lineVariant={isSelected ? 'solid' : 'dashed'}
      // A pointer only where clicking does something, so the editor's rows do
      // not advertise an interaction they do not have.
      style={selectable ? { cursor: 'pointer' } : undefined}
      onClick={selectable ? () => onPreview(version) : undefined}
    >
      <Stack gap={2}>
        <Group gap={6} wrap="nowrap">
          <Tooltip label={absTime(version.created_at)} withArrow withinPortal>
            <Text size="xs" c="dimmed">
              {relTime(version.created_at)}
            </Text>
          </Tooltip>
          {version.author_email && (
            <Text size="xs" c="dimmed" truncate>
              · {version.author_email}
            </Text>
          )}
        </Group>

        <Group gap={6} wrap="nowrap">
          <Text size="xs" c="dimmed">
            {version.component_count} component{version.component_count === 1 ? '' : 's'}
            {version.tab_count > 1 ? ` · ${version.tab_count} tabs` : ''}
          </Text>
          {span && (
            <Text size="xs" c="dimmed">
              · {span}
            </Text>
          )}
        </Group>

        {coverage && (
          // One badge per mechanism that actually recorded something, with the
          // sentence kept as the tooltip so "2 of 3 pinned" is not lost.
          <Tooltip label={coverage} withArrow withinPortal>
            <Group gap={4} wrap="nowrap">
              {DATA_KIND_BADGES.map(({ key, label, color }) => {
                const count = version.data_version_kinds?.[key] ?? 0;
                if (!count) return null;
                return (
                  <Badge key={key} size="xs" variant="light" color={color}>
                    {count} {label}
                  </Badge>
                );
              })}
            </Group>
          </Tooltip>
        )}

        {detail}
      </Stack>
    </Timeline.Item>
  );
};

export default VersionTimelineItem;
