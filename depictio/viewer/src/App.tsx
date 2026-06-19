import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import {
  ActionIcon,
  AppShell,
  Button,
  Center,
  Group,
  Text,
  Loader,
  Anchor,
  Stack,
  Title,
  Paper,
  Box,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import {
  fetchDashboard,
  fetchAllDashboards,
  bulkComputeCards,
  AvailableFilterValuesProvider,
  ComponentRenderer,
  DashboardGrid,
  InteractiveGroupCard,
  TopPanel,
  groupInteractiveComponents,
  mergeFiltersBySource,
  enrichFilterWithDcId,
  hasSelectionFilters,
  useDataCollectionUpdates,
  RealtimeIndicator,
  useRealtimeJournal,
  fetchProjectFromDashboard,
  fetchIngestionHealth,
} from 'depictio-react-core';
import type {
  DashboardData,
  DashboardPermissions,
  DashboardSummary,
  InteractiveFilter,
  RealtimeMode,
  IngestionSummary,
} from 'depictio-react-core';
import { parseTemplateOrigin } from './projects/template';

/** localStorage key for the dismissed ingestion banner, scoped per project so
 *  the dismissal sticks across the dashboard's sibling tabs. */
const ingestionBannerKey = (projectId: string) =>
  `depictio:ingestion-banner-dismissed:${projectId}`;
import { notifications } from '@mantine/notifications';
import { Header, Sidebar, SettingsDrawer } from './chrome';
import { useSidebarOpen } from './hooks/useSidebarOpen';
import { useCurrentUser } from './hooks/useCurrentUser';
import { isDashboardOwner } from './lib/dashboardOwnership';
import NotesFooter from './components/NotesFooter';

/**
 * Top-level SPA. Layout:
 *
 *   ┌──────── Header (65px) ─────────────────┐
 *   │ Burger | tab-icon | Title  | PoweredBy | Edit | Reset | Settings │
 *   ├──────────┬─────────────────────────────┤
 *   │ Sidebar  │ Main: 1/3 + 2/3             │
 *   │ (tabs    │ ┌─────┬───────────────────┐ │
 *   │  theme   │ │ 1/3 │  Cards row        │ │
 *   │  status  │ │ inter│──────────────────│ │
 *   │  profile)│ │ active│ figures/tables  │ │
 *
 * The chrome (Header + Sidebar + per-component action icons) mirrors the Dash
 * viewer's UI for cross-app parity.
 */
const App: React.FC = () => {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [allDashboards, setAllDashboards] = useState<DashboardSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<InteractiveFilter[]>([]);
  const [cardValues, setCardValues] = useState<Record<string, unknown>>({});
  const [cardSecondaryValues, setCardSecondaryValues] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [cardsLoading, setCardsLoading] = useState(false);
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  // Desktop state is persisted across tab/page navigations via the same
  // `sidebar-collapsed` localStorage key the Dash app writes.
  const [desktopOpened, toggleDesktop] = useSidebarOpen();
  const [settingsOpened, { open: openSettings, close: closeSettings }] = useDisclosure(false);
  const { user: currentUser } = useCurrentUser();
  const isOwner = isDashboardOwner(dashboard, currentUser?.email ?? null);

  const dashboardId = extractDashboardId();
  const bulkCtrl = useRef<AbortController | null>(null);

  // Ingestion-health banner: for template-derived dashboards, surface a
  // prominent prompt when a required data collection was not found during
  // ingestion (or things came in partial). Best-effort — never blocks the view.
  const [ingestionHealth, setIngestionHealth] = useState<IngestionSummary | null>(null);
  const [ingestionProjectId, setIngestionProjectId] = useState<string | null>(null);
  const [ingestionBannerDismissed, setIngestionBannerDismissed] = useState(false);

  // Keep the browser tab title in sync with the dashboard name.
  useEffect(() => {
    if (dashboard?.title) {
      document.title = `Depictio — ${dashboard.title}`;
    } else if (dashboardId) {
      document.title = `Depictio — ${dashboardId}`;
    }
  }, [dashboard?.title, dashboardId]);

  // Fetch dashboard + tab list in parallel
  useEffect(() => {
    if (!dashboardId) {
      setError('No dashboard ID in URL. Expected /dashboard/<id>.');
      setLoading(false);
      return;
    }
    Promise.all([fetchDashboard(dashboardId), fetchAllDashboards()])
      .then(([dash, all]) => {
        setDashboard(dash);
        setAllDashboards(all);
      })
      .catch((err) => {
        setError(`Failed to load dashboard: ${err.message || err}`);
      })
      .finally(() => setLoading(false));
  }, [dashboardId]);

  // Resolve the parent project and its ingestion health (template projects only).
  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    (async () => {
      try {
        const { project } = await fetchProjectFromDashboard(dashboardId);
        if (cancelled || !project) return;
        // Only template-instantiated projects have an expected-DC manifest worth
        // reporting against; skip the banner entirely otherwise.
        if (!parseTemplateOrigin((project as { template_origin?: unknown }).template_origin)) {
          return;
        }
        const pid = String(project._id || '');
        if (!pid) return;
        const health = await fetchIngestionHealth(pid);
        if (cancelled) return;
        setIngestionProjectId(pid);
        setIngestionHealth(health);
        // Dismissal is remembered per project so it stays hidden across the
        // dashboard's sibling tabs (which share one project_id).
        let dismissed = false;
        try {
          dismissed = localStorage.getItem(ingestionBannerKey(pid)) === '1';
        } catch {
          /* private mode / disabled storage — treat as not dismissed */
        }
        setIngestionBannerDismissed(dismissed);
      } catch {
        // Banner is non-critical: swallow lookup/permission errors silently.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [dashboardId]);

  // Bumping a counter is the only signal effects can key off — every
  // data-fetching effect uses ``stableFilterKey(filters)`` / ``JSON.stringify(filters)``
  // as its dep, so a new ARRAY reference with identical contents is a no-op.
  // ``refreshTick`` is wired into bulk-compute here and into every per-component
  // fetch via ``DashboardGrid`` → ``ComponentRenderer``.
  const [refreshTick, setRefreshTick] = useState(0);

  // Bulk-compute card values whenever filters change
  useEffect(() => {
    if (!dashboard || !dashboardId) return;
    const cardIds = (dashboard.stored_metadata || [])
      .filter((m) => m.component_type === 'card')
      .map((m) => m.index);
    if (cardIds.length === 0) return;

    const timer = setTimeout(() => {
      setCardsLoading(true);
      // Keep the previous card values mounted while the new bulk-compute
      // round-trip is in flight. ``cardsLoading`` is what CardRenderer
      // already consults to dim the value — clearing the values here would
      // snap every card back to ``…`` on every keystroke / drag step.
      if (bulkCtrl.current) bulkCtrl.current.abort();
      bulkCtrl.current = new AbortController();
      bulkComputeCards(dashboardId, filters, cardIds)
        .then((res) => {
          setCardValues(res.values);
          setCardSecondaryValues(res.secondary_values || {});
        })
        .catch((err) => {
          if (err?.name !== 'AbortError') console.warn('[App] bulk-compute failed:', err);
        })
        .finally(() => setCardsLoading(false));
    }, 250);
    return () => clearTimeout(timer);
  }, [dashboard, dashboardId, stableFilterKey(filters), refreshTick]);

  const handleFilterChange = useCallback(
    (update: InteractiveFilter) => {
      const enriched = enrichFilterWithDcId(update, dashboard?.stored_metadata);
      // Dedupe by (index, source) so chart selections coexist with the same
      // component's other filters. Mirrors mergeFiltersBySource in
      // packages/depictio-react-core/src/selection.ts.
      setFilters((prev) => mergeFiltersBySource(prev, enriched));
    },
    [dashboard],
  );

  const handleResetAllFilters = useCallback(() => setFilters([]), []);

  // ---- Realtime: WebSocket subscription + UI toggle -------------------------
  // Mode toggle persisted to localStorage so the user's choice survives
  // reloads. Defaults to ``auto`` (silent re-fetch on update) — users who
  // prefer notification-then-click can opt out via RealtimeIndicator.
  const [realtimeMode, setRealtimeMode] = useState<RealtimeMode>(() => {
    try {
      const v = localStorage.getItem('depictio.realtime.mode');
      return v === 'manual' ? 'manual' : 'auto';
    } catch {
      return 'auto';
    }
  });
  const [realtimePaused, setRealtimePaused] = useState(false);
  const persistMode = useCallback((next: RealtimeMode) => {
    setRealtimeMode(next);
    try {
      localStorage.setItem('depictio.realtime.mode', next);
    } catch {
      // ignore quota / private mode
    }
  }, []);

  // Persistent log of captured WS events (visible in the RealtimeIndicator
  // dropdown). Survives page reload via localStorage. Cleared on demand via
  // the "Reset" button on the dropdown.
  const [journal, appendJournal, clearJournal] = useRealtimeJournal(50);

  const triggerRefresh = useCallback(() => {
    setRefreshTick((t) => t + 1);
  }, []);

  const onRealtimeUpdate = useCallback(
    (
      event: {
        event_type: string;
        data_collection_id?: string;
        dashboard_id?: string;
        payload?: Record<string, unknown>;
      },
      auto: boolean,
    ) => {
      // Always log the event — auto vs. manual only changes the visual UX,
      // not whether the user wants to see it in the journal afterwards.
      const payload = event.payload || {};
      const op = payload.operation as string | undefined;
      const tag = payload.data_collection_tag as string | undefined;
      const summary = [
        op && `op=${op}`,
        tag && `tag=${tag}`,
      ]
        .filter(Boolean)
        .join(' ') || event.event_type;
      appendJournal({
        eventType: event.event_type,
        dataCollectionId: event.data_collection_id,
        dashboardId: event.dashboard_id,
        summary,
        payload,
      });
      if (auto) {
        triggerRefresh();
        return;
      }
      notifications.show({
        title: 'Data updated',
        message: 'A linked data collection just changed. Click to refresh.',
        color: 'blue',
        autoClose: 8000,
        onClick: () => triggerRefresh(),
      });
    },
    [triggerRefresh, appendJournal],
  );

  // Only subscribe + render the indicator when the dashboard's project has
  // ``realtime.enabled === true`` in its YAML. Projects without that flag
  // never see live-update UI — keeps the chrome quiet for static dashboards.
  const realtimeEnabled = Boolean(dashboard?.project_realtime?.enabled);
  const realtime = useDataCollectionUpdates(dashboardId, {
    enabled: realtimeEnabled && Boolean(dashboardId),
    mode: realtimeMode,
    paused: realtimePaused,
    onUpdate: onRealtimeUpdate,
  });

  // Group tabs: parent dashboard + all its child tabs.
  const tabSiblings = useMemo(() => {
    if (!dashboard || !allDashboards.length) return [] as DashboardSummary[];
    const dashId = String(dashboard.dashboard_id || dashboard._id || dashboardId || '');
    const current = allDashboards.find((d) => d.dashboard_id === dashId);
    const parentId = current?.parent_dashboard_id || dashId;
    const family = allDashboards.filter(
      (d) => d.dashboard_id === parentId || d.parent_dashboard_id === parentId,
    );
    return family.sort((a, b) => {
      // Parent first, then children alphabetically by title
      if (!a.parent_dashboard_id && b.parent_dashboard_id) return -1;
      if (a.parent_dashboard_id && !b.parent_dashboard_id) return 1;
      return (a.title || '').localeCompare(b.title || '');
    });
  }, [dashboard, allDashboards, dashboardId]);

  const activeTab = useMemo(
    () => tabSiblings.find((d) => d.dashboard_id === dashboardId) || null,
    [tabSiblings, dashboardId],
  );
  const parentTab = useMemo(
    () => tabSiblings.find((d) => !d.parent_dashboard_id) || null,
    [tabSiblings],
  );

  const interactiveComponents = useMemo(
    () => (dashboard?.stored_metadata || []).filter((m) => m.component_type === 'interactive'),
    [dashboard],
  );
  const topComponents = useMemo(
    () => interactiveComponents.filter((m) => m.placement === 'top'),
    [interactiveComponents],
  );
  const leftComponents = useMemo(
    () => interactiveComponents.filter((m) => m.placement !== 'top'),
    [interactiveComponents],
  );
  const leftGroups = useMemo(
    () => groupInteractiveComponents(leftComponents),
    [leftComponents],
  );
  const cardComponents = useMemo(
    () => (dashboard?.stored_metadata || []).filter((m) => m.component_type === 'card'),
    [dashboard],
  );
  const otherComponents = useMemo(
    () =>
      (dashboard?.stored_metadata || []).filter(
        (m) => m.component_type !== 'card' && m.component_type !== 'interactive',
      ),
    [dashboard],
  );

  // View mode uses the SAME DashboardGrid + saved-layout source as the editor;
  // only `editMode`/`isDraggable`/`isResizable` differ. Identical visual output
  // for any given dashboard, regardless of which URL the user lands on.
  const rightComponents = useMemo(
    () => [...cardComponents, ...otherComponents],
    [cardComponents, otherComponents],
  );

  return (
    <AvailableFilterValuesProvider
      dashboardMetadata={dashboard?.stored_metadata}
      projectId={dashboard?.project_id}
    >
      <AppShell
      header={{ height: 50 }}
      navbar={{
        width: 250,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      padding={0}
      transitionDuration={300}
      transitionTimingFunction="ease"
    >
      <AppShell.Header data-tour-id="header-title">
        <Header
          dashboardId={dashboardId}
          dashboard={dashboard}
          activeTab={activeTab}
          parentTab={parentTab}
          mobileOpened={mobileOpened}
          desktopOpened={desktopOpened}
          onToggleMobile={toggleMobile}
          onToggleDesktop={toggleDesktop}
          onOpenSettings={openSettings}
          cardsLoading={cardsLoading}
          isOwner={isOwner}
          rightExtras={
            <>
              {realtimeEnabled && (
                <span data-tour-id="realtime-indicator" style={{ display: 'inline-flex' }}>
                  <RealtimeIndicator
                    status={realtime.status}
                    mode={realtimeMode}
                    paused={realtimePaused}
                    pendingUpdate={realtime.pendingUpdate}
                    onModeChange={persistMode}
                    onPausedChange={setRealtimePaused}
                    onAcknowledgePending={() => {
                      realtime.acknowledgePending();
                      triggerRefresh();
                    }}
                    journal={journal}
                    onClearJournal={clearJournal}
                  />
                </span>
              )}
            </>
          }
        />
      </AppShell.Header>

      <AppShell.Navbar p="md" data-tour-id="sidebar">
        <Sidebar tabs={tabSiblings} activeId={dashboardId} />
      </AppShell.Navbar>

      <AppShell.Main style={{ height: 'calc(100vh - 50px)' }}>
        {ingestionHealth &&
          ingestionProjectId &&
          !ingestionBannerDismissed &&
          (ingestionHealth.health === 'missing_required' ||
            ingestionHealth.health === 'partial') &&
          (() => {
            const critical = ingestionHealth.health === 'missing_required';
            const color = critical ? 'red' : 'yellow';
            const dismiss = () => {
              setIngestionBannerDismissed(true);
              try {
                localStorage.setItem(ingestionBannerKey(ingestionProjectId), '1');
              } catch {
                /* storage unavailable — dismissal is in-memory only this session */
              }
            };
            // Compact one-line bar: softer for "partial", stronger for the
            // critical "missing required" case. Uses Mantine color tokens so it
            // tracks the theme (no hardcoded literals).
            return (
              <Paper
                m="sm"
                py={6}
                px="sm"
                radius="md"
                withBorder
                style={{ backgroundColor: `var(--mantine-color-${color}-light)` }}
              >
                <Group justify="space-between" align="center" wrap="nowrap" gap="sm">
                  <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
                    <Icon
                      icon={critical ? 'mdi:alert-octagon' : 'mdi:alert'}
                      width={18}
                      color={`var(--mantine-color-${color}-7)`}
                    />
                    <Text size="sm" fw={500} truncate>
                      {critical
                        ? `${ingestionHealth.required_missing} required data collection(s) were not ingested.`
                        : 'Ingestion partial — some optional data collections are missing.'}
                    </Text>
                  </Group>
                  <Group gap={8} wrap="nowrap" style={{ flexShrink: 0 }}>
                    <Button
                      component="a"
                      href={`/projects/${ingestionProjectId}#ingestion`}
                      size="xs"
                      radius="xl"
                      variant="white"
                      color={color}
                      leftSection={
                        <Icon icon="mdi:clipboard-text-search-outline" width={15} />
                      }
                      rightSection={<Icon icon="mdi:arrow-right" width={15} />}
                    >
                      View report
                    </Button>
                    <ActionIcon
                      variant="filled"
                      color={color}
                      radius="xl"
                      size="md"
                      onClick={dismiss}
                      aria-label="Dismiss"
                    >
                      <Icon icon="mdi:close" width={16} />
                    </ActionIcon>
                  </Group>
                </Group>
              </Paper>
            );
          })()}
        {loading && (
          <Group p="lg">
            <Loader size="sm" />
            <Text>Loading dashboard…</Text>
          </Group>
        )}
        {error && <Text c="red" p="lg">{error}</Text>}
        {dashboard && !loading && !error && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '20vw 1fr',
              height: '100%',
              width: '100%',
              gap: 4,
              overflow: 'hidden',
            }}
          >
            <Box
              px={4}
              py={4}
              style={{
                height: '100%',
                minWidth: 0,
                overflowY: 'auto',
                overflowX: 'hidden',
              }}
            >
              <Paper
                p="md"
                withBorder
                radius="md"
                style={{ height: '100%' }}
                data-tour-id="filter-panel"
              >
                <Group justify="space-between" align="center" mb="sm" wrap="nowrap">
                  <Title order={5}>Filters</Title>
                  <Button
                    leftSection={<Icon icon="bx:reset" width={12} />}
                    color="orange"
                    variant="filled"
                    size="xs"
                    onClick={handleResetAllFilters}
                    disabled={filters.length === 0}
                  >
                    Reset all
                  </Button>
                </Group>
                <Stack gap="sm">
                  {leftComponents.length === 0 && (
                    <Text size="sm" c="dimmed">No interactive components.</Text>
                  )}
                  {leftGroups.map((g) =>
                    g.groupName ? (
                      <InteractiveGroupCard
                        key={g.key}
                        groupName={g.groupName}
                        members={g.members}
                        filters={filters}
                        onFilterChange={handleFilterChange}
                      />
                    ) : (
                      <ComponentRenderer
                        key={g.key}
                        metadata={g.members[0]}
                        filters={filters}
                        onFilterChange={handleFilterChange}
                      />
                    ),
                  )}
                  {hasSelectionFilters(filters) && (
                    <Anchor
                      component="button"
                      onClick={() =>
                        setFilters((prev) => prev.filter((f) => f.source === undefined))
                      }
                      size="xs"
                      mt="xs"
                    >
                      Clear chart selections
                    </Anchor>
                  )}
                </Stack>
              </Paper>
            </Box>
            <Box
              px={4}
              py={4}
              style={{
                height: '100%',
                minWidth: 0,
                overflowY: 'auto',
                overflowX: 'hidden',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {topComponents.length > 0 && (
                <TopPanel
                  components={topComponents}
                  filters={filters}
                  onFilterChange={handleFilterChange}
                />
              )}
              <Box style={{ flex: 1, minHeight: 0 }}>
                {rightComponents.length === 0 ? (
                  <Center style={{ height: '100%', minHeight: 320 }}>
                    <Stack align="center" gap="md" maw={420}>
                      <Box
                        style={{
                          width: 72,
                          height: 72,
                          borderRadius: '50%',
                          background: 'var(--mantine-color-gray-1)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <Icon icon="mdi:view-dashboard-outline" width={36} color="var(--mantine-color-gray-5)" />
                      </Box>
                      <Stack gap={4} align="center">
                        <Title order={4} fw={700} ta="center">
                          This dashboard is empty
                        </Title>
                        <Text size="sm" c="dimmed" ta="center">
                          No components have been added yet.
                          {isOwner && ' Start editing to add visualizations, tables, and more.'}
                        </Text>
                      </Stack>
                      {isOwner && (
                        <Button
                          component="a"
                          href={`/dashboard-beta-edit/${dashboardId}`}
                          leftSection={<Icon icon="mdi:pencil" width={16} />}
                          size="md"
                          variant="filled"
                        >
                          Start editing
                        </Button>
                      )}
                    </Stack>
                  </Center>
                ) : (
                  <DashboardGrid
                    dashboardId={dashboardId!}
                    metadataList={rightComponents}
                    layoutData={dashboard.right_panel_layout_data}
                    filters={filters}
                    onFilterChange={handleFilterChange}
                    cardValues={cardValues}
                    cardSecondaryValues={cardSecondaryValues}
                    cardValuesLoading={cardsLoading}
                    refreshTick={refreshTick}
                    isDraggable={false}
                    isResizable={false}
                    editMode={false}
                  />
                )}
              </Box>
            </Box>
          </div>
        )}
        {dashboard && dashboardId && (
          <NotesFooter
            dashboardId={dashboardId}
            initialContent={(dashboard.notes_content as string) ?? ''}
            permissions={dashboard.permissions as DashboardPermissions | undefined}
          />
        )}
      </AppShell.Main>

      <SettingsDrawer
        opened={settingsOpened}
        onClose={closeSettings}
        dashboard={dashboard}
      />
    </AppShell>
    </AvailableFilterValuesProvider>
  );
};

export default App;

// ---------------------------------------------------------------------------

function extractDashboardId(): string | null {
  const path = window.location.pathname;
  const match = path.match(/\/dashboard\/([^/?#]+)/);
  return match?.[1] || null;
}

function stableFilterKey(filters: InteractiveFilter[]): string {
  // Key on (index, source, value) so chart selections coexist with regular
  // filters under the same component index — switching only the ``source``
  // still triggers the bulk-compute re-run.
  const sorted = [...filters].sort((a, b) => {
    if (a.index !== b.index) return a.index.localeCompare(b.index);
    return (a.source ?? '').localeCompare(b.source ?? '');
  });
  return JSON.stringify(sorted.map((f) => [f.index, f.source ?? null, f.value]));
}
