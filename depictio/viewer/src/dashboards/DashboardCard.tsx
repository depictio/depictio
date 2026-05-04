import React, { useState } from 'react';
import {
  ActionIcon,
  AspectRatio,
  Badge,
  Card,
  Center,
  Group,
  Menu,
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

interface DashboardCardProps {
  dashboard: DashboardListEntry;
  childTabs?: DashboardListEntry[];
  isOwner: boolean;
  projectName?: string;
  onView: (d: DashboardListEntry) => void;
  onEdit: (d: DashboardListEntry) => void;
  onDelete: (d: DashboardListEntry) => void;
  onDuplicate: (d: DashboardListEntry) => void;
  onExport: (d: DashboardListEntry) => void;
}

/** True for icon values that point at an image file (e.g. workflow logos
 *  shipped with the Dash app at `/assets/images/logos/...`). */
function isImagePath(s: string | null | undefined): boolean {
  if (!s) return false;
  return /^(\/|https?:\/\/|data:)/.test(s) || /\.(png|svg|jpe?g|webp)$/i.test(s);
}

/** Resolve a Dash asset path (e.g. `/assets/images/logos/multiqc.png`) to a
 *  loadable URL. The Dash app serves /assets/ on port 5122; the SPA on 8122
 *  doesn't proxy them, so cross-port in dev. Mirrors `resolveAssetUrl()` in
 *  `chrome/Sidebar.tsx`. */
function resolveAssetUrl(s: string): string {
  if (/^(https?:\/\/|data:)/.test(s)) return s;
  if (s.startsWith('/')) {
    const env = (import.meta as unknown as { env?: Record<string, string> }).env;
    if (env?.VITE_DASH_ORIGIN) return env.VITE_DASH_ORIGIN.replace(/\/$/, '') + s;
    if (
      typeof window !== 'undefined' &&
      window.location.hostname &&
      window.location.port === '8122'
    ) {
      return `${window.location.protocol}//${window.location.hostname}:5122${s}`;
    }
    return s;
  }
  return s;
}

/** Format `last_saved_ts` (ISO or "%Y-%m-%d %H:%M:%S") as "yyyy-mm-dd HH:MM"
 *  to match `dashboards_management.py:607-611`. */
function formatLastSaved(raw: string): string {
  const d = new Date(raw.replace('Z', '+00:00'));
  if (Number.isNaN(d.getTime())) return raw;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function screenshotUrl(
  dashboardId: string,
  theme: 'light' | 'dark',
  lastSavedTs?: string,
): string {
  // Cache-bust on every save: the auto-screenshot job overwrites the file
  // in place, so without a versioned URL the browser keeps showing the old
  // image until a hard reload. ``last_saved_ts`` changes whenever the
  // dashboard is saved (and the screenshot job runs as part of save), so
  // it's the right version key.
  const base = `/static/screenshots/${dashboardId}_${theme}.png`;
  if (!lastSavedTs) return base;
  return `${base}?v=${encodeURIComponent(lastSavedTs)}`;
}

const SingleThumbnail: React.FC<{
  dashboard: DashboardListEntry;
  theme: 'light' | 'dark';
}> = ({ dashboard, theme }) => {
  const [errored, setErrored] = useState(false);
  const icon =
    (typeof dashboard.icon === 'string' && dashboard.icon) || 'mdi:view-dashboard';
  const color =
    (typeof dashboard.icon_color === 'string' && dashboard.icon_color) || 'orange';

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
  onView,
  onEdit,
  onDelete,
  onDuplicate,
  onExport,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';

  const dashboardIcon =
    (typeof dashboard.icon === 'string' && dashboard.icon) || 'mdi:view-dashboard';
  const dashboardIconColor =
    (typeof dashboard.icon_color === 'string' && dashboard.icon_color) || 'orange';
  const subtitle =
    typeof dashboard.subtitle === 'string' ? dashboard.subtitle : '';
  const ownerEmail = dashboard.permissions?.owners?.[0]?.email ?? '';
  const isPublic = Boolean(dashboard.is_public);
  const lastSavedRaw =
    typeof dashboard.last_saved_ts === 'string' ? dashboard.last_saved_ts : '';
  const lastSaved = lastSavedRaw ? formatLastSaved(lastSavedRaw) : 'Never';
  const titleText = dashboard.title || dashboard.dashboard_id;
  const totalTabs = childTabs.length + 1;
  const hasMultipleTabs = childTabs.length > 0;

  return (
    <Card shadow="sm" padding="md" radius="md" withBorder>
      <Card.Section>
        <AspectRatio ratio={16 / 10}>
          {hasMultipleTabs ? (
            <MultiTabPreview parent={dashboard} childTabs={childTabs} theme={theme} />
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
        <Menu position="bottom-end" shadow="md" withinPortal width={170}>
          <Menu.Target>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              aria-label="Dashboard actions"
            >
              <Icon icon="tabler:dots-vertical" width={18} />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item
              leftSection={<Icon icon="mdi:eye" width={14} />}
              onClick={() => onView(dashboard)}
            >
              Open
            </Menu.Item>
            <Menu.Item
              leftSection={<Icon icon="tabler:edit" width={14} />}
              disabled={!isOwner}
              onClick={() => onEdit(dashboard)}
            >
              Edit
            </Menu.Item>
            <Menu.Item
              leftSection={<Icon icon="mdi:content-duplicate" width={14} />}
              onClick={() => onDuplicate(dashboard)}
            >
              Duplicate
            </Menu.Item>
            <Menu.Item
              leftSection={<Icon icon="mdi:download" width={14} />}
              onClick={() => onExport(dashboard)}
            >
              Export JSON
            </Menu.Item>
            <Menu.Divider />
            <Menu.Item
              color="red"
              leftSection={<Icon icon="tabler:trash" width={14} />}
              disabled={!isOwner}
              onClick={() => onDelete(dashboard)}
            >
              Delete
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
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
