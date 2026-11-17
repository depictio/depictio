import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Card,
  Center,
  Code,
  Collapse,
  CopyButton,
  Divider,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  ScrollArea,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
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
import RunProvenanceCard from './RunProvenanceCard';
import { SortableTh, formatTimestamp } from './DcViewerParts';
import DerivedLineage from './DerivedLineage';

/** Visual treatment per DC display-status. Colors are Mantine palette names
 *  (theme tokens), not literals — they recolor with the active theme. */
const STATUS_META: Record<string, { color: string; icon: string; label: string }> = {
  identified: { color: 'green', icon: 'mdi:check-circle', label: 'Identified' },
  aggregated: { color: 'teal', icon: 'mdi:source-branch', label: 'Derived' },
  found_zero: { color: 'yellow', icon: 'mdi:alert', label: 'No files found' },
  gated_out: { color: 'gray', icon: 'mdi:filter-remove-outline', label: 'Gated out' },
};

/** Status legend — same keys/icons/colors as STATUS_META so the tiles match the
 *  icons shown in the Status column. */
const LEGEND: Array<{ key: string; desc: string }> = [
  { key: 'identified', desc: 'Source files matched (expand to list them)' },
  { key: 'aggregated', desc: 'Computed by a recipe from other collections, with no files of its own (expand to see how)' },
  { key: 'found_zero', desc: 'Expected, but nothing was found' },
  { key: 'gated_out', desc: 'Excluded by a template condition (hover for the reason)' },
];

// `gated_out` is dropped from the legend without a manifest: no row can carry
// that status, so explaining it would describe something the reader cannot see.


const HEALTH_META: Record<string, { color: string; icon: string; label: string }> = {
  ok: { color: 'green', icon: 'mdi:check-circle', label: 'Healthy' },
  partial: { color: 'yellow', icon: 'mdi:alert', label: 'Partial' },
  missing_required: { color: 'red', icon: 'mdi:alert-octagon', label: 'Missing required data' },
};

// Trigger engines with a brand identity. Keyed by what the CLI stamps into
// `triggered_by`, which is the engine name in lowercase.
const TRIGGER_ENGINES: Record<string, { label: string; color: string; icon: string }> = {
  nextflow: { label: 'Nextflow', color: 'teal', icon: 'simple-icons:nextflow' },
};

const RUN_STATUS_COLOR: Record<string, string> = { ok: 'green', partial: 'yellow' };

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
  /** Explains a value the tile cannot state outright (e.g. an unknown count). */
  hint?: string;
}> = ({ label, value, icon, color, hint }) => {
  const card = (
    <Card withBorder padding="md" radius="md">
      <Group gap="sm" wrap="nowrap">
        <ThemeIcon size={40} radius="md" variant="light" color={color}>
          <Icon icon={icon} width={22} />
        </ThemeIcon>
        <Stack gap={0} style={{ minWidth: 0 }}>
          <Text size="xl" fw={700} c={color === 'gray' ? undefined : color}>
            {value}
          </Text>
          <Group gap={4} wrap="nowrap">
            <Text size="xs" c="dimmed">
              {label}
            </Text>
            {hint && (
              <Icon icon="mdi:help-circle-outline" width={12} color="var(--mantine-color-dimmed)" />
            )}
          </Group>
        </Stack>
      </Group>
    </Card>
  );
  return hint ? (
    <Tooltip label={hint} withArrow multiline maw={320} withinPortal>
      {card}
    </Tooltip>
  ) : (
    card
  );
};

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

const FILE_SEARCH_FROM = 9;

const formatSize = (bytes?: number | null): string => {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
};

const trimSlash = (p: string) => p.replace(/\/+$/, '');

/** The run a file was read from, by its location, and the file's folder
 *  inside that run ("" at its root). */
function placeInRun(
  location: string,
  runs: Array<{ run_tag: string; run_location?: string | null }>,
): { run: string | null; folder: string } {
  const dir = location.includes('/') ? location.slice(0, location.lastIndexOf('/')) : '';
  for (const r of runs) {
    const root = r.run_location ? trimSlash(r.run_location) : null;
    if (root && (dir === root || dir.startsWith(`${root}/`))) {
      return { run: r.run_tag, folder: dir.slice(root.length + 1) };
    }
  }
  return { run: null, folder: dir };
}

/** The files a collection registered: one row each, with the run it came
 *  from and where in that run, its size and when it changed. Fetched when the
 *  row is first unfolded. */
const DcFileList: React.FC<{
  dcId: string | null;
  tag: string;
  runs: Array<{ run_tag: string; run_location?: string | null }>;
}> = ({ dcId, tag, runs }) => {
  const [files, setFiles] = useState<RegisteredFile[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (!dcId) return;
    let cancelled = false;
    fetchDataCollectionFiles(dcId)
      .then((f) => !cancelled && setFiles(f))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [dcId]);

  if (!dcId) return null;
  if (error) {
    return (
      <Text size="xs" c="red">
        {error}
      </Text>
    );
  }
  if (!files) return <Loader size="xs" />;
  if (files.length === 0) {
    return (
      <Text size="xs" c="dimmed">
        No files registered for {tag}.
      </Text>
    );
  }
  const rows = files
    .map((f) => {
      const location = f.file_location || f.filename || '';
      return { f, location, ...placeInRun(location, runs) };
    })
    .sort((a, b) => (a.run ?? '').localeCompare(b.run ?? '', undefined, { numeric: true }) || a.location.localeCompare(b.location));
  const showRun = rows.some((r) => r.run);
  const needle = query.trim().toLowerCase();
  const shown = needle ? rows.filter((r) => r.location.toLowerCase().includes(needle)) : rows;

  return (
    <Stack gap="xs" data-testid={`ingestion-files-${tag}`}>
      {rows.length >= FILE_SEARCH_FROM && (
        <TextInput
          size="xs"
          maw={300}
          placeholder="Search files"
          aria-label={`Search the files of ${tag}`}
          leftSection={<Icon icon="mdi:magnify" width={14} />}
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
        />
      )}
      <ScrollArea.Autosize mah={320} type="auto">
        <Table verticalSpacing={4} horizontalSpacing="sm" fz="sm" layout="auto">
          <Table.Thead>
            <Table.Tr>
              <Table.Th fz="xs" c="dimmed" w="100%">File</Table.Th>
              {showRun && <Table.Th fz="xs" c="dimmed">Run</Table.Th>}
              <Table.Th fz="xs" c="dimmed" ta="right">Size</Table.Th>
              <Table.Th fz="xs" c="dimmed">Modified</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {shown.map(({ f, location, run, folder }, i) => (
              <Table.Tr key={`${location}-${i}`}>
                <Table.Td>
                  <Group gap={8} wrap="nowrap" align="flex-start">
                    <Icon icon="mdi:file-outline" width={15} style={{ opacity: 0.55, marginTop: 2, flexShrink: 0 }} />
                    <div style={{ minWidth: 0 }}>
                      <Text size="sm" fw={600} style={{ overflowWrap: 'anywhere' }}>
                        {f.filename || location.split('/').pop()}
                      </Text>
                      {folder && (
                        <Text size="xs" c="dimmed" ff="monospace" style={{ overflowWrap: 'anywhere' }}>
                          {folder}/
                        </Text>
                      )}
                    </div>
                  </Group>
                </Table.Td>
                {showRun && (
                  <Table.Td style={{ whiteSpace: 'nowrap' }}>
                    <Text size="sm" ff="monospace">
                      {run ?? '—'}
                    </Text>
                  </Table.Td>
                )}
                <Table.Td ta="right" style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                  {formatSize(f.filesize)}
                </Table.Td>
                <Table.Td style={{ whiteSpace: 'nowrap' }}>
                  <Text size="sm" c="dimmed">
                    {formatTimestamp(f.modification_time, { utc: false }) ?? '—'}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <CopyButton value={location} timeout={1500}>
                    {({ copied, copy }) => (
                      <Tooltip label={copied ? 'Copied' : 'Copy the full path'} withArrow>
                        <ActionIcon size="sm" variant="subtle" color="gray" onClick={copy} aria-label="Copy the full path">
                          <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
                        </ActionIcon>
                      </Tooltip>
                    )}
                  </CopyButton>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {shown.length === 0 && (
          <Text size="sm" c="dimmed">
            No file matches.
          </Text>
        )}
      </ScrollArea.Autosize>
    </Stack>
  );
};

/** One badge per non-zero change count, so a data collection and a run show
 *  the same change in the same colour. Empty when nothing changed. */
function changeBadges(added: number, updated: number, failed = 0): React.ReactNode[] {
  const badges: React.ReactNode[] = [];
  if (added > 0) {
    badges.push(
      <Badge key="new" size="sm" variant="light" color="blue">
        +{added} new
      </Badge>,
    );
  }
  if (updated > 0) {
    badges.push(
      <Badge key="updated" size="sm" variant="light" color="orange">
        {updated} updated
      </Badge>,
    );
  }
  if (failed > 0) {
    badges.push(
      <Badge key="failed" size="sm" variant="light" color="red">
        {failed} failed
      </Badge>,
    );
  }
  return badges;
}

/** "12 new · 3 updated" chips for one data collection.
 *
 *  Deliberately *not* a fifth entry in STATUS_META: status answers "is the
 *  expected data there", freshness answers "did it change recently". Folding
 *  the second into the first would make a collection that gained files look
 *  like a different kind of thing from one that did not.
 *
 *  The counts come from each run's most recent scan, so they describe the last
 *  ingestion rather than all-time totals — hence the tooltip. */
const ChangeChips: React.FC<{ dc: IngestionDataCollection }> = ({ dc }) => {
  const chips = changeBadges(dc.files_new, dc.files_updated, dc.files_failed);
  if (chips.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        —
      </Text>
    );
  }
  return (
    <Tooltip
      label="Counted from the latest scan of each run: what the most recent ingestion changed, not an all-time total."
      multiline
      w={280}
      withArrow
      withinPortal
    >
      <Group gap={4} wrap="nowrap">
        {chips}
      </Group>
    </Tooltip>
  );
};

const DcRow: React.FC<{
  dc: IngestionDataCollection;
  dcId: string | null;
  onPreviewDc?: (dcId: string) => void;
  runs: Array<{ run_tag: string; run_location?: string | null }>;
  lineage: LineageContext;
}> = ({ dc, dcId, onPreviewDc, runs, lineage }) => {
  const status = displayStatus(dc);
  const meta = STATUS_META[status] ?? STATUS_META.found_zero;
  const canPreview = Boolean(dcId && onPreviewDc && dc.status !== 'gated_out');
  const filesCell =
    dc.status === 'gated_out' || status === 'aggregated' ? '—' : dc.files_found;

  const [expanded, setExpanded] = useState(false);
  const showFiles = dc.status === 'identified' && dc.files_found > 0 && Boolean(dcId);
  const showAgg =
    status === 'aggregated' &&
    ((dc.recipe_inputs?.length ?? 0) > 0 ||
      dc.source_inputs.length > 0 ||
      Boolean(dc.table_location) ||
      Boolean(dc.recipe));
  const hasDetails = showFiles || showAgg;

  return (
    <>
    <Table.Tr
      onClick={hasDetails ? () => setExpanded((e) => !e) : undefined}
      style={hasDetails ? { cursor: 'pointer' } : undefined}
      data-testid={`ingestion-dc-row-${dc.data_collection_tag}`}
    >
      <Table.Td w={28}>
        {hasDetails && (
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            aria-label={expanded ? 'Hide the files' : 'Show the files'}
            aria-expanded={expanded}
          >
            <Icon icon={expanded ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />
          </ActionIcon>
        )}
      </Table.Td>
      <Table.Td>
        <Group gap={8} wrap="nowrap">
          <DcTypeIcon type={dc.type} />
          {canPreview ? (
            <Tooltip label="Open data collection preview" withArrow withinPortal>
              <Anchor
                component="button"
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onPreviewDc!(dcId!);
                }}
              >
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
        <ChangeChips dc={dc} />
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
        </Group>
      </Table.Td>
    </Table.Tr>
    {expanded && hasDetails && (
      <Table.Tr>
        <Table.Td />
        <Table.Td colSpan={6}>
          <div style={{ padding: '4px 0 8px' }}>
            {showFiles && <DcFileList dcId={dcId} tag={dc.data_collection_tag} runs={runs} />}
            {showAgg && (
              <DerivedLineage
                inputs={
                  dc.recipe_inputs?.length
                    ? dc.recipe_inputs
                    : dc.source_inputs.map((p) => ({ kind: 'file', name: p.split('/').pop() || p, path: p }))
                }
                recipe={dc.recipe}
                recipeUrl={dc.recipe_url}
                summary={dc.recipe_summary}
                description={dc.recipe_description}
                result={{
                  tag: dc.data_collection_tag,
                  type: (dc.type ?? 'table').toLowerCase(),
                  location: dc.table_location,
                  ...(lineage.shapeByTag[dc.data_collection_tag] ?? {}),
                }}
                typeByTag={lineage.typeByTag}
                emptyInputs={lineage.emptyTags}
                idByTag={lineage.idByTag}
                onOpenDc={onPreviewDc}
                onOpenResult={canPreview ? () => onPreviewDc!(dcId!) : undefined}
              />
            )}
          </div>
        </Table.Td>
      </Table.Tr>
    )}
    </>
  );
};

/** What a derived row needs to know about the other collections. */
interface LineageContext {
  typeByTag: Record<string, string>;
  emptyTags: Set<string>;
  idByTag: Record<string, string>;
  shapeByTag: Record<string, { rows: number | null; columns: number | null }>;
}

/** Order a problem first: what needs looking at sorts to the top ascending. */
const STATUS_RANK: Record<string, number> = { found_zero: 0, gated_out: 1, identified: 2, aggregated: 3 };

type IngestionSortKey = 'report' | 'tag' | 'requirement' | 'status' | 'files' | 'changes' | 'ingested';

const sortValue = (dc: IngestionDataCollection, key: IngestionSortKey): string | number => {
  switch (key) {
    case 'tag':
      return dc.data_collection_tag.toLowerCase();
    case 'requirement':
      return dc.optional ? 1 : 0;
    case 'status':
      return STATUS_RANK[displayStatus(dc)] ?? 9;
    case 'files':
      return dc.status === 'gated_out' || displayStatus(dc) === 'aggregated' ? -1 : dc.files_found;
    case 'changes':
      return dc.files_new + dc.files_updated + dc.files_failed;
    case 'ingested':
      return dc.ingested ? 1 : 0;
    default:
      return 0;
  }
};

/** The collections table: search and status filter once there are enough rows
 *  to hunt through, every column sortable. Report order is the default. */
const DcTable: React.FC<{
  dcs: IngestionDataCollection[];
  dcIdByTag: Record<string, string>;
  onPreviewDc?: (dcId: string) => void;
  runs: Array<{ run_tag: string; run_location?: string | null }>;
  lineage: LineageContext;
}> = ({ dcs, dcIdByTag, onPreviewDc, runs, lineage }) => {
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sortKey, setSortKey] = useState<IngestionSortKey>('report');
  const [dir, setDir] = useState<'asc' | 'desc'>('asc');

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const dc of dcs) c[displayStatus(dc)] = (c[displayStatus(dc)] ?? 0) + 1;
    return c;
  }, [dcs]);
  const statuses = Object.keys(STATUS_META).filter((k) => counts[k]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = dcs.filter((dc) => {
      if (statusFilter !== 'all' && displayStatus(dc) !== statusFilter) return false;
      if (!q) return true;
      return [dc.data_collection_tag, dc.type, dc.recipe].some((v) => v?.toLowerCase().includes(q));
    });
    if (sortKey === 'report') return filtered;
    const sign = dir === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const va = sortValue(a, sortKey);
      const vb = sortValue(b, sortKey);
      if (va === vb) return a.data_collection_tag.localeCompare(b.data_collection_tag);
      return va < vb ? -sign : sign;
    });
  }, [dcs, query, statusFilter, sortKey, dir]);

  const onSort = (k: string) => {
    if (k === sortKey) setDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(k as IngestionSortKey);
      // Counts read best largest first; names and statuses top-down.
      setDir(k === 'files' || k === 'changes' ? 'desc' : 'asc');
    }
  };
  const th = (label: string, k: IngestionSortKey) => (
    <SortableTh label={label} sortKey={k} activeKey={sortKey} dir={dir} onSort={onSort} />
  );
  const showTools = dcs.length >= 8;

  return (
    <Stack gap="sm">
      {showTools && (
        <Group gap="sm" wrap="wrap" justify="space-between">
          <Group gap="sm" wrap="wrap">
            <TextInput
              size="xs"
              w={240}
              placeholder="Search collections, types, recipes"
              leftSection={<Icon icon="mdi:magnify" width={14} />}
              value={query}
              onChange={(e) => setQuery(e.currentTarget.value)}
              data-testid="ingestion-dc-search"
            />
            {statuses.length > 1 && (
              <SegmentedControl
                size="xs"
                value={statusFilter}
                onChange={setStatusFilter}
                data-testid="ingestion-dc-status-filter"
                data={[
                  { value: 'all', label: `All ${dcs.length}` },
                  ...statuses.map((k) => ({ value: k, label: `${STATUS_META[k].label} ${counts[k]}` })),
                ]}
              />
            )}
          </Group>
          {rows.length !== dcs.length && (
            <Text size="xs" c="dimmed">
              {rows.length} of {dcs.length}
            </Text>
          )}
        </Group>
      )}
      <Table.ScrollContainer minWidth={640}>
        <Table verticalSpacing="xs" striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th />
              {th('Data collection', 'tag')}
              {th('Requirement', 'requirement')}
              {th('Status', 'status')}
              {th('Files', 'files')}
              {th('Changes', 'changes')}
              {th('Aggregated', 'ingested')}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((dc) => (
              <DcRow
                key={dc.data_collection_tag}
                dc={dc}
                dcId={dcIdByTag[dc.data_collection_tag] ?? null}
                onPreviewDc={onPreviewDc}
                runs={runs}
                lineage={lineage}
              />
            ))}
            {rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={7}>
                  <Text size="sm" c="dimmed" ta="center" py="sm">
                    No collection matches.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
};

interface IngestionReportPanelProps {
  projectId: string;
  /** Map of DC tag → DC id, so identified rows can fetch their file lists. */
  dcIdByTag: Record<string, string>;
  /** Select a data collection in the Overview tab to preview its table. */
  onPreviewDc?: (dcId: string) => void;
  /** Open the project's Runs tab, where each run is shown in full. */
  onShowRuns?: () => void;
  /** Rows and columns per collection tag, for a derived collection's result. */
  shapeByTag?: Record<string, { rows: number | null; columns: number | null }>;
}

const IngestionReportPanel: React.FC<IngestionReportPanelProps> = ({
  projectId,
  dcIdByTag,
  onPreviewDc,
  onShowRuns,
  shapeByTag = {},
}) => {
  const [report, setReport] = useState<IngestionReport | null>(null);
  const [runsOpen, setRunsOpen] = useState(false);
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
  // No frozen manifest: the report is assembled from the collections the project
  // currently declares. What a template excluded or pruned was never recorded,
  // so "gated out" is unknown here — not zero — and the expected-vs-found
  // framing has no baseline to compare against.
  const isLive = report.manifest_source === 'live_project';
  const lineage: LineageContext = {
    typeByTag: Object.fromEntries(
      report.data_collections.map((d) => [d.data_collection_tag, (d.type ?? 'table').toLowerCase()]),
    ),
    // A collection that matched nothing, or was left out, feeds nothing.
    emptyTags: new Set(
      report.data_collections
        .filter((d) => d.status === 'found_zero' || d.status === 'gated_out')
        .map((d) => d.data_collection_tag),
    ),
    idByTag: dcIdByTag,
    shapeByTag,
  };
  // A template project predating the manifest is a different story from a
  // project that never had a template: only the former can be re-imported.
  const isLegacyTemplate = isLive && !!template;
  // Only an automated ingestion earns a badge. "manual" is the default and the
  // overwhelming majority, so labelling it would be noise on every project.
  // The vocabulary is open, so whatever the server sends is shown as-is rather
  // than switched on.
  const trigger =
    report.triggered_by && report.triggered_by !== 'manual' ? report.triggered_by : null;
  // Engines we can badge properly. Nextflow is the only one whose brand mark is
  // in the bundled simple-icons set, so anything else keeps a generic pipeline
  // icon: a recognisable-but-wrong logo is worse than a neutral one.
  const engine = trigger
    ? (TRIGGER_ENGINES[trigger.toLowerCase()] ?? {
        label: trigger,
        color: 'violet',
        icon: 'mdi:pipe',
      })
    : null;
  const provenance = isLive
    ? {
        color: 'blue',
        icon: 'mdi:database-eye-outline',
        label: 'Live project',
        tip: "Built from the project's current data collections — there is no template manifest to compare against.",
      }
    : {
        color: 'gray',
        icon: 'mdi:file-document-check-outline',
        label: 'Template manifest',
        tip: 'Compared against the expected-collection manifest frozen when the template was applied.',
      };

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
          <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
            {engine && (
              <Tooltip
                label={
                  <Stack gap={2}>
                    <Text size="xs">
                      Ingested automatically when a {engine.label} pipeline completed, not by a
                      command someone ran.
                    </Text>
                    {/* Everything below is what the run itself reported, so it is
                        absent for a run whose engine left no breadcrumbs rather
                        than shown as "unknown". */}
                    {report.pipeline?.name && (
                      <Text size="xs">
                        Pipeline: {report.pipeline.name}
                        {report.pipeline.version ? ` ${report.pipeline.version}` : ''}
                      </Text>
                    )}
                    {report.pipeline?.engine_version && (
                      <Text size="xs">
                        {engine.label} {report.pipeline.engine_version}
                      </Text>
                    )}
                    {!!report.pipeline?.tool_count && (
                      <Text size="xs">
                        {report.pipeline.tool_count} tools recorded, listed under Run provenance
                      </Text>
                    )}
                    {template?.data_root && <Text size="xs">Ingested from {template.data_root}</Text>}
                  </Stack>
                }
                withArrow
                multiline
                maw={360}
                withinPortal
              >
                <Badge
                  size="lg"
                  radius="sm"
                  variant="light"
                  color={engine.color}
                  tt="none"
                  leftSection={<Icon icon={engine.icon} width={14} />}
                >
                  Triggered by {engine.label}
                </Badge>
              </Tooltip>
            )}
            <Tooltip label={provenance.tip} withArrow multiline maw={320} withinPortal>
              <Badge
                size="lg"
                radius="sm"
                variant="default"
                color={provenance.color}
                leftSection={<Icon icon={provenance.icon} width={14} />}
              >
                {provenance.label}
              </Badge>
            </Tooltip>
            <Badge
              size="lg"
              radius="sm"
              variant="light"
              color={health.color}
              leftSection={<Icon icon={health.icon} width={14} />}
            >
              {health.label}
            </Badge>
          </Group>
        </Group>

        <Divider my="xs" />

        <Group gap="lg" wrap="wrap">
          {template?.applied_at && (
            <InlineMeta icon="mdi:calendar-check" label="Applied" value={template.applied_at} />
          )}
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

        {isLegacyTemplate && (
          <Alert mt="xs" color="yellow" variant="light" icon={<Icon icon="mdi:information" />}>
            This project was created before ingestion-report tracking was added, so the collections
            the template skipped or gated out weren't recorded — only the collections actually
            present are listed below. Refresh it from its template (depictio ingest --template …
            --update-config) to get the full expected-vs-found breakdown.
          </Alert>
        )}
        {isLive && !template && (
          <Alert mt="xs" color="blue" variant="light" icon={<Icon icon="mdi:information" />}>
            This project wasn't created from a template, so there is no manifest of expected
            collections. Everything below is read from the collections the project declares today:
            it shows which of them have data, but it cannot tell you whether a collection is
            missing entirely.
          </Alert>
        )}
      </Paper>

      {/* Summary tiles */}
      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
        <SummaryStat
          icon="mdi:shield-check"
          label={isLive ? 'Required with data' : 'Required identified'}
          // Without a manifest the denominator is just "the collections that
          // exist", so the ratio compares a number to itself. Show the count.
          value={
            isLive
              ? summary.required_identified
              : `${summary.required_identified}/${summary.required_total}`
          }
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
          label={isLive ? 'Optional with data' : 'Optional identified'}
          value={
            isLive
              ? summary.optional_identified
              : `${summary.optional_identified}/${summary.optional_total}`
          }
          color="teal"
        />
        <SummaryStat
          icon="mdi:filter-remove-outline"
          label="Gated out"
          // A manifest is the only thing that records what a conditional
          // excluded. Reporting 0 without one would assert something unverified.
          value={isLive ? '—' : summary.gated}
          color="gray"
          hint={
            isLive
              ? 'Unknown without a template manifest — exclusions were never recorded for this project.'
              : undefined
          }
        />
      </SimpleGrid>

      {/* Data collections table */}
      <Card withBorder padding="md" radius="md">
        <Title order={5} mb="sm">
          Data collections
        </Title>
        <DcTable
          dcs={report.data_collections}
          dcIdByTag={dcIdByTag}
          onPreviewDc={onPreviewDc}
          runs={report.runs}
          lineage={lineage}
        />
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

      {/* Run provenance — pipeline parameters / thresholds / tool versions */}
      {(report.run_provenance?.length ?? 0) > 0 && (
        <RunProvenanceCard
          groups={report.run_provenance}
          files={report.run_provenance_files ?? []}
        />
      )}

      {/* Runs: what the last ingestion scanned. The Runs tab shows each run in full. */}
      {report.runs.length > 0 && (
        <Card withBorder padding="md" radius="md" data-testid="ingestion-runs-card">
          <Group justify="space-between" wrap="nowrap" gap="sm">
            <UnstyledButton onClick={() => setRunsOpen((o) => !o)} aria-expanded={runsOpen}>
              <Group gap={6} wrap="nowrap">
                <Icon icon={runsOpen ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={18} />
                <Title order={5}>Runs scanned ({report.runs.length})</Title>
              </Group>
            </UnstyledButton>
            {onShowRuns && (
              <Anchor component="button" type="button" size="sm" onClick={onShowRuns}>
                Open the Runs tab
              </Anchor>
            )}
          </Group>
          <Collapse in={runsOpen}>
          <Table verticalSpacing="sm" striped highlightOnHover mt="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Run</Table.Th>
                <Table.Th>Location</Table.Th>
                <Table.Th>Last scan</Table.Th>
                <Table.Th>Files</Table.Th>
                <Table.Th>Changes</Table.Th>
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
                    <Text size="sm">{r.files_total || '—'}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      {changeBadges(r.files_new, r.files_updated)}
                      {!r.files_new && !r.files_updated && (
                        <Text size="sm" c="dimmed">
                          —
                        </Text>
                      )}
                    </Group>
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
          </Collapse>
        </Card>
      )}

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="xs">
        {LEGEND.filter(({ key }) => !(isLive && key === 'gated_out')).map(({ key, desc }) => {
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
