import React from 'react';
import { Drawer, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData } from 'depictio-react-core';
import DashboardInfoBody from './DashboardInfoBody';

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
}

/**
 * Right-side drawer with read-only metadata about the current dashboard.
 *
 * The content lives in `DashboardInfoBody`, shared with the inspector's Info
 * tab — which is what the inspector replaces this drawer with when enabled.
 */
const SettingsDrawer: React.FC<SettingsDrawerProps> = ({ opened, onClose, dashboard }) => (
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
    <DashboardInfoBody dashboard={dashboard} active={opened} />
  </Drawer>
);

export default SettingsDrawer;
