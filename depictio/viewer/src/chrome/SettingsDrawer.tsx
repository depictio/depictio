import React, { useEffect, useState } from 'react';
import {
  Badge,
  Code,
  CopyButton,
  Divider,
  Drawer,
  Group,
  Stack,
  Text,
  Tooltip,
  ActionIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData } from 'depictio-react-core';
import { fetchProject } from 'depictio-react-core';
import JourneysSection from './JourneysSection';

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
}

/** "yyyy-mm-dd HH:MM" — same format the dashboards list uses. */
function formatTimestamp(raw: string): string {
  const d = new Date(raw.replace('Z', '+00:00'));
  if (Number.isNaN(d.getTime())) return raw;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Pull the first owner's email from a permissions blob, regardless of
 *  exact shape (server uses ``permissions.owners[].email``). */
function pickOwnerEmail(dashboard: DashboardData | null): string | null {
  const perms = dashboard?.permissions as
    | { owners?: Array<{ email?: string }> }
    | undefined;
  return perms?.owners?.[0]?.email ?? null;
}

/**
 * Right-side drawer with read-only metadata about the current dashboard.
 * Displays the same fields the dashboards list shows (project, owner,
 * visibility, modified date) plus the dashboard / project IDs.
 */
const SettingsDrawer: React.FC<SettingsDrawerProps> = ({
  opened,
  onClose,
  dashboard,
}) => {
  const [projectName, setProjectName] = useState<string | null>(null);

  const dashboardId =
    (dashboard?.dashboard_id as string | undefined) ||
    (dashboard?._id as string | undefined) ||
    null;
  const projectId = (dashboard?.project_id as string | undefined) || null;
  const title =
    (typeof dashboard?.title === 'string' && dashboard.title) || null;
  const subtitle =
    (typeof dashboard?.subtitle === 'string' && dashboard.subtitle) || null;
  const ownerEmail = pickOwnerEmail(dashboard);
  const isPublic = Boolean(dashboard?.is_public);
  const lastSavedRaw =
    (typeof dashboard?.last_saved_ts === 'string' && dashboard.last_saved_ts) ||
    null;
  const lastSaved = lastSavedRaw ? formatTimestamp(lastSavedRaw) : null;
  const realtimeEnabled = Boolean(
    (dashboard?.project_realtime as { enabled?: boolean } | undefined)?.enabled,
  );
  const isMainTab =
    typeof dashboard?.is_main_tab === 'boolean'
      ? (dashboard.is_main_tab as boolean)
      : null;
  const parentDashboardId =
    (dashboard?.parent_dashboard_id as string | undefined) || null;

  // Resolve project_id → project.name asynchronously. Skip enrichment to
  // keep the request small (we only need the name).
  useEffect(() => {
    if (!projectId || !opened) {
      setProjectName(null);
      return;
    }
    let cancelled = false;
    fetchProject(projectId, { skipEnrichment: true })
      .then(({ project }) => {
        if (!cancelled) setProjectName(project.name ?? null);
      })
      .catch(() => {
        if (!cancelled) setProjectName(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, opened]);

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="md"
      title={
        <Group gap="xs">
          <Icon icon="mdi:cog" width={20} />
          <Text fw={600}>Dashboard settings</Text>
        </Group>
      }
    >
      <Stack gap="md">
        {title && (
          <Stack gap={2}>
            <Text size="lg" fw={600}>
              {title}
            </Text>
            {subtitle && (
              <Text size="sm" c="dimmed">
                {subtitle}
              </Text>
            )}
          </Stack>
        )}

        <Divider />

        <JourneysSection />

        <Divider />

        <Stack gap="sm">
          <MetaRow
            icon="mdi:jira"
            iconColor="var(--mantine-color-teal-6)"
            label="Project"
            value={
              projectName ? (
                <Text size="sm" fw={500}>
                  {projectName}
                </Text>
              ) : (
                <Text size="sm" c="dimmed">
                  {projectId ? 'Loading…' : '—'}
                </Text>
              )
            }
          />
          {ownerEmail && (
            <MetaRow
              icon="mdi:account-circle-outline"
              iconColor="var(--mantine-color-blue-6)"
              label="Owner"
              value={<Text size="sm">{ownerEmail}</Text>}
            />
          )}
          <MetaRow
            icon={isPublic ? 'mdi:earth' : 'mdi:lock'}
            iconColor={
              isPublic
                ? 'var(--mantine-color-teal-6)'
                : 'var(--mantine-color-violet-6)'
            }
            label="Visibility"
            value={
              <Badge
                color={isPublic ? 'teal' : 'violet'}
                variant="light"
                size="md"
              >
                {isPublic ? 'Public' : 'Private'}
              </Badge>
            }
          />
          {lastSaved && (
            <MetaRow
              icon="mdi:clock-outline"
              iconColor="var(--mantine-color-gray-6)"
              label="Last modified"
              value={<Text size="sm">{lastSaved}</Text>}
            />
          )}
          {realtimeEnabled && (
            <MetaRow
              icon="mdi:flash"
              iconColor="var(--mantine-color-orange-6)"
              label="Realtime"
              value={
                <Badge color="orange" variant="light" size="md">
                  Enabled
                </Badge>
              }
            />
          )}
          {isMainTab === false && parentDashboardId && (
            <MetaRow
              icon="mdi:tab"
              iconColor="var(--mantine-color-grape-6)"
              label="Parent tab"
              value={<Code>{parentDashboardId}</Code>}
            />
          )}
        </Stack>

        <Divider label="Identifiers" labelPosition="left" my="xs" />

        <Stack gap="xs">
          {dashboardId && <CopyableId label="Dashboard ID" value={dashboardId} />}
          {projectId && <CopyableId label="Project ID" value={projectId} />}
        </Stack>
      </Stack>
    </Drawer>
  );
};

interface MetaRowProps {
  icon: string;
  iconColor: string;
  label: string;
  value: React.ReactNode;
}

const MetaRow: React.FC<MetaRowProps> = ({ icon, iconColor, label, value }) => (
  <Group gap="sm" wrap="nowrap" align="center">
    <Icon icon={icon} width={20} color={iconColor} />
    <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
        {label}
      </Text>
      {value}
    </Stack>
  </Group>
);

const CopyableId: React.FC<{ label: string; value: string }> = ({
  label,
  value,
}) => (
  <Group gap="xs" wrap="nowrap" align="center">
    <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
        {label}
      </Text>
      <Code style={{ overflowWrap: 'anywhere' }}>{value}</Code>
    </Stack>
    <CopyButton value={value} timeout={1500}>
      {({ copied, copy }) => (
        <Tooltip label={copied ? 'Copied' : 'Copy'} withArrow withinPortal>
          <ActionIcon
            variant="subtle"
            color={copied ? 'teal' : 'gray'}
            size="sm"
            onClick={copy}
          >
            <Icon
              icon={copied ? 'mdi:check' : 'mdi:content-copy'}
              width={14}
            />
          </ActionIcon>
        </Tooltip>
      )}
    </CopyButton>
  </Group>
);

export default SettingsDrawer;
