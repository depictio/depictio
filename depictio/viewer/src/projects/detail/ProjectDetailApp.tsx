import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  ActionIcon,
  AppShell,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Paper,
  ScrollArea,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  Title,
  useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type { ColDef } from 'ag-grid-community';

import { notifications } from '@mantine/notifications';
import {
  Alert,
  Anchor,
  Modal,
  Select,
  Switch,
  Textarea,
  TextInput,
} from '@mantine/core';

import {
  fetchProject,
  fetchDataCollectionPreview,
  fetchMultiQCByDataCollection,
  renameDataCollection,
  deleteDataCollection,
  createDataCollectionFromUpload,
  createMultiQCDataCollection,
  checkMultiQCUniformity,
} from 'depictio-react-core';
import type {
  ProjectListEntry,
  PreviewResult,
  MultiQCReportSummary,
  DCLink,
} from 'depictio-react-core';
import LinksSection from './LinksSection';
import ManageDataCollectionModal, {
  type ManageDcType,
} from './ManageDataCollectionModal';
import { UnstyledDropZone } from '../../components/UnstyledDropZone';
import { useFolderDropzone } from '../../hooks/useFolderDropzone';

import { useCurrentUser } from '../../hooks/useCurrentUser';
import { AppSidebar } from '../../chrome';
import JoinsGraph from './JoinsGraph';
import { parseTemplate, TemplateChip, templateDocsUrl } from '../template';

interface DataCollectionShape {
  _id?: string;
  id?: string;
  data_collection_tag?: string;
  description?: string;
  registration_time?: string;
  /** S3 path of the registered delta table (post-aggregation) — stamped on
   *  the DC by the project enrichment query. */
  delta_location?: string;
  /** Last-aggregation snapshot. Shape depends on the DC type; we just
   *  pull `aggregation_time` for the "Last Aggregated" line. */
  last_aggregation?:
    | {
        aggregation_time?: string;
        [k: string]: unknown;
      }
    | Array<{ aggregation_time?: string; [k: string]: unknown }>;
  /** Free-form metadata bag — backend stamps `deltatable_size_bytes` for
   *  table-typed DCs and `total_file_size_bytes` / `s3_location` for
   *  multiqc DCs. Mirrors `flexible_metadata` on the Pydantic model. */
  flexible_metadata?: {
    deltatable_size_bytes?: number;
    deltatable_size_updated?: string;
    total_file_size_bytes?: number;
    file_size_bytes?: number;
    s3_size_bytes?: number;
    s3_location?: string;
    primary_s3_location?: string;
    [k: string]: unknown;
  } | null;
  config?: {
    type?: string;
    metatype?: string;
    dc_specific_properties?: { format?: string };
    [k: string]: unknown;
  };
  [k: string]: unknown;
}

/** Convert a byte count to a human-readable string. Mirrors the Dash
 *  `format_storage_size` helper at project_data_collections.py:85. */
function formatBytes(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

/** Pick the right storage size for a DC. Tables come from the delta-table
 *  size field; MultiQC DCs come from one of the file-size aliases. */
function getDcSizeBytes(dc: DataCollectionShape): number {
  const flex = dc.flexible_metadata || {};
  const type = (dc.config?.type as string | undefined)?.toLowerCase();
  if (type === 'multiqc') {
    return (
      (flex.total_file_size_bytes as number | undefined) ??
      (flex.file_size_bytes as number | undefined) ??
      (flex.s3_size_bytes as number | undefined) ??
      0
    );
  }
  return (flex.deltatable_size_bytes as number | undefined) ?? 0;
}

/** Pick the right "where is this data stored" string for a DC. */
function getDcStorageLocation(dc: DataCollectionShape): string {
  const dcId = (dc._id ?? dc.id) as string;
  const type = (dc.config?.type as string | undefined)?.toLowerCase();
  const flex = dc.flexible_metadata || {};
  if (type === 'multiqc') {
    return (
      (flex.s3_location as string | undefined) ||
      (flex.primary_s3_location as string | undefined) ||
      `s3://depictio-bucket/${dcId}/`
    );
  }
  return dc.delta_location || 'Not aggregated yet';
}

/** Pick "Last Aggregated" timestamp. The Dash version reads
 *  `last_aggregation[-1].aggregation_time` when the field is a list, but
 *  newer projects just have it as an object. */
function getDcLastAggregated(dc: DataCollectionShape): string {
  const la = dc.last_aggregation;
  if (Array.isArray(la)) return la[la.length - 1]?.aggregation_time || 'Never';
  if (la && typeof la === 'object' && la.aggregation_time) {
    return la.aggregation_time;
  }
  const updated = dc.flexible_metadata?.deltatable_size_updated;
  return updated || 'Never';
}

interface WorkflowShape {
  _id?: string;
  id?: string;
  name?: string;
  workflow_tag?: string;
  version?: string;
  engine?: { name?: string; version?: string } | string;
  catalog?: { name?: string; url?: string };
  repository_url?: string;
  data_collections?: DataCollectionShape[];
  [k: string]: unknown;
}

function workflowLabel(wf: WorkflowShape): string {
  return (
    wf.workflow_tag ||
    wf.name ||
    (wf._id ?? wf.id) as string ||
    'workflow'
  );
}

function engineDescription(wf: WorkflowShape): string | null {
  if (!wf.engine) return null;
  if (typeof wf.engine === 'string') return wf.engine;
  const name = wf.engine.name;
  const version = wf.engine.version;
  if (name && version) return `${name} ${version}`;
  return name || null;
}

/** Read project ID from /projects-beta/{id}[/permissions] pathname. */
function readProjectIdFromPath(): string | null {
  const m = window.location.pathname.match(/^\/projects-beta\/([^/?#]+)/);
  return m?.[1] || null;
}

/** Flatten DCs across all workflows. For Basic projects there's typically a
 *  single workflow with all DCs; for Advanced, multiple workflows. */
function flattenDataCollections(
  workflows: WorkflowShape[] | undefined,
): DataCollectionShape[] {
  if (!workflows) return [];
  return workflows.flatMap((wf) => wf.data_collections ?? []);
}

/** Best-effort column extraction matching the Dash version's priority
 *  (depictio/dash/components/depictio_cytoscape_joins.py:948-989):
 *  last_aggregation.aggregation_columns_specs > config.columns
 *  > config.dc_specific_properties.columns_description (keys)
 *  > delta_table_schema (keys or field names). Falls back to []. */
function extractColumns(dc: DataCollectionShape): string[] {
  // Priority 1: aggregation_columns_specs from the latest aggregation entry.
  // For DCs ingested through the React table-create / append flow this is
  // the only populated source — without it the cytoscape table-DC node
  // renders an empty box.
  const lastAggRaw = dc.last_aggregation;
  const lastAgg = Array.isArray(lastAggRaw)
    ? lastAggRaw[lastAggRaw.length - 1]
    : lastAggRaw;
  const specs = (lastAgg as
    | { aggregation_columns_specs?: Array<{ name?: unknown }> }
    | undefined)?.aggregation_columns_specs;
  if (Array.isArray(specs) && specs.length > 0) {
    const names = specs
      .map((s) => (typeof s?.name === 'string' ? s.name : null))
      .filter((n): n is string => !!n);
    if (names.length > 0) return names;
  }

  const config = (dc.config ?? {}) as Record<string, unknown>;
  const direct = config.columns;
  if (Array.isArray(direct)) return direct.map(String);

  const dcSpec = config.dc_specific_properties as
    | { columns_description?: Record<string, unknown> }
    | undefined;
  if (dcSpec?.columns_description && typeof dcSpec.columns_description === 'object') {
    return Object.keys(dcSpec.columns_description);
  }

  const schema = (dc as Record<string, unknown>).delta_table_schema;
  if (schema && typeof schema === 'object' && !Array.isArray(schema)) {
    return Object.keys(schema as Record<string, unknown>);
  }
  if (Array.isArray(schema)) {
    return (schema as Array<Record<string, unknown>>)
      .map((f) => (typeof f?.name === 'string' ? f.name : null))
      .filter((n): n is string => !!n);
  }
  return [];
}

const ProjectDetailApp: React.FC = () => {
  const [project, setProject] = useState<ProjectListEntry | null>(null);
  const [deltaLocations, setDeltaLocations] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedDcId, setSelectedDcId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [renameTarget, setRenameTarget] = useState<DataCollectionShape | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DataCollectionShape | null>(null);
  const [manageTarget, setManageTarget] = useState<DataCollectionShape | null>(null);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [createDcOpened, setCreateDcOpened] = useState(false);
  /** Cross-DC links for this project. Fetched alongside the project doc and
   *  refreshed when the user creates / edits / deletes a link from the
   *  Links section. Wired into the JoinsGraph for visualization. */
  const [projectLinks, setProjectLinks] = useState<DCLink[]>([]);

  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);

  const { user } = useCurrentUser();
  const projectId = readProjectIdFromPath();

  useEffect(() => {
    document.title = 'Depictio — Project Data Collections';
  }, []);

  useEffect(() => {
    if (!projectId) {
      setLoadError('No project ID in URL.');
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    fetchProject(projectId)
      .then(({ project, delta_locations }) => {
        setProject(project);
        setDeltaLocations(delta_locations || {});
      })
      .catch((err: Error) => {
        setLoadError(err.message || 'Failed to load project.');
      })
      .finally(() => setLoading(false));
  }, [projectId, refreshKey]);

  const refresh = () => setRefreshKey((k) => k + 1);

  // Permission check — owners, editors, or admins may mutate DCs.
  const canMutate = useMemo(() => {
    if (!user || !project) return false;
    if (user.is_admin) return true;
    const matchUser = (list?: Array<{ _id?: string; id?: string }>) =>
      !!list?.some((u) => (u._id ?? u.id) === user.id);
    return (
      matchUser(project.permissions?.owners) ||
      matchUser(project.permissions?.editors)
    );
  }, [user, project]);

  const workflows = useMemo<WorkflowShape[]>(
    () => (project?.workflows as WorkflowShape[] | undefined) || [],
    [project],
  );

  const allDataCollections = useMemo(
    () => flattenDataCollections(workflows),
    [workflows],
  );

  // Advanced projects let the user filter DCs by workflow. When no workflow
  // is selected, show all. Basic projects ignore this filter.
  const dataCollections = useMemo(() => {
    if (!selectedWorkflowId) return allDataCollections;
    const wf = workflows.find(
      (w) => (w._id ?? w.id) === selectedWorkflowId,
    );
    return wf?.data_collections || [];
  }, [allDataCollections, selectedWorkflowId, workflows]);

  const selectedDc = useMemo(
    () =>
      dataCollections.find((dc) => (dc._id ?? dc.id) === selectedDcId) || null,
    [dataCollections, selectedDcId],
  );

  const projectType: 'basic' | 'advanced' =
    project?.project_type === 'advanced' ? 'advanced' : 'basic';

  // Aggregate metrics for the 3 stat cards. Backend stamps `metatype` with
  // mixed casing — basic projects use "Metadata", advanced ones "Aggregated".
  // Bucket on prefix so both casings/forms count toward the same label.
  const stats = useMemo(() => {
    const total = dataCollections.length;
    let aggregate = 0;
    let metadata = 0;
    let totalBytes = 0;
    dataCollections.forEach((dc) => {
      const raw = (dc.config?.metatype as string | undefined) || '';
      const lc = raw.toLowerCase();
      if (lc.startsWith('aggregat')) aggregate += 1;
      else if (lc.startsWith('metadat')) metadata += 1;
      totalBytes += getDcSizeBytes(dc);
    });
    return { total, aggregate, metadata, totalBytes };
  }, [dataCollections]);

  return (
    <AppShell
      layout="alt"
      header={{ height: 64 }}
      navbar={{
        width: 260,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleMobile}
              hiddenFrom="sm"
              aria-label="Toggle navigation (mobile)"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleDesktop}
              visibleFrom="sm"
              aria-label="Toggle navigation"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <Icon
              icon="mdi:jira"
              width={22}
              color="var(--mantine-color-teal-6)"
            />
            <Title order={3} c="teal">
              Project Data Manager
            </Title>
          </Group>
          <Group gap="xs">
            <Button
              component="a"
              href={`/projects-beta/${projectId}/permissions`}
              variant="subtle"
              color="blue"
              leftSection={<Icon icon="mdi:shield-account-outline" width={16} />}
            >
              Permissions
            </Button>
            <Button
              component="a"
              href="/projects-beta"
              variant="subtle"
              color="gray"
              leftSection={<Icon icon="mdi:arrow-left" width={16} />}
            >
              Back to Projects
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="projects" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Box px="lg" py="md">
          {loading ? (
            <Center mih={300}>
              <Loader />
            </Center>
          ) : loadError ? (
            <Center mih={300}>
              <Stack align="center" gap="xs">
                <Icon
                  icon="mdi:alert-circle"
                  width={32}
                  color="var(--mantine-color-red-6)"
                />
                <Text c="red">{loadError}</Text>
                <Button component="a" href="/projects-beta" variant="light">
                  Back to projects
                </Button>
              </Stack>
            </Center>
          ) : !project ? null : (
            <Stack gap="lg">
              <ProjectHeader project={project} projectType={projectType} />
              {projectType === 'advanced' && workflows.length > 0 && (
                <WorkflowsPanel
                  workflows={workflows}
                  templateSource={parseTemplate(project)?.source.toLowerCase() || null}
                  selectedWorkflowId={selectedWorkflowId}
                  onSelect={(id) => {
                    setSelectedWorkflowId(id);
                    setSelectedDcId(null);
                  }}
                />
              )}
              <DataCollectionsManagerSection
                projectType={projectType}
                stats={stats}
                dataCollections={dataCollections}
                selectedDcId={selectedDcId}
                canMutate={canMutate}
                onSelect={setSelectedDcId}
                onRename={setRenameTarget}
                onDelete={setDeleteTarget}
                onManage={setManageTarget}
                onCreate={() => setCreateDcOpened(true)}
              />
              {projectId && (
                <LinksSection
                  projectId={projectId}
                  dataCollections={allDataCollections.map((d) => ({
                    id: (d._id ?? d.id) as string,
                    tag: d.data_collection_tag || ((d._id ?? d.id) as string),
                    type: (d.config?.type as string | undefined) || 'unknown',
                  }))}
                  canMutate={canMutate}
                  onLinksChange={setProjectLinks}
                />
              )}
              {selectedDc && (
                <DataCollectionViewer
                  dc={selectedDc}
                  allDataCollections={dataCollections}
                  joins={
                    ((project as Record<string, unknown>).joins as
                      | Array<{
                          dc1?: string;
                          dc2?: string;
                          on_columns?: string[];
                        }>
                      | undefined) || []
                  }
                  links={projectLinks}
                />
              )}
            </Stack>
          )}
        </Box>
      </AppShell.Main>

      <CreateDataCollectionModal
        opened={createDcOpened}
        projectType={projectType}
        projectId={projectId}
        onClose={() => setCreateDcOpened(false)}
        onSuccess={() => {
          setCreateDcOpened(false);
          refresh();
        }}
      />
      <RenameDataCollectionModal
        target={renameTarget}
        onClose={() => setRenameTarget(null)}
        onSuccess={() => {
          setRenameTarget(null);
          refresh();
        }}
      />
      <DeleteDataCollectionModal
        target={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onSuccess={() => {
          setDeleteTarget(null);
          if (selectedDcId === (deleteTarget?._id ?? deleteTarget?.id)) {
            setSelectedDcId(null);
          }
          refresh();
        }}
      />
      {manageTarget && (
        <ManageDataCollectionModal
          opened={!!manageTarget}
          dcId={(manageTarget._id ?? manageTarget.id) as string}
          dcName={manageTarget.data_collection_tag || 'data collection'}
          dcType={
            (((manageTarget.config?.type as string | undefined) || '').toLowerCase() ===
            'multiqc'
              ? 'multiqc'
              : 'table') as ManageDcType
          }
          tableFormat={
            (manageTarget.config?.dc_specific_properties?.format as string | undefined) || null
          }
          onClose={() => setManageTarget(null)}
          onSuccess={() => {
            setManageTarget(null);
            refresh();
          }}
        />
      )}
    </AppShell>
  );
};

const FORMAT_OPTIONS = [
  { value: 'csv', label: 'CSV' },
  { value: 'tsv', label: 'TSV' },
  { value: 'parquet', label: 'Parquet' },
  { value: 'feather', label: 'Feather' },
];

const SEPARATOR_OPTIONS = [
  { value: ',', label: 'Comma (,)' },
  { value: '\t', label: 'Tab (\\t)' },
  { value: ';', label: 'Semicolon (;)' },
  { value: '|', label: 'Pipe (|)' },
  { value: 'custom', label: 'Custom…' },
];

const COMPRESSION_OPTIONS = [
  { value: 'none', label: 'None' },
  { value: 'gzip', label: 'gzip' },
  { value: 'zip', label: 'zip' },
  { value: 'bz2', label: 'bz2' },
];

type MultiQCMismatchKind = 'modules' | 'plots' | 'version' | 'samples';
type MultiQCMismatch = {
  code: 'multiqc_report_mismatch';
  kind: MultiQCMismatchKind;
  summary: string;
  details: Record<string, unknown>;
};

/** Try to recover the structured 422 detail the server raised from a
 *  `multiqc_report_mismatch`. `throwHttpDetailError` JSON-stringifies the
 *  detail into the Error message, so we parse it back out here. */
function tryParseMultiQCMismatch(message: string): MultiQCMismatch | null {
  try {
    const parsed = JSON.parse(message);
    if (parsed && parsed.code === 'multiqc_report_mismatch') {
      return parsed as MultiQCMismatch;
    }
  } catch {
    /* not JSON; not a structured mismatch */
  }
  return null;
}

const MULTIQC_CHECKS: ReadonlyArray<{
  kind: MultiQCMismatchKind;
  label: string;
  desc: string;
}> = [
  {
    kind: 'modules',
    label: 'Modules',
    desc: 'All reports include the same MultiQC modules.',
  },
  {
    kind: 'plots',
    label: 'Plot keys',
    desc: 'All reports expose the same set of plots.',
  },
  {
    kind: 'version',
    label: 'MultiQC version',
    desc: 'All reports share the same major.minor version.',
  },
  {
    kind: 'samples',
    label: 'Sample uniqueness',
    desc: 'No sample name appears in more than one report.',
  },
];

const MultiQCMismatchDetails: React.FC<{ mismatch: MultiQCMismatch }> = ({
  mismatch,
}) => {
  const d = mismatch.details || {};
  const list = (xs: unknown): string[] => (Array.isArray(xs) ? (xs as string[]) : []);
  const added = list(d.added_in_compared);
  const removed = list(d.removed_in_compared);
  const dupes =
    mismatch.kind === 'samples' && d.duplicate_samples
      ? (d.duplicate_samples as Record<string, string[]>)
      : {};
  const dupeEntries = Object.entries(dupes);
  return (
    <Paper
      withBorder
      p={8}
      radius="xs"
      ml={26}
      bg="var(--mantine-color-red-0)"
    >
      <Text size="xs" c="red" mb={4}>
        {mismatch.summary}
      </Text>
      {(mismatch.kind === 'modules' || mismatch.kind === 'plots') && (
        <Stack gap={2}>
          {added.length > 0 && (
            <Text size="xs" c="dimmed">
              Added in <code>{String(d.compared_report ?? '?')}</code>:{' '}
              {added.join(', ')}
            </Text>
          )}
          {removed.length > 0 && (
            <Text size="xs" c="dimmed">
              Missing in <code>{String(d.compared_report ?? '?')}</code>:{' '}
              {removed.join(', ')}
            </Text>
          )}
        </Stack>
      )}
      {mismatch.kind === 'version' && (
        <Text size="xs" c="dimmed">
          <code>{String(d.baseline_report ?? '?')}</code> ={' '}
          {String(d.baseline_version ?? '?')} ·{' '}
          <code>{String(d.compared_report ?? '?')}</code> ={' '}
          {String(d.compared_version ?? '?')}
        </Text>
      )}
      {mismatch.kind === 'samples' && dupeEntries.length > 0 && (
        <Stack gap={2}>
          {dupeEntries.slice(0, 5).map(([sample, reports]) => (
            <Text key={sample} size="xs" c="dimmed">
              <code>{sample}</code> in {reports.join(', ')}
            </Text>
          ))}
          {dupeEntries.length > 5 && (
            <Text size="xs" c="dimmed">
              …and {dupeEntries.length - 5} more
            </Text>
          )}
        </Stack>
      )}
    </Paper>
  );
};

const MultiQCUniformityChecklist: React.FC<{
  fileCount: number;
  submitting: boolean;
  validating: boolean;
  lastCheckPassed: boolean;
  mismatch: MultiQCMismatch | null;
  onCheck: () => void;
}> = ({ fileCount, submitting, validating, lastCheckPassed, mismatch, onCheck }) => {
  const hasMultiple = fileCount >= 2;
  const busy = submitting || validating;
  const statusText = !hasMultiple
    ? 'activated with 2+ reports'
    : submitting
      ? 'running on Create…'
      : validating
        ? 'checking…'
        : mismatch
          ? 'failed'
          : lastCheckPassed
            ? 'all uniform'
            : 'not checked yet';
  return (
    <Paper withBorder p="sm" radius="sm">
      <Group justify="space-between" mb={6} wrap="nowrap">
        <Group gap={6} wrap="nowrap">
          <Icon
            icon="mdi:clipboard-check-outline"
            width={16}
            color="var(--mantine-color-teal-6)"
          />
          <Text size="sm" fw={500}>
            Uniformity checks
          </Text>
        </Group>
        <Group gap={8} wrap="nowrap">
          <Text size="xs" c="dimmed">
            {statusText}
          </Text>
          <Button
            size="compact-xs"
            variant="light"
            color="teal"
            onClick={onCheck}
            disabled={!hasMultiple || busy}
            loading={validating}
            leftSection={<Icon icon="mdi:check-decagram-outline" width={14} />}
          >
            Check now
          </Button>
        </Group>
      </Group>
      <Stack gap={4}>
        {MULTIQC_CHECKS.map((c) => {
          // 1) red X if this row is the failing kind in mismatch
          // 2) animated dots while validating or submitting
          // 3) green check if the last check passed (and no mismatch since)
          // 4) gray pending dot otherwise (never checked, files just staged)
          const failed = mismatch?.kind === c.kind;
          const iconName = failed
            ? 'mdi:close-circle'
            : busy && hasMultiple
              ? 'mdi:dots-horizontal-circle-outline'
              : lastCheckPassed && hasMultiple
                ? 'mdi:check-circle'
                : 'mdi:circle-outline';
          const iconColor = failed
            ? 'var(--mantine-color-red-6)'
            : busy && hasMultiple
              ? 'var(--mantine-color-teal-6)'
              : lastCheckPassed && hasMultiple
                ? 'var(--mantine-color-teal-6)'
                : 'var(--mantine-color-gray-5)';
          return (
            <Stack gap={2} key={c.kind}>
              <Group gap="xs" wrap="nowrap" align="flex-start">
                <Icon icon={iconName} width={18} color={iconColor} />
                <Text
                  size="sm"
                  c={failed ? 'red' : undefined}
                  fw={failed ? 500 : 400}
                  style={{ minWidth: 140 }}
                >
                  {c.label}
                </Text>
                <Text size="xs" c="dimmed" style={{ flex: 1 }}>
                  {c.desc}
                </Text>
              </Group>
              {failed && mismatch && <MultiQCMismatchDetails mismatch={mismatch} />}
            </Stack>
          );
        })}
      </Stack>
    </Paper>
  );
};

/** Guess the file format from extension. Lets the user override afterwards. */
function guessFormat(name: string | undefined): string | null {
  if (!name) return null;
  const lower = name.toLowerCase();
  if (lower.endsWith('.csv')) return 'csv';
  if (lower.endsWith('.tsv') || lower.endsWith('.tab')) return 'tsv';
  if (lower.endsWith('.parquet') || lower.endsWith('.pq')) return 'parquet';
  if (lower.endsWith('.feather') || lower.endsWith('.arrow')) return 'feather';
  return null;
}

const CreateDataCollectionModal: React.FC<{
  opened: boolean;
  projectType: 'basic' | 'advanced';
  projectId: string | null;
  onClose: () => void;
  onSuccess: () => void;
}> = ({ opened, projectType, projectId, onClose, onSuccess }) => {
  const [dcType, setDcType] = useState<'table' | 'multiqc'>('table');
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [fileFormat, setFileFormat] = useState<string>('csv');
  const [separator, setSeparator] = useState<string>(',');
  const [customSeparator, setCustomSeparator] = useState('');
  const [compression, setCompression] = useState<string>('none');
  const [hasHeader, setHasHeader] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [validating, setValidating] = useState(false);
  const [lastCheckPassed, setLastCheckPassed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mismatch, setMismatch] = useState<MultiQCMismatch | null>(null);

  // MultiQC folder dropzone — owned by the modal so close-and-reopen clears it.
  const multiqcDropzone = useFolderDropzone({
    filterFilename: 'multiqc.parquet',
    maxPerFile: 50 * 1024 * 1024,
    maxTotal: 500 * 1024 * 1024,
  });

  // Single-file dropzone for the table DC flow. Same drag-anywhere UX as the
  // MultiQC dropzone — we just take the first file and pipe it into `file`.
  const tableDropzone = useFolderDropzone({
    maxPerFile: 50 * 1024 * 1024,
  });
  // Sync the first dropped/picked file into the existing `file` state so the
  // rest of the table flow (auto-fill, submit) keeps working unchanged.
  useEffect(() => {
    if (dcType !== 'table') return;
    const first = tableDropzone.files[0];
    if (!first) return;
    if (file && first === file) return;
    setFile(first);
  }, [dcType, tableDropzone.files, file]);

  // Reset everything when the modal closes — otherwise re-opening shows stale
  // state from the previous attempt.
  useEffect(() => {
    if (!opened) {
      setDcType('table');
      setFile(null);
      setName('');
      setDescription('');
      setFileFormat('csv');
      setSeparator(',');
      setCustomSeparator('');
      setCompression('none');
      setHasHeader(true);
      setError(null);
      setSubmitting(false);
      multiqcDropzone.clear();
      tableDropzone.clear();
    }
    // multiqcDropzone is recreated on each render but its `clear` is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  // Auto-fill format + name from picked filename. Don't clobber a name the
  // user already typed; do clobber the format because picking a new file
  // means a new format.
  useEffect(() => {
    if (!file) return;
    const guessed = guessFormat(file.name);
    if (guessed) {
      setFileFormat(guessed);
      setSeparator(guessed === 'tsv' ? '\t' : ',');
    }
    if (!name.trim()) {
      const stem = file.name.replace(/\.[^.]+$/, '');
      setName(stem);
    }
  }, [file, name]);

  // Clear any prior uniformity mismatch (and stale pass state) when the user
  // changes the dropped file set — both refer to a different set of reports.
  useEffect(() => {
    setMismatch(null);
    setLastCheckPassed(false);
  }, [multiqcDropzone.files, dcType]);

  // Auto-fill name when the user drops MultiQC files, so the Create button
  // doesn't sit silently disabled. Picks the deepest shared parent directory
  // across all dropped files so multi-run drops get a representative name.
  useEffect(() => {
    if (dcType !== 'multiqc') return;
    if (name.trim()) return;
    if (multiqcDropzone.files.length === 0) return;

    const splitPaths = multiqcDropzone.files.map((f) =>
      f.name.replace(/\\/g, '/').split('/').filter(Boolean),
    );
    // Drop the trailing filename segment so we compare directories only.
    const dirPaths = splitPaths.map((p) => p.slice(0, -1));
    const common: string[] = [];
    const minLen = Math.min(...dirPaths.map((p) => p.length));
    for (let i = 0; i < minLen; i++) {
      const seg = dirPaths[0][i];
      if (dirPaths.every((p) => p[i] === seg)) common.push(seg);
      else break;
    }
    // The deepest shared dir is usually wrapper-ish (e.g. `multiqc_data`)
    // when only one run was dropped; prefer its parent for >1 run so the
    // wrapper folder (`mysamples`) wins over the per-run `multiqc_data`.
    const deepest =
      common.length > 0 && common[common.length - 1] === 'multiqc_data'
        ? common[common.length - 2]
        : common[common.length - 1];
    setName(deepest || 'multiqc_reports');
  }, [dcType, multiqcDropzone.files, name]);

  if (projectType === 'advanced') {
    return (
      <Modal
        opened={opened}
        onClose={onClose}
        title="Create data collection"
        centered
        size="md"
      >
        <Stack gap="md">
          <Group gap="xs">
            <Icon
              icon="mdi:database-plus-outline"
              width={28}
              color="var(--mantine-color-orange-6)"
            />
            <Text fw={500}>Advanced project — use depictio-CLI</Text>
          </Group>
          <Alert
            color="yellow"
            variant="light"
            icon={<Icon icon="mdi:information-outline" width={18} />}
          >
            <Text size="sm">
              For advanced (CLI-driven) projects, data collections are added by
              running <code>depictio-cli</code> against your workflow output —
              not from this UI.
            </Text>
          </Alert>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Got it
            </Button>
          </Group>
        </Stack>
      </Modal>
    );
  }

  const handleCheckUniformity = async () => {
    if (multiqcDropzone.files.length < 2) return;
    setValidating(true);
    setError(null);
    setMismatch(null);
    setLastCheckPassed(false);
    try {
      await checkMultiQCUniformity(multiqcDropzone.files);
      setLastCheckPassed(true);
    } catch (err) {
      const raw = (err as Error).message || 'Uniformity check failed.';
      const parsed = tryParseMultiQCMismatch(raw);
      if (parsed) {
        setMismatch(parsed);
        setError(parsed.summary);
      } else {
        setError(raw);
      }
    } finally {
      setValidating(false);
    }
  };

  const handleSubmit = async () => {
    if (!projectId) {
      setError('Project ID missing from URL.');
      return;
    }
    if (!name.trim()) {
      setError('Data collection name is required.');
      return;
    }

    setSubmitting(true);
    setError(null);
    setMismatch(null);
    try {
      if (dcType === 'multiqc') {
        if (multiqcDropzone.files.length === 0) {
          setError('Drop one or more folders containing multiqc.parquet.');
          setSubmitting(false);
          return;
        }
        const result = await createMultiQCDataCollection({
          projectId,
          name: name.trim(),
          description: description.trim(),
          files: multiqcDropzone.files,
        });
        notifications.show({
          color: 'teal',
          title: 'MultiQC data collection created',
          message: result.message || `"${name.trim()}" is ready.`,
          autoClose: 4000,
        });
      } else {
        if (!file) {
          setError('Pick a file to upload.');
          setSubmitting(false);
          return;
        }
        if (separator === 'custom' && !customSeparator) {
          setError('Custom separator cannot be empty.');
          setSubmitting(false);
          return;
        }
        const result = await createDataCollectionFromUpload({
          projectId,
          name: name.trim(),
          description: description.trim(),
          dataType: 'table',
          fileFormat,
          separator,
          customSeparator: separator === 'custom' ? customSeparator : null,
          compression,
          hasHeader,
          file,
        });
        notifications.show({
          color: 'teal',
          title: 'Data collection created',
          message: result.message || `"${name.trim()}" is ready.`,
          autoClose: 2500,
        });
      }
      onSuccess();
    } catch (err) {
      const rawMessage = (err as Error).message || 'Upload failed.';
      const parsed = tryParseMultiQCMismatch(rawMessage);
      if (parsed) {
        setMismatch(parsed);
        setError(parsed.summary);
      } else {
        setError(rawMessage);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const isDelimited = fileFormat === 'csv' || fileFormat === 'tsv';

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={null}
      centered
      size="lg"
      closeOnClickOutside={!submitting}
      withCloseButton={!submitting}
    >
      <Stack gap="md">
        <Group justify="center" gap="sm">
          <Icon
            icon="mdi:database-plus-outline"
            width={32}
            color="var(--mantine-color-teal-6)"
          />
          <Title order={3} c="teal" m={0}>
            Create a Data Collection
          </Title>
        </Group>

        <Tabs
          value={dcType}
          onChange={(v) => v && setDcType(v as 'table' | 'multiqc')}
          variant="default"
        >
          <Tabs.List grow>
            <Tabs.Tab
              value="table"
              leftSection={<Icon icon="mdi:table" width={18} />}
              disabled={submitting}
            >
              Table (CSV / TSV / Parquet)
            </Tabs.Tab>
            <Tabs.Tab
              value="multiqc"
              leftSection={
                <img
                  src={`${import.meta.env.BASE_URL}logos/multiqc_icon_color.svg`}
                  alt=""
                  width={18}
                  height={18}
                  style={{ objectFit: 'contain', display: 'block' }}
                />
              }
              disabled={submitting}
            >
              MultiQC report(s)
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="table" pt="md">
            <Stack gap="xs">
            <Text size="sm" fw={500}>
              File <span style={{ color: 'var(--mantine-color-red-6)' }}>*</span>
            </Text>
            <div ref={tableDropzone.rootRef}>
              <UnstyledDropZone
                onClick={() => !submitting && tableDropzone.openPicker()}
                disabled={submitting}
                active={tableDropzone.isDragOver}
              >
                <Stack gap={4} align="center">
                  <Icon icon="mdi:file-upload-outline" width={28} />
                  <Text fw={500}>
                    Drop a CSV, TSV, Parquet, or Feather file
                  </Text>
                  <Text size="xs" c="dimmed">
                    or click to pick · max 50 MB
                  </Text>
                </Stack>
              </UnstyledDropZone>
              <input
                ref={tableDropzone.inputRef}
                type="file"
                accept=".csv,.tsv,.tab,.parquet,.pq,.feather,.arrow"
                style={{ display: 'none' }}
              />
            </div>
            {tableDropzone.error && (
              <Alert
                color="orange"
                variant="light"
                icon={<Icon icon="mdi:alert" width={16} />}
              >
                {tableDropzone.error}
              </Alert>
            )}
            {file && (
              <Paper withBorder p="xs" radius="sm">
                <Group justify="space-between" wrap="nowrap" gap="xs">
                  <Group gap="xs" wrap="nowrap">
                    <Icon icon="mdi:file-outline" width={16} />
                    <Text size="sm" ff="monospace" lineClamp={1}>
                      {file.name}
                    </Text>
                  </Group>
                  <Group gap={4} wrap="nowrap">
                    <Text size="xs" c="dimmed">
                      {(file.size / (1024 * 1024)).toFixed(1)} MB
                    </Text>
                    <ActionIcon
                      size="xs"
                      variant="subtle"
                      color="red"
                      onClick={() => {
                        setFile(null);
                        tableDropzone.clear();
                      }}
                      disabled={submitting}
                      aria-label="Remove file"
                    >
                      <Icon icon="mdi:close" width={14} />
                    </ActionIcon>
                  </Group>
                </Group>
              </Paper>
            )}
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="multiqc" pt="md">
            <Stack gap="xs">
            <Text size="sm" fw={500}>
              MultiQC reports
            </Text>
            <div ref={multiqcDropzone.rootRef}>
              <UnstyledDropZone
                onClick={() => !submitting && multiqcDropzone.openPicker()}
                disabled={submitting}
                active={multiqcDropzone.isDragOver}
              >
                <Stack gap={4} align="center">
                  <Icon icon="mdi:folder-upload" width={28} />
                  <Text fw={500}>
                    Drop a multiqc.parquet file or a folder of runs
                  </Text>
                  <Text size="xs" c="dimmed">
                    Only multiqc.parquet files are kept · run folder name is preserved
                  </Text>
                </Stack>
              </UnstyledDropZone>
              <input
                ref={multiqcDropzone.inputRef}
                type="file"
                multiple
                accept=".parquet"
                style={{ display: 'none' }}
              />
            </div>
            {multiqcDropzone.error && (
              <Alert
                color="orange"
                variant="light"
                icon={<Icon icon="mdi:alert" width={16} />}
              >
                {multiqcDropzone.error}
              </Alert>
            )}
            {multiqcDropzone.files.length > 0 && (
              <Paper withBorder p="xs" radius="sm">
                <Group justify="space-between" mb={6}>
                  <Text size="sm" fw={500}>
                    {multiqcDropzone.files.length} file
                    {multiqcDropzone.files.length === 1 ? '' : 's'} ·{' '}
                    {(multiqcDropzone.totalBytes / (1024 * 1024)).toFixed(1)} MB
                  </Text>
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={multiqcDropzone.clear}
                    disabled={submitting}
                  >
                    Clear list
                  </Button>
                </Group>
                <ScrollArea h={Math.min(multiqcDropzone.files.length * 28 + 8, 200)}>
                  <Stack gap={2}>
                    {multiqcDropzone.files.map((f, i) => (
                      <Group
                        key={`${f.name}-${i}`}
                        justify="space-between"
                        wrap="nowrap"
                        gap="xs"
                      >
                        <Text size="xs" ff="monospace" lineClamp={1}>
                          {f.name}
                        </Text>
                        <Group gap={4} wrap="nowrap">
                          <Text size="xs" c="dimmed">
                            {(f.size / (1024 * 1024)).toFixed(1)} MB
                          </Text>
                          <ActionIcon
                            size="xs"
                            variant="subtle"
                            color="red"
                            onClick={() => multiqcDropzone.removeFile(f)}
                            disabled={submitting}
                            aria-label="Remove file"
                          >
                            <Icon icon="mdi:close" width={14} />
                          </ActionIcon>
                        </Group>
                      </Group>
                    ))}
                  </Stack>
                </ScrollArea>
                {multiqcDropzone.skipped.length > 0 && (
                  <Text size="xs" c="dimmed" mt={6}>
                    Skipped {multiqcDropzone.skipped.length} non-multiqc file
                    {multiqcDropzone.skipped.length === 1 ? '' : 's'}.
                  </Text>
                )}
              </Paper>
            )}
            {multiqcDropzone.files.length > 0 && (
              <MultiQCUniformityChecklist
                fileCount={multiqcDropzone.files.length}
                submitting={submitting}
                validating={validating}
                lastCheckPassed={lastCheckPassed}
                mismatch={mismatch}
                onCheck={handleCheckUniformity}
              />
            )}
            </Stack>
          </Tabs.Panel>
        </Tabs>

        <TextInput
          label="Name"
          placeholder={
            dcType === 'multiqc' ? 'e.g. multiqc_qc' : 'e.g. samples_metadata'
          }
          required
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          disabled={submitting}
        />

        <Textarea
          label="Description"
          placeholder="What does this data collection contain? (optional)"
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          autosize
          minRows={2}
          maxRows={4}
          disabled={submitting}
        />

        {dcType === 'table' && (
          <>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
              <Select
                label="Format"
                data={FORMAT_OPTIONS}
                value={fileFormat}
                onChange={(v) => v && setFileFormat(v)}
                allowDeselect={false}
                disabled={submitting}
              />
              {isDelimited && (
                <Select
                  label="Separator"
                  data={SEPARATOR_OPTIONS}
                  value={separator}
                  onChange={(v) => v && setSeparator(v)}
                  allowDeselect={false}
                  disabled={submitting}
                />
              )}
            </SimpleGrid>

            {isDelimited && separator === 'custom' && (
              <TextInput
                label="Custom separator"
                placeholder="e.g. ::"
                value={customSeparator}
                onChange={(e) => setCustomSeparator(e.currentTarget.value)}
                required
                disabled={submitting}
              />
            )}

            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
              <Select
                label="Compression"
                data={COMPRESSION_OPTIONS}
                value={compression}
                onChange={(v) => v && setCompression(v)}
                allowDeselect={false}
                disabled={submitting}
              />
              {isDelimited && (
                <Switch
                  mt="lg"
                  label="File has header row"
                  checked={hasHeader}
                  onChange={(e) => setHasHeader(e.currentTarget.checked)}
                  disabled={submitting}
                />
              )}
            </SimpleGrid>
          </>
        )}

        {error && (
          <Alert
            color="red"
            variant="light"
            icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
          >
            {error}
          </Alert>
        )}

        <Alert
          color="blue"
          variant="light"
          icon={<Icon icon="mdi:information-outline" width={18} />}
        >
          <Text size="xs">
            The file will be scanned and aggregated to a Delta table on the
            server. Larger files take longer — keep this dialog open until you
            see the success notification. Need the legacy flow?{' '}
            <Anchor
              href={`/project/${readProjectIdFromPath()}/data`}
              target="_blank"
              rel="noreferrer"
            >
              Open in Dash
            </Anchor>
            .
          </Text>
        </Alert>

        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            color="teal"
            onClick={handleSubmit}
            loading={submitting}
            disabled={
              !name.trim() ||
              (dcType === 'table'
                ? !file
                : multiqcDropzone.files.length === 0)
            }
            leftSection={<Icon icon="mdi:cloud-upload-outline" width={16} />}
          >
            Create
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

const RenameDataCollectionModal: React.FC<{
  target: DataCollectionShape | null;
  onClose: () => void;
  onSuccess: () => void;
}> = ({ target, onClose, onSuccess }) => {
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!target) return;
    setName(target.data_collection_tag || '');
    setError(null);
    setSubmitting(false);
  }, [target]);

  const handleSubmit = async () => {
    if (!target) return;
    const id = (target._id ?? target.id) as string;
    if (!name.trim()) {
      setError('Name is required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await renameDataCollection(id, name.trim());
      notifications.show({
        color: 'teal',
        title: 'Renamed',
        message: `Data collection is now "${name.trim()}".`,
        autoClose: 2000,
      });
      onSuccess();
    } catch (err) {
      setError((err as Error).message || 'Failed to rename.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={Boolean(target)}
      onClose={onClose}
      title="Rename data collection"
      centered
      size="md"
    >
      <Stack gap="md">
        <TextInput
          label="Data collection tag"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
          disabled={submitting}
        />
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button color="teal" onClick={handleSubmit} loading={submitting}>
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

const DeleteDataCollectionModal: React.FC<{
  target: DataCollectionShape | null;
  onClose: () => void;
  onSuccess: () => void;
}> = ({ target, onClose, onSuccess }) => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!target) return;
    setError(null);
    setSubmitting(false);
  }, [target]);

  const handleSubmit = async () => {
    if (!target) return;
    const id = (target._id ?? target.id) as string;
    setSubmitting(true);
    setError(null);
    try {
      await deleteDataCollection(id);
      notifications.show({
        color: 'teal',
        title: 'Deleted',
        message: `"${target.data_collection_tag || id}" removed.`,
        autoClose: 2000,
      });
      onSuccess();
    } catch (err) {
      setError((err as Error).message || 'Failed to delete.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={Boolean(target)}
      onClose={onClose}
      title="Delete data collection"
      centered
      size="md"
    >
      <Stack gap="md">
        <Text>
          Permanently delete{' '}
          <strong>{target?.data_collection_tag || 'this data collection'}</strong>?
        </Text>
        <Alert
          color="red"
          icon={<Icon icon="mdi:alert" width={18} />}
          variant="light"
        >
          This deletes the registered files, delta tables, runs, and MultiQC
          metadata associated with this collection. Cannot be undone.
        </Alert>
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button color="red" onClick={handleSubmit} loading={submitting}>
            Delete
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

const ProjectHeader: React.FC<{
  project: ProjectListEntry;
  projectType: 'basic' | 'advanced';
}> = ({ project, projectType }) => {
  const tmpl = parseTemplate(project);
  return (
    <Paper withBorder radius="md" p="lg">
      <Stack gap="xs">
        <Group gap="sm">
          <Icon
            icon="mdi:database-outline"
            width={26}
            color="var(--mantine-color-teal-6)"
          />
          <Title order={3} c="teal" style={{ fontWeight: 600 }}>
            Project Data Manager
          </Title>
        </Group>
        <Text size="sm" c="dimmed">
          Manage workflows and data collections for your project
        </Text>
        <Group justify="space-between" mt="xs">
          <Group gap="xs">
            <Icon
              icon="mdi:source-branch"
              width={18}
              color="var(--mantine-color-teal-6)"
            />
            <Text fw={600} size="sm">
              Project Type:
            </Text>
            <Badge
              color={projectType === 'advanced' ? 'orange' : 'cyan'}
              variant="light"
              radius="sm"
              size="md"
            >
              {projectType === 'advanced' ? 'Advanced' : 'Basic'}
            </Badge>
          </Group>
          <Text size="sm" c="dimmed">
            {projectType === 'advanced'
              ? 'CLI-driven project with workflows and pipelines'
              : 'Simple project with direct data collection management'}
          </Text>
        </Group>
        {tmpl && (
          <Group gap="xs" mt="xs" wrap="nowrap">
            <Icon
              icon="mdi:puzzle-outline"
              width={18}
              color="var(--mantine-color-grape-6)"
            />
            <Text fw={600} size="sm">
              Template:
            </Text>
            <TemplateChip parsed={tmpl} verbose />
            <Anchor
              href={templateDocsUrl(tmpl)}
              target="_blank"
              rel="noreferrer"
              size="sm"
            >
              View documentation →
            </Anchor>
          </Group>
        )}
        {project.name && (
          <Text size="xs" c="dimmed" mt={4}>
            {project.name}
          </Text>
        )}
      </Stack>
    </Paper>
  );
};

interface DcStats {
  total: number;
  aggregate: number;
  metadata: number;
  totalBytes: number;
}

/** Template-source → workflow brand image. Maps to PNGs already shipped in
 *  ``depictio/viewer/public/logos/workflows/``. Returns null for sources we
 *  don't have a brand mark for (the card falls back to a generic icon). */
const WORKFLOW_BRAND_IMAGE: Record<string, string> = {
  'nf-core': 'nf-core.png',
  'snakemake-workflows': 'snakemake.png',
  galaxy: 'galaxy.png',
  iwc: 'iwc.png',
};

const WorkflowsPanel: React.FC<{
  workflows: WorkflowShape[];
  /** Lower-cased project template source (e.g. ``'nf-core'``) — when set we
   *  render the matching brand mark on each workflow card and drop the
   *  redundant engine badge. */
  templateSource: string | null;
  selectedWorkflowId: string | null;
  onSelect: (id: string | null) => void;
}> = ({ workflows, templateSource, selectedWorkflowId, onSelect }) => {
  const brandImage = templateSource ? WORKFLOW_BRAND_IMAGE[templateSource] : undefined;
  return (
    <Stack gap="md">
      <Group gap="xs">
        <Icon
          icon="mdi:source-branch"
          width={22}
          color="var(--mantine-color-orange-6)"
        />
        <Title order={4}>Workflows</Title>
        <Badge color="orange" variant="light" radius="sm" size="sm">
          {workflows.length}
        </Badge>
        {selectedWorkflowId && (
          <Button
            variant="subtle"
            size="xs"
            color="gray"
            onClick={() => onSelect(null)}
            leftSection={<Icon icon="mdi:close" width={14} />}
          >
            Clear filter
          </Button>
        )}
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
        {workflows.map((wf) => {
          const id = (wf._id ?? wf.id) as string;
          const isSelected = id === selectedWorkflowId;
          const dcCount = wf.data_collections?.length ?? 0;
          const engine = engineDescription(wf);
          return (
            <Card
              key={id}
              withBorder
              radius="md"
              p="md"
              onClick={() => onSelect(isSelected ? null : id)}
              style={{
                cursor: 'pointer',
                borderColor: isSelected
                  ? 'var(--mantine-color-orange-6)'
                  : undefined,
                borderWidth: isSelected ? 2 : 1,
                background: isSelected
                  ? 'var(--mantine-color-orange-0)'
                  : undefined,
                transition:
                  'border-color 120ms ease, background 120ms ease',
              }}
            >
              <Stack gap={6}>
                <Group gap="xs" wrap="nowrap">
                  {brandImage ? (
                    <img
                      src={`${import.meta.env.BASE_URL}logos/workflows/${brandImage}`}
                      alt={templateSource ?? 'workflow'}
                      width={20}
                      height={20}
                      style={{ objectFit: 'contain', display: 'block' }}
                    />
                  ) : (
                    <Icon
                      icon="mdi:cube-outline"
                      width={20}
                      color="var(--mantine-color-orange-6)"
                    />
                  )}
                  <Text fw={600} truncate>
                    {workflowLabel(wf)}
                  </Text>
                </Group>
                {wf.version && (
                  <Text size="xs" c="dimmed">
                    Version {wf.version}
                  </Text>
                )}
                {/* Engine badge omitted when we already render the
                 *  workflow's brand mark — it's redundant. */}
                {!brandImage && engine && (
                  <Group gap={4}>
                    <Text size="xs" c="dimmed">
                      Engine:
                    </Text>
                    <Badge color="cyan" variant="light" size="xs" radius="sm">
                      {engine}
                    </Badge>
                  </Group>
                )}
                <Group gap={4} mt={4}>
                  <Icon
                    icon="mdi:database-outline"
                    width={14}
                    color="var(--mantine-color-teal-6)"
                  />
                  <Text size="xs" c="dimmed">
                    {dcCount} data collection{dcCount === 1 ? '' : 's'}
                  </Text>
                </Group>
              </Stack>
            </Card>
          );
        })}
      </SimpleGrid>
    </Stack>
  );
};

const DataCollectionsManagerSection: React.FC<{
  projectType: 'basic' | 'advanced';
  stats: DcStats;
  dataCollections: DataCollectionShape[];
  selectedDcId: string | null;
  canMutate: boolean;
  onSelect: (id: string | null) => void;
  onRename: (dc: DataCollectionShape) => void;
  onDelete: (dc: DataCollectionShape) => void;
  /** Open the manage-data modal for a MultiQC DC. Optional so non-MultiQC
   *  callers don't have to wire it. */
  onManage?: (dc: DataCollectionShape) => void;
  onCreate: () => void;
}> = ({
  projectType,
  stats,
  dataCollections,
  selectedDcId,
  canMutate,
  onSelect,
  onRename,
  onDelete,
  onManage,
  onCreate,
}) => {
  return (
    <Stack gap="md">
      <Group gap="xs">
        <Icon
          icon="mdi:database-outline"
          width={22}
          color="var(--mantine-color-dark-6)"
        />
        <Title order={4}>Data Collections Manager</Title>
        <Badge
          color={projectType === 'advanced' ? 'orange' : 'cyan'}
          variant="light"
          radius="sm"
          size="sm"
        >
          {projectType === 'advanced' ? 'Advanced Project' : 'Basic Project'}
        </Badge>
      </Group>
      <Text size="sm" c="dimmed">
        Managing data collections for this {projectType} project
      </Text>

      <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
        <StatCard
          icon="mdi:database-outline"
          iconColor="var(--mantine-color-cyan-6)"
          label="Total Collections"
          primary={String(stats.total)}
          secondary="Data Collections"
          primaryColor="cyan"
        />
        <StatCard
          icon="mdi:tag-outline"
          iconColor="var(--mantine-color-orange-6)"
          label="Collection Types"
          primaryDual={[
            { count: stats.aggregate, label: 'Aggregate', color: 'orange' },
            { count: stats.metadata, label: 'Metadata', color: 'orange' },
          ]}
        />
        <StatCard
          icon="mdi:harddisk"
          iconColor="var(--mantine-color-orange-6)"
          label="Total Storage"
          primary={formatBytes(stats.totalBytes)}
          secondary={
            stats.totalBytes > 0
              ? `${dataCollections.length} collection${dataCollections.length === 1 ? '' : 's'}`
              : 'No size info yet'
          }
          primaryColor="orange"
        />
      </SimpleGrid>

      <Paper withBorder radius="md" p="md">
        <Group justify="space-between" mb="xs">
          <Group gap="xs">
            <Title order={5}>Data Collections</Title>
            <Badge variant="light" color="dark" size="sm">
              {dataCollections.length} COLLECTIONS
            </Badge>
          </Group>
          <Button
            color="teal"
            size="sm"
            leftSection={<Icon icon="mdi:plus" width={16} />}
            disabled={!canMutate}
            onClick={onCreate}
            title={
              canMutate
                ? 'Create a new data collection'
                : 'Owner permission required'
            }
          >
            Create Data Collection
          </Button>
        </Group>
        <Stack gap="xs">
          {dataCollections.length === 0 && (
            <Text size="sm" c="dimmed" ta="center" py="md">
              No data collections defined for this project.
            </Text>
          )}
          {dataCollections.map((dc) => {
            const id = (dc._id ?? dc.id) as string;
            const isSelected = id === selectedDcId;
            return (
              <DataCollectionRow
                key={id}
                dc={dc}
                selected={isSelected}
                canMutate={canMutate}
                onClick={() => onSelect(isSelected ? null : id)}
                onRename={() => onRename(dc)}
                onDelete={() => onDelete(dc)}
                onManage={onManage ? () => onManage(dc) : undefined}
              />
            );
          })}
        </Stack>
      </Paper>
    </Stack>
  );
};

const StatCard: React.FC<{
  icon: string;
  iconColor: string;
  label: string;
  primary?: string;
  secondary?: string;
  primaryColor?: string;
  primaryDual?: Array<{ count: number; label: string; color: string }>;
}> = ({ icon, iconColor, label, primary, secondary, primaryColor, primaryDual }) => (
  <Card withBorder radius="md" p="md">
    <Stack gap="xs" align="center">
      <Group gap={6}>
        <Icon icon={icon} width={20} color={iconColor} />
        <Text fw={600}>{label}</Text>
      </Group>
      {primary && (
        <Text fz={32} fw={700} c={primaryColor || 'dark'} lh={1}>
          {primary}
        </Text>
      )}
      {primaryDual && (
        <Group gap="lg" justify="center">
          {primaryDual.map((p) => (
            <Stack key={p.label} gap={0} align="center">
              <Text fz={32} fw={700} c={p.color} lh={1}>
                {p.count}
              </Text>
              <Text size="xs" c="dimmed">
                {p.label}
              </Text>
            </Stack>
          ))}
        </Group>
      )}
      {secondary && (
        <Text size="xs" c="dimmed">
          {secondary}
        </Text>
      )}
    </Stack>
  </Card>
);

const DataCollectionRow: React.FC<{
  dc: DataCollectionShape;
  selected: boolean;
  canMutate: boolean;
  onClick: () => void;
  onRename: () => void;
  onDelete: () => void;
  /** Set for both MultiQC and Table DCs — opens the unified Manage Data modal. */
  onManage?: () => void;
}> = ({ dc, selected, canMutate, onClick, onRename, onDelete, onManage }) => {
  const type = (dc.config?.type as string | undefined) || 'unknown';
  const metatype = (dc.config?.metatype as string | undefined) || null;
  const isTable = type === 'table';
  const isMultiQC = type.toLowerCase() === 'multiqc';
  // Tables that aren't metadata are aggregates — surface that with a badge so
  // the user can tell at a glance which collection is the joined fact table.
  const isAggregate = isTable && (metatype || '').toLowerCase() !== 'metadata';
  // Stop propagation on action-icon clicks so the row's onClick doesn't toggle
  // selection underneath the modal trigger.
  const guard = (fn: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation();
    fn();
  };
  return (
    <Paper
      withBorder
      radius="sm"
      p="sm"
      onClick={onClick}
      style={{
        cursor: 'pointer',
        borderColor: selected ? 'var(--mantine-color-teal-6)' : undefined,
        background: selected ? 'var(--mantine-color-teal-0)' : undefined,
        transition: 'background 120ms ease, border-color 120ms ease',
      }}
    >
      <Group justify="space-between" wrap="nowrap">
        <Group gap="sm" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
          {isMultiQC ? (
            <img
              src={`${import.meta.env.BASE_URL}logos/multiqc_icon_color.svg`}
              alt="MultiQC"
              width={20}
              height={20}
              style={{ objectFit: 'contain', display: 'block' }}
            />
          ) : (
            <Icon
              icon={isTable ? 'mdi:table' : 'mdi:file-document-outline'}
              width={20}
              color="var(--mantine-color-teal-6)"
            />
          )}
          {type && (
            <Badge color="blue" variant="filled" size="sm" radius="sm">
              {type.toUpperCase()}
            </Badge>
          )}
          {metatype && (
            <Badge color="gray" variant="light" size="sm" radius="sm">
              {metatype.toUpperCase()}
            </Badge>
          )}
          {isAggregate && !metatype && (
            <Badge color="orange" variant="light" size="sm" radius="sm">
              AGGREGATE
            </Badge>
          )}
          <Text fw={500} truncate>
            {dc.data_collection_tag || (dc._id ?? dc.id)}
          </Text>
        </Group>
        <Group gap={4}>
          {onManage && (
            <ActionIcon
              variant="subtle"
              color="teal"
              size="sm"
              disabled={!canMutate}
              onClick={guard(onManage)}
              title={
                canMutate ? 'Manage data (append / replace / clear)' : 'Owner permission required'
              }
            >
              <Icon icon="mdi:database-cog-outline" width={16} />
            </ActionIcon>
          )}
          <ActionIcon
            variant="subtle"
            color="blue"
            size="sm"
            disabled={!canMutate}
            onClick={guard(onRename)}
            title={canMutate ? 'Rename' : 'Owner permission required'}
          >
            <Icon icon="mdi:pencil" width={16} />
          </ActionIcon>
          <ActionIcon
            variant="subtle"
            color="red"
            size="sm"
            disabled={!canMutate}
            onClick={guard(onDelete)}
            title={canMutate ? 'Delete' : 'Owner permission required'}
          >
            <Icon icon="mdi:delete" width={16} />
          </ActionIcon>
        </Group>
      </Group>
    </Paper>
  );
};

const DataCollectionViewer: React.FC<{
  dc: DataCollectionShape;
  allDataCollections: DataCollectionShape[];
  joins: Array<{
    dc1?: string;
    dc2?: string;
    dc_tag1?: string;
    dc_tag2?: string;
    on_columns?: string[];
  }>;
  links: Array<{
    source_dc_id?: string;
    target_dc_id?: string;
    source_column?: string;
    target_field?: string;
    enabled?: boolean;
  }>;
}> = ({ dc, allDataCollections, joins, links }) => {
  const dcId = (dc._id ?? dc.id) as string;
  const type = (dc.config?.type as string | undefined) || 'unknown';
  const metatype = (dc.config?.metatype as string | undefined) || null;
  const format =
    (dc.config?.dc_specific_properties?.format as string | undefined) || null;
  const isMultiQC = type.toLowerCase() === 'multiqc';
  // Backend stamps `metatype: "Metadata"` on metadata tables but leaves
  // aggregate tables with `metatype: null` (see project YAMLs and
  // `/projects/get/all` payload). Mirror the row's fallback so the viewer
  // surfaces the implicit "AGGREGATE" classification too.
  const isTable = type.toLowerCase() === 'table';
  const isAggregate = isTable && (metatype || '').toLowerCase() !== 'metadata';

  return (
    <Paper withBorder radius="md" p="lg">
      <Stack gap="md">
        <Group gap="xs">
          <Icon
            icon="mdi:eye-outline"
            width={22}
            color="var(--mantine-color-blue-6)"
          />
          <Title order={4}>Data Collection Viewer</Title>
        </Group>
        <Group gap="sm">
          <Icon
            icon={
              isMultiQC
                ? 'mdi:chart-bar'
                : type === 'table'
                  ? 'mdi:table'
                  : 'mdi:file-document-outline'
            }
            width={22}
            color={
              isMultiQC
                ? 'var(--mantine-color-blue-6)'
                : 'var(--mantine-color-teal-6)'
            }
          />
          <Title order={4}>{dc.data_collection_tag || dcId}</Title>
        </Group>

        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
          <Card withBorder radius="md" p="md">
            <Group gap="xs" mb="xs">
              <Icon
                icon="mdi:cog-outline"
                width={20}
                color="var(--mantine-color-blue-6)"
              />
              <Text fw={600}>Configuration</Text>
            </Group>
            <Stack gap={4}>
              <DetailRow label="Data Collection ID" value={dcId} mono />
              <DetailRow
                label="Type"
                badge={
                  <Badge color="blue" size="sm" radius="sm">
                    {type.toUpperCase()}
                  </Badge>
                }
              />
              {metatype ? (
                <DetailRow
                  label="Metatype"
                  badge={
                    <Badge color="gray" variant="light" size="sm" radius="sm">
                      {metatype.toUpperCase()}
                    </Badge>
                  }
                />
              ) : isAggregate ? (
                <DetailRow
                  label="Metatype"
                  badge={
                    <Badge color="orange" variant="light" size="sm" radius="sm">
                      AGGREGATE
                    </Badge>
                  }
                />
              ) : null}
            </Stack>
          </Card>
          {isMultiQC ? (
            <MultiQCSummaryCard dc={dc} />
          ) : (
            <Card withBorder radius="md" p="md">
              <Group gap="xs" mb="xs">
                <Icon
                  icon="mdi:delta"
                  width={20}
                  color="var(--mantine-color-green-6)"
                />
                <Text fw={600}>Delta Table Details</Text>
              </Group>
              <Stack gap={4}>
                <DetailRow
                  label="Delta Location"
                  value={getDcStorageLocation(dc)}
                  mono
                  wrap
                />
                <DetailRow
                  label="Last Aggregated"
                  value={getDcLastAggregated(dc)}
                />
                {format && (
                  <DetailRow
                    label="Format"
                    badge={
                      <Badge color="cyan" size="sm" radius="sm">
                        {format.toUpperCase()}
                      </Badge>
                    }
                  />
                )}
                <DetailRow
                  label="Size"
                  value={formatBytes(getDcSizeBytes(dc))}
                  mono
                />
              </Stack>
            </Card>
          )}
        </SimpleGrid>

        <Card withBorder radius="md" p="md">
          <Group gap="xs" mb="xs">
            <Icon
              icon="mdi:information-outline"
              width={20}
              color="var(--mantine-color-orange-6)"
            />
            <Text fw={600}>Additional Information</Text>
          </Group>
          <Stack gap={4}>
            <DetailRow
              label="Description"
              value={
                typeof dc.description === 'string' && dc.description
                  ? dc.description
                  : 'Not defined'
              }
            />
            <DetailRow
              label="Created"
              value={dc.registration_time || 'N/A'}
            />
          </Stack>
        </Card>

        {/* Tabular preview only makes sense for table-type DCs. MultiQC has
         *  its own per-module preview elsewhere; image and JBrowse types
         *  don't fit a row/column grid. */}
        {!isMultiQC && type === 'table' && (
          <Card withBorder radius="md" p="md">
            <Group gap="xs" mb="md">
              <Icon
                icon="mdi:table"
                width={20}
                color="var(--mantine-color-teal-6)"
              />
              <Text fw={600}>Data Preview</Text>
            </Group>
            <DataPreviewPanel key={dcId} dcId={dcId} />
          </Card>
        )}

        {isMultiQC && <MultiQCReportsCard dcId={dcId} />}

        {/* Relationships graph — rendered under the per-DC metadata so the
         *  selected collection's joins/links sit alongside its details. */}
        <JoinsGraph
          dataCollections={allDataCollections.map((d) => ({
            id: (d._id ?? d.id) as string,
            tag: d.data_collection_tag || ((d._id ?? d.id) as string),
            type: (d.config?.type as string | undefined) || 'unknown',
            columns: extractColumns(d),
          }))}
          joins={joins}
          links={links}
          highlightDcId={dcId}
        />
      </Stack>
    </Paper>
  );
};

/** Count helper that handles both shapes the backend returns:
 *  array-of-X or object-keyed-by-index. Returns 0 if neither. */
function countCollection(v: unknown): number {
  if (Array.isArray(v)) return v.length;
  if (v && typeof v === 'object') return Object.keys(v as object).length;
  return 0;
}

/** Module/plot keys are sometimes integer-indexed, in which case we want
 *  the values (module names); other times they're already keyed by name. */
function listKeys(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String);
  if (v && typeof v === 'object') {
    const obj = v as Record<string, unknown>;
    const keys = Object.keys(obj);
    // If keys look numeric ("0","1",...) the keys themselves aren't useful;
    // surface the values instead.
    if (keys.length > 0 && keys.every((k) => /^\d+$/.test(k))) {
      return keys.map((k) => String(obj[k] ?? k));
    }
    return keys;
  }
  return [];
}

/** Flatten one module's plot entry into a list of human-readable plot
 *  names. The Dash data model accepts strings, dicts of subplots, or a
 *  mix — see project_data_collections.py:2937-2942. */
function flattenPlotEntries(entry: unknown): string[] {
  if (!entry) return [];
  if (Array.isArray(entry)) {
    const out: string[] = [];
    entry.forEach((p) => {
      if (typeof p === 'string') out.push(p);
      else if (p && typeof p === 'object') {
        Object.entries(p as Record<string, unknown>).forEach(([k, sub]) => {
          if (Array.isArray(sub) && sub.length > 0) {
            out.push(...sub.map((s) => `${k} › ${String(s)}`));
          } else {
            out.push(k);
          }
        });
      }
    });
    return out;
  }
  if (typeof entry === 'string') return [entry];
  return [];
}

/** Right-side card on the DC viewer when type === 'multiqc'. Replaces the
 *  Delta Table Details card (which has no meaning for a MultiQC DC). Shows
 *  sample / module / plot counts pulled from the first report's metadata. */
const MultiQCSummaryCard: React.FC<{ dc: DataCollectionShape }> = ({ dc }) => {
  const dcId = (dc._id ?? dc.id) as string;
  const [data, setData] = useState<MultiQCReportSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchMultiQCByDataCollection(dcId, 1)
      .then((res) => {
        if (cancelled) return;
        setData(res.reports?.[0] || null);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load MultiQC summary.');
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [dcId]);

  const r = data?.report;
  const meta = r?.metadata;
  // Prefer the deduplicated `canonical_samples` list — the raw `samples`
  // array contains adapter sub-rows for sequencing runs and balloons into
  // 20K+ entries. Fall back to `samples` otherwise.
  const sampleCount = meta
    ? countCollection(meta.canonical_samples) || countCollection(meta.samples)
    : 0;
  const moduleCount = countCollection(meta?.modules);
  const plotCount = countCollection(meta?.plots);
  const hasReport = Boolean(r);
  const sizeBytes =
    (r?.file_size_bytes as number | undefined) ?? getDcSizeBytes(dc);
  const s3Location = r?.s3_location || getDcStorageLocation(dc);

  return (
    <Card withBorder radius="md" p="md">
      <Group gap="xs" mb="xs">
        <Icon
          icon="mdi:cloud"
          width={20}
          color="var(--mantine-color-blue-6)"
        />
        <Text fw={600}>Reports & S3 Storage Details</Text>
      </Group>
      {loading ? (
        <Center py="md">
          <Loader size="sm" />
        </Center>
      ) : error ? (
        <Text size="sm" c="red">
          {error}
        </Text>
      ) : !hasReport ? (
        <Stack gap={4}>
          <DetailRow label="S3 Location" value={s3Location} mono wrap />
          <Text size="xs" c="dimmed" mt="xs">
            No MultiQC report registered for this data collection yet.
          </Text>
        </Stack>
      ) : (
        <Stack gap={4}>
          <DetailRow label="S3 Location" value={s3Location} mono wrap />
          <DetailRow
            label="Processed"
            value={r?.processed_at || r?.creation_date || '—'}
          />
          <DetailRow label="MultiQC version" value={r?.multiqc_version || '—'} />
          <DetailRow label="Size" value={formatBytes(sizeBytes)} mono />
          <Group gap="md" mt="xs" justify="center">
            <Stack gap={0} align="center">
              <Text fz={22} fw={700} c="blue" lh={1}>
                {sampleCount}
              </Text>
              <Text size="xs" c="dimmed">
                Samples
              </Text>
            </Stack>
            <Stack gap={0} align="center">
              <Text fz={22} fw={700} c="cyan" lh={1}>
                {moduleCount}
              </Text>
              <Text size="xs" c="dimmed">
                Modules
              </Text>
            </Stack>
            <Stack gap={0} align="center">
              <Text fz={22} fw={700} c="teal" lh={1}>
                {plotCount}
              </Text>
              <Text size="xs" c="dimmed">
                Plots
              </Text>
            </Stack>
          </Group>
        </Stack>
      )}
    </Card>
  );
};

/** Per-report block: the report header (name/version/processed/size) +
 *  two collapsible sections — Samples and Modules & Plots — that mirror
 *  the Dash UI at project_data_collections.py:3068-3145. */
const MultiQCReportBlock: React.FC<{
  report: MultiQCReportSummary;
  index: number;
}> = ({ report, index }) => {
  const r = report.report;
  const meta = r?.metadata;
  const canonicalSamples =
    meta && Array.isArray(meta.canonical_samples)
      ? [...meta.canonical_samples].sort()
      : [];
  const allSamples =
    meta && Array.isArray(meta.samples) ? [...meta.samples].sort() : [];
  const sampleList = canonicalSamples.length > 0 ? canonicalSamples : allSamples;

  const moduleNames = listKeys(meta?.modules).filter((m) => !!m);
  const sortedModules = [...moduleNames].sort();
  const plotsByModule = (meta?.plots ?? {}) as Record<string, unknown>;

  return (
    <Stack gap="sm">
      {/* Report info row — 4 columns matching the Dash SimpleGrid */}
      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md">
        <Stack gap={2}>
          <Text size="xs" c="dimmed">
            Report
          </Text>
          <Text size="sm" ff="monospace" truncate>
            {r?.report_name || r?.title || r?.report_id || `Report ${index + 1}`}
          </Text>
        </Stack>
        <Stack gap={2}>
          <Text size="xs" c="dimmed">
            Version
          </Text>
          <Text size="sm" ff="monospace">
            {r?.multiqc_version || '—'}
          </Text>
        </Stack>
        <Stack gap={2}>
          <Text size="xs" c="dimmed">
            Processed
          </Text>
          <Text size="sm">
            {r?.processed_at ? r.processed_at.slice(0, 10) : '—'}
          </Text>
        </Stack>
        <Stack gap={2}>
          <Text size="xs" c="dimmed">
            Size
          </Text>
          <Text size="sm" ff="monospace">
            {r?.file_size_bytes ? formatBytes(r.file_size_bytes) : '—'}
          </Text>
        </Stack>
      </SimpleGrid>

      {/* Outer accordion: Samples + Modules & Plots */}
      <Accordion variant="separated" chevronPosition="left" multiple>
        <Accordion.Item value="samples">
          <Accordion.Control>
            <Group gap="xs">
              <Icon
                icon="mdi:test-tube"
                width={18}
                color="var(--mantine-color-blue-6)"
              />
              <Text size="sm" fw={500}>
                Samples
              </Text>
              <Text size="sm" c="dimmed">
                ({sampleList.length})
              </Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            {sampleList.length === 0 ? (
              <Text size="sm" c="dimmed" fs="italic">
                No samples found.
              </Text>
            ) : (
              <ScrollArea h={150} type="auto" offsetScrollbars>
                <Stack gap={2}>
                  {sampleList.map((s) => (
                    <Text key={s} size="xs" ff="monospace">
                      {s}
                    </Text>
                  ))}
                </Stack>
              </ScrollArea>
            )}
          </Accordion.Panel>
        </Accordion.Item>

        <Accordion.Item value="modules-plots">
          <Accordion.Control>
            <Group gap="xs">
              <Icon
                icon="mdi:puzzle"
                width={18}
                color="var(--mantine-color-green-6)"
              />
              <Text size="sm" fw={500}>
                Modules & Plots
              </Text>
              <Text size="sm" c="dimmed">
                ({sortedModules.length} modules)
              </Text>
            </Group>
          </Accordion.Control>
          <Accordion.Panel>
            {sortedModules.length === 0 ? (
              <Text size="sm" c="dimmed" fs="italic">
                No modules found.
              </Text>
            ) : (
              <Accordion variant="contained" chevronPosition="left" multiple>
                {sortedModules.map((module) => {
                  const plotEntries = flattenPlotEntries(plotsByModule[module]);
                  return (
                    <Accordion.Item key={module} value={module}>
                      <Accordion.Control>
                        <Group gap="xs">
                          <Icon
                            icon="mdi:puzzle"
                            width={16}
                            color="var(--mantine-color-green-6)"
                          />
                          <Text size="sm" fw={500}>
                            {module}
                          </Text>
                          <Text size="xs" c="dimmed">
                            ({plotEntries.length} plot
                            {plotEntries.length === 1 ? '' : 's'})
                          </Text>
                        </Group>
                      </Accordion.Control>
                      <Accordion.Panel>
                        {plotEntries.length === 0 ? (
                          <Text size="xs" c="dimmed" fs="italic" pl="md">
                            No plots
                          </Text>
                        ) : (
                          <Stack gap={4} pl="md">
                            {plotEntries.map((p, i) => (
                              <Group key={`${module}-${i}-${p}`} gap="xs">
                                <Icon
                                  icon="mdi:chart-box"
                                  width={14}
                                  color="var(--mantine-color-orange-6)"
                                />
                                <Text size="xs">{p}</Text>
                              </Group>
                            ))}
                          </Stack>
                        )}
                      </Accordion.Panel>
                    </Accordion.Item>
                  );
                })}
              </Accordion>
            )}
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
};

/** Wrapper that fetches reports for a MultiQC DC and renders ONE block at a
 *  time, picked via a Select dropdown. Mirrors Dash's
 *  `_build_multiqc_section` (project_data_collections.py L3308+) which uses
 *  a `dmc.Select` to keep the panel scannable when the DC has many reports.
 *  When there's only a single report the dropdown is hidden. */
const MultiQCReportsCard: React.FC<{ dcId: string }> = ({ dcId }) => {
  const [reports, setReports] = useState<MultiQCReportSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState<string>('0');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchMultiQCByDataCollection(dcId, 50)
      .then((res) => {
        if (cancelled) return;
        setReports(res.reports || []);
        setTotal(res.total_count || 0);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load reports.');
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [dcId]);

  // Reset selection when the DC changes or the report set shrinks below the
  // current index — otherwise we'd render `reports[undefined]` after a clear.
  useEffect(() => {
    setSelectedIdx('0');
  }, [dcId, reports.length]);

  const reportOptions = useMemo(
    () =>
      reports.map((r, i) => ({
        value: String(i),
        label: r.report?.report_name || `Report ${i + 1}`,
      })),
    [reports],
  );

  const activeIdx = Math.min(Number(selectedIdx) || 0, reports.length - 1);
  const activeReport = reports[activeIdx];

  return (
    <Card withBorder radius="md" p="md">
      <Group gap="xs" mb="xs">
        <img
          src={`${import.meta.env.BASE_URL}logos/multiqc_icon_color.svg`}
          alt="MultiQC"
          width={20}
          height={20}
          style={{ objectFit: 'contain', display: 'block' }}
        />
        <Text fw={600}>MultiQC Report Metadata</Text>
        <Text size="sm" c="dimmed">
          ·{' '}
          {total} report{total === 1 ? '' : 's'} available
        </Text>
      </Group>
      {loading ? (
        <Center py="md">
          <Loader size="sm" />
        </Center>
      ) : error ? (
        <Text size="sm" c="red">
          {error}
        </Text>
      ) : reports.length === 0 ? (
        <Text size="sm" c="dimmed">
          No MultiQC reports registered yet.
        </Text>
      ) : (
        <Stack gap="md">
          {reports.length > 1 && (
            <Select
              label="Select Report"
              data={reportOptions}
              value={selectedIdx}
              onChange={(v) => v != null && setSelectedIdx(v)}
              size="xs"
              w={280}
              leftSection={<Icon icon="mdi:file-document-outline" width={14} />}
              comboboxProps={{ withinPortal: true }}
            />
          )}
          {activeReport && (
            <MultiQCReportBlock
              key={activeReport.report?.report_id || activeReport.report?.id || activeIdx}
              report={activeReport}
              index={activeIdx}
            />
          )}
        </Stack>
      )}
    </Card>
  );
};

const DetailRow: React.FC<{
  label: string;
  value?: string;
  mono?: boolean;
  wrap?: boolean;
  badge?: React.ReactNode;
}> = ({ label, value, mono, wrap, badge }) => (
  <Group gap="xs" wrap="nowrap" align="baseline" justify="space-between">
    <Text size="sm" fw={600} miw={140} style={{ flexShrink: 0 }}>
      {label}:
    </Text>
    {badge ? (
      badge
    ) : (
      <Text
        size="sm"
        c="dimmed"
        ta="right"
        style={{
          fontFamily: mono ? 'monospace' : undefined,
          flex: 1,
          wordBreak: wrap ? 'break-all' : undefined,
        }}
      >
        {value}
      </Text>
    )}
  </Group>
);

const DataPreviewPanel: React.FC<{ dcId: string }> = ({ dcId }) => {
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { colorScheme } = useMantineColorScheme();

  const handleLoad = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchDataCollectionPreview(dcId, 100);
      setPreview(result);
    } catch (err) {
      setError((err as Error).message || 'Failed to load preview.');
    } finally {
      setLoading(false);
    }
  };

  if (!preview && !loading && !error) {
    return (
      <Button
        color="teal"
        variant="light"
        size="sm"
        onClick={handleLoad}
        leftSection={<Icon icon="mdi:table-eye" width={16} />}
      >
        Load Data
      </Button>
    );
  }
  if (loading) {
    return (
      <Center py="md">
        <Loader size="sm" />
      </Center>
    );
  }
  if (error) {
    return (
      <Stack gap="xs">
        <Text size="sm" c="red">
          {error}
        </Text>
        <Button size="xs" variant="subtle" onClick={handleLoad}>
          Retry
        </Button>
      </Stack>
    );
  }
  if (!preview) return null;

  const columns = preview.columns ?? [];
  const rows = preview.rows ?? [];
  const isDark = colorScheme === 'dark';

  const colDefs: ColDef[] = columns.map((col) => ({
    // AG Grid's `field` treats "." as a path separator into nested objects, so
    // a column named "FastQC.total_sequences" would resolve to row.FastQC.total_sequences.
    // Use `valueGetter` with flat key access so dotted column names render
    // their actual values.
    colId: col,
    headerName: col,
    valueGetter: (params) =>
      params.data ? (params.data as Record<string, unknown>)[col] : undefined,
    sortable: true,
    filter: true,
    resizable: true,
  }));

  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">
        Showing {rows.length} of {preview.total_rows ?? rows.length} rows ·{' '}
        {preview.total_columns ?? columns.length} columns
      </Text>
      <Box
        className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
        style={{ height: 400, width: '100%' }}
      >
        <AgGridReact
          rowData={rows as Record<string, unknown>[]}
          columnDefs={colDefs}
          defaultColDef={{ sortable: true, filter: true, resizable: true }}
          animateRows
          suppressCellFocus
        />
      </Box>
    </Stack>
  );
};

export default ProjectDetailApp;
