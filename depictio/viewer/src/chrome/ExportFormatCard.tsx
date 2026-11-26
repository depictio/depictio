import React from 'react';
import { Group, Paper, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

interface ExportFormatCardProps {
  icon: string;
  title: string;
  /** One sentence: what the file is and when to pick it. */
  description: React.ReactNode;
  /** The card's buttons. */
  children: React.ReactNode;
  /** Lines under the buttons: which view a ready copy shows, why an action
   *  is off (a tooltip on a disabled button never fires). */
  footer?: React.ReactNode;
  testId?: string;
}

/** One export format: an icon, what it gives, and the buttons that start it. */
const ExportFormatCard: React.FC<ExportFormatCardProps> = ({
  icon,
  title,
  description,
  children,
  footer,
  testId,
}) => (
  <Paper withBorder radius="md" p="sm" data-testid={testId}>
    <Group align="flex-start" wrap="nowrap" gap="sm">
      <ThemeIcon variant="light" size="lg" radius="md">
        <Icon icon={icon} width={20} />
      </ThemeIcon>
      <Stack gap="xs" style={{ flex: 1, minWidth: 0 }}>
        <div>
          <Text fw={600} size="sm">
            {title}
          </Text>
          <Text size="xs" c="dimmed" lh={1.4}>
            {description}
          </Text>
        </div>
        <Group gap="xs">{children}</Group>
        {footer}
      </Stack>
    </Group>
  </Paper>
);

export default ExportFormatCard;
