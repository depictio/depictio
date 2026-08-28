import React, { useMemo, useState } from 'react';
import {
  Accordion,
  ActionIcon,
  Badge,
  Card,
  Code,
  CopyButton,
  Group,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  isUnsetProvenanceValue,
  matchesProvenanceQuery,
  type ProvenanceGroupLike,
} from '../../lib/provenance';

/**
 * The run's own provenance — every pipeline parameter, filtering threshold and
 * tool version the template's ProvenanceSpec collected, grouped per tool.
 * Complete by construction (only explicit exclude_keys are omitted at
 * collection time), so a search box keeps the long tail navigable. Highlighted
 * entries are the ones the dashboard Settings drawer also surfaces.
 */
const RunProvenanceCard: React.FC<{
  groups: ProvenanceGroupLike[];
  files: string[];
  /** Chrome off when the host already frames it (the dashboard's modal). */
  withCard?: boolean;
}> = ({ groups, files, withCard = true }) => {
  const [query, setQuery] = useState('');
  // Unset parameters are hidden by default: half of an nf-core params file is
  // keys the run never touched, and a page of `null` buries the decisions that
  // were actually made. The switch is the escape hatch — nothing is dropped at
  // collection time, so "everything" stays one click away.
  const [hideUnset, setHideUnset] = useState(true);
  const filtered = useMemo(() => {
    return groups
      .map((g) => ({
        ...g,
        entries: g.entries.filter(
          (e) =>
            matchesProvenanceQuery(e, query) && !(hideUnset && isUnsetProvenanceValue(e.value)),
        ),
      }))
      .filter((g) => g.entries.length > 0);
  }, [groups, query, hideUnset]);
  // Open every group while searching — a hit hidden behind a folded accordion
  // reads as "no result".
  const openValues = query.trim() ? filtered.map((g) => g.group) : undefined;
  const total = groups.reduce((n, g) => n + g.entries.length, 0);
  const shown = filtered.reduce((n, g) => n + g.entries.length, 0);

  const content = (
    <>
      <Group justify="space-between" align="baseline" mb={4}>
        <Title order={5}>Run provenance</Title>
        <Text size="xs" c="dimmed">
          {shown === total ? `${total} entries` : `${shown} of ${total} entries`} ·{' '}
          {files.join(', ')}
        </Text>
      </Group>
      <Text size="sm" c="dimmed" mb="sm">
        Parameters, filtering thresholds and tool versions captured from the
        pipeline run itself.
      </Text>
      <Group gap="sm" mb="sm" wrap="nowrap" align="center">
        <TextInput
          size="xs"
          style={{ flex: 1 }}
          placeholder="Search parameters…"
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
        />
        <Switch
          size="xs"
          checked={hideUnset}
          onChange={(e) => setHideUnset(e.currentTarget.checked)}
          label="Hide unset"
          styles={{ label: { whiteSpace: 'nowrap' } }}
        />
      </Group>
      <Accordion multiple variant="contained" radius="md" value={openValues}>
        {filtered.map((g) => (
          <Accordion.Item key={g.group} value={g.group}>
            <Accordion.Control>
              <Group gap="xs">
                <Text size="sm" fw={600}>
                  {g.group}
                </Text>
                <Badge size="xs" variant="light" color="gray">
                  {g.entries.length}
                </Badge>
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Table verticalSpacing={4}>
                <Table.Tbody>
                  {g.entries.map((e) => (
                    <Table.Tr key={`${g.group}:${e.key}`}>
                      <Table.Td w={280}>
                        <Group gap={6} wrap="nowrap">
                          <Text size="sm" fw={e.highlight ? 700 : 500} style={{ overflowWrap: 'anywhere' }}>
                            {e.key}
                          </Text>
                          {e.highlight && (
                            <Tooltip label="Shown in the dashboard's Settings drawer">
                              <Icon
                                icon="mdi:star"
                                width={12}
                                color="var(--mantine-color-yellow-6)"
                              />
                            </Tooltip>
                          )}
                        </Group>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={6} wrap="nowrap" justify="space-between">
                          <Code style={{ overflowWrap: 'anywhere' }}>{e.value}</Code>
                          <CopyButton value={e.value}>
                            {({ copied, copy }) => (
                              <ActionIcon
                                size="xs"
                                variant="subtle"
                                color={copied ? 'teal' : 'gray'}
                                onClick={copy}
                                aria-label={`Copy ${e.key}`}
                              >
                                <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={12} />
                              </ActionIcon>
                            )}
                          </CopyButton>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
    </>
  );

  return withCard ? (
    <Card withBorder padding="md" radius="md">
      {content}
    </Card>
  ) : (
    content
  );
};

export default RunProvenanceCard;
