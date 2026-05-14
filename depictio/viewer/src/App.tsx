import React, { useEffect, useState, useCallback, useRef, useMemo, useDeferredValue } from 'react';
import {
  AppShell,
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
  hasSelectionFilters,
  useDataCollectionUpdates,
  RealtimeIndicator,
  useRealtimeJournal,
} from 'depictio-react-core';
import type {
  DashboardData,
  DashboardSummary,
  InteractiveFilter,
  RealtimeMode,
} from 'depictio-react-core';
import { notifications } from '@mantine/notifications';
import { Header, Sidebar, SettingsDrawer } from './chrome';
import { useSidebarOpen } from './hooks/useSidebarOpen';
import { useAuthMode } from './auth/hooks/useAuthMode';
import DemoTour from './demo/DemoTour';
import DemoModeBanner from './components/DemoModeBanner';

// Demo onboarding UI temporarily disabled — flip to true to re-enable.
const ENABLE_DEMO_UI = false;

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
  // Heavy renderers (figures / tables / maps / image grid) consume a deferred
  // copy of the filter array — React batches updates while the user is still
  // interacting (slider drag, multi-select typing) so the figure/table fetch
  // doesn't re-fire on every intermediate value. Interactive controls keep
  // using the live ``filters`` so they stay snappy under input.
  const deferredFilters = useDeferredValue(filters);
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
  const auth = useAuthMode();
  const isDemoMode = auth.status?.is_demo_mode === true;

  const dashboardId = extractDashboardId();
  const bulkCtrl = useRef<AbortController | null>(null);

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
      setError('No dashboard ID in URL. Expected /dashboard-beta/<id>.');
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

  const handleFilterChange = useCallback((update: InteractiveFilter) => {
    // Dedupe by (index, source) so chart selections coexist with the same
    // component's other filters. Mirrors mergeFiltersBySource in
    // packages/depictio-react-core/src/selection.ts.
    setFilters((prev) => mergeFiltersBySource(prev, update));
  }, []);

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
    >
      {ENABLE_DEMO_UI && isDemoMode && <DemoModeBanner />}
      <DemoTour active={ENABLE_DEMO_UI && isDemoMode} />
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
          onReset={handleResetAllFilters}
          onOpenSettings={openSettings}
          cardsLoading={cardsLoading}
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
                <Title order={5} mb="sm">
                  Filters
                </Title>
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
                  {filters.length > 0 && (
                    <Anchor
                      component="button"
                      onClick={handleResetAllFilters}
                      size="xs"
                      mt="xs"
                    >
                      Reset all filters
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
                <DashboardGrid
                  dashboardId={dashboardId!}
                  metadataList={rightComponents}
                  layoutData={dashboard.right_panel_layout_data}
                  filters={deferredFilters}
                  onFilterChange={handleFilterChange}
                  cardValues={cardValues}
                  cardSecondaryValues={cardSecondaryValues}
                  cardValuesLoading={cardsLoading}
                  refreshTick={refreshTick}
                  isDraggable={false}
                  isResizable={false}
                  editMode={false}
                />
              </Box>
            </Box>
          </div>
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
  const match = path.match(/\/dashboard-beta\/([^/?#]+)/);
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
