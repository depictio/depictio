import React from 'react';
import { Divider, Drawer, Group, Stack, Switch, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData } from 'depictio-react-core';
import DashboardInfoBody from './DashboardInfoBody';

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
  /** Editor-only: persists the dashboard's `funnel_filtering` field (issue
   *  #939). Omitted in the viewer, where the drawer stays read-only. */
  onToggleFunnelFiltering?: (enabled: boolean) => void;
}

/**
 * Right-side drawer with metadata about the current dashboard.
 *
 * The content lives in `DashboardInfoBody`, shared with the inspector's Info
 * tab — which is what the inspector replaces this drawer with when enabled.
 * The editor adds one writable control on top: the funnel-filtering default.
 */
const SettingsDrawer: React.FC<SettingsDrawerProps> = ({
  opened,
  onClose,
  dashboard,
  onToggleFunnelFiltering,
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
    {onToggleFunnelFiltering && (
      <Stack gap="xs" mb="md">
        <Switch
          label="Funnel filtering by default"
          description="Highlight, in every other filter, the values that still lead to a non-empty result set. Viewers can still turn it off from the filter panel."
          checked={Boolean(dashboard?.funnel_filtering)}
          onChange={(e) => onToggleFunnelFiltering(e.currentTarget.checked)}
          color="teal"
        />
        <Divider />
      </Stack>
    )}
    <DashboardInfoBody dashboard={dashboard} active={opened} />
  </Drawer>
);

export default SettingsDrawer;
