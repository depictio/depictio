import React, { useMemo, useState } from 'react';
import {
  Accordion,
  ActionIcon,
  Badge,
  Card,
  Code,
  CopyButton,
  Group,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { Z_LAYERS } from 'depictio-react-core';
import {
  isUnsetProvenanceValue,
  matchesProvenanceQuery,
  type ProvenanceGroupLike,
} from '../../lib/provenance';

/**
 * Undo the CLI's stringification where it is unambiguous, so the raw view
 * reads like the JSON the pipeline wrote rather than a wall of quoted
 * scalars. A value that round-trips through Number() is emitted as a number;
 * everything else stays a string, which keeps version strings like "1.10"
 * from being mangled into 1.1.
 */
function parseProvenanceScalar(value: string): unknown {
  if (value === 'null') return null;
  if (value === 'true') return true;
  if (value === 'false') return false;
  if (value !== '' && String(Number(value)) === value) return Number(value);
  return value;
}

interface RawBlock {
  source: string;
  count: number;
  json: string;
}

/**
 * One JSON blob per provenance source, rebuilt from the entries.
 *
 * Deliberately NOT the file's own bytes: the CLI parses the run's files and
 * stores the facts, never a copy of the text, so there is nothing verbatim to
 * serve. What this shows is every key/value that was collected from that
 * source, which is the same content minus the keys the template excluded and
 * minus formatting. The caption in the raw view says so.
 */
function rawBlocks(groups: ProvenanceGroupLike[]): RawBlock[] {
  const bySource = new Map<string, Record<string, unknown>>();
  for (const group of groups) {
    for (const entry of group.entries) {
      const source = entry.source || 'params';
      let bucket = bySource.get(source);
      if (!bucket) {
        bucket = {};
        bySource.set(source, bucket);
      }
      bucket[entry.key] = parseProvenanceScalar(entry.value);
    }
  }
  return [...bySource.entries()].map(([source, obj]) => ({
    source,
    count: Object.keys(obj).length,
    json: JSON.stringify(obj, null, 2),
  }));
}

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
  /** Title + blurb off when the host's own header already says what this is,
   *  so the modal doesn't stack two headings. The entry count and the source
   *  file list stay either way — they are per-run facts, not decoration. */
  withHeading?: boolean;
}> = ({ groups, files, withCard = true, withHeading = true }) => {
  const [query, setQuery] = useState('');
  // Unset parameters are hidden by default: half of an nf-core params file is
  // keys the run never touched, and a page of `null` buries the decisions that
  // were actually made. The switch is the escape hatch — nothing is dropped at
  // collection time, so "everything" stays one click away.
  const [hideUnset, setHideUnset] = useState(true);
  const [view, setView] = useState<'grouped' | 'raw'>('grouped');
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
  const raw = useMemo(() => rawBlocks(groups), [groups]);
  const total = groups.reduce((n, g) => n + g.entries.length, 0);
  const shown = filtered.reduce((n, g) => n + g.entries.length, 0);
  // Split the missing entries by cause, because "82 of 112" on its own reads
  // as data loss. Almost always it is just the unset switch doing its job.
  const unsetHidden = useMemo(() => {
    if (!hideUnset) return 0;
    return groups
      .flatMap((g) => g.entries)
      .filter((e) => matchesProvenanceQuery(e, query) && isUnsetProvenanceValue(e.value)).length;
  }, [groups, query, hideUnset]);

  const content = (
    <>
      <Group justify="space-between" align="baseline" mb={4}>
        {withHeading && <Title order={5}>Run provenance</Title>}
        <Text size="sm" c="dimmed" ml="auto">
          {view === 'raw' || shown === total
            ? `${total} entries`
            : `${shown} of ${total} entries`}
          {view === 'grouped' && unsetHidden > 0 ? `, ${unsetHidden} unset hidden` : ''}
          {files.length > 0 ? ` · ${files.join(', ')}` : ''}
        </Text>
      </Group>
      {withHeading && (
        <Text size="sm" c="dimmed" mb="sm">
          Parameters, filtering thresholds and tool versions captured from the
          pipeline run itself.
        </Text>
      )}
      <Group gap="sm" mb="sm" wrap="nowrap" align="center">
        <SegmentedControl
          size="xs"
          value={view}
          onChange={(value) => setView(value as 'grouped' | 'raw')}
          data={[
            { label: 'Grouped', value: 'grouped' },
            { label: 'Raw', value: 'raw' },
          ]}
        />
        {view === 'grouped' && (
          <>
            <TextInput
              size="xs"
              style={{ flex: 1 }}
              placeholder="Search parameters…"
              value={query}
              onChange={(e) => setQuery(e.currentTarget.value)}
            />
            <Tooltip
              label="Keys the run left at their default: null, false or empty"
              withArrow
              withinPortal
              zIndex={Z_LAYERS.tooltip}
            >
              <Switch
                size="xs"
                checked={hideUnset}
                onChange={(e) => setHideUnset(e.currentTarget.checked)}
                label={`Hide unset${unsetHidden > 0 ? ` (${unsetHidden})` : ''}`}
                styles={{ label: { whiteSpace: 'nowrap' } }}
              />
            </Tooltip>
          </>
        )}
      </Group>
      {view === 'grouped' && (
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
                              <Tooltip
                              label="Named in the template's provenance.highlight, so it also shows inline in the dashboard's Settings drawer"
                              withArrow
                              withinPortal
                              zIndex={Z_LAYERS.tooltip}
                              multiline
                              w={260}
                            >
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
      )}
      {view === 'raw' && (
        <Stack gap="md" style={{ minWidth: 0 }}>
          <Text size="sm" c="dimmed">
            One block per source the template collected from, rebuilt from the stored entries.
            Depictio keeps the values it read, not a copy of the file, so this is the same
            content rather than the original bytes: keys the template excluded are absent, and
            ordering is alphabetical.
          </Text>
          {raw.map((block) => (
            <Stack key={block.source} gap={4} style={{ minWidth: 0 }}>
              <Group gap="xs" justify="space-between" wrap="nowrap">
                <Group gap="xs" wrap="nowrap">
                  <Text size="sm" fw={600} ff="monospace">
                    {block.source}
                  </Text>
                  <Badge size="xs" variant="light" color="gray">
                    {block.count} keys
                  </Badge>
                </Group>
                <CopyButton value={block.json}>
                  {({ copied, copy }) => (
                    <ActionIcon
                      size="sm"
                      variant="subtle"
                      color={copied ? 'teal' : 'gray'}
                      onClick={copy}
                      aria-label={`Copy ${block.source} as JSON`}
                    >
                      <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
                    </ActionIcon>
                  )}
                </CopyButton>
              </Group>
              {/* Wrap rather than scroll sideways. The modal's ScrollArea lays
                  its content out as a table, so a child sized to a long line
                  (an nf-core reference URL runs past 120 chars) widens the
                  whole dialog instead of scrolling inside its own box. */}
              <Code
                block
                fz={12}
                style={{
                  maxHeight: 360,
                  overflowY: 'auto',
                  whiteSpace: 'pre-wrap',
                  overflowWrap: 'anywhere',
                }}
              >
                {block.json}
              </Code>
            </Stack>
          ))}
        </Stack>
      )}
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
