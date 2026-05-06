/**
 * Bottom panel listing every column of the selected data collection with its
 * type. Mirrors the Dash "Data Collection — Columns description" section
 * rendered below most builder forms.
 */
import React from 'react';
import { Card, ScrollArea, Stack, Table, Text, Title } from '@mantine/core';
import { useBuilderStore } from '../store/useBuilderStore';

const ColumnsDescription: React.FC = () => {
  const cols = useBuilderStore((s) => s.cols);

  if (!cols || cols.length === 0) return null;

  return (
    <Stack gap="xs" mt="lg">
      <Title order={5} fw={700} size="sm">
        Data Collection — Columns description
      </Title>
      <Card withBorder radius="md" p="xs">
        <ScrollArea h={200}>
          <Table verticalSpacing="xs" horizontalSpacing="md" striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ width: 200 }}>
                  <Text size="xs" fw={700}>
                    Column
                  </Text>
                </Table.Th>
                <Table.Th style={{ width: 120 }}>
                  <Text size="xs" fw={700}>
                    Type
                  </Text>
                </Table.Th>
                <Table.Th>
                  <Text size="xs" fw={700}>
                    Details
                  </Text>
                </Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {cols.map((c) => (
                <Table.Tr key={c.name}>
                  <Table.Td>
                    <Text size="xs" ff="monospace">
                      {c.name}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {c.type || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed" lineClamp={1}>
                      {summarizeSpecs(c.specs)}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Card>
    </Stack>
  );
};

function summarizeSpecs(specs?: Record<string, unknown>): string {
  if (!specs) return '';
  const parts: string[] = [];
  if (typeof specs.min === 'number' || typeof specs.max === 'number') {
    parts.push(`min=${specs.min ?? '—'} max=${specs.max ?? '—'}`);
  }
  if (typeof specs.nunique === 'number') parts.push(`unique=${specs.nunique}`);
  if (Array.isArray(specs.unique_values)) {
    const sample = (specs.unique_values as unknown[])
      .slice(0, 3)
      .map((v) => String(v))
      .join(', ');
    if (sample) parts.push(`e.g. ${sample}`);
  }
  return parts.join(' · ');
}

export default ColumnsDescription;
