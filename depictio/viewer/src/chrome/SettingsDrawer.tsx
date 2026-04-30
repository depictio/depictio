import React from 'react';
import { Code, Divider, Drawer, Stack, Text } from '@mantine/core';

import type { DashboardData } from 'depictio-react-core';

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
}

/**
 * Right-side drawer with read-only metadata about the current dashboard.
 * Mirrors the Dash settings drawer shell — the Dash version exposes more
 * controls (toggles, actions); those will be ported in later phases.
 */
const SettingsDrawer: React.FC<SettingsDrawerProps> = ({ opened, onClose, dashboard }) => {
  const dashboardId =
    (dashboard?.dashboard_id as string | undefined) ||
    (dashboard?._id as string | undefined) ||
    '—';
  const projectId = (dashboard?.project_id as string | undefined) || '—';
  const title = dashboard?.title || '—';
  const ownerEmail = (dashboard?.owner_email as string | undefined) || '—';
  const lastModified = (dashboard?.last_modified as string | undefined) || '—';

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="md"
      title="Settings"
    >
      <Stack gap="sm">
        <MetaRow label="Dashboard ID" value={<Code>{dashboardId}</Code>} />
        <MetaRow label="Project ID" value={<Code>{projectId}</Code>} />
        <MetaRow label="Title" value={<Text size="sm">{title}</Text>} />
        <MetaRow label="Owner" value={<Text size="sm">{ownerEmail}</Text>} />
        <MetaRow label="Last modified" value={<Text size="sm">{lastModified}</Text>} />
        <Divider my="sm" />
        <Text size="sm" c="dimmed">
          More settings coming soon
        </Text>
      </Stack>
    </Drawer>
  );
};

interface MetaRowProps {
  label: string;
  value: React.ReactNode;
}

const MetaRow: React.FC<MetaRowProps> = ({ label, value }) => (
  <Stack gap={2}>
    <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
      {label}
    </Text>
    {value}
  </Stack>
);

export default SettingsDrawer;
