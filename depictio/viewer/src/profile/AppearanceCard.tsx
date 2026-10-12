import React from 'react';
import { Group, Paper, Radio, Stack, Text, Title } from '@mantine/core';
import { Icon } from '@iconify/react';

import { CHROME_VARIANTS, useChromeChoice } from '../chrome/variants';

/** Value of the "follow the instance" option; a style id never collides with it. */
const FOLLOW_INSTANCE = '';

/**
 * The reader's own look for the app. Kept in this browser; without a pick the
 * instance default (set by an admin) applies, then Glass.
 */
const AppearanceCard: React.FC = () => {
  const { pick, instanceDefault, choose } = useChromeChoice();
  return (
    <Paper shadow="md" radius="lg" p="xl" withBorder data-testid="profile-appearance">
      <Stack gap="md">
        <Group justify="space-between">
          <Title order={3} fw={600}>
            Appearance
          </Title>
          <Icon icon="mdi:palette-outline" width={28} height={28} />
        </Group>
        <Text size="sm" c="dimmed">
          How the app looks to you. Saved in this browser only.
        </Text>
        <Radio.Group
          value={pick ?? FOLLOW_INSTANCE}
          onChange={(value) => choose(value === FOLLOW_INSTANCE ? null : value)}
          data-testid="chrome-style-section"
        >
          <Stack gap="xs">
            <Radio
              value={FOLLOW_INSTANCE}
              label={`Instance default (${instanceDefault.name})`}
              description="Whatever this instance's admin chose"
              data-testid="chrome-style-default"
            />
            {CHROME_VARIANTS.map((v) => (
              <Radio
                key={v.id}
                value={v.id}
                label={v.name}
                description={v.tagline}
                data-testid={`chrome-style-${v.id}`}
              />
            ))}
          </Stack>
        </Radio.Group>
      </Stack>
    </Paper>
  );
};

export default AppearanceCard;
