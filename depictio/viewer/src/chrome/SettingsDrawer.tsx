import React from 'react';
import { Divider, Drawer, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData } from 'depictio-react-core';
import DashboardInfoBody from './DashboardInfoBody';

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
  /** Extra section rendered above the dashboard info (e.g. the AI key
   *  section when the AI feature is enabled). */
  extraSection?: React.ReactNode;
}

/**
 * Right-side drawer with read-only metadata about the current dashboard.
 *
 * The content lives in `DashboardInfoBody`, shared with the inspector's Info
 * tab — which is what the inspector replaces this drawer with when enabled.
 */
const SettingsDrawer: React.FC<SettingsDrawerProps> = ({
  opened,
  onClose,
  dashboard,
  extraSection,
}) => (
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
    {extraSection && (
      <>
        {extraSection}
        <Divider my="md" />
      </>
    )}
    <DashboardInfoBody dashboard={dashboard} active={opened} />
  </Drawer>
);

export default SettingsDrawer;
