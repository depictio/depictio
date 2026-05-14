import React, { useState } from 'react';
import {
  ActionIcon,
  AspectRatio,
  Badge,
  Card,
  Center,
  Group,
  Stack,
  Space,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
  UnstyledButton,
  useMantineColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardListEntry } from 'depictio-react-core';
import MultiTabPreview from './MultiTabPreview';
import DashboardActionsMenu from './DashboardActionsMenu';
import {
  coerceString,
  formatLastSaved,
  isImagePath,
  resolveAssetUrl,
  screenshotUrl,
} from './lib/format';

interface DashboardCardProps {
  dashboard: DashboardListEntry;
  childTabs?: DashboardListEntry[];
  isOwner: boolean;
  projectName?: string;
  pinned?: boolean;
  pinDisabled?: boolean;
  onTogglePin?: () => void;
  onView: (d: DashboardListEntry) => void;
  onEdit: (d: DashboardListEntry) => void;
  onDelete: (d: DashboardListEntry) => void;
  onDuplicate: (d: DashboardListEntry) => void;
  onExport: (d: DashboardListEntry) => void;
}

const SingleThumbnail: React.FC<{
  dashboard: DashboardListEntry;
  theme: 'light' | 'dark';
}> = ({ dashboard, theme }) => {
  const [errored, setErrored] = useState(false);
  const icon = coerceString(dashboard.icon, 'mdi:view-dashboard');
  const color = coerceString(dashboard.icon_color, 'orange');

  if (errored) {
    return (
      <Center h="100%" w="100%" bg="var(--mantine-color-default-hover)">
        <ThemeIcon size={64} variant="light" color={color} radius="md">
          <Icon icon={isImagePath(icon) ? 'mdi:view-dashboard' : icon} width={36} />
        </ThemeIcon>
      </Center>
    );
  }
  return (
    <img
      key={`${theme}-${dashboard.last_saved_ts ?? ''}`}
      src={screenshotUrl(dashboard.dashboard_id, theme, dashboard.last_saved_ts)}
      alt={dashboard.title || dashboard.dashboard_id}
      loading="lazy"
      decoding="async"
      onError={() => setErrored(true)}
      style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
    />
  );
};

/** Header icon: workflow-logo image when `dashboard.icon` is a path,
 *  otherwise a filled circular ActionIcon with the Iconify icon. Mirrors
 *  `dashboards_management.py:696-713`. */
const HeaderIcon: React.FC<{ icon: string; color: string }> = ({ icon, color }) => {
  if (isImagePath(icon)) {
    return (
      <img
        src={resolveAssetUrl(icon)}
        alt=""
        style={{
          width: 48,
          height: 48,
          objectFit: 'contain',
          borderRadius: '50%',
          padding: 4,
        }}
      />
    );
  }
  return (
    <ActionIcon color={color} radius="xl" size="lg" variant="filled" aria-hidden>
      <Icon icon={icon} width={24} height={24} />
    </ActionIcon>
  );
};

const DashboardCard: React.FC<DashboardCardProps> = ({
  dashboard,
  childTabs = [],
  isOwner,
  projectName,
  pinned = false,
  pinDisabled = false,
  onTogglePin,
  onView,
  onEdit,
  onDelete,
  onDuplicate,
  onExport,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';

  const dashboardIcon = coerceString(dashboard.icon, 'mdi:view-dashboard');
  const dashboardIconColor = coerceString(dashboard.icon_color, 'orange');
  const subtitle = coerceString(dashboard.subtitle, '');
  const ownerEmail = dashboard.permissions?.owners?.[0]?.email ?? '';
  const isPublic = Boolean(dashboard.is_public);
  const lastSavedRaw = coerceString(dashboard.last_saved_ts, '');
  const lastSaved = lastSavedRaw ? formatLastSaved(lastSavedRaw) : 'Never';
  const titleText = dashboard.title || dashboard.dashboard_id;
  const totalTabs = childTabs.length + 1;
  const hasMultipleTabs = childTabs.length > 0;

  return (
    <Card shadow="sm" padding="md" radius="md" withBorder style={{ position: 'relative' }}>
      {onTogglePin && (
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
            size="md"
            onClick={onTogglePin}
            disabled={pinDisabled}
            aria-label={pinned ? 'Unpin dashboard' : 'Pin dashboard'}
            style={{
              position: 'absolute',
              top: 8,
              right: 8,
              zIndex: 2,
              // Drop shadow keeps the icon legible against any screenshot.
              filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.4))',
            }}
          >
            <Icon
              icon={pinned ? 'mdi:star' : 'mdi:star-outline'}
              width={20}
              color={
                pinned
                  ? 'var(--mantine-color-yellow-5)'
                  : 'var(--mantine-color-white)'
              }
            />
          </ActionIcon>
        </Tooltip>
      )}

      <Card.Section>
        <AspectRatio ratio={16 / 10}>
          {hasMultipleTabs ? (
            <MultiTabPreview
              parent={dashboard}
              childTabs={childTabs}
              theme={theme}
              // Route each slide click to its OWN tab's dashboard ID, not
              // the parent's. The parent slide (index 0) routes via its own
              // ``slide.id`` which equals ``dashboard.dashboard_id``.
              onTabClick={(tabDashboardId) => {
                const target =
                  tabDashboardId === dashboard.dashboard_id
                    ? dashboard
                    : (childTabs.find(
                        (t) => t.dashboard_id === tabDashboardId,
                      ) ?? dashboard);
                onView(target);
              }}
            />
          ) : (
            <UnstyledButton
              onClick={() => onView(dashboard)}
              style={{ width: '100%', height: '100%', display: 'block' }}
              aria-label={`Open ${titleText}`}
            >
              <SingleThumbnail dashboard={dashboard} theme={theme} />
            </UnstyledButton>
          )}
        </AspectRatio>
      </Card.Section>

      <Space h={10} />

      <Group align="flex-start" wrap="nowrap" gap="sm">
        <HeaderIcon icon={dashboardIcon} color={dashboardIconColor} />
        <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
          <UnstyledButton
            onClick={() => onView(dashboard)}
            style={{ textAlign: 'left' }}
          >
            <Title
              order={4}
              style={{
                wordWrap: 'break-word',
                whiteSpace: 'normal',
                marginBottom: 0,
              }}
            >
              {titleText}
            </Title>
          </UnstyledButton>
          {subtitle && (
            <Text size="sm" c="gray">
              {subtitle}
            </Text>
          )}
        </Stack>
        <DashboardActionsMenu
          dashboard={dashboard}
          isOwner={isOwner}
          onView={onView}
          onEdit={onEdit}
          onDelete={onDelete}
          onDuplicate={onDuplicate}
          onExport={onExport}
        />
      </Group>

      <Space h={10} />

      <Stack gap={4} align="flex-start">
        {projectName && (
          <Tooltip label={`Project: ${projectName}`} withinPortal>
            <Badge
              color="teal"
              leftSection={<Icon icon="mdi:jira" width={14} color="white" />}
              style={{ maxWidth: '100%' }}
            >
              Project: {projectName}
            </Badge>
          </Tooltip>
        )}
        {ownerEmail && (
          <Tooltip label={`Owner: ${ownerEmail}`} withinPortal>
            <Badge
              color={isOwner ? 'blue' : 'gray'}
              leftSection={<Icon icon="mdi:account" width={14} color="white" />}
              style={{ maxWidth: '100%' }}
            >
              Owner: {ownerEmail}
            </Badge>
          </Tooltip>
        )}
        <Tooltip label={`Visibility: ${isPublic ? 'Public' : 'Private'}`} withinPortal>
          <Badge
            color={isPublic ? 'green' : 'grape'}
            leftSection={
              <Icon
                icon={isPublic ? 'material-symbols:public' : 'material-symbols:lock'}
                width={14}
                color="white"
              />
            }
          >
            {isPublic ? 'Public' : 'Private'}
          </Badge>
        </Tooltip>
        <Tooltip label={`Last modified: ${lastSaved}`} withinPortal>
          <Badge
            color="gray"
            variant="light"
            leftSection={<Icon icon="mdi:clock-outline" width={14} />}
          >
            Modified: {lastSaved}
          </Badge>
        </Tooltip>
        {hasMultipleTabs && (
          <Badge
            color="orange"
            variant="light"
            leftSection={<Icon icon="mdi:tab" width={14} />}
          >
            {totalTabs} Tabs
          </Badge>
        )}
      </Stack>
    </Card>
  );
};

export default DashboardCard;
