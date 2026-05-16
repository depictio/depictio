/**
 * FunnelsSection — Settings drawer entry for the Funnels feature.
 *
 * Reduced to the master enable/disable toggle: every funnel-related action
 * (create / switch / rename / delete / set-default funnels, reorder /
 * remove steps, switch view modes, inspect cascades) lives inside the
 * funnel modal launched from the dashboard header. Keeping Settings to
 * the toggle alone closes the open-the-modal-to-look, close-it-to-edit
 * loop authors were hitting.
 */

import React from 'react';
import { Badge, Box, Group, Switch, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useFunnelsEnabled } from '../hooks/useFunnelsEnabled';

const FunnelsSection: React.FC = () => {
  const [enabled, setEnabled] = useFunnelsEnabled();

  return (
    <Box>
      <Group gap={6} mb={6} align="center" justify="space-between" wrap="nowrap">
        <Group gap={6} align="center">
          <Icon icon="tabler:filter-cog" width={14} />
          <Text size="xs" tt="uppercase" c="dimmed" fw={600}>
            Funnels
          </Text>
          <Badge size="xs" variant="light" color="violet">
            experimental
          </Badge>
        </Group>
        <Switch
          size="xs"
          checked={enabled}
          onChange={(e) => setEnabled(e.currentTarget.checked)}
          aria-label="Enable funnels feature"
        />
      </Group>

      <Text size="sm" c="dimmed">
        {enabled
          ? 'Funnels are on. Manage them from the Funnel button in the dashboard header — Settings only owns this master toggle.'
          : 'Funnels are off. Turn the switch on to expose the pin-to-funnel icon on every filter card and the Funnel button in the dashboard header.'}
      </Text>
    </Box>
  );
};

export default FunnelsSection;
