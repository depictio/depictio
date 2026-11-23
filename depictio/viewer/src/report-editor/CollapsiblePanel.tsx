import React, { useState } from 'react';
import { Box, Card, Collapse, Group, Text, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';

interface CollapsiblePanelProps {
  icon: string;
  title: string;
  /** One line shown beside the title while the panel is closed. */
  summary: string;
  defaultOpen?: boolean;
  testId?: string;
  children: React.ReactNode;
}

/** A card whose body opens and closes; its summary shows when it is closed. */
const CollapsiblePanel: React.FC<CollapsiblePanelProps> = ({
  icon,
  title,
  summary,
  defaultOpen = false,
  testId,
  children,
}) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Card withBorder radius="md" p="md" data-testid={testId}>
      <UnstyledButton
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        data-testid={testId ? `${testId}-toggle` : undefined}
        style={{ width: '100%' }}
      >
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <Icon icon={icon} width={18} />
            <Text fw={600}>{title}</Text>
            {!open && (
              <Text size="sm" c="dimmed" truncate>
                {summary}
              </Text>
            )}
          </Group>
          <Box c="dimmed" style={{ display: 'flex', flex: 'none' }} aria-hidden>
            <Icon icon={open ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={18} />
          </Box>
        </Group>
      </UnstyledButton>
      <Collapse in={open}>
        <Box pt="sm">{children}</Box>
      </Collapse>
    </Card>
  );
};

export default CollapsiblePanel;
