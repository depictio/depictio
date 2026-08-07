import React from 'react';
import { Divider, Drawer, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData, InteractiveFilter } from 'depictio-react-core';
import DashboardInfoBody from './DashboardInfoBody';
import ShareFiltersButton from './ShareFiltersButton';

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
  /** Current filter state, for the Share section's copy-link button.
   *  Omitted by hosts without one (the editor) — the button then copies the
   *  plain page URL. */
  filters?: InteractiveFilter[];
  activeFilterCount?: number;
}

/**
 * Right-side drawer with read-only metadata about the current dashboard,
 * followed by per-dashboard actions grouped in labelled sections (Share
 * today; serverless export is planned as a sibling section).
 *
 * The metadata content lives in `DashboardInfoBody`, shared with the
 * inspector's Info tab — which is what the inspector replaces this drawer
 * with when enabled.
 */
const SettingsDrawer: React.FC<SettingsDrawerProps> = ({
  opened,
  onClose,
  dashboard,
  filters = [],
  activeFilterCount = 0,
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
    <DashboardInfoBody dashboard={dashboard} active={opened} />
    <Divider label="Share" labelPosition="left" my="md" />
    <ShareFiltersButton filters={filters} activeCount={activeFilterCount} />
  </Drawer>
);

export default SettingsDrawer;
