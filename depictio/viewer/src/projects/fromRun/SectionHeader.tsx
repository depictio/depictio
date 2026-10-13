/**
 * The header of a folded block in the run-folder plan (a group of data
 * collections, the template settings): a tinted icon, the title with its
 * count, and one line saying what the block holds.
 */
import React from 'react';
import { Group, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

interface SectionHeaderProps {
  icon: string;
  /** A Mantine palette name. */
  color: string;
  title: string;
  count: number;
  /** Said after the count, e.g. "2 overridden". */
  note?: string;
  description: string;
}

export const SectionHeader: React.FC<SectionHeaderProps> = ({
  icon,
  color,
  title,
  count,
  note,
  description,
}) => (
  <Group gap="sm" wrap="nowrap">
    <ThemeIcon variant="light" color={color} size="md" radius="md">
      <Icon icon={icon} width={16} />
    </ThemeIcon>
    <Stack gap={0} style={{ minWidth: 0 }}>
      <Text size="sm" fw={600}>
        {title}{' '}
        <Text span size="sm" c="dimmed" fw={400}>
          ({count}){note ? `, ${note}` : ''}
        </Text>
      </Text>
      <Text size="xs" c="dimmed">
        {description}
      </Text>
    </Stack>
  </Group>
);
