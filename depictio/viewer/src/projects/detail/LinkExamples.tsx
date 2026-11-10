/** What a proposed link does, on real values: each source value beside what it
 *  reaches in the target, or that it reaches nothing. */
import React from 'react';
import { Table, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { LinkSuggestion } from 'depictio-react-core';

const MAX_TARGETS_SHOWN = 3;

export const LinkExamples: React.FC<{ suggestion: LinkSuggestion }> = ({ suggestion: s }) => {
  const examples = s.examples ?? [];
  if (examples.length === 0) return null;
  const targetColumn = s.target_field ?? 'samples';
  return (
    <Table withTableBorder verticalSpacing={4} fz="xs" data-testid="link-examples">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>
            {s.source_dc_tag} · {s.source_column}
          </Table.Th>
          <Table.Th w={32} aria-hidden />
          <Table.Th>
            {s.target_dc_tag} · {targetColumn}
          </Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {examples.map((example) => {
          const found = example.targets.length > 0;
          const extra = example.targets.length - MAX_TARGETS_SHOWN;
          return (
            <Table.Tr key={example.source} data-found={found}>
              <Table.Td style={{ overflowWrap: 'anywhere' }}>{example.source}</Table.Td>
              <Table.Td>
                <Icon
                  icon={found ? 'mdi:arrow-right' : 'mdi:close'}
                  width={14}
                  color={found ? undefined : 'var(--mantine-color-red-6)'}
                />
              </Table.Td>
              <Table.Td style={{ overflowWrap: 'anywhere' }}>
                {found ? (
                  `${example.targets.slice(0, MAX_TARGETS_SHOWN).join(', ')}${extra > 0 ? ` +${extra}` : ''}`
                ) : (
                  <Text span size="xs" c="dimmed">
                    Not found
                  </Text>
                )}
              </Table.Td>
            </Table.Tr>
          );
        })}
      </Table.Tbody>
    </Table>
  );
};
