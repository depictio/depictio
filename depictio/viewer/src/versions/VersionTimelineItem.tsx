/**
 * One row in the version timeline.
 *
 * Deliberately inert on click: selecting a version must never write anything.
 * Every mutating action is an explicit item in the row's menu, and the two
 * irreversible ones (restore, delete) route through a confirm modal owned by
 * the drawer.
 */

import React from 'react';
import { ActionIcon, Badge, Group, Menu, Stack, Text, Timeline } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DashboardVersionSummary } from 'depictio-react-core';

import { absDateTime, dataCoverageLabel, kindMeta, relTime, saveSpanLabel, versionTitle } from './format';

interface VersionTimelineItemProps {
  version: DashboardVersionSummary;
  isCurrent: boolean;
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
      // Mantine's default item padding assumes a title plus a paragraph. These
      // rows are three short lines, so the default leaves more gap than
      // content and a session's worth of versions stops being scannable.
      lineVariant="solid"
      styles={{ itemBody: { paddingBottom: 2 }, item: { paddingLeft: 20 } }}
    >
      <Stack gap={1}>
        <Group gap={6} wrap="nowrap">
          {/* Full date and time, not just the clock. Relative time answers "how
              long ago" at a glance, but choosing between a day's worth of
              autosaves needs the wall clock, and choosing between months needs
              the date — the day-group heading scrolls out of view. */}
          <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
            {absDateTime(version.created_at)}
          </Text>
          <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
            · {relTime(version.created_at)}
          </Text>
        </Group>

        {version.author_email && (
          <Text size="xs" c="dimmed" truncate>
            {version.author_email}
          </Text>
        )}

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
          <Text size="xs" c="dimmed">
            {coverage}
          </Text>
        )}
      </Stack>
    </Timeline.Item>
  );
};

export default VersionTimelineItem;
