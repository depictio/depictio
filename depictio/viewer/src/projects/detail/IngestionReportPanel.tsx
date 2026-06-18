import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Card,
  Center,
  Code,
  CopyButton,
  Divider,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  fetchIngestionReport,
  fetchDataCollectionFiles,
  type IngestionReport,
  type IngestionDataCollection,
  type RegisteredFile,
} from 'depictio-react-core';
import { DcTypeIcon } from '../dcTypeIcon';

/** Visual treatment per DC display-status. Colors are Mantine palette names
 *  (theme tokens), not literals — they recolor with the active theme. */
const STATUS_META: Record<string, { color: string; icon: string; label: string }> = {
  identified: { color: 'green', icon: 'mdi:check-circle', label: 'Identified' },
  aggregated: { color: 'teal', icon: 'mdi:database-check', label: 'Aggregated' },
  found_zero: { color: 'yellow', icon: 'mdi:alert', label: 'No files found' },
  gated_out: { color: 'gray', icon: 'mdi:filter-remove-outline', label: 'Gated out' },
};

/** Status legend — same keys/icons/colors as STATUS_META so the tiles match the
 *  icons shown in the Status column. */
const LEGEND: Array<{ key: string; desc: string }> = [
  { key: 'identified', desc: 'Source files matched (expand to list them)' },
  { key: 'aggregated', desc: 'Table derived from other collections (expand for inputs + path)' },
  { key: 'found_zero', desc: 'Expected, but nothing was found' },
  { key: 'gated_out', desc: 'Excluded by a template condition (hover for the reason)' },
];

const HEALTH_META: Record<string, { color: string; icon: string; label: string }> = {
  ok: { color: 'green', icon: 'mdi:check-circle', label: 'Healthy' },
  partial: { color: 'yellow', icon: 'mdi:alert', label: 'Partial' },
  missing_required: { color: 'red', icon: 'mdi:alert-octagon', label: 'Missing required data' },
};

const RUN_STATUS_COLOR: Record<string, string> = { ok: 'green', partial: 'yellow' };

/** Plain list of monospace paths that wrap instead of widening their container. */
const PathsList: React.FC<{ paths: string[] }> = ({ paths }) => (
  <Stack gap={2}>
    {paths.map((p, i) => (
      <Code key={`${p}-${i}`} block style={{ fontSize: 11, overflowWrap: 'anywhere' }}>
        {p}
      </Code>
    ))}
  </Stack>
);

/** One monospace path with a copy button — used for the aggregated table path. */
const PathLine: React.FC<{ path: string }> = ({ path }) => (
  <Group gap={4} wrap="nowrap" mt={6} style={{ maxWidth: 360, minWidth: 0 }}>
    <Icon icon="mdi:database-outline" width={13} color="var(--mantine-color-gray-6)" />
    <Tooltip label={path} withArrow withinPortal multiline maw={420}>
      <Text size="xs" ff="monospace" truncate>
        {path}
      </Text>
    </Tooltip>
    <CopyButton value={path} timeout={1500}>
      {({ copied, copy }) => (
        <ActionIcon
          variant="subtle"
          color={copied ? 'teal' : 'gray'}
          size="xs"
          onClick={copy}
          style={{ flexShrink: 0 }}
        >
          <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={13} />
        </ActionIcon>
      )}
    </CopyButton>
  </Group>
);

/** "identified but 0 files + aggregated" is reported by the backend as
 *  `identified`; surface it as a distinct "Aggregated" display status so a
 *  count of 0 reads sensibly (e.g. MultiQC / recipe-derived collections that
 *  produce a table without scanning individual source files). */
function displayStatus(dc: IngestionDataCollection): string {
  if (dc.status === 'identified' && dc.files_found === 0 && dc.ingested) return 'aggregated';
  return dc.status;
}

/** One icon+number tile in the summary strip. */
const SummaryStat: React.FC<{
  label: string;
  value: React.ReactNode;
  icon: string;
  color: string;
}> = ({ label, value, icon, color }) => (
  <Card withBorder padding="md" radius="md">
    <Group gap="sm" wrap="nowrap">
      <ThemeIcon size={40} radius="md" variant="light" color={color}>
        <Icon icon={icon} width={22} />
      </ThemeIcon>
      <Stack gap={0} style={{ minWidth: 0 }}>
        <Text size="xl" fw={700} c={color === 'gray' ? undefined : color}>
          {value}
        </Text>
        <Text size="xs" c="dimmed">
          {label}
        </Text>
      </Stack>
    </Group>
  </Card>
);

/** A compact inline "icon · label · value" metadata chip for the header row. */
const InlineMeta: React.FC<{ icon: string; label: string; value?: string | null }> = ({
  icon,
  label,
  value,
}) => (
  <Group gap={6} wrap="nowrap">
    <Icon icon={icon} width={15} color="var(--mantine-color-gray-6)" />
    <Text size="xs" c="dimmed">
      {label}
    </Text>
    <Text size="xs" fw={500}>
      {value || '—'}
    </Text>
  </Group>
);

/** Expandable file list for one identified data collection. Lazily fetches the
 *  registered files the first time the row is expanded and shows their full
 *  paths (falling back to filename when no location was recorded). */
/** Lazily fetches and lists a DC's registered file paths. Rendered only when its
 *  details row is expanded, so the fetch happens on demand. */
const DcFileList: React.FC<{ dcId: string | null; tag: string }> = ({ dcId, tag }) => {
  const [files, setFiles] = useState<RegisteredFile[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dcId) return;
    let cancelled = false;
    setLoading(true);
    fetchDataCollectionFiles(dcId)
      .then((f) => !cancelled && setFiles(f))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [dcId]);

  if (!dcId) return null;
  return (
    <Stack gap={2}>
      {loading && <Loader size="xs" />}
      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}
      {files && files.length === 0 && (
        <Text size="xs" c="dimmed">
          No files registered for {tag}.
        </Text>
      )}
      {files && files.length > 0 && (
        <Stack gap={2}>
          {files.map((f, i) => (
            <Code
              key={`${f.file_location ?? f.filename ?? i}`}
              block
              style={{ fontSize: 11, overflowWrap: 'anywhere' }}
            >
              {f.file_location || f.filename || '(unnamed)'}
            </Code>
          ))}
        </Stack>
      )}
    </Stack>
  );
};

const DcRow: React.FC<{
  dc: IngestionDataCollection;
  dcId: string | null;
  onPreviewDc?: (dcId: string) => void;
}> = ({ dc, dcId, onPreviewDc }) => {
  const status = displayStatus(dc);
  const meta = STATUS_META[status] ?? STATUS_META.found_zero;
  const canPreview = Boolean(dcId && onPreviewDc && dc.status !== 'gated_out');
  const filesCell =
    dc.status === 'gated_out' || status === 'aggregated' ? '—' : dc.files_found;

  const [expanded, setExpanded] = useState(false);
  const showFiles = dc.status === 'identified' && dc.files_found > 0 && Boolean(dcId);
  const showAgg =
    status === 'aggregated' &&
    (dc.source_inputs.length > 0 || Boolean(dc.table_location) || Boolean(dc.recipe));
  const hasDetails = showFiles || showAgg;

  return (
    <>
    <Table.Tr>
      <Table.Td>
        <Group gap={8} wrap="nowrap">
          <DcTypeIcon type={dc.type} />
          {canPreview ? (
            <Tooltip label="Open data collection preview" withArrow withinPortal>
              <Anchor component="button" type="button" onClick={() => onPreviewDc!(dcId!)}>
                <Group gap={4} wrap="nowrap">
                  <Text fw={600} size="sm">
                    {dc.data_collection_tag}
                  </Text>
                  <Icon icon="mdi:table-eye" width={14} />
                </Group>
              </Anchor>
            </Tooltip>
          ) : (
            <Text fw={600} size="sm">
              {dc.data_collection_tag}
            </Text>
          )}
        </Group>
      </Table.Td>
      <Table.Td>
        <Badge variant="light" color={dc.optional ? 'gray' : 'blue'} size="sm">
          {dc.optional ? 'optional' : 'required'}
        </Badge>
      </Table.Td>
      <Table.Td>
        <Group gap={6} wrap="nowrap">
          <Icon icon={meta.icon} width={18} color={`var(--mantine-color-${meta.color}-6)`} />
          <Text size="sm">{meta.label}</Text>
          {dc.removal_reason && (
            <Tooltip label={dc.removal_reason} multiline w={260} withArrow withinPortal>
              <Icon icon="mdi:information-outline" width={15} />
            </Tooltip>
          )}
          {status === 'aggregated' && (
            <Tooltip
              label="This collection's table is derived from other collections (e.g. a recipe or a MultiQC report), so it has no source files of its own."
              multiline
              w={280}
              withArrow
              withinPortal
            >
              <Icon icon="mdi:information-outline" width={15} />
            </Tooltip>
          )}
        </Group>
      </Table.Td>
      <Table.Td>
        <Text size="sm">{filesCell}</Text>
      </Table.Td>
      <Table.Td>
        <Group gap={8} wrap="nowrap">
          {dc.status === 'gated_out' ? (
            <Text size="sm" c="dimmed">
              —
            </Text>
          ) : (
            <Icon
              icon={dc.ingested ? 'mdi:database-check' : 'mdi:database-off-outline'}
              width={18}
              color={`var(--mantine-color-${dc.ingested ? 'green' : 'gray'}-6)`}
            />
          )}
          {hasDetails && (
            <UnstyledButton onClick={() => setExpanded((e) => !e)}>
              <Group gap={2} wrap="nowrap">
                <Icon icon={expanded ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={16} />
                <Text size="xs" c="dimmed">
                  {showFiles ? 'files' : 'details'}
                </Text>
              </Group>
            </UnstyledButton>
          )}
        </Group>
      </Table.Td>
    </Table.Tr>
    {expanded && hasDetails && (
      <Table.Tr>
        <Table.Td colSpan={5} style={{ background: 'var(--mantine-color-default-hover)' }}>
          <div style={{ padding: '4px 0 4px 28px' }}>
            {showFiles && <DcFileList dcId={dcId} tag={dc.data_collection_tag} />}
            {showAgg && (
              <Stack gap={8}>
                {dc.recipe && (
                  <Group gap={6} wrap="nowrap">
                    <Icon
                      icon="mdi:flask-outline"
                      width={14}
                      color="var(--mantine-color-grape-6)"
                    />
                    <Text size="xs" fw={600} c="dimmed">
                      Recipe
                    </Text>
                    {dc.recipe_url ? (
                      <Anchor
                        href={dc.recipe_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        size="xs"
                      >
                        <Group gap={3} wrap="nowrap">
                          <Code style={{ fontSize: 11 }}>{dc.recipe}</Code>
                          <Icon icon="mdi:github" width={14} />
                        </Group>
                      </Anchor>
                    ) : (
                      <Code style={{ fontSize: 11 }}>{dc.recipe}</Code>
                    )}
                  </Group>
                )}
                {dc.source_inputs.length > 0 && (
                  <div>
                    <Text size="xs" fw={600} c="dimmed" mb={2}>
                      Aggregation inputs
                    </Text>
                    <PathsList paths={dc.source_inputs} />
                  </div>
                )}
                {dc.table_location && (
                  <div>
                    <Text size="xs" fw={600} c="dimmed" mb={2}>
                      Output table
                    </Text>
                    <PathLine path={dc.table_location} />
                  </div>
                )}
              </Stack>
            )}
          </div>
        </Table.Td>
      </Table.Tr>
    )}
    </>
  );
};

interface IngestionReportPanelProps {
  projectId: string;
  /** Map of DC tag → DC id, so identified rows can fetch their file lists. */
  dcIdByTag: Record<string, string>;
  /** Select a data collection in the Overview tab to preview its table. */
  onPreviewDc?: (dcId: string) => void;
}

const IngestionReportPanel: React.FC<IngestionReportPanelProps> = ({
  projectId,
  dcIdByTag,
  onPreviewDc,
}) => {
  const [report, setReport] = useState<IngestionReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchIngestionReport(projectId)
      .then((r) => {
        if (!cancelled) setReport(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (loading) {
    return (
      <Center mih={200}>
        <Loader />
      </Center>
    );
  }
  if (error) {
    return (
      <Alert color="red" icon={<Icon icon="mdi:alert-circle" />} title="Could not load report">
        {error}
      </Alert>
    );
  }
  if (!report) return null;

  const health = HEALTH_META[report.summary.health] ?? HEALTH_META.ok;
  const { summary, template } = report;

  return (
    <Stack gap="md">
      {/* Header — compact identity bar + inline run context */}
      <Paper withBorder radius="md" p="sm">
        <Group justify="space-between" wrap="nowrap" align="center" gap="sm">
          <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
            <ThemeIcon size={34} radius="md" variant="light" color={health.color}>
              <Icon icon="mdi:clipboard-check-outline" width={20} />
            </ThemeIcon>
            <div style={{ minWidth: 0 }}>
              <Text size="lg" fw={700} truncate>
                {report.project.name}
              </Text>
              {template?.template_id && (
                <Text size="xs" c="dimmed" truncate>
                  {template.template_id}
                  {template.template_version ? ` · v${template.template_version}` : ''}
                </Text>
              )}
            </div>
          </Group>
          <Badge
            size="lg"
            radius="sm"
            variant="light"
            color={health.color}
            leftSection={<Icon icon={health.icon} width={14} />}
            style={{ flexShrink: 0 }}
          >
            {health.label}
          </Badge>
        </Group>

        <Divider my="xs" />

        <Group gap="lg" wrap="wrap">
          <InlineMeta icon="mdi:calendar-check" label="Applied" value={template?.applied_at} />
          <InlineMeta icon="mdi:clock-outline" label="Last scan" value={report.scanned_at} />
          <InlineMeta icon="mdi:database-outline" label="Runs" value={String(report.runs.length)} />
          {template?.data_root && (
            <Group gap={6} wrap="nowrap" style={{ minWidth: 0, maxWidth: 360 }}>
              <Icon
                icon="mdi:folder-outline"
                width={15}
                color="var(--mantine-color-gray-6)"
                style={{ flexShrink: 0 }}
              />
              <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                Data root
              </Text>
              <Tooltip label={template.data_root} withArrow multiline maw={420} withinPortal>
                <Text size="xs" fw={500} truncate>
                  {template.data_root}
                </Text>
              </Tooltip>
              <CopyButton value={template.data_root} timeout={1500}>
                {({ copied, copy }) => (
                  <ActionIcon
                    variant="subtle"
                    color={copied ? 'teal' : 'gray'}
                    size="sm"
                    onClick={copy}
                    style={{ flexShrink: 0 }}
                  >
                    <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
                  </ActionIcon>
                )}
              </CopyButton>
            </Group>
          )}
        </Group>

        {report.manifest_source === 'live_project' && (
          <Alert mt="xs" color="yellow" variant="light" icon={<Icon icon="mdi:information" />}>
            This project was created before ingestion-report tracking was added, so the collections
            the template skipped or gated out weren't recorded — only the collections actually
            present are listed below. Re-import it from its template (depictio run --template …) to
            get the full expected-vs-found breakdown.
          </Alert>
        )}
      </Paper>

      {/* Summary tiles */}
      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
        <SummaryStat
          icon="mdi:shield-check"
          label="Required identified"
          value={`${summary.required_identified}/${summary.required_total}`}
          color={summary.required_missing > 0 ? 'orange' : 'green'}
        />
        <SummaryStat
          icon="mdi:alert-octagon"
          label="Required missing"
          value={summary.required_missing}
          color={summary.required_missing > 0 ? 'red' : 'gray'}
        />
        <SummaryStat
          icon="mdi:check-circle-outline"
          label="Optional identified"
          value={`${summary.optional_identified}/${summary.optional_total}`}
          color="teal"
        />
        <SummaryStat
          icon="mdi:filter-remove-outline"
          label="Gated out"
          value={summary.gated}
          color="gray"
        />
      </SimpleGrid>

      {/* Data collections table */}
      <Card withBorder padding="md" radius="md">
        <Title order={5} mb="sm">
          Data collections
        </Title>
        <Table.ScrollContainer minWidth={640}>
          <Table verticalSpacing="xs" striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Data collection</Table.Th>
                <Table.Th>Requirement</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Files</Table.Th>
                <Table.Th>Aggregated</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {report.data_collections.map((dc) => (
                <DcRow
                  key={dc.data_collection_tag}
                  dc={dc}
                  dcId={dcIdByTag[dc.data_collection_tag] ?? null}
                  onPreviewDc={onPreviewDc}
                />
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Card>

      {/* Parameters / variables */}
      {report.variables.length > 0 && (
        <Card withBorder padding="md" radius="md">
          <Title order={5} mb="sm">
            Parameters used
          </Title>
          <Table verticalSpacing="xs">
            <Table.Tbody>
              {report.variables.map((v) => (
                <Table.Tr key={v.name}>
                  <Table.Td w={220}>
                    <Text size="sm" fw={500}>
                      {v.name}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Code style={{ overflowWrap: 'anywhere' }}>{v.value}</Code>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}

      {/* Runs */}
      {report.runs.length > 0 && (
        <Card withBorder padding="md" radius="md">
          <Title order={5} mb="sm">
            Runs identified ({report.runs.length})
          </Title>
          <Table verticalSpacing="sm" striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Run</Table.Th>
                <Table.Th>Location</Table.Th>
                <Table.Th>Last scan</Table.Th>
                <Table.Th>Status</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {report.runs.map((r) => (
                <Table.Tr key={r.run_tag}>
                  <Table.Td>
                    <Group gap={6} wrap="nowrap">
                      <Icon
                        icon="mdi:dna"
                        width={16}
                        color="var(--mantine-color-grape-6)"
                      />
                      <Text size="sm" fw={600}>
                        {r.run_tag}
                      </Text>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Code style={{ overflowWrap: 'anywhere', fontSize: 11 }}>
                      {r.run_location || '—'}
                    </Code>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs">{r.scan_time || '—'}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge size="sm" variant="light" color={RUN_STATUS_COLOR[r.status] ?? 'gray'}>
                      {r.status}
                    </Badge>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="xs">
        {LEGEND.map(({ key, desc }) => {
          const m = STATUS_META[key];
          return (
            <Paper key={key} withBorder radius="md" p="xs">
              <Group gap={8} wrap="nowrap" align="flex-start">
                <Icon
                  icon={m.icon}
                  width={16}
                  color={`var(--mantine-color-${m.color}-6)`}
                  style={{ flexShrink: 0, marginTop: 2 }}
                />
                <div style={{ minWidth: 0 }}>
                  <Text size="xs" fw={600}>
                    {m.label}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {desc}
                  </Text>
                </div>
              </Group>
            </Paper>
          );
        })}
      </SimpleGrid>
    </Stack>
  );
};

export default IngestionReportPanel;
