import React from 'react';
import { Group, Stack, Text } from '@mantine/core';

interface SecondaryMetricsProps {
  rows: { name: string; value: unknown }[];
}

const SecondaryMetrics: React.FC<SecondaryMetricsProps> = ({ rows }) => {
  if (!rows.length) return null;
  return (
    <Stack gap={4} mt="xs" px="sm" pb="sm">
      {rows.map((row) => (
        <Group key={row.name} justify="space-between" gap="xs" wrap="nowrap">
          <Text size="xs" c="dimmed" tt="capitalize">
            {row.name.replace(/_/g, ' ')}
          </Text>
          <Text size="xs" fw={500}>
            {formatSecondary(row.value)}
          </Text>
        </Group>
      ))}
    </Stack>
  );
};

function formatSecondary(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return '—';
    if (!Number.isInteger(v)) return v.toFixed(4).replace(/\.?0+$/, '');
    return String(v);
  }
  return String(v);
}

export default SecondaryMetrics;
