import React from 'react';
import { Badge, Group, Spoiler, Table, Text } from '@mantine/core';
import type { StaticExportCollection } from 'depictio-react-core';

/**
 * What an offline file carries, per data collection: its name and type, the
 * rows, the columns, and whether a live table ships it whole. Read from the
 * binding preflight (`collections`), so it is the file's content, not a guess.
 * Shared by the owner's export modal and the public download preview (#1480).
 */
const CollectionInventory: React.FC<{ collections: StaticExportCollection[] }> = ({
  collections,
}) => {
  if (collections.length === 0) {
    return (
      <Text size="xs" c="dimmed" data-testid="collection-inventory-empty">
        No table data ships with this dashboard: every tile is a picture.
      </Text>
    );
  }
  return (
    <Table withTableBorder={false} verticalSpacing={4} fz="xs" data-testid="collection-inventory">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Collection</Table.Th>
          <Table.Th ta="right">Rows</Table.Th>
          <Table.Th>Columns</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {collections.map((c) => (
          <Table.Tr key={c.dc_id} data-testid="public-download-preview-collection">
            <Table.Td style={{ verticalAlign: 'top' }}>
              <Group gap={4} wrap="nowrap">
                <Text size="xs" fw={500}>
                  {c.name}
                </Text>
                {c.type && (
                  <Badge
                    variant="outline"
                    color="gray"
                    size="xs"
                    style={{ flexShrink: 0, textTransform: 'none' }}
                  >
                    {c.type}
                  </Badge>
                )}
              </Group>
              {c.whole && (
                <Badge variant="light" size="xs" mt={2} style={{ textTransform: 'none' }}>
                  ships whole
                </Badge>
              )}
            </Table.Td>
            <Table.Td ta="right" style={{ verticalAlign: 'top' }}>
              {c.rows.toLocaleString()}
            </Table.Td>
            <Table.Td style={{ verticalAlign: 'top' }}>
              <Spoiler
                maxHeight={36}
                showLabel="all columns"
                hideLabel="fewer"
                styles={{ control: { fontSize: 'var(--mantine-font-size-xs)' } }}
              >
                <Text size="xs" c="dimmed" style={{ wordBreak: 'break-word' }}>
                  {c.columns.length} · {c.columns.join(', ')}
                </Text>
              </Spoiler>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
};

export default CollectionInventory;
