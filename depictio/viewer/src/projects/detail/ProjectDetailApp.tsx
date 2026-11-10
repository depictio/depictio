import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Accordion,
  ActionIcon,
  AppShell,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Collapse,
  Group,
  Loader,
  LoadingOverlay,
  Paper,
  ScrollArea,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
  UnstyledButton,
  useMantineColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type { ColDef } from 'ag-grid-community';
import { GlassPage, STROKE, useGlassPages } from '../../chrome/variants/glass/pages';
import '../../chrome/variants/glass/pages/project-detail.css';
import {
  Check,
  ClipboardCheck,
  Database,
  GitBranch,
  HardDrive,
  Layers,
  Settings,
  ShieldCheck,
  FolderGit,
  Workflow,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { notifications } from '@mantine/notifications';
import {
  Alert,
  Modal,
  Select,
  Switch,
  TextInput,
} from '@mantine/core';

import {
  deleteDataCollection,
  fetchDataCollectionPreview,
  fetchDeltaHistory,
  fetchMultiQCByDataCollection,
  fetchProject,
  fetchTableEditStatus,
  fetchIngestionReport,
  fetchVizSuggestions,
  listLinkResolvers,
  renameDataCollection,
  useBrandAccents,
} from 'depictio-react-core';
import type {
  TableEditStatus,
  ProjectListEntry,
  PreviewResult,
  MultiQCReportSummary,
  DCLink,
  IngestionDataCollection,
  ResolverInfo,
  VizSuggestionsResponse,
} from 'depictio-react-core';
import LinksSection from './LinksSection';
import LinkEditModal from './LinkEditModal';
import { LinkMappingInspector } from './LinkMappingInspector';
import {
  CopyId,
  DcColumnsTable,
  DcDetailsGrid,
  DcFacts,
  DcLinksTable,
  DcSuggestedCharts,
  SortableTh,
  userColumns,
  dcColumns,
  dcOrigin,
  dcShape,
  formatTimestamp,
  lastAggregation,
  scanSource,
  typeDetails,
} from './DcViewerParts';
import type { DcLinkRow, DetailItem, Fact } from './DcViewerParts';
import type { ProjectJoin } from './ConnectionsMap';
import ManageDataCollectionModal, {
  type ManageDcType,
} from './ManageDataCollectionModal';
import MultiQCViewerPreview from './MultiQCViewerPreview';
import CoordinatesMapPreview from './CoordinatesMapPreview';
import {
  GeoJsonPreview,
  ImagesPreview,
  LegacyTracksNotice,
  TracksPreview,
  TreePreview,
} from './AssetPreviews';

import { useCurrentUser } from '../../hooks/useCurrentUser';
import { AppSidebar, LoadErrorCard } from '../../chrome';
import IngestionReportPanel from './IngestionReportPanel';
import ProjectIngestionHistoryPanel from './ProjectIngestionHistoryPanel';
import ProjectIngestionTrigger from './ProjectIngestionTrigger';
import { DeltaVersionHistory } from './DeltaVersionHistory';
import TableEditor from './TableEditor';
import ProjectSettingsModal, { type ProjectSettingsSectionKey } from './ProjectSettingsModal';
import { parseTemplate } from '../template';
import {
  DcTypeBadges,
  DcTypeIcon,
  dcHasCoordinates,
  dcTypeSearchKey,
  GEO_COLOR,
  GEO_ICON,
} from '../dcTypeIcon';
import {
  AGGREGATE_COLOR,
  DcMetatypeBadge,
  dcMetatypeMeta,
  METADATA_COLOR,
} from '../dcMetatype';
import { usePageTitle } from '../../branding';
import { UnrecognisedFilesPanel } from './UnrecognisedFilesPanel';
import { ProvenanceBadge } from './ProvenanceBadge';
import { PublishedLockBadge } from './PublishedLockBadge';
import { ProjectDashboardsPanel } from './ProjectDashboardsPanel';
import { ProjectPart } from './ProjectPart';
import { ProjectSummary } from './ProjectSummary';
import AddDataButton from './addData/AddDataButton';
import { isRealWorkflow } from '../layout';
import RunsPanel from './RunsPanel';
import DerivedLineage from './DerivedLineage';

interface DataCollectionShape {
  _id?: string;
  id?: string;
  data_collection_tag?: string;
  description?: string;
  registration_time?: string;
  /** S3 path of the registered delta table (post-aggregation) — stamped on
   *  the DC by the project enrichment query. */
  delta_location?: string;
  /** Last-aggregation snapshot. Shape depends on the DC type; we pull
   *  `aggregation_time` for the "Last Aggregated" line and `delta_version` for
   *  the "Delta version" line. */
  last_aggregation?:
    | {
        aggregation_time?: string;
        delta_version?: number | null;
        [k: string]: unknown;
      }
    | Array<{
        aggregation_time?: string;
        delta_version?: number | null;
        [k: string]: unknown;
      }>;
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

/** Pick the right storage size for a DC. Tables (and genomic_tracks
 *  manifests, which are Delta tables too) come from the delta-table size
 *  field; MultiQC DCs come from one of the file-size aliases. */
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

/** The genomic_tracks settings the DC viewer lists. The assembly is a preset
 *  name or a custom-assembly object named by `name`. */
function readTracksProps(props: Record<string, unknown> | undefined): {
  assembly: string;
  uriColumn: string;
  sampleColumn: string;
} {
  const assembly = props?.assembly;
  const assemblyName =
    typeof assembly === 'string'
      ? assembly
      : assembly && typeof assembly === 'object'
        ? `${String((assembly as { name?: unknown }).name ?? 'custom')} (custom)`
        : 'hg38';
  return {
    assembly: assemblyName,
    uriColumn: (props?.uri_column as string | undefined) || 'uri',
    sampleColumn: (props?.sample_column as string | undefined) || '—',
  };
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

/** Delta commit version of the latest aggregation, when the writer recorded
 *  one. Read from the same `last_aggregation` bag as the timestamp — no extra
 *  request. Aggregations written before versions were captured return null and
 *  the row renders as unknown rather than as version 0. */
function getDcDeltaVersion(dc: DataCollectionShape): number | null {
  const la = dc.last_aggregation;
  const latest = Array.isArray(la) ? la[la.length - 1] : la;
  const version = latest?.delta_version;
  return typeof version === 'number' ? version : null;
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

/** What the page below the workflows is scoped to: the selected workflow, the
 *  only one there is, or all of them. */
function workflowScope(
  workflows: WorkflowShape[],
  selectedId: string | null,
): { label: string; count: number } | null {
  if (workflows.length === 0) return null;
  const wf =
    workflows.length === 1
      ? workflows[0]
      : workflows.find((w) => (w._id ?? w.id) === selectedId);
  if (wf) return { label: workflowLabel(wf), count: wf.data_collections?.length ?? 0 };
  return {
    label: 'All workflows',
    count: workflows.reduce((n, w) => n + (w.data_collections?.length ?? 0), 0),
  };
}

function engineDescription(wf: WorkflowShape): string | null {
  if (!wf.engine) return null;
  if (typeof wf.engine === 'string') return wf.engine;
  const name = wf.engine.name;
  const version = wf.engine.version;
  if (name && version) return `${name} ${version}`;
  return name || null;
}

/** Read project ID from /projects/{id}[/permissions] pathname. */
function readProjectIdFromPath(): string | null {
  const m = window.location.pathname.match(/^\/projects\/([^/?#]+)/);
  return m?.[1] || null;
}

/** `?table={dc_id}`: the data collection a link asks the page to open. */
function readTableFromQuery(): string | null {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get('table') || null;
}

/** Flatten DCs across all workflows. The workflows are the project's own
 *  (a pipeline's, plus one wrapped around each hand-added collection). */
function flattenDataCollections(
  workflows: WorkflowShape[] | undefined,
): DataCollectionShape[] {
  if (!workflows) return [];
  return workflows.flatMap((wf) => wf.data_collections ?? []);
}

const ProjectDetailApp: React.FC = () => {
  const accent = useBrandAccents();
  const [project, setProject] = useState<ProjectListEntry | null>(null);
  const [deltaLocations, setDeltaLocations] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<{ error: unknown } | null>(null);
  const [selectedDcId, setSelectedDcId] = useState<string | null>(null);
  // `/projects/{id}?table={dc_id}` opens that table: the Data part unfolds, the
  // collection is selected and its rows load. Applied once per visit.
  const requestedTableId = useMemo(readTableFromQuery, []);
  const requestedTableHandled = useRef(false);
  // Active project-detail tab. Honors `#ingestion` deep links (e.g. from the
  // dashboard banner / settings drawer) and is controlled so the ingestion
  // report can switch back to Overview when previewing a data collection.
  const [activeTab, setActiveTab] = useState<string | null>(
    typeof window !== 'undefined' &&
      ['#ingestion', '#ingestion-history'].includes(window.location.hash)
      ? 'ingestion'
      : typeof window !== 'undefined' && window.location.hash === '#runs'
        ? 'runs'
        : 'overview',
  );
  // The run the Runs tab opens on, when another part of the page asked for one.
  const [focusRun, setFocusRun] = useState<string | null>(null);
  // Which half of the Ingestion tab is showing. `#ingestion-history` deep-links
  // straight to the run history, which is what a "your ingestion failed" link
  // should open.
  const [ingestionView, setIngestionView] = useState<'report' | 'history'>(
    typeof window !== 'undefined' && window.location.hash === '#ingestion-history'
      ? 'history'
      : 'report',
  );
  const [refreshKey, setRefreshKey] = useState(0);
  // Nudges the history panel off its idle 30s cadence when a browser-triggered
  // ingestion finishes, so the completed run shows up straight away.
  const [ingestionHistorySignal, setIngestionHistorySignal] = useState(0);
  // Scroll-to + auto-open the DC viewer when a preview was requested from the
  // ingestion report (set when onPreviewDc fires, consumed once the viewer mounts).
  const dcViewerRef = useRef<HTMLDivElement>(null);
  const scrollToDcRef = useRef(false);
  const [renameTarget, setRenameTarget] = useState<DataCollectionShape | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DataCollectionShape | null>(null);
  const [manageTarget, setManageTarget] = useState<DataCollectionShape | null>(null);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [settingsOpened, setSettingsOpened] = useState(false);
  // `?settings=send` opens the project settings on that section: the project
  // list's menu links here instead of carrying a dialog of its own.
  const [settingsSection, setSettingsSection] = useState<ProjectSettingsSectionKey | undefined>();
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const wanted = params.get('settings');
    if (wanted !== 'send') return;
    setSettingsSection('send');
    setSettingsOpened(true);
    params.delete('settings');
    const rest = params.toString();
    window.history.replaceState(
      window.history.state,
      '',
      `${window.location.pathname}${rest ? `?${rest}` : ''}${window.location.hash}`,
    );
  }, []);
  /** Cross-DC links for this project. Fetched alongside the project doc and
   *  refreshed when the user creates / edits / deletes a link from the
   *  Links section. */
  const [projectLinks, setProjectLinks] = useState<DCLink[]>([]);
  // Bumped when the collection viewer saved a link, so the links section reloads.
  const [linksReload, setLinksReload] = useState(0);

  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);
  // Held at this level (not inside DataCollectionsManagerSection) so the
  // expand/collapse state survives the remount that a refresh() triggers —
  // every DC mutation bumps refreshKey → setLoading(true) swaps the section
  // for a <Loader/>, and section-local state would reset to collapsed.
  const [dcManagerOpened, { toggle: toggleDcManager }] = useDisclosure(true);

  const { user, isPublicMode, loading: userLoading } = useCurrentUser();
  const projectId = readProjectIdFromPath();

  usePageTitle('Project Data Collections');
  const glass = useGlassPages();

  useEffect(() => {
    if (!projectId) {
      setLoadError({ error: Object.assign(new Error('No project ID in URL.'), { status: 404 }) });
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
      .catch((err: unknown) => {
        setLoadError({ error: err });
      })
      .finally(() => setLoading(false));
  }, [projectId, refreshKey]);

  const refresh = () => setRefreshKey((k) => k + 1);
  // Open the ingestion report (latest run) and bring the Data part into view.
  const showIngestion = () => {
    setActiveTab('ingestion');
    setIngestionView('report');
    window.setTimeout(() => {
      const toggle = document.querySelector<HTMLElement>('[data-testid="project-part-data-toggle"]');
      if (toggle?.getAttribute('aria-expanded') === 'false') toggle.click();
      document
        .querySelector('[data-testid="project-part-data"]')
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  };

  // Open the Runs tab, on one run when given, and bring the Data part into view.
  const showRuns = (run?: string) => {
    setFocusRun(run ?? null);
    setActiveTab('runs');
    window.setTimeout(() => {
      const toggle = document.querySelector<HTMLElement>('[data-testid="project-part-data-toggle"]');
      if (toggle?.getAttribute('aria-expanded') === 'false') toggle.click();
      document
        .querySelector('[data-testid="project-part-data"]')
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  };

  // Permission check: owners, editors, or admins may mutate DCs. Storage
  // credentials are owners-only (stricter than canMutate), mirroring the
  // backend's owner gate on /storage.
  const { canMutate, isOwner } = useMemo(() => {
    if (!user || !project) return { canMutate: false, isOwner: false };
    // Published read-only: nobody mutates until an admin unlocks.
    if (project.published_lock) return { canMutate: false, isOwner: false };
    if (user.is_admin) return { canMutate: true, isOwner: true };
    const matchUser = (list?: Array<{ _id?: string; id?: string }>) =>
      !!list?.some((u) => (u._id ?? u.id) === user.id);
    const owner = matchUser(project.permissions?.owners);
    return { canMutate: owner || matchUser(project.permissions?.editors), isOwner: owner };
  }, [user, project]);

  // Pushing to another instance is for owners and admins, locked or not.
  const canPushProject = useMemo(() => {
    if (!user || !project) return false;
    if (user.is_admin) return true;
    return !!project.permissions?.owners?.some(
      (u: { _id?: string; id?: string }) => (u._id ?? u.id) === user.id,
    );
  }, [user, project]);

  // Refresh and export are refused to non-admins on a public/demo deployment.
  // Whether this is one is unknown until the auth status lands, so both stay
  // gated until then rather than being enabled for a moment.
  const publicModeReason = userLoading
    ? 'Checking what you can change in this project...'
    : isPublicMode && !user?.is_admin
      ? 'Disabled in public/demo mode for non-admin users.'
      : null;

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

  useEffect(() => {
    if (!requestedTableId || requestedTableHandled.current || !project) return;
    requestedTableHandled.current = true;
    const known = allDataCollections.some((dc) => (dc._id ?? dc.id) === requestedTableId);
    if (!known) {
      notifications.show({
        color: 'yellow',
        message: 'The table in this link is not in this project (it may have been deleted).',
      });
      return;
    }
    setSelectedWorkflowId(null);
    setActiveTab('overview');
    scrollToDcRef.current = true;
    setSelectedDcId(requestedTableId);
  }, [requestedTableId, project, allDataCollections]);

  const selectedDc = useMemo(
    () =>
      dataCollections.find((dc) => (dc._id ?? dc.id) === selectedDcId) || null,
    [dataCollections, selectedDcId],
  );

  // Only workflows that name a pipeline engine or catalog count; the one
  // made around hand-added collections is bookkeeping, not something to list.
  const realWorkflows = useMemo(() => workflows.filter(isRealWorkflow), [workflows]);
  // Ids of the collections a pipeline made (they are the "Aggregate" ones).
  const pipelineDcIds = useMemo(() => {
    const ids = new Set<string>();
    for (const wf of realWorkflows) {
      for (const dc of wf.data_collections ?? []) {
        const id = (dc._id ?? dc.id) as string | undefined;
        if (id) ids.add(id);
      }
    }
    return ids;
  }, [realWorkflows]);

  // Tag → DC id, so identified ingestion rows can lazily list their files.
  const dcIdByTag = useMemo(() => {
    const map: Record<string, string> = {};
    for (const d of allDataCollections) {
      const id = (d._id ?? d.id) as string | undefined;
      const tag = d.data_collection_tag;
      if (id && tag) map[tag] = id;
    }
    return map;
  }, [allDataCollections]);
  const dcTypeByTag = useMemo(() => {
    const map: Record<string, string> = {};
    for (const d of allDataCollections) {
      const type = (d.config?.type as string | undefined)?.toLowerCase();
      if (d.data_collection_tag && type) map[d.data_collection_tag] = type;
    }
    return map;
  }, [allDataCollections]);
  const shapeByTag = useMemo(() => {
    const map: Record<string, { rows: number | null; columns: number | null }> = {};
    for (const d of allDataCollections) {
      if (d.data_collection_tag) map[d.data_collection_tag] = dcShape(d as unknown as Record<string, unknown>);
    }
    return map;
  }, [allDataCollections]);
  // A project made from a pipeline has runs: it gets the Runs tab.
  const hasRuns = realWorkflows.length > 0;

  // After an ingestion-report "preview" jumps to Overview with a DC selected,
  // scroll the DC viewer (which renders the table preview) into view.
  useEffect(() => {
    if (scrollToDcRef.current && activeTab === 'overview' && selectedDcId) {
      scrollToDcRef.current = false;
      requestAnimationFrame(() => {
        dcViewerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }
  }, [activeTab, selectedDcId]);

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

  const body = (
    <>
      {loading ? (
        <Center mih={300}>
          <Loader />
        </Center>
      ) : loadError ? (
        <Center mih={300} py="xl">
          <LoadErrorCard
            subject="project"
            resourceId={projectId}
            error={loadError.error}
            onRetry={refresh}
          />
        </Center>
      ) : !project ? null : (
        (() => {
          // The workflows come first and scope everything below them, so the
          // tabs sit under the panel rather than the panel inside a tab.
          const workflowsPanel =
            realWorkflows.length > 0 ? (
              <WorkflowsPanel
                workflows={realWorkflows}
                templateSource={parseTemplate(project)?.source.toLowerCase() || null}
                selectedWorkflowId={selectedWorkflowId}
                scope={workflowScope(realWorkflows, selectedWorkflowId)}
                onSelect={(id) => {
                  setSelectedWorkflowId(id);
                  setSelectedDcId(null);
                }}
              />
            ) : null;
          const overviewSections = (
            <Stack gap="lg">
              <DataCollectionsManagerSection
                projectId={projectId}
                project={project}
                pipelineDcIds={pipelineDcIds}
                scopeLabel={
                  realWorkflows.length > 0
                    ? (workflowScope(realWorkflows, selectedWorkflowId)?.label ?? null)
                    : null
                }
                stats={stats}
                dataCollections={dataCollections}
                selectedDcId={selectedDcId}
                canMutate={canMutate}
                opened={dcManagerOpened}
                onToggle={toggleDcManager}
                onSelect={setSelectedDcId}
                onRename={setRenameTarget}
                onDelete={setDeleteTarget}
                onManage={setManageTarget}
                onAdded={refresh}
              />
              <UnrecognisedFilesPanel
                templateOrigin={(project as Record<string, unknown>).template_origin}
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
                  reloadKey={linksReload}
                  joins={
                    ((project as Record<string, unknown>).joins as ProjectJoin[] | undefined) || []
                  }
                />
              )}
              <Box ref={dcViewerRef}>
                {selectedDc && (
                  <DataCollectionViewer
                    dc={selectedDc}
                    fromPipeline={pipelineDcIds.has((selectedDc._id ?? selectedDc.id) as string)}
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
                    projectId={projectId}
                    canMutate={canMutate}
                    onLinkSaved={() => setLinksReload((k) => k + 1)}
                    onShowRuns={hasRuns ? () => showRuns() : undefined}
                    onOpenDc={(id) => {
                      scrollToDcRef.current = true;
                      setSelectedDcId(id);
                    }}
                    autoLoadPreview={requestedTableId === selectedDcId}
                  />
                )}
              </Box>
            </Stack>
          );
          // The page's second major part, beside Dashboards: what the
          // dashboards read (workflows, collections, ingestion runs).
          const dataSummary = [
            realWorkflows.length > 0
              ? `${realWorkflows.length} workflow${realWorkflows.length === 1 ? '' : 's'}`
              : null,
            `${stats.total} collection${stats.total === 1 ? '' : 's'}`,
            stats.totalBytes > 0 ? formatBytes(stats.totalBytes) : null,
          ]
            .filter(Boolean)
            .join(' · ');
          return (
            <Stack gap="xl">
              <ProjectHeader
                project={project}
                projectId={projectId}
                onShowIngestion={showIngestion}
                onShowRuns={showRuns}
                refreshKey={refreshKey}
              />
              {projectId && <ProjectDashboardsPanel projectId={projectId} />}
              <ProjectPart
                id="data"
                icon={Database}
                title="Data"
                summary={dataSummary}
                forceOpen={requestedTableId != null}
              >
                <Stack gap="lg">
                  {workflowsPanel}
                  {projectId ? (
                    <Tabs
                      value={activeTab}
                      onChange={setActiveTab}
                      keepMounted={false}
                      variant="pills"
                      className="dc-project-tabs"
                    >
                      {glass ? (
                        // Glass: the page's switch, two equal halves across the
                        // content width, each saying what it holds.
                        <Tabs.List mb="xl">
                          <Tabs.Tab
                            value="overview"
                            className="dc-project-tab"
                            leftSection={
                              <span className="dc-project-tab-icon">
                                <Database size={20} strokeWidth={STROKE} aria-hidden />
                              </span>
                            }
                          >
                            <span className="dc-project-tab-label">Data collections</span>
                            <span className="dc-project-tab-meta">
                              {stats.total} collection{stats.total === 1 ? '' : 's'}
                              {stats.totalBytes > 0 ? ` · ${formatBytes(stats.totalBytes)}` : ''}
                            </span>
                          </Tabs.Tab>
                          {hasRuns && (
                            <Tabs.Tab
                              value="runs"
                              className="dc-project-tab"
                              data-testid="project-tab-runs"
                              leftSection={
                                <span className="dc-project-tab-icon">
                                  <FolderGit size={20} strokeWidth={STROKE} aria-hidden />
                                </span>
                              }
                            >
                              <span className="dc-project-tab-label">Runs</span>
                              <span className="dc-project-tab-meta">Each run folder and what it holds</span>
                            </Tabs.Tab>
                          )}
                          <Tabs.Tab
                            value="ingestion"
                            className="dc-project-tab"
                            leftSection={
                              <span className="dc-project-tab-icon">
                                <ClipboardCheck size={20} strokeWidth={STROKE} aria-hidden />
                              </span>
                            }
                          >
                            <span className="dc-project-tab-label">Ingestion report</span>
                            <span className="dc-project-tab-meta">What each run found, and when</span>
                          </Tabs.Tab>
                        </Tabs.List>
                      ) : (
                        <Tabs.List mb="md">
                          <Tabs.Tab
                            value="overview"
                            fz="md"
                            px="lg"
                            leftSection={<Icon icon="mdi:table-cog" width={18} />}
                          >
                            Data collections
                          </Tabs.Tab>
                          {hasRuns && (
                            <Tabs.Tab
                              value="runs"
                              fz="md"
                              px="lg"
                              data-testid="project-tab-runs"
                              leftSection={<Icon icon="mdi:folder-play-outline" width={18} />}
                            >
                              Runs
                            </Tabs.Tab>
                          )}
                          <Tabs.Tab
                            value="ingestion"
                            fz="md"
                            px="lg"
                            leftSection={<Icon icon="mdi:clipboard-check-outline" width={18} />}
                          >
                            Ingestion report
                          </Tabs.Tab>
                        </Tabs.List>
                      )}
                      <Tabs.Panel value="overview">{overviewSections}</Tabs.Panel>
                      {hasRuns && (
                        <Tabs.Panel value="runs">
                          <RunsPanel
                            projectId={projectId}
                            refreshKey={refreshKey}
                            focusRun={focusRun}
                            dcIdByTag={dcIdByTag}
                            dcTypeByTag={dcTypeByTag}
                            onOpenDc={(dcId) => {
                              scrollToDcRef.current = true;
                              setSelectedWorkflowId(null);
                              setSelectedDcId(dcId);
                              setActiveTab('overview');
                            }}
                          />
                        </Tabs.Panel>
                      )}
                      <Tabs.Panel value="ingestion">
                        <Stack gap="md">
                          <Group justify="space-between" wrap="wrap" gap="sm">
                            <SegmentedControl
                              size="xs"
                              w="fit-content"
                              value={ingestionView}
                              onChange={(v: string) => setIngestionView(v as 'report' | 'history')}
                              data={[
                                { value: 'report', label: 'Latest run' },
                                { value: 'history', label: 'History' },
                              ]}
                            />
                            <ProjectIngestionTrigger
                              projectId={projectId}
                              // Switch to History as soon as a run starts —
                              // that is where its progress is visible.
                              onStarted={() => setIngestionView('history')}
                              onFinished={() => setIngestionHistorySignal((n) => n + 1)}
                            />
                          </Group>
                          {ingestionView === 'report' ? (
                            <IngestionReportPanel
                              projectId={projectId}
                              dcIdByTag={dcIdByTag}
                              onPreviewDc={(dcId) => {
                                // Jump to the Overview tab with this DC selected so
                                // its table/preview shows in the DataCollectionViewer,
                                // then scroll it into view (see the effect above).
                                scrollToDcRef.current = true;
                                setSelectedWorkflowId(null);
                                setSelectedDcId(dcId);
                                setActiveTab('overview');
                              }}
                              onShowRuns={hasRuns ? () => showRuns() : undefined}
                              shapeByTag={shapeByTag}
                            />
                          ) : (
                            <ProjectIngestionHistoryPanel
                              projectId={projectId}
                              refreshSignal={ingestionHistorySignal}
                            />
                          )}
                        </Stack>
                      </Tabs.Panel>
                    </Tabs>
                  ) : (
                    overviewSections
                  )}
                </Stack>
              </ProjectPart>
            </Stack>
          );
        })()
      )}
    </>
  );

  const modals = (
    <>
      {/* Outside the loading switch, so reloading the project after a
          refresh keeps the dialog, and the run it follows, mounted. */}
      {projectId && (
        <ProjectSettingsModal
          opened={settingsOpened}
          onClose={() => setSettingsOpened(false)}
          projectId={projectId}
          projectName={project?.name}
          canManageStorage={isOwner}
          canMutate={canMutate}
          publicModeReason={publicModeReason}
          dataCollections={allDataCollections}
          canPush={canPushProject}
          publishedLock={project?.published_lock}
          isAdmin={!!user?.is_admin}
          initialSection={settingsSection}
          onReloadProject={refresh}
        />
      )}
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
    </>
  );

  // After adding data the next thing to do: open the dialog on this project.
  const createDashboardButton = (
    <Button
      component="a"
      href={`/dashboards?create_for_project=${encodeURIComponent(projectId ?? '')}`}
      leftSection={<Icon icon="mdi:view-dashboard-outline" width={16} />}
      data-disabled={!project ? true : undefined}
      data-testid="project-create-dashboard"
    >
      Create a dashboard
    </Button>
  );

  if (glass) {
    const name = project?.name || 'Project';
    return (
      <>
        <GlassPage
          section="projects"
          title={name}
          description="Workflows, data collections, ingestion runs and the links between them."
          crumbs={[{ label: name }]}
          actions={
            <Group gap="xs">
              {createDashboardButton}
              {/* Open to every reader once the project has loaded: the sections
                  inside disable what the reader may not change and say why. */}
              <Button
                variant="default"
                data-testid="project-settings-button"
                leftSection={<Settings size={17} strokeWidth={1.8} aria-hidden />}
                disabled={!project}
                onClick={() => setSettingsOpened(true)}
              >
                Project settings
              </Button>
              <Button
                component="a"
                href={`/projects/${projectId}/permissions`}
                variant="default"
                leftSection={<ShieldCheck size={17} strokeWidth={1.8} aria-hidden />}
              >
                Permissions
              </Button>
            </Group>
          }
        >
          {body}
        </GlassPage>
        {modals}
      </>
    );
  }

  return (
    <AppShell
      data-testid="app-shell"
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
              color={`var(--mantine-color-${accent.secondary}-6)`}
            />
            <Title order={3} c={accent.secondary}>
              Project Data Manager
            </Title>
          </Group>
          <Group gap="xs">
            {createDashboardButton}
            {/* Open to every reader once the project has loaded: the sections
                inside disable what the reader may not change and say why. */}
            <Button
              variant="light"
              color={accent.secondary}
              data-testid="project-settings-button"
              leftSection={<Icon icon="ic:baseline-settings" width={16} />}
              disabled={!project}
              onClick={() => setSettingsOpened(true)}
            >
              Project settings
            </Button>
            <Button
              component="a"
              href={`/projects/${projectId}/permissions`}
              variant="subtle"
              color="blue"
              leftSection={<Icon icon="mdi:shield-account-outline" width={16} />}
            >
              Permissions
            </Button>
            <Button
              component="a"
              href="/projects"
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
          {body}
        </Box>
      </AppShell.Main>
      {modals}
    </AppShell>
  );
};

const RenameDataCollectionModal: React.FC<{
  target: DataCollectionShape | null;
  onClose: () => void;
  onSuccess: () => void;
}> = ({ target, onClose, onSuccess }) => {
  const accent = useBrandAccents();
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
          <Button color={accent.secondary} onClick={handleSubmit} loading={submitting}>
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
  projectId: string | null;
  onShowIngestion: () => void;
  onShowRuns: (run?: string) => void;
  refreshKey: number;
}> = ({ project, projectId, onShowIngestion, onShowRuns, refreshKey }) => {
  const accent = useBrandAccents();
  const glass = useGlassPages();
  const summary = (
    <ProjectSummary
      project={project}
      projectId={projectId}
      onShowIngestion={onShowIngestion}
      onShowRuns={onShowRuns}
      refreshKey={refreshKey}
    />
  );
  const badges = (
    <Group gap="xs" wrap="wrap">
      <ProvenanceBadge provenance={project.provenance} />
      <PublishedLockBadge lock={project.published_lock} />
    </Group>
  );
  // Glass: the page head already names the project, so the card keeps only
  // its facts.
  if (glass) {
    return (
      <Paper withBorder radius="md" px="lg" py="md">
        <Group gap="lg" wrap="wrap" align="flex-start" justify="space-between">
          {summary}
          {badges}
        </Group>
      </Paper>
    );
  }
  return (
    <Paper withBorder radius="md" p="lg">
      <Stack gap="xs">
        <Group gap="sm">
          <Icon
            icon="mdi:database-outline"
            width={26}
            color={`var(--mantine-color-${accent.secondary}-6)`}
          />
          <Title order={3} c={accent.secondary} style={{ fontWeight: 600 }}>
            Project Data Manager
          </Title>
        </Group>
        <Group justify="space-between" align="flex-start" mt="xs">
          {summary}
          {badges}
        </Group>
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
  /** What the content below is scoped to (Glass draws the link to it). */
  scope: { label: string; count: number } | null;
  onSelect: (id: string | null) => void;
}> = ({ workflows, templateSource, selectedWorkflowId, scope, onSelect }) => {
  const glass = useGlassPages();
  const brandImage = templateSource ? WORKFLOW_BRAND_IMAGE[templateSource] : undefined;
  if (glass) {
    // A lone workflow is the scope whether or not it was clicked, so it
    // always shows as selected and cannot be toggled off.
    const only = workflows.length === 1;
    return (
      <section className="pd-workflows" aria-label="Workflows">
        <div className="pd-section-head">
          <GitBranch size={18} strokeWidth={STROKE} aria-hidden />
          <Title order={4}>Workflows</Title>
          <span className="pd-count">{workflows.length}</span>
          {!only && (
            <span className="pd-hint">
              {selectedWorkflowId
                ? 'The data collections below are scoped to the selected workflow.'
                : 'Pick one to scope the data collections below.'}
            </span>
          )}
          {selectedWorkflowId && !only && (
            <Button
              variant="subtle"
              color="gray"
              size="compact-xs"
              ml="auto"
              onClick={() => onSelect(null)}
            >
              Show all
            </Button>
          )}
        </div>
        <div className="pd-wf-grid" role="group" aria-label="Workflow">
          {workflows.map((wf) => {
            const id = (wf._id ?? wf.id) as string;
            const isSelected = only || id === selectedWorkflowId;
            const dcCount = wf.data_collections?.length ?? 0;
            const engine = engineDescription(wf);
            const toggle = () => {
              if (!only) onSelect(isSelected ? null : id);
            };
            return (
              <div
                key={id}
                className="pd-wf-card"
                data-selected={isSelected || undefined}
                role="button"
                tabIndex={0}
                aria-pressed={isSelected}
                aria-disabled={only || undefined}
                onClick={toggle}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggle();
                  }
                }}
              >
                <span className="pd-wf-chip">
                  {brandImage ? (
                    <img
                      src={`${import.meta.env.BASE_URL}logos/workflows/${brandImage}`}
                      alt=""
                      width={22}
                      height={22}
                    />
                  ) : (
                    <Workflow size={20} strokeWidth={STROKE} aria-hidden />
                  )}
                </span>
                <span className="pd-wf-body">
                  <span className="pd-wf-name">{workflowLabel(wf)}</span>
                  <span className="pd-wf-meta">
                    {[
                      wf.version ? `Version ${wf.version}` : null,
                      !brandImage && engine ? engine : null,
                    ]
                      .filter(Boolean)
                      .join(' · ') || 'Workflow'}
                  </span>
                  <span className="pd-wf-meta">
                    <Database size={13} strokeWidth={STROKE} aria-hidden />
                    {dcCount} data collection{dcCount === 1 ? '' : 's'}
                  </span>
                </span>
                <span className="pd-wf-mark" aria-hidden>
                  {isSelected && <Check size={13} strokeWidth={3} />}
                </span>
                {isSelected && <span className="pd-wf-selected">Selected</span>}
              </div>
            );
          })}
        </div>
        {scope && (
          <div className="pd-scope" role="status">
            <span className="pd-scope-label">
              <GitBranch size={14} strokeWidth={STROKE} aria-hidden />
              <b>{scope.label}</b>
              <span>
                {scope.count} data collection{scope.count === 1 ? '' : 's'}
              </span>
            </span>
          </div>
        )}
      </section>
    );
  }
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
  projectId: string | null;
  project: ProjectListEntry;
  pipelineDcIds: Set<string>;
  /** The workflow the list is scoped to (pipeline projects), named in the
   *  Glass header. */
  scopeLabel?: string | null;
  stats: DcStats;
  dataCollections: DataCollectionShape[];
  selectedDcId: string | null;
  canMutate: boolean;
  /** Expand/collapse state, lifted to the parent so it survives the remount a
   *  refresh() triggers after any DC mutation. Collapsed by default keeps the
   *  Overview tab compact; expands into a height-capped scroll area so a long
   *  DC list never dominates the page. */
  opened: boolean;
  onToggle: () => void;
  onSelect: (id: string | null) => void;
  onRename: (dc: DataCollectionShape) => void;
  onDelete: (dc: DataCollectionShape) => void;
  /** Open the manage-data modal for a MultiQC DC. Optional so non-MultiQC
   *  callers don't have to wire it. */
  onManage?: (dc: DataCollectionShape) => void;
  /** Called after data was added through the Add data menu. */
  onAdded: () => void;
}> = ({
  projectId,
  project,
  pipelineDcIds,
  scopeLabel,
  stats,
  dataCollections,
  selectedDcId,
  canMutate,
  opened,
  onToggle,
  onSelect,
  onRename,
  onDelete,
  onManage,
  onAdded,
}) => {
  const accent = useBrandAccents();
  const glass = useGlassPages();
  if (glass) {
    const n = dataCollections.length;
    return (
      <Paper withBorder radius="md" p="md" className="pd-manager">
        <Group justify="space-between" wrap="nowrap" gap="sm">
          <UnstyledButton
            onClick={onToggle}
            style={{ flex: 1, minWidth: 0 }}
            aria-expanded={opened}
          >
            <div className="pd-manager-title">
              <Title order={4}>
                {scopeLabel ? `${scopeLabel} data collections` : 'Data collections'}
              </Title>
              <span className="pd-hint">
                {n} data collection{n === 1 ? '' : 's'}
                {scopeLabel ? ` in ${scopeLabel}` : ''}
              </span>
            </div>
          </UnstyledButton>
          <Group gap="xs" wrap="nowrap">
            <AddDataButton
              projectId={projectId}
              project={project}
              canMutate={canMutate}
              onAdded={onAdded}
              onOpen={() => {
                if (!opened) onToggle();
              }}
            />
            <ActionIcon
              variant="subtle"
              color="gray"
              onClick={onToggle}
              aria-label={opened ? 'Collapse data collections' : 'Expand data collections'}
            >
              <Icon icon={opened ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={22} />
            </ActionIcon>
          </Group>
        </Group>
        <Collapse in={opened}>
          <ScrollArea.Autosize mah={640} type="auto" offsetScrollbars pt="md">
            <Stack gap="md" pr="sm">
              <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
                <StatCard glassIcon={Database} label="Total collections" primary={String(stats.total)} secondary="Data collections" />
                <StatCard
                  glassIcon={Layers}
                  label="Collection types"
                  primaryDual={[
                    { count: stats.aggregate, label: 'Aggregate', color: 'var(--gl-accent)' },
                    { count: stats.metadata, label: 'Metadata', color: 'var(--gl-faint)' },
                  ]}
                />
                <StatCard
                  glassIcon={HardDrive}
                  label="Total storage"
                  primary={formatBytes(stats.totalBytes)}
                  secondary={
                    stats.totalBytes > 0
                      ? `${n} collection${n === 1 ? '' : 's'}`
                      : 'No size info yet'
                  }
                />
              </SimpleGrid>
              <Paper withBorder radius="md" p="md">
                <Group gap="xs" mb="xs">
                  <Title order={5}>Data collections</Title>
                  <span className="pd-count">{n}</span>
                </Group>
                <DataCollectionsTable
          pipelineDcIds={pipelineDcIds}
                  dataCollections={dataCollections}
                  selectedDcId={selectedDcId}
                  canMutate={canMutate}
                  onSelect={onSelect}
                  onRename={onRename}
                  onDelete={onDelete}
                  onManage={onManage}
                />
              </Paper>
            </Stack>
          </ScrollArea.Autosize>
        </Collapse>
      </Paper>
    );
  }
  return (
    /* Header mirrors the Cross-DC links section (LinksSection.tsx): Paper,
       clickable title area, then the primary action and the chevron as an
       ActionIcon on the far right. Create Data Collection lives in the
       always-visible header — inside the Collapse it was unreachable while
       the section was collapsed (the default). */
    <Paper withBorder radius="md" p="sm">
      <Group justify="space-between" wrap="nowrap">
        <UnstyledButton onClick={onToggle} style={{ flex: 1, minWidth: 0 }}>
          <Group gap="xs" wrap="nowrap">
            <Icon
              icon="mdi:database-outline"
              width={22}
              color="var(--mantine-color-dark-6)"
            />
            <Title order={4}>Data Collections Manager</Title>
            <Badge variant="light" color="dark" size="sm">
              {dataCollections.length}
            </Badge>
          </Group>
        </UnstyledButton>
        <Group gap="xs" wrap="nowrap">
          <AddDataButton
            projectId={projectId}
            project={project}
            canMutate={canMutate}
            color={accent.secondary}
            onAdded={onAdded}
            onOpen={() => {
              // Expand the section too, so the new DC lands in view.
              if (!opened) onToggle();
            }}
          />
          <ActionIcon
            variant="subtle"
            color="gray"
            onClick={onToggle}
            aria-label={opened ? 'Collapse data collections' : 'Expand data collections'}
          >
            <Icon icon={opened ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={22} />
          </ActionIcon>
        </Group>
      </Group>

      <Collapse in={opened}>
        <ScrollArea.Autosize mah={640} type="auto" offsetScrollbars pt="sm">
          <Stack gap="md" pr="sm">
            <Text size="sm" c="dimmed">
              Managing data collections for this project
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
            { count: stats.aggregate, label: 'Aggregate', color: AGGREGATE_COLOR },
            { count: stats.metadata, label: 'Metadata', color: METADATA_COLOR },
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
        <Group gap="xs" mb="xs">
          <Title order={5}>Data Collections</Title>
          <Badge variant="light" color="dark" size="sm">
            {dataCollections.length} COLLECTIONS
          </Badge>
        </Group>
        <DataCollectionsTable
          pipelineDcIds={pipelineDcIds}
          dataCollections={dataCollections}
          selectedDcId={selectedDcId}
          canMutate={canMutate}
          onSelect={onSelect}
          onRename={onRename}
          onDelete={onDelete}
          onManage={onManage}
        />
      </Paper>
          </Stack>
        </ScrollArea.Autosize>
      </Collapse>
    </Paper>
  );
};

const StatCard: React.FC<{
  icon?: string;
  iconColor?: string;
  /** Glass: a Lucide glyph in a small accent chip instead of a coloured icon. */
  glassIcon?: LucideIcon;
  label: string;
  primary?: string;
  secondary?: string;
  primaryColor?: string;
  primaryDual?: Array<{ count: number; label: string; color: string }>;
}> = ({ icon, iconColor, glassIcon: GlassGlyph, label, primary, secondary, primaryColor, primaryDual }) => GlassGlyph ? (
  <Card withBorder radius="md" p="md" className="pd-stat">
    <div className="pd-stat-head">
      <span className="pd-stat-chip">
        <GlassGlyph size={16} strokeWidth={STROKE} />
      </span>
      <span className="pd-stat-label">{label}</span>
    </div>
    {primary && <div className="pd-stat-value">{primary}</div>}
    {primaryDual && (
      <div className="pd-stat-dual">
        {primaryDual.map((p) => (
          <div key={p.label}>
            <div className="pd-stat-value">{p.count}</div>
            <div className="pd-stat-sub">
              <i style={{ background: p.color }} aria-hidden />
              {p.label}
            </div>
          </div>
        ))}
      </div>
    )}
    {secondary && <div className="pd-stat-sub">{secondary}</div>}
  </Card>
) : (
  <Card withBorder radius="md" p="md">
    <Stack gap="xs" align="center">
      <Group gap={6}>
        {icon && <Icon icon={icon} width={20} color={iconColor} />}
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

type DcSortKey = 'tag' | 'type' | 'size' | 'updated';

/** Sortable + filterable table of a project's data collections. Replaces the
 *  former card list; row click selects the DC (drives the detail viewer). */
const DataCollectionsTable: React.FC<{
  pipelineDcIds: Set<string>;
  dataCollections: DataCollectionShape[];
  selectedDcId: string | null;
  canMutate: boolean;
  onSelect: (id: string | null) => void;
  onRename: (dc: DataCollectionShape) => void;
  onDelete: (dc: DataCollectionShape) => void;
  onManage?: (dc: DataCollectionShape) => void;
}> = ({
  pipelineDcIds,
  dataCollections,
  selectedDcId,
  canMutate,
  onSelect,
  onRename,
  onDelete,
  onManage,
}) => {
  const accent = useBrandAccents();
  const glass = useGlassPages();
  const [filter, setFilter] = useState('');
  const [sortKey, setSortKey] = useState<DcSortKey>('tag');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const onSort = (k: string) => {
    const key = k as DcSortKey;
    if (key === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase();
    // A geomap answers to both "table" and "geomap", the two words the Type
    // cell shows for it. Sorting on the same key keeps geomaps next to the
    // plain tables they are a kind of.
    const dcType = (dc: DataCollectionShape) => dcTypeSearchKey(dc);
    const list = dataCollections.filter(
      (dc) =>
        !q ||
        (dc.data_collection_tag || '').toLowerCase().includes(q) ||
        dcType(dc).includes(q),
    );
    const cmp = (a: DataCollectionShape, b: DataCollectionShape) => {
      switch (sortKey) {
        case 'type':
          return dcType(a).localeCompare(dcType(b));
        case 'size':
          return getDcSizeBytes(a) - getDcSizeBytes(b);
        case 'updated':
          return getDcLastAggregated(a).localeCompare(getDcLastAggregated(b));
        default:
          return (a.data_collection_tag || '').localeCompare(b.data_collection_tag || '');
      }
    };
    return [...list].sort((a, b) => (sortDir === 'asc' ? cmp(a, b) : -cmp(a, b)));
  }, [dataCollections, filter, sortKey, sortDir]);

  const guard = (fn: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation();
    fn();
  };

  if (dataCollections.length === 0) {
    return (
      <Text size="sm" c="dimmed" ta="center" py="md">
        No data collections defined for this project.
      </Text>
    );
  }

  return (
    <Stack gap="sm">
      <TextInput
        placeholder="Filter by name or type…"
        leftSection={<Icon icon="mdi:magnify" width={16} />}
        value={filter}
        onChange={(e) => setFilter(e.currentTarget.value)}
        size="xs"
      />
      <Table
        verticalSpacing="xs"
        striped
        highlightOnHover
        stickyHeader
        layout="fixed"
        miw={850}
      >
        <Table.Thead>
          <Table.Tr>
            <SortableTh
              label="Type"
              sortKey="type"
              activeKey={sortKey}
              dir={sortDir}
              onSort={onSort}
              w={190}
            />
            <SortableTh
              label="Data collection"
              sortKey="tag"
              activeKey={sortKey}
              dir={sortDir}
              onSort={onSort}
            />
            <Table.Th w={130}>Metatype</Table.Th>
            <SortableTh
              label="Size"
              sortKey="size"
              activeKey={sortKey}
              dir={sortDir}
              onSort={onSort}
              w={90}
            />
            <SortableTh
              label="Last aggregated"
              sortKey="updated"
              activeKey={sortKey}
              dir={sortDir}
              onSort={onSort}
              w={160}
            />
            <Table.Th w={100} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={6}>
                <Text size="sm" c="dimmed" ta="center" py="sm">
                  No data collections match “{filter}”.
                </Text>
              </Table.Td>
            </Table.Tr>
          )}
          {rows.map((dc) => {
            const id = (dc._id ?? dc.id) as string;
            const isSelected = id === selectedDcId;
            const type = (dc.config?.type as string | undefined) || 'unknown';
            const isMultiQC = type.toLowerCase() === 'multiqc';
            const sizeBytes = getDcSizeBytes(dc);
            // The two axes come from their own modules, so the row, the DC
            // viewer and the ingestion report name a collection the same way.
            const metatypeMeta = dcMetatypeMeta(dc, pipelineDcIds.has(id));
            return (
              <Table.Tr
                key={id}
                onClick={() => onSelect(isSelected ? null : id)}
                style={{
                  cursor: 'pointer',
                  background: isSelected
                    ? glass
                      ? 'var(--gl-accent-soft)'
                      : 'var(--mantine-color-teal-light)'
                    : undefined,
                }}
              >
                <Table.Td>
                  {/* Same component as the DC viewer's Type row: a type reads
                      identically wherever it is shown. Geomap sits beside the
                      type, never in place of it, since the collection is still
                      a table and still binds to every table component. */}
                  <DcTypeBadges dc={dc} size="xs" />
                </Table.Td>
                <Table.Td>
                  <Text fw={600} size="sm" style={{ wordBreak: 'break-word' }}>
                    {dc.data_collection_tag || id}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {metatypeMeta ? (
                    <DcMetatypeBadge dc={dc} fromPipeline={pipelineDcIds.has(id)} />
                  ) : (
                    <Text size="xs" c="dimmed">
                      —
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{sizeBytes > 0 ? formatBytes(sizeBytes) : '—'}</Text>
                </Table.Td>
                <Table.Td>
                  {/* MultiQC DCs aren't delta-aggregated, so "Never" would be
                      misleading — show n/a. Table DCs with no aggregation show
                      "Never" (genuinely not aggregated, e.g. not produced). */}
                  <Text size="xs" c={isMultiQC ? 'dimmed' : undefined}>
                    {isMultiQC ? '—' : getDcLastAggregated(dc)}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Group gap={2} wrap="nowrap" justify="flex-end">
                    {onManage && (
                      <ActionIcon
                        data-testid="manage-dc-btn"
                        variant="subtle"
                        color={glass ? 'gray' : accent.secondary}
                        size="sm"
                        disabled={!canMutate}
                        onClick={guard(() => onManage(dc))}
                        title={
                          canMutate
                            ? 'Manage data (append / replace / clear)'
                            : 'Owner permission required'
                        }
                      >
                        <Icon icon="mdi:database-cog-outline" width={16} />
                      </ActionIcon>
                    )}
                    <ActionIcon
                      variant="subtle"
                      color={glass ? 'gray' : 'blue'}
                      size="sm"
                      disabled={!canMutate}
                      onClick={guard(() => onRename(dc))}
                      title={canMutate ? 'Rename' : 'Owner permission required'}
                    >
                      <Icon icon="mdi:pencil" width={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      size="sm"
                      disabled={!canMutate}
                      onClick={guard(() => onDelete(dc))}
                      title={canMutate ? 'Delete' : 'Owner permission required'}
                    >
                      <Icon icon="mdi:delete" width={16} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Stack>
  );
};

const DataCollectionViewer: React.FC<{
  dc: DataCollectionShape;
  fromPipeline: boolean;
  allDataCollections: DataCollectionShape[];
  joins: Array<{
    dc1?: string;
    dc2?: string;
    dc_tag1?: string;
    dc_tag2?: string;
    on_columns?: string[];
  }>;
  links: DCLink[];
  projectId: string | null;
  canMutate: boolean;
  /** A link was edited from here: the page reloads its links. */
  onLinkSaved: () => void;
  /** Open the project's Runs tab; absent for a project without runs. */
  onShowRuns?: () => void;
  /** Select another collection (an input of this one). */
  onOpenDc?: (dcId: string) => void;
  /** Open on the rows (a table the URL asked for). */
  autoLoadPreview?: boolean;
}> = ({
  dc,
  fromPipeline,
  allDataCollections,
  joins,
  links,
  projectId,
  canMutate,
  onLinkSaved,
  onShowRuns,
  onOpenDc,
  autoLoadPreview = false,
}) => {
  const dcId = (dc._id ?? dc.id) as string;
  const type = (dc.config?.type as string | undefined) || 'unknown';
  const format =
    (dc.config?.dc_specific_properties?.format as string | undefined) || null;
  const isMultiQC = type.toLowerCase() === 'multiqc';
  const isTable = type.toLowerCase() === 'table';
  // A genomic_tracks DC is a track manifest stored as a Delta table: it previews
  // like a table, but isn't scored for advanced viz.
  const isTracks = type.toLowerCase() === 'genomic_tracks';
  const tracksProps = isTracks
    ? readTracksProps(dc.config?.dc_specific_properties as Record<string, unknown> | undefined)
    : null;
  const isCoordTable = dcHasCoordinates(dc);
  const isGeoJson = type.toLowerCase() === 'geojson';
  const isMapPreview = isCoordTable || isGeoJson;
  let previewBody: React.ReactNode = null;
  if (isMultiQC) previewBody = <MultiQCViewerPreview dcId={dcId} />;
  else if (isGeoJson) previewBody = <GeoJsonPreview dc={dc} />;
  else if (isCoordTable) previewBody = <CoordinatesMapPreview dc={dc} />;
  else if (type.toLowerCase() === 'image') previewBody = <ImagesPreview dc={dc} />;
  else if (type.toLowerCase() === 'phylogeny') previewBody = <TreePreview dcId={dcId} />;
  else if (isTracks) previewBody = <TracksPreview dcId={dcId} />;
  else if (type.toLowerCase() === 'jbrowse2') previewBody = <LegacyTracksNotice />;
  const deltaVersion = getDcDeltaVersion(dc);
  // Bumped when the table is edited, so the version history reloads.
  const [editTick, setEditTick] = useState(0);

  // Ranked viz-kind fit scores for this DC — surfaced in the viewer as
  // "compatible advanced visualizations" chips so users discover the affinity
  // post-creation. Only tables are scored; MultiQC has its own viewer.
  const [vizSuggestions, setVizSuggestions] =
    useState<VizSuggestionsResponse | null>(null);
  useEffect(() => {
    if (!isTable) {
      setVizSuggestions(null);
      return;
    }
    let cancelled = false;
    fetchVizSuggestions(dcId)
      .then((res) => {
        if (!cancelled) setVizSuggestions(res);
      })
      .catch(() => {
        if (!cancelled) setVizSuggestions(null);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId, isTable]);
  // Only surface strong matches as "compatible" chips — mirrors the builder's
  // recommended threshold (RECOMMENDED_SCORE in schemas.py).
  const detectedVizKinds = (vizSuggestions?.viz_kinds ?? []).filter((v) => v.score >= 0.8);

  const doc = dc as unknown as Record<string, unknown>;
  const lowerType = type.toLowerCase();
  const agg = lastAggregation(doc);
  const columns = dcColumns(doc);
  const origin = dcOrigin(doc);
  const sizeBytes = getDcSizeBytes(dc);
  const rows = typeof agg?.rows_total === 'number' ? agg.rows_total : null;
  const updated = formatTimestamp(agg?.aggregation_time, { utc: false });
  const description = typeof dc.description === 'string' && dc.description ? dc.description : null;

  const facts: Fact[] = [];
  const shownColumns = userColumns(columns);
  if (rows != null)
    facts.push({ label: 'Rows', icon: 'mdi:table-row', value: rows.toLocaleString(), testId: 'dc-fact-rows' });
  if (shownColumns.length > 0)
    facts.push({ label: 'Columns', icon: 'mdi:table-column', value: shownColumns.length, testId: 'dc-fact-columns' });
  if (sizeBytes > 0) facts.push({ label: 'Size', icon: 'mdi:harddisk', value: formatBytes(sizeBytes) });
  if (format) facts.push({ label: 'Format', icon: 'mdi:file-document-outline', value: format.toUpperCase() });
  if (tracksProps?.assembly) facts.push({ label: 'Assembly', icon: 'mdi:dna', value: tracksProps.assembly });
  if (deltaVersion != null) facts.push({ label: 'Version', icon: 'mdi:source-commit', value: `v${deltaVersion}` });
  // Real runs only: a one-file scan records a tag of its own, not a run.
  const runs = (Array.isArray(agg?.run_tags) ? (agg?.run_tags as unknown[]) : [])
    .filter((t): t is string => typeof t === 'string' && !t.endsWith('-single-file-scan'))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  // The runs themselves belong to the project: the tile opens its Runs tab.
  if (runs.length > 0)
    facts.push({
      label: runs.length === 1 ? 'Run' : 'Runs',
      icon: 'mdi:folder-play-outline',
      value: runs.length === 1 ? runs[0] : runs.length,
      hint: onShowRuns ? 'Open the project’s runs' : null,
      onClick: onShowRuns,
      testId: 'dc-fact-runs',
    });
  if (updated) facts.push({ label: 'Updated', icon: 'mdi:clock-outline', value: updated });
  if (origin) facts.push({ label: 'Source', icon: origin.icon, value: origin.label, hint: origin.location });

  const otherOf = (id?: string) => {
    const d = allDataCollections.find((x) => (x._id ?? x.id) === id);
    return {
      tag: d?.data_collection_tag || id || '?',
      type: ((d?.config?.type as string | undefined) || 'unknown').toLowerCase(),
    };
  };
  const linkRows: DcLinkRow[] = [
    ...links
      .filter((l) => l.source_dc_id === dcId || l.target_dc_id === dcId)
      .map((l, i): DcLinkRow => {
        const out = l.source_dc_id === dcId;
        return {
          key: `link-${i}`,
          linkId: l.id,
          kind: out ? 'out' : 'in',
          enabled: l.enabled !== false,
          here: out ? (l.source_column ?? null) : (l.link_config?.target_field ?? null),
          other: otherOf(out ? l.target_dc_id : l.source_dc_id),
          otherField: out ? (l.link_config?.target_field ?? null) : (l.source_column ?? null),
        };
      }),
    ...joins
      .filter((j) => j.dc1 === dcId || j.dc2 === dcId)
      .map((j, i): DcLinkRow => {
        const cols = j.on_columns?.join(', ') || '?';
        const other = otherOf(j.dc1 === dcId ? j.dc2 : j.dc1);
        const tag = j.dc1 === dcId ? j.dc_tag2 : j.dc_tag1;
        return {
          key: `join-${i}`,
          kind: 'join',
          enabled: true,
          here: cols,
          other: tag ? { ...other, tag } : other,
          otherField: cols,
        };
      }),
  ];

  // A derived collection says where it comes from: the recipe and its
  // inputs live in the ingestion report, read once it is selected.
  const isDerived = (dc.config as { source?: string } | undefined)?.source === 'transformed';
  const [lineage, setLineage] = useState<{
    entry: IngestionDataCollection;
    typeByTag: Record<string, string>;
    emptyTags: Set<string>;
  } | null>(null);
  useEffect(() => {
    setLineage(null);
    if (!isDerived || !projectId) return undefined;
    let cancelled = false;
    fetchIngestionReport(projectId)
      .then((report) => {
        const entry = report.data_collections.find((d) => d.data_collection_tag === dc.data_collection_tag);
        if (cancelled || !entry) return;
        setLineage({
          entry,
          typeByTag: Object.fromEntries(
            report.data_collections.map((d) => [d.data_collection_tag, (d.type ?? 'table').toLowerCase()]),
          ),
          emptyTags: new Set(
            report.data_collections
              .filter((d) => d.status === 'found_zero' || d.status === 'gated_out')
              .map((d) => d.data_collection_tag),
          ),
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [dcId, isDerived, projectId, dc.data_collection_tag]);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [editingLink, setEditingLink] = useState<DCLink | null>(null);
  const [resolvers, setResolvers] = useState<ResolverInfo[]>([]);
  const openLinkEdit = (id: string) => {
    const link = links.find((l) => l.id === id);
    if (!link || !projectId) return;
    // The modal falls back to its own list if this fails.
    if (resolvers.length === 0) listLinkResolvers(projectId).then(setResolvers).catch(() => undefined);
    setEditingLink(link);
  };

  const by = (agg?.aggregation_by as { email?: string } | undefined)?.email;
  const details: DetailItem[] = [
    { label: 'Collection id', value: dcId, mono: true },
    { label: 'Stored at', value: getDcStorageLocation(dc), mono: true },
    { label: 'Read from', value: scanSource(doc), mono: true },
    { label: origin?.label === 'Upload' ? 'Uploaded file' : 'Origin', value: origin?.location },
    { label: 'Added', value: origin?.addedAt },
    { label: 'Last ingestion by', value: by },
    { label: 'Write mode', value: typeof agg?.write_mode === 'string' ? agg.write_mode : null },
    { label: 'Ingestion', value: typeof agg?.aggregation_status === 'string' ? agg.aggregation_status : null },
    { label: 'Registered', value: formatTimestamp(dc.registration_time, { utc: false }) },
    { label: 'Optional in the pipeline', value: (dc as { optional?: boolean }).optional ? 'Yes' : null },
    ...typeDetails(doc, lowerType),
  ];

  const hasData = !isMultiQC && (isTable || isTracks);
  const [opened, setOpened] = useState<string[]>([]);
  // A newly selected collection opens on what it shows.
  useEffect(() => {
    const first = [
      ...(isDerived ? ['lineage'] : []),
      ...(previewBody ? ['preview'] : hasData ? ['data'] : []),
    ];
    // A table asked for by the URL opens on its rows.
    setOpened(autoLoadPreview && hasData && !first.includes('data') ? [...first, 'data'] : first);
    // Only on a change of collection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dcId]);
  const section = (value: string, icon: string, title: string, body: React.ReactNode, extra?: React.ReactNode) => (
    <Accordion.Item value={value} data-testid={`dc-section-${value}`}>
      <Accordion.Control icon={<Icon icon={icon} width={18} />}>
        <Group gap={8}>
          <Text fw={600} size="sm">
            {title}
          </Text>
          {extra}
        </Group>
      </Accordion.Control>
      <Accordion.Panel>{body}</Accordion.Panel>
    </Accordion.Item>
  );
  const count = (n: number) => (
    <Text size="xs" c="dimmed">
      {n}
    </Text>
  );

  return (
    <Paper withBorder radius="md" p="md" data-testid="dc-viewer">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap" gap="md">
          <Group gap="sm" align="flex-start" wrap="nowrap" style={{ minWidth: 0 }}>
            <DcTypeIcon type={lowerType} size={28} withTooltip={false} />
            <Stack gap={4} style={{ minWidth: 0 }}>
              <Group gap="xs" wrap="wrap">
                <Title order={4} style={{ wordBreak: 'break-word' }}>
                  {dc.data_collection_tag || dcId}
                </Title>
                {/* The same badges the manager row carries, in the same order. */}
                <DcTypeBadges dc={dc} />
                <DcMetatypeBadge dc={dc} fromPipeline={fromPipeline} />
              </Group>
              {description && (
                <Text size="sm" c="dimmed" lineClamp={2} title={description} data-testid="dc-viewer-description">
                  {description}
                </Text>
              )}
            </Stack>
          </Group>
          <CopyId id={dcId} />
        </Group>

        {/* A report's figures come from the report itself, not the collection. */}
        {isMultiQC ? <MultiQCSummaryCard dc={dc} bare /> : facts.length > 0 && <DcFacts facts={facts} />}

        {detectedVizKinds.length > 0 && (
          <DcSuggestedCharts kinds={detectedVizKinds.slice(0, 6).map((v) => v.viz_kind)} />
        )}

        <Accordion
          multiple
          variant="separated"
          radius="md"
          chevronPosition="right"
          value={opened}
          onChange={setOpened}
          styles={{ control: { paddingBlock: 2 }, content: { paddingTop: 0 } }}
        >
          {isDerived &&
            section(
              'lineage',
              'mdi:source-branch',
              'Lineage',
              lineage ? (
                <DerivedLineage
                  inputs={lineage.entry.recipe_inputs ?? []}
                  recipe={lineage.entry.recipe}
                  recipeUrl={lineage.entry.recipe_url}
                  summary={lineage.entry.recipe_summary}
                  description={lineage.entry.recipe_description}
                  result={{
                    tag: dc.data_collection_tag || dcId,
                    type: lowerType,
                    rows,
                    columns: shownColumns.length || null,
                    location: getDcStorageLocation(dc),
                  }}
                  typeByTag={lineage.typeByTag}
                  emptyInputs={lineage.emptyTags}
                  idByTag={Object.fromEntries(
                    allDataCollections.map((d) => [d.data_collection_tag ?? '', (d._id ?? d.id) as string]),
                  )}
                  onOpenDc={onOpenDc}
                />
              ) : (
                <Loader size="xs" />
              ),
            )}
          {previewBody &&
            section('preview', isMapPreview ? GEO_ICON : 'mdi:eye-outline', isMapPreview ? 'Map' : 'Preview', previewBody)}
          {hasData &&
            section(
              'data',
              'mdi:table',
              'Data',
              // Read the rows once the section is open, not on every selection.
              opened.includes('data') ? (
                <TableDataSection
                  key={dcId}
                  dcId={dcId}
                  checkEditable={isTable}
                  autoLoad
                  onEdited={() => setEditTick((n) => n + 1)}
                />
              ) : null,
              rows != null ? count(rows) : undefined,
            )}
          {isMultiQC &&
            section('samples', 'mdi:format-list-bulleted', 'Samples, modules and plots', <MultiQCReportsCard dcId={dcId} bare />)}
          {shownColumns.length > 0 &&
            section('columns', 'mdi:table-column', 'Columns', <DcColumnsTable columns={columns} rows={rows} />, count(shownColumns.length))}
          {linkRows.length > 0 &&
            section('links', 'mdi:link-variant', 'Links', <DcLinksTable
                rows={linkRows}
                inspecting={inspecting}
                onInspect={setInspecting}
                mapping={(id) =>
                  projectId ? <LinkMappingInspector projectId={projectId} linkId={id} collapsible={false} /> : null
                }
                onEdit={projectId ? openLinkEdit : undefined}
                canEdit={canMutate}
              />, count(linkRows.length))}
          {section('details', 'mdi:information-outline', 'Details', <DcDetailsGrid items={details} />)}
        </Accordion>

        {hasData && <DeltaVersionHistory key={`history-${dcId}-${editTick}`} dcId={dcId} />}
      </Stack>
      {projectId && (
        <LinkEditModal
          key={editingLink?.id ?? 'none'}
          opened={!!editingLink}
          projectId={projectId}
          link={editingLink}
          dataCollections={allDataCollections.map((d) => ({
            id: (d._id ?? d.id) as string,
            tag: d.data_collection_tag || ((d._id ?? d.id) as string),
            type: (d.config?.type as string | undefined) || 'unknown',
          }))}
          resolvers={resolvers}
          onClose={() => setEditingLink(null)}
          onSaved={() => {
            setEditingLink(null);
            onLinkSaved();
          }}
        />
      )}
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
const MultiQCSummaryCard: React.FC<{ dc: DataCollectionShape; bare?: boolean }> = ({ dc, bare = false }) => {
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

  if (bare) {
    if (loading || error || !hasReport) return null;
    const processed = formatTimestamp(r?.processed_at || r?.creation_date, { utc: false });
    const facts: Fact[] = [
      { label: 'Samples', icon: 'mdi:test-tube', value: sampleCount },
      { label: 'Modules', icon: 'mdi:puzzle-outline', value: moduleCount },
      { label: 'Plots', icon: 'mdi:chart-box-outline', value: plotCount },
    ];
    if (sizeBytes > 0) facts.push({ label: 'Size', icon: 'mdi:harddisk', value: formatBytes(sizeBytes) });
    if (r?.multiqc_version)
      facts.push({ label: 'MultiQC', icon: 'mdi:tag-outline', value: `v${r.multiqc_version}` });
    if (processed) facts.push({ label: 'Processed', icon: 'mdi:clock-outline', value: processed });
    return <DcFacts facts={facts} />;
  }

  return (
    <Card withBorder={!bare} radius="md" p={bare ? 0 : 'md'}>
      {!bare && (
        <Group gap="xs" mb="xs">
          <Icon icon="mdi:cloud" width={20} color="var(--mantine-color-blue-6)" />
          <Text fw={600}>Reports & S3 Storage Details</Text>
        </Group>
      )}
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
const MultiQCReportsCard: React.FC<{ dcId: string; bare?: boolean }> = ({ dcId, bare = false }) => {
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
    <Card withBorder={!bare} radius="md" p={bare ? 0 : 'md'}>
      <Group gap="xs" mb="xs" display={bare ? 'none' : undefined}>
        <DcTypeIcon type="multiqc" size={20} withTooltip={false} />
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

/** The table card's body. Owners and editors of a table a user added get one
 *  editable grid straight away, with the read-only view behind "Past versions".
 *  Everyone else gets the read-only view; someone who could edit the project is
 *  also told why this table cannot be edited. */
const TableDataSection: React.FC<{
  dcId: string;
  /** Only tables can be edited; other Delta-backed types skip the lookup. */
  checkEditable: boolean;
  autoLoad: boolean;
  onEdited: () => void;
}> = ({ dcId, checkEditable, autoLoad, onEdited }) => {
  const accent = useBrandAccents();
  const glass = useGlassPages();
  const [status, setStatus] = useState<TableEditStatus | null>(null);
  // Until the answer is in, neither grid: one would flash and give way to the other.
  const [statusKnown, setStatusKnown] = useState(!checkEditable);
  const [readOnlyView, setReadOnlyView] = useState(false);
  // Bumped after an edit: remounts the preview, which then reloads its rows.
  const [previewKey, setPreviewKey] = useState(0);

  useEffect(() => {
    setStatus(null);
    setStatusKnown(!checkEditable);
    if (!checkEditable) return;
    let cancelled = false;
    fetchTableEditStatus(dcId)
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch(() => {
        // No edit control rather than a broken one.
        if (!cancelled) setStatus(null);
      })
      .finally(() => {
        if (!cancelled) setStatusKnown(true);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId, checkEditable]);

  const editing = !!status?.can_edit && !readOnlyView;

  if (!statusKnown) {
    return (
      <Center py="md">
        <Loader size="sm" />
      </Center>
    );
  }

  return (
    <>
      {/* The viewer's "Data" section names it; editing shows only when allowed. */}
      {!editing && status?.can_edit && (
        <Group justify="flex-end" mb="xs">
          <Button
            size="xs"
            variant="light"
            color={glass ? undefined : accent.secondary}
            onClick={() => setReadOnlyView(false)}
            leftSection={<Icon icon="mdi:table-edit" width={16} />}
            data-testid="table-edit-button"
          >
            Edit table
          </Button>
        </Group>
      )}
      {editing ? (
        <TableEditor
          dcId={dcId}
          onSaved={() => {
            setPreviewKey((k) => k + 1);
            onEdited();
          }}
          onShowReadOnly={() => setReadOnlyView(true)}
        />
      ) : (
        <DataPreviewPanel
          key={`${dcId}-${previewKey}`}
          dcId={dcId}
          autoLoad={autoLoad || previewKey > 0 || readOnlyView}
        />
      )}
    </>
  );
};

const DataPreviewPanel: React.FC<{ dcId: string; autoLoad?: boolean }> = ({
  dcId,
  autoLoad = false,
}) => {
  const accent = useBrandAccents();
  const glass = useGlassPages();
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Delta versions available for time travel. Fetched alongside the first
  // preview rather than on mount: both reads touch the object store, so they
  // should only happen once the user has asked to see the data.
  const [versions, setVersions] = useState<number[]>([]);
  const [currentVersion, setCurrentVersion] = useState<number | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const { colorScheme } = useMantineColorScheme();

  const load = async (version: number | null) => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchDataCollectionPreview(dcId, 100, [], version);
      setPreview(result);
      setSelectedVersion(version);
    } catch (err) {
      setError((err as Error).message || 'Failed to load preview.');
    } finally {
      setLoading(false);
    }
  };

  const handleLoad = async () => {
    // The version list is a nicety; failing to get it must not stop the
    // preview, so it is fetched independently and its failure swallowed.
    void fetchDeltaHistory(dcId, 50)
      .then((history) => {
        setVersions(
          history.versions
            .map((entry) => entry.version)
            .filter((v): v is number => typeof v === 'number'),
        );
        setCurrentVersion(history.current_version);
      })
      .catch(() => undefined);
    await load(null);
  };

  useEffect(() => {
    if (autoLoad) void handleLoad();
    // Once, on mount: `autoLoad` only says whether the rows were asked for up front.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Pre-first-load states replace the whole panel. Once a preview exists the
  // panel keeps its chrome (version picker, staleness warning) while a
  // different version loads — otherwise the control you just used to switch
  // version vanishes underneath you.
  if (!preview) {
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
    return (
      <Button
        color={glass ? undefined : accent.secondary}
        variant="light"
        size="sm"
        onClick={handleLoad}
        leftSection={<Icon icon="mdi:table-eye" width={16} />}
      >
        Load Data
      </Button>
    );
  }

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

  // Only worth offering when there is somewhere to travel to. A table with a
  // single commit gets no picker rather than a picker with one entry.
  const showVersionPicker = versions.length >= 2;
  const isHistorical = selectedVersion != null && selectedVersion !== currentVersion;

  return (
    <Stack gap="xs">
      <Group gap="sm" justify="space-between" wrap="wrap">
        <Text size="xs" c="dimmed">
          Showing {rows.length} of {preview.total_rows ?? rows.length} rows ·{' '}
          {preview.total_columns ?? columns.length} columns
        </Text>
        {showVersionPicker && (
          <Group gap={6} wrap="nowrap">
            <Text size="xs" c="dimmed">
              At version
            </Text>
            <Select
              size="xs"
              w={140}
              disabled={loading}
              value={selectedVersion == null ? 'current' : String(selectedVersion)}
              onChange={(value) => {
                if (value == null) return;
                void load(value === 'current' ? null : Number(value));
              }}
              data={[
                { value: 'current', label: 'Current' },
                ...versions.map((v) => ({
                  value: String(v),
                  label: v === currentVersion ? `v${v} (current)` : `v${v}`,
                })),
              ]}
            />
          </Group>
        )}
      </Group>
      {isHistorical && (
        <Alert
          color="yellow"
          variant="light"
          icon={<Icon icon="mdi:history" width={16} />}
          py={6}
        >
          Viewing v{selectedVersion}: this is not the current data.
        </Alert>
      )}
      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}
      <Box
        className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
        style={{ height: 400, width: '100%', position: 'relative' }}
      >
        <LoadingOverlay visible={loading} zIndex={1} />
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
