import React from 'react';
import {
  ActionIcon,
  Badge,
  Card,
  Group,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardListEntry } from 'depictio-react-core';
import DashboardActionsMenu from '../DashboardActionsMenu';
import type { CategoryInfo } from '../DashboardsList';
import { coerceString, formatLastSaved, isImagePath } from '../lib/format';

export interface DashboardCompactCardProps {
  dashboard: DashboardListEntry;
  childCount: number;
  isOwner: boolean;
  projectName?: string;
  pinned: boolean;
  pinDisabled: boolean;
  category?: CategoryInfo;
  onView: (d: DashboardListEntry) => void;
  onEdit: (d: DashboardListEntry) => void;
  onDelete: (d: DashboardListEntry) => void;
  onDuplicate: (d: DashboardListEntry) => void;
  onExport: (d: DashboardListEntry) => void;
  onTogglePin: () => void;
}

const DashboardCompactCard: React.FC<DashboardCompactCardProps> = ({
  dashboard,
  childCount,
  isOwner,
  projectName,
  pinned,
  pinDisabled,
  category,
  onView,
  onEdit,
  onDelete,
  onDuplicate,
  onExport,
  onTogglePin,
}) => {
  const icon = coerceString(dashboard.icon, 'mdi:view-dashboard');
  const iconColor = coerceString(dashboard.icon_color, 'orange');
  const ownerEmail = dashboard.permissions?.owners?.[0]?.email ?? '';
  const isPublic = Boolean(dashboard.is_public);
  const lastSavedRaw = coerceString(dashboard.last_saved_ts, '');
  const lastSaved = lastSavedRaw ? formatLastSaved(lastSavedRaw) : 'Never';
  const titleText = dashboard.title || dashboard.dashboard_id;
  const totalTabs = childCount + 1;

  // Left border accent uses the CATEGORY color so users can scan ownership
  // status at a glance even before reading the badge text. Falls back to the
  // dashboard's own brand color when no category is provided (thumbnails view
  // already handles category via section headers).
  const accent =
    category?.color ??
    (iconColor.startsWith('var(') || iconColor.startsWith('#')
      ? iconColor
      : `var(--mantine-color-${iconColor}-6)`);

  return (
    <Card
      shadow="none"
      padding="xs"
      radius="sm"
      withBorder
      style={{ borderLeft: `4px solid ${accent}`, height: '100%' }}
    >
      <Stack gap={6} h="100%">
        <Group wrap="nowrap" gap={6} align="center">
          {isImagePath(icon) ? (
            <img
              src={icon}
              alt=""
              style={{
                width: 24,
                height: 24,
                objectFit: 'contain',
                borderRadius: 4,
                flexShrink: 0,
              }}
            />
          ) : (
            <ThemeIcon
              color={iconColor}
              radius="sm"
              size={24}
              variant="filled"
              style={{ flexShrink: 0 }}
            >
              <Icon icon={icon} width={14} />
            </ThemeIcon>
          )}

          <UnstyledButton
            onClick={() => onView(dashboard)}
            style={{ textAlign: 'left', flex: 1, minWidth: 0 }}
          >
            <Text fw={600} size="sm" lineClamp={1}>
              {titleText}
            </Text>
          </UnstyledButton>

          <Tooltip
            label={
              pinDisabled
                ? 'Pinning is disabled in public mode'
                : pinned
                  ? 'Unpin'
                  : 'Pin to top'
            }
            withinPortal
          >
            <ActionIcon
              variant="transparent"
              size="sm"
              onClick={onTogglePin}
              disabled={pinDisabled}
              aria-label={pinned ? 'Unpin dashboard' : 'Pin dashboard'}
            >
              <Icon
                icon={pinned ? 'mdi:star' : 'mdi:star-outline'}
                width={16}
                color={
                  pinned
                    ? 'var(--mantine-color-yellow-5)'
                    : 'var(--mantine-color-gray-5)'
                }
              />
            </ActionIcon>
          </Tooltip>
          <DashboardActionsMenu
            dashboard={dashboard}
            isOwner={isOwner}
            onView={onView}
            onEdit={onEdit}
            onDelete={onDelete}
            onDuplicate={onDuplicate}
            onExport={onExport}
            triggerSize="sm"
          />
        </Group>

        <Group gap={4} wrap="wrap">
          {category && (
            <Badge
              variant="dot"
              size="sm"
              color={category.color}
              styles={{ root: { textTransform: 'none', fontWeight: 600 } }}
            >
              {category.label}
            </Badge>
          )}
          {projectName && (
            <Badge
              color="cyan"
              variant="light"
              size="sm"
              leftSection={<Icon icon="mdi:folder-outline" width={11} />}
            >
              {projectName}
            </Badge>
          )}
          <Badge
            color={isPublic ? 'green' : 'grape'}
            variant="light"
            size="sm"
            leftSection={
              <Icon
                icon={isPublic ? 'mdi:earth' : 'mdi:lock-outline'}
                width={11}
              />
            }
          >
            {isPublic ? 'Public' : 'Private'}
          </Badge>
          {childCount > 0 && (
            <Badge
              color="orange"
              variant="light"
              size="sm"
              leftSection={<Icon icon="mdi:tab" width={11} />}
            >
              {totalTabs} Tabs
            </Badge>
          )}
        </Group>

        <Group justify="space-between" gap="xs" wrap="nowrap" mt="auto">
          <Text c="dimmed" size="xs" truncate>
            {ownerEmail || '—'}
          </Text>
          <Text c="dimmed" size="xs" style={{ flexShrink: 0 }}>
            {lastSaved}
          </Text>
        </Group>
      </Stack>
    </Card>
  );
};

export default DashboardCompactCard;
