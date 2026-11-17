/**
 * One source of a project's data, the same wherever sources are listed: an
 * icon, a title and a one-line summary always visible, the details folded
 * underneath. A run folder, a plain folder and dropped files all look alike
 * this way, and stay in sight side by side when their details are closed.
 */
import React, { useState } from 'react';
import { Box, Collapse, Group, Paper, Stack, Text, ThemeIcon, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useListingAccents } from '../../lib/useListingAccents';

export const SourceSection: React.FC<{
  icon: string;
  title: string;
  summary: React.ReactNode;
  defaultOpen?: boolean;
  testId: string;
  children: React.ReactNode;
}> = ({ icon, title, summary, defaultOpen = false, testId, children }) => {
  const accent = useListingAccents('projects');
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Paper withBorder radius="md" data-testid={testId} data-open={open}>
      <UnstyledButton
        w="100%"
        p="sm"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        data-testid={`${testId}-toggle`}
      >
        <Group gap="sm" wrap="nowrap">
          <ThemeIcon variant="light" color={accent.secondary} size="lg" radius="md">
            <Icon icon={icon} width={20} />
          </ThemeIcon>
          <Stack gap={0} style={{ flex: 1, minWidth: 0 }}>
            <Text size="sm" fw={600}>
              {title}
            </Text>
            <Text size="xs" c="dimmed" component="div" data-testid={`${testId}-summary`}>
              {summary}
            </Text>
          </Stack>
          <Icon icon={open ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={20} style={{ flexShrink: 0 }} />
        </Group>
      </UnstyledButton>
      <Collapse in={open}>
        <Box p="sm" style={{ borderTop: '1px solid var(--mantine-color-default-border)' }}>
          {children}
        </Box>
      </Collapse>
    </Paper>
  );
};
