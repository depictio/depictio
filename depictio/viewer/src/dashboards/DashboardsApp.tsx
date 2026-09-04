import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  AppShell,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { createDashboard, deleteDashboard as apiDeleteDashboard, duplicateDashboard as apiDuplicateDashboard, editDashboard as apiEditDashboard, exportDashboardJson, fetchProject, importDashboardJson, listDashboards, listProjects, useBrandAccents } from 'depictio-react-core';
import type {
  CreateDashboardInput,
  DashboardListEntry,
  EditDashboardInput,
  ImportDashboardOptions,
  ProjectListEntry,
} from 'depictio-react-core';
import { AI_COLOR, useAIHealth, useGenerationRun } from 'depictio-react-ai';
import type { GenerateDataCollection, GenerateJoinInfo } from 'depictio-react-ai';

import { useCurrentUser } from '../hooks/useCurrentUser';
import { useServerStatus } from '../hooks/useServerStatus';
import { AppSidebar } from '../chrome';
import DashboardsList from './DashboardsList';
import CreateDashboardModal from './CreateDashboardModal';
import type { CreateTab } from './CreateDashboardModal';
import EditDashboardModal from './EditDashboardModal';
import DeleteDashboardModal from './DeleteDashboardModal';
import { recordOpen as recordDashboardOpen } from './lib/dashboardRecents';
import { usePageTitle } from '../branding';

/** Separate storage key from the per-dashboard sidebar (`sidebar-collapsed`)
 *  so the management page can default to OPEN regardless of the user's
 *  in-dashboard preference. */
const SIDEBAR_KEY = 'dashboards-sidebar-collapsed';

function useDashboardsSidebar(): [boolean, () => void] {
  const [opened, setOpened] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem(SIDEBAR_KEY);
      if (raw == null) return true;
      return JSON.parse(raw) === false;
    } catch {
      return true;
    }
  });
  const toggle = useCallback(() => {
    setOpened((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_KEY, JSON.stringify(!next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);
  return [opened, toggle];
}

/** One id for the generation outcome, so a second run's notification replaces
 *  the previous one instead of stacking under it. */
const GENERATION_NOTIFICATION_ID = 'ai-generation-outcome';

/** The fields of a project-level `joins[]` entry the Generate picker needs.
 *  Same subset the builder reads in `builder/steps/StepData.tsx`; the
 *  endpoint returns more plumbing around them. */
interface ProjectJoin {
  result_dc_id?: string;
  left_dc: string;
  right_dc: string;
  on_columns: string[];
  how: string;
}

const DashboardsApp: React.FC = () => {
  const accent = useBrandAccents();
  const [dashboards, setDashboards] = useState<DashboardListEntry[]>([]);
  const [projects, setProjects] = useState<ProjectListEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [createOpened, { open: openCreate, close: closeCreate }] = useDisclosure(false);
  /** Which tab the dialog opens on: Create for the usual entry points,
   *  Generate when the user comes back to a run left in flight. */
  const [createTab, setCreateTab] = useState<CreateTab>('create');
  const [editTarget, setEditTarget] = useState<DashboardListEntry | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DashboardListEntry | null>(null);

  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, toggleDesktop] = useDashboardsSidebar();
  const { user, isPublicMode, isDemoMode, loading: authLoading } = useCurrentUser();
  // Public/demo deployments don't allow importing user-supplied dashboard
  // JSON — that would let an anonymous visitor write into shared projects.
  // Mirrors the Dash gate added in `layouts_toolbox.create_dashboard_modal`.
  // Fail closed while auth is loading so the import tab can't be reached on
  // the first frame before `/auth/me/optional` resolves.
  const importDisabled = authLoading || isPublicMode || isDemoMode;

  // "Generate with AI" tab of the New Dashboard dialog. The status flag
  // already folds `ai` in; the health probe says whether a server-side key
  // exists (otherwise the tab asks for one).
  const { features: serverFeatures } = useServerStatus();
  const aiGenerateEnabled = serverFeatures.ai_generate_dashboard;
  const aiHealth = useAIHealth(aiGenerateEnabled);
  const aiServerKeyAvailable = aiHealth?.server_key_configured === true;

  // A whole-dashboard generation takes minutes and lives in the AI store, not
  // in the dialog: it keeps streaming after the dialog is closed. This page
  // reads it to offer a way back into it, and to say how it ended.
  const generation = useGenerationRun();

  const openCreateOn = useCallback(
    (tab: CreateTab) => {
      setCreateTab(tab);
      openCreate();
    },
    [openCreate],
  );
  const openCreateNew = useCallback(() => openCreateOn('create'), [openCreateOn]);
  const openGenerateTab = useCallback(() => openCreateOn('generate'), [openCreateOn]);

  usePageTitle('Dashboards');

  useEffect(() => {
    setLoading(true);
    setLoadError(null);
    Promise.all([listDashboards(true), listProjects()])
      .then(([list, projs]) => {
        setDashboards(list);
        setProjects(projs);
      })
      .catch((err: Error) => {
        setLoadError(err.message || 'Failed to load dashboards');
      })
      .finally(() => setLoading(false));
  }, [refreshKey]);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  const currentUserEmail = user?.email ?? null;

  const handleCreate = useCallback(
    async (input: CreateDashboardInput) => {
      const newId = await createDashboard(input);
      notifications.show({
        color: 'teal',
        title: 'Dashboard created',
        message: `"${input.title}" is ready.`,
        autoClose: 2500,
      });
      closeCreate();
      refresh();
      return newId;
    },
    [closeCreate, refresh],
  );

  const handleImport = useCallback(
    async (jsonContent: Record<string, unknown>, opts: ImportDashboardOptions) => {
      const result = await importDashboardJson(jsonContent, opts);
      notifications.show({
        color: 'teal',
        title: 'Dashboard imported',
        message: result.message || 'Imported successfully.',
        autoClose: 2500,
      });
      closeCreate();
      refresh();
    },
    [closeCreate, refresh],
  );

  const handleEdit = useCallback(
    async (dashboardId: string, input: EditDashboardInput) => {
      await apiEditDashboard(dashboardId, input);
      notifications.show({
        color: 'teal',
        title: 'Dashboard updated',
        message: 'Changes saved.',
        autoClose: 2000,
      });
      setEditTarget(null);
      refresh();
    },
    [refresh],
  );

  const handleDelete = useCallback(
    async (dashboardId: string) => {
      await apiDeleteDashboard(dashboardId);
      notifications.show({
        color: 'teal',
        title: 'Dashboard deleted',
        message: 'Dashboard removed.',
        autoClose: 2000,
      });
      setDeleteTarget(null);
      refresh();
    },
    [refresh],
  );

  const handleDuplicate = useCallback(
    async (dashboard: DashboardListEntry) => {
      try {
        await apiDuplicateDashboard(dashboard.dashboard_id);
        notifications.show({
          color: 'teal',
          title: 'Dashboard duplicated',
          message: `"${dashboard.title} (copy)" is ready.`,
          autoClose: 2500,
        });
        refresh();
      } catch (err) {
        notifications.show({
          color: 'red',
          title: 'Duplicate failed',
          message: (err as Error).message,
        });
      }
    },
    [refresh],
  );

  /** Wrap navigation so opening a dashboard from any view records it in the
   *  Recently opened pile. localStorage-only — see lib/dashboardRecents.ts. */
  const handleView = useCallback((dashboard: DashboardListEntry) => {
    recordDashboardOpen(String(dashboard.dashboard_id));
    window.location.assign(`/dashboard/${dashboard.dashboard_id}`);
  }, []);

  /** Collections of one project for the Generate tab: every DC of every
   *  workflow, typed so the panel can keep the tables. DC tags are unique per
   *  workflow only, so they carry the workflow tag when the project has
   *  several. Enrichment (delta locations) is skipped: only names are needed.
   *  Join results are marked as such so the picker can tell a joined
   *  collection from a native one, the way the builder's data step does. */
  const loadProjectCollections = useCallback(
    async (projectId: string): Promise<{ dataCollections: GenerateDataCollection[] }> => {
      const { project } = await fetchProject(projectId, { skipEnrichment: true });
      const workflows = project.workflows ?? [];
      const qualify = workflows.length > 1;
      // Keyed by `result_dc_id`, which is the joined collection's own `_id`.
      const joinsRaw = (project as { joins?: unknown }).joins;
      const joinByDcId = new Map<string, GenerateJoinInfo>();
      if (Array.isArray(joinsRaw)) {
        for (const j of joinsRaw as ProjectJoin[]) {
          if (!j?.result_dc_id) continue;
          joinByDcId.set(j.result_dc_id, {
            leftDc: j.left_dc,
            rightDc: j.right_dc,
            onColumns: Array.isArray(j.on_columns) ? j.on_columns : [],
            how: j.how || 'inner',
          });
        }
      }
      const dataCollections: GenerateDataCollection[] = [];
      for (const wf of workflows) {
        for (const dc of wf.data_collections ?? []) {
          // Some response paths stamp `id` instead of `_id`.
          const id = String(dc._id ?? dc.id ?? '');
          if (!id) continue;
          const tag = dc.data_collection_tag ?? id;
          const join = joinByDcId.get(id);
          dataCollections.push({
            id,
            tag: qualify && wf.workflow_tag ? `${wf.workflow_tag}/${tag}` : tag,
            type: String(dc.config?.type ?? ''),
            ...(join ? { join } : {}),
          });
        }
      }
      return { dataCollections };
    },
    [],
  );

  /** The Generate tab's hand-off: the draft opens in the editor, where the AI
   *  draft banner carries the promote / discard decision. Same full-page
   *  navigation as every other editor entry (plain regex routing, no router). */
  const handleOpenGenerated = useCallback((dashboardId: string) => {
    recordDashboardOpen(dashboardId);
    window.location.assign(`/dashboard-edit/${dashboardId}`);
  }, []);

  /** Runs already announced, so a re-render never repeats one. */
  const announcedRun = useRef<string | null>(null);

  // A run can reach its end with nobody watching it. Say so once, and only
  // when the dialog is closed: the panel spells out the same outcome, draft
  // and failure alike, and does not need repeating over the top of itself.
  useEffect(() => {
    const { id, pending, dashboard, error } = generation;
    // A planning call that stopped for its verdict has not ended; the header
    // indicator is what leads back to it.
    if (!id || pending || (!dashboard && !error)) return;
    if (announcedRun.current === id) return;
    announcedRun.current = id;
    if (createOpened) return;
    if (dashboard) {
      notifications.show({
        id: GENERATION_NOTIFICATION_ID,
        color: 'teal',
        title: 'Dashboard draft ready',
        message: (
          <Stack gap="xs" data-testid="generation-ready-notification">
            <Text size="sm">&quot;{dashboard.title}&quot; is saved as an AI draft.</Text>
            <Button
              size="xs"
              variant="light"
              color={AI_COLOR}
              radius="md"
              leftSection={<Icon icon="mdi:open-in-new" width={14} />}
              onClick={() => {
                notifications.hide(GENERATION_NOTIFICATION_ID);
                handleOpenGenerated(dashboard.dashboard_id);
              }}
              data-testid="generation-ready-open"
            >
              Open in editor
            </Button>
          </Stack>
        ),
        // Long enough to be read and acted on, since it carries the only
        // hand-off into the draft the user has not seen yet.
        autoClose: 12000,
      });
      return;
    }
    notifications.show({
      id: GENERATION_NOTIFICATION_ID,
      color: 'red',
      title: 'Generation failed',
      message: (
        <Text size="sm" data-testid="generation-failed-notification">
          {error}
        </Text>
      ),
    });
  }, [generation, createOpened, handleOpenGenerated]);

  const handleExport = useCallback(async (dashboard: DashboardListEntry) => {
    try {
      const payload = await exportDashboardJson(dashboard.dashboard_id);
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const safeTitle = (dashboard.title || dashboard.dashboard_id).replace(
        /[^a-zA-Z0-9._-]+/g,
        '_',
      );
      const a = document.createElement('a');
      a.href = url;
      a.download = `${safeTitle}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Export failed',
        message: (err as Error).message,
      });
    }
  }, []);

  const handleBulkExport = useCallback(
    async (targets: DashboardListEntry[]) => {
      // Sequential to keep download prompts in order; each call yields a
      // separate file, matching the per-row Export JSON action.
      for (const d of targets) {
        // eslint-disable-next-line no-await-in-loop
        await handleExport(d);
      }
    },
    [handleExport],
  );

  /** Wiring for the Generate tab, memoised: the dialog keys effects on it,
   *  and this page now re-renders as a run streams. */
  const generateTab = useMemo(
    () =>
      aiGenerateEnabled
        ? {
            loadProject: loadProjectCollections,
            onOpen: handleOpenGenerated,
            serverKeyAvailable: aiServerKeyAvailable,
            // Same gate as Import: generation writes a dashboard into a
            // shared project, which an anonymous visitor must not do.
            disabled: importDisabled,
          }
        : undefined,
    [
      aiGenerateEnabled,
      loadProjectCollections,
      handleOpenGenerated,
      aiServerKeyAvailable,
      importDisabled,
    ],
  );

  /** What the header indicator says a run is doing: the stage the stream last
   *  named, or the verdict a plan is waiting for, and the project either way. */
  const stageText = generation.pending
    ? `Generating: ${generation.status || 'starting'}`
    : 'Plan ready for review';
  const generationLabel = generation.projectName
    ? `${stageText} · ${generation.projectName}`
    : stageText;

  const handleBulkDelete = useCallback(
    (targets: DashboardListEntry[]) => {
      if (targets.length === 0) return;
      const first = targets[0];
      // For >1 we still go through the single-row delete modal one at a time
      // to keep the confirmation flow consistent. The user picks them off one
      // at a time after bulk-selecting in the table.
      // (A dedicated bulk-delete modal can come later if the workflow demands it.)
      setDeleteTarget(first);
    },
    [],
  );

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
              icon="material-symbols:dashboard"
              width={22}
              color={`var(--mantine-color-${accent.tertiary}-6)`}
            />
            <Title order={3} c={accent.tertiary}>
              Dashboards
            </Title>
          </Group>
          <Group gap="sm" wrap="nowrap">
            {/* The way back into a run the user walked away from. It sits
                beside the action that started it rather than floating over
                the list, and goes when the run does. Nothing to come back to
                while the dialog holding the run is open. */}
            {generation.active && !createOpened && (
              <Button
                variant="light"
                color={AI_COLOR}
                size="md"
                radius="md"
                maw={340}
                onClick={openGenerateTab}
                leftSection={
                  generation.pending ? (
                    <Loader size="xs" color={AI_COLOR} />
                  ) : (
                    <Icon icon="mdi:clipboard-check-outline" width={18} />
                  )
                }
                data-testid="generation-running-indicator"
              >
                <Text size="sm" fw={500} truncate>
                  {generationLabel}
                </Text>
              </Button>
            )}
            <Button
              color={accent.tertiary}
              variant="filled"
              size="md"
              onClick={openCreateNew}
              data-testid="new-dashboard-btn"
              style={{ fontFamily: 'Virgil' }}
              data-tour-id="dashboards-create"
            >
              + New Dashboard
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="dashboards" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Box px="lg" py="md">
          {loading ? (
            <Center mih={200}>
              <Loader />
            </Center>
          ) : loadError ? (
            <Center mih={200}>
              <Stack align="center" gap="xs">
                <Icon
                  icon="mdi:alert-circle"
                  width={32}
                  color="var(--mantine-color-red-6)"
                />
                <Text c="red">{loadError}</Text>
                <Button variant="light" onClick={refresh}>
                  Try again
                </Button>
              </Stack>
            </Center>
          ) : (
            <DashboardsList
              dashboards={dashboards}
              projects={projects}
              currentUserEmail={currentUserEmail}
              onView={handleView}
              onEdit={(d) => setEditTarget(d)}
              onDelete={(d) => setDeleteTarget(d)}
              onDuplicate={handleDuplicate}
              onExport={handleExport}
              onCreateClick={openCreateNew}
              onBulkExport={handleBulkExport}
              onBulkDelete={handleBulkDelete}
            />
          )}
        </Box>
      </AppShell.Main>

      <CreateDashboardModal
        opened={createOpened}
        projects={projects}
        existingTitles={dashboards.map((d) => d.title || '').filter(Boolean)}
        onClose={closeCreate}
        onCreate={handleCreate}
        onImport={handleImport}
        disableImport={importDisabled}
        generate={generateTab}
        initialTab={createTab}
      />
      <EditDashboardModal
        opened={Boolean(editTarget)}
        dashboard={editTarget}
        onClose={() => setEditTarget(null)}
        onSubmit={handleEdit}
      />
      <DeleteDashboardModal
        opened={Boolean(deleteTarget)}
        dashboard={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </AppShell>
  );
};

export default DashboardsApp;
