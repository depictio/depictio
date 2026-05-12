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
  Collapse,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { useDisclosure } from '@mantine/hooks';

import {
  fetchDashboard,
  fetchAllDashboards,
  bulkComputeCards,
  ComponentRenderer,
  DashboardGrid,
  InteractiveGroupCard,
  TopPanel,
  groupInteractiveComponents,
  mergeFiltersBySource,
  mergeWithGlobal,
  buildSyntheticInteractiveComponents,
  isSyntheticComponentIndex,
  filterIdFromSyntheticIndex,
  syntheticComponentIndex,
  isEmptyGlobalValue,
  hasSelectionFilters,
  useDataCollectionUpdates,
  RealtimeIndicator,
  useRealtimeJournal,
  GlobeToggle,
  StoryPicker,
  StoryStepper,
  FunnelWidget,
} from 'depictio-react-core';
import type {
  DashboardData,
  DashboardSummary,
  InteractiveFilter,
  RealtimeMode,
  StoredMetadata,
  FunnelStep,
  FunnelTargetDC,
} from 'depictio-react-core';
import { notifications } from '@mantine/notifications';
import { Header, Sidebar, SettingsDrawer } from './chrome';
import { useGlobalFiltersStore } from './stores/useGlobalFiltersStore';
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

  // Global filters store — survives tab navigation within the same dashboard
  // family. Hydrated on the parent dashboard ID below.
  const globalDefinitions = useGlobalFiltersStore((s) => s.definitions);
  const globalValues = useGlobalFiltersStore((s) => s.values);
  const globalStories = useGlobalFiltersStore((s) => s.stories);
  const activeStoryId = useGlobalFiltersStore((s) => s.activeStoryId);
  const globalParentId = useGlobalFiltersStore((s) => s.parentDashboardId);
  const hydrateGlobal = useGlobalFiltersStore((s) => s.hydrate);
  const resetGlobal = useGlobalFiltersStore((s) => s.reset);
  const setGlobalValue = useGlobalFiltersStore((s) => s.setValue);
  const demoteGlobal = useGlobalFiltersStore((s) => s.demote);
  const setActiveStory = useGlobalFiltersStore((s) => s.setActiveStory);

  // Hydrate the store when we know which parent dashboard the active tab
  // belongs to. The store internally short-circuits if the same parent is
  // already hydrated — so navigating between sibling tabs is a no-op here.
  const parentDashboardIdForStore = useMemo(() => {
    if (!dashboard) return null;
    return (
      (dashboard.parent_dashboard_id as string | undefined) ||
      (dashboard.dashboard_id as string | undefined) ||
      dashboardId
    );
  }, [dashboard, dashboardId]);

  useEffect(() => {
    if (!parentDashboardIdForStore) return;
    if (globalParentId && globalParentId !== parentDashboardIdForStore) {
      // Switched to a different dashboard family — drop the previous family's
      // global filters before hydrating the new one.
      resetGlobal();
    }
    void hydrateGlobal(parentDashboardIdForStore);
  }, [parentDashboardIdForStore, globalParentId, hydrateGlobal, resetGlobal]);

  // DC IDs referenced on the currently-rendered tab. Used by `mergeWithGlobal`
  // to decide which links to expand into synthetic filters.
  const dcIdsOnTab = useMemo(() => {
    const set = new Set<string>();
    for (const m of dashboard?.stored_metadata || []) {
      const dc = (m as { dc_id?: string }).dc_id;
      if (dc) set.add(dc);
    }
    return set;
  }, [dashboard]);

  /** Per-tab local filters AUGMENTED with synthetic entries for every active
   *  global filter targeting a DC on this tab. This is what every backend
   *  fetch (bulk-compute, figures, tables, maps) must consume — the backend
   *  treats `InteractiveFilter[]` uniformly so no API-shape changes needed.
   */
  const effectiveFilters = useMemo(
    () => mergeWithGlobal(filters, globalDefinitions, globalValues, dcIdsOnTab),
    [filters, globalDefinitions, globalValues, dcIdsOnTab],
  );
  const effectiveDeferredFilters = useMemo(
    () => mergeWithGlobal(deferredFilters, globalDefinitions, globalValues, dcIdsOnTab),
    [deferredFilters, globalDefinitions, globalValues, dcIdsOnTab],
  );

  // Rail-only filter array: per-tab local filters + one entry per synthetic
  // global card, keyed on its synthetic-component index, carrying the current
  // global filter value so MultiSelect/RangeSlider/etc. render the selected
  // state. Distinct from `effectiveFilters`, which is for backend queries
  // (those go through mergeWithGlobal's `__global_${id}__${dc}` synthetic
  // filters scoped per DC link).
  const railFilters = useMemo<InteractiveFilter[]>(() => {
    const extras: InteractiveFilter[] = [];
    for (const def of globalDefinitions) {
      const v = globalValues[def.id];
      if (isEmptyGlobalValue(v)) continue;
      extras.push({ index: syntheticComponentIndex(def.id), value: v });
    }
    return [...filters, ...extras];
  }, [filters, globalDefinitions, globalValues]);

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
      bulkComputeCards(dashboardId, effectiveFilters, cardIds)
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
  }, [dashboard, dashboardId, stableFilterKey(effectiveFilters), refreshTick]);

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

  // Source-tab title lookup for "From [tab]" captions on synthetic cards.
  const tabTitleById = useMemo(() => {
    const m = new Map<string, string>();
    for (const t of allDashboards) {
      if (t.dashboard_id && t.title) m.set(t.dashboard_id, t.title);
    }
    return m;
  }, [allDashboards]);

  // Synthetic card per active global filter (one per def whose links target
  // this tab) + the set of native indices to hide because a global already
  // covers them (either as source or by (dc_id, column_name) match).
  const { synthetic: globalCards, hiddenNativeIndices } = useMemo(
    () => buildSyntheticInteractiveComponents(globalDefinitions, leftComponents, dcIdsOnTab),
    [globalDefinitions, leftComponents, dcIdsOnTab],
  );

  // Per-tab filter list with global-covered components stripped out, so the
  // bottom "Filters" section never duplicates a card the top "Global filters"
  // section is already showing.
  const visibleLeftComponents = useMemo(
    () => leftComponents.filter((c) => !hiddenNativeIndices.has(c.index)),
    [leftComponents, hiddenNativeIndices],
  );
  const leftGroups = useMemo(
    () => groupInteractiveComponents(visibleLeftComponents),
    [visibleLeftComponents],
  );
  // Group the global cards the same way (so multi-member groups stay grouped)
  // — usually globals are loose cards, but the grouping logic still works.
  const globalGroups = useMemo(
    () => groupInteractiveComponents(globalCards),
    [globalCards],
  );
  // `effectiveLeftComponents` is still consumed by `extraActionsByIndex`
  // (one globe per visible card on either side of the rail).
  const effectiveLeftComponents = useMemo<StoredMetadata[]>(
    () => [...visibleLeftComponents, ...globalCards],
    [visibleLeftComponents, globalCards],
  );

  // Funnel inputs derived from the active global filter values + every DC
  // referenced by at least one link. Empty arrays → the footer is hidden.
  const funnelSteps = useMemo<FunnelStep[]>(
    () =>
      globalDefinitions
        .filter((d) => !isEmptyGlobalValue(globalValues[d.id]))
        .map((d) => ({ filter_id: d.id, value: globalValues[d.id] })),
    [globalDefinitions, globalValues],
  );
  const funnelTargetDcs = useMemo<FunnelTargetDC[]>(() => {
    const seen = new Set<string>();
    const out: FunnelTargetDC[] = [];
    for (const def of globalDefinitions) {
      for (const link of def.links) {
        const key = `${link.wf_id}::${link.dc_id}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ wf_id: link.wf_id, dc_id: link.dc_id });
      }
    }
    return out;
  }, [globalDefinitions]);
  // Collapsible footer: open by default whenever the funnel has work to show.
  const [funnelOpen, setFunnelOpen] = useState(true);

  // "From [tab]" caption per synthetic card — lets the user see at a glance
  // which tab the global was originally promoted from.
  const sourceTabNameByIndex = useMemo<Record<string, string>>(() => {
    const defById = new Map(globalDefinitions.map((d) => [d.id, d] as const));
    const map: Record<string, string> = {};
    for (const card of globalCards) {
      const fid = filterIdFromSyntheticIndex(card.index);
      if (!fid) continue;
      const def = defById.get(fid);
      if (!def) continue;
      const tabName = tabTitleById.get(String(def.source_tab_id));
      if (tabName) map[card.index] = tabName;
    }
    return map;
  }, [globalDefinitions, globalCards, tabTitleById]);
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

  const promoteGlobal = useGlobalFiltersStore((s) => s.promote);

  // Map of component index → GlobeToggle, so each card in the unified left
  // rail gets a "promote ↔ demote" affordance in its chrome row.
  //   - Native per-tab card not yet global  → globe off, click promotes.
  //   - Native per-tab card already global  → globe on,  click demotes.
  //   - Synthetic card (from another tab)   → globe on,  click demotes.
  const extraActionsByIndex = useMemo(() => {
    const map: Record<string, React.ReactNode> = {};
    if (!dashboardId) return map;
    for (const m of effectiveLeftComponents) {
      const idx = m.index;
      // Synthetic card path — already global by construction; click demotes.
      if (isSyntheticComponentIndex(idx)) {
        const defId = filterIdFromSyntheticIndex(idx)!;
        map[idx] = (
          <GlobeToggle
            active
            onClick={() => {
              void demoteGlobal(defId);
            }}
          />
        );
        continue;
      }
      const meta = m as {
        index: string;
        title?: string;
        interactive_component_type?: string;
        column_name?: string;
        column_type?: string;
        wf_id?: string;
        dc_id?: string;
        default_state?: unknown;
        custom_color?: string;
        icon_name?: string;
        title_size?: string;
      };
      const existing = globalDefinitions.find((d) => d.source_component_index === idx);
      const isGlobal = Boolean(existing);
      const handleClick = () => {
        if (isGlobal && existing) {
          void demoteGlobal(existing.id);
          return;
        }
        if (!meta.interactive_component_type || !meta.column_name || !meta.dc_id || !meta.wf_id) {
          notifications.show({
            title: 'Cannot promote',
            message:
              'This interactive component is missing the (workflow, data collection, column) metadata needed to promote it.',
            color: 'orange',
          });
          return;
        }
        const newId = `gf_${idx}`;
        void promoteGlobal({
          id: newId,
          label: meta.title || meta.column_name,
          source_component_index: idx,
          source_tab_id: dashboardId,
          interactive_component_type: meta.interactive_component_type,
          column_type: meta.column_type || 'object',
          default_state: meta.default_state,
          links: [
            {
              wf_id: meta.wf_id,
              dc_id: meta.dc_id,
              column_name: meta.column_name,
            },
          ],
          // Capture styling so synthetic cards on OTHER tabs still look like
          // the original — same title text, icon, custom color, title size.
          display: {
            title: meta.title,
            custom_color: meta.custom_color,
            icon_name: meta.icon_name,
            title_size: meta.title_size,
          },
        }).catch((err) => {
          notifications.show({
            title: 'Failed to promote',
            message: String((err as Error).message ?? err),
            color: 'red',
          });
        });
      };
      map[idx] = <GlobeToggle active={isGlobal} onClick={handleClick} />;
    }
    return map;
  }, [effectiveLeftComponents, globalDefinitions, demoteGlobal, promoteGlobal, dashboardId]);

  // Filter-change interceptor: when the change comes from a synthetic card,
  // route the value to setGlobalValue (per-user state) instead of mixing it
  // into the per-tab `filters` array. Native per-tab filters keep using
  // handleFilterChange unchanged.
  const handleRailFilterChange = useCallback(
    (update: InteractiveFilter) => {
      if (isSyntheticComponentIndex(update.index)) {
        const fid = filterIdFromSyntheticIndex(update.index);
        if (fid) setGlobalValue(fid, update.value);
        return;
      }
      handleFilterChange(update);
    },
    [setGlobalValue, handleFilterChange],
  );

  return (
    <>
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
                  <StoryPicker
                    stories={globalStories}
                    activeStoryId={activeStoryId}
                    onChange={setActiveStory}
                    onNavigateToFirstStep={(firstTabId) => {
                      // Same-tab guard: if the story starts on the tab we're
                      // already viewing, skip the full-page reload — the
                      // stepper appears in-place via the Zustand state update.
                      if (firstTabId && firstTabId !== dashboardId) {
                        window.location.assign(`/dashboard-beta/${firstTabId}`);
                      }
                    }}
                  />
                  {/* Top "Global filters" section — renders one card per
                   *  active global, preserving the original component's
                   *  styling (icon, color, title) regardless of which tab
                   *  the user is currently on. */}
                  {globalCards.length > 0 && (
                    <Paper
                      withBorder
                      radius="md"
                      p="sm"
                      style={{
                        backgroundColor: 'var(--mantine-color-blue-0)',
                        borderColor: 'var(--mantine-color-blue-3)',
                      }}
                    >
                      <Group gap={6} mb="xs" wrap="nowrap" align="center">
                        <Icon
                          icon="tabler:world"
                          width={14}
                          color="var(--mantine-color-blue-filled)"
                        />
                        <Text size="xs" fw={700} c="blue.7" tt="uppercase" style={{ letterSpacing: 0.4 }}>
                          Global filters
                        </Text>
                      </Group>
                      <Stack gap="xs">
                        {globalGroups.map((g) => {
                          const renderMember = (m: StoredMetadata) => {
                            const tabName = sourceTabNameByIndex[m.index];
                            return (
                              <Stack key={m.index} gap={2}>
                                <ComponentRenderer
                                  metadata={m}
                                  filters={railFilters}
                                  onFilterChange={handleRailFilterChange}
                                  extraActions={extraActionsByIndex[m.index]}
                                />
                                {tabName && (
                                  <Text size="xs" c="dimmed" fs="italic" pl={4}>
                                    From {tabName}
                                  </Text>
                                )}
                              </Stack>
                            );
                          };
                          return g.groupName ? (
                            <InteractiveGroupCard
                              key={g.key}
                              groupName={g.groupName}
                              members={g.members}
                              filters={railFilters}
                              onFilterChange={handleRailFilterChange}
                              extraActionsByIndex={extraActionsByIndex}
                            />
                          ) : (
                            renderMember(g.members[0])
                          );
                        })}
                      </Stack>
                    </Paper>
                  )}
                  {effectiveLeftComponents.length === 0 && (
                    <Text size="sm" c="dimmed">No interactive components.</Text>
                  )}
                  {leftGroups.map((g) =>
                    g.groupName ? (
                      <InteractiveGroupCard
                        key={g.key}
                        groupName={g.groupName}
                        members={g.members}
                        filters={railFilters}
                        onFilterChange={handleRailFilterChange}
                        extraActionsByIndex={extraActionsByIndex}
                      />
                    ) : (
                      <ComponentRenderer
                        key={g.key}
                        metadata={g.members[0]}
                        filters={railFilters}
                        onFilterChange={handleRailFilterChange}
                        extraActions={extraActionsByIndex[g.members[0].index]}
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
                  {/* Collapsible funnel footer — visible when ≥1 global filter
                   *  has a non-empty value. Shows per-DC `N → N₁ → …` so the
                   *  user can see how the chain narrows the underlying data. */}
                  {funnelSteps.length > 0 && globalParentId && funnelTargetDcs.length > 0 && (
                    <Box mt="md">
                      <UnstyledButton
                        onClick={() => setFunnelOpen((o) => !o)}
                        style={{ width: '100%' }}
                      >
                        <Group gap={6} wrap="nowrap" align="center">
                          <Icon
                            icon={funnelOpen ? 'tabler:chevron-down' : 'tabler:chevron-right'}
                            width={14}
                            color="var(--mantine-color-dimmed)"
                          />
                          <Text size="xs" fw={600} c="dimmed" tt="uppercase" style={{ letterSpacing: 0.4 }}>
                            Filter funnel
                          </Text>
                        </Group>
                      </UnstyledButton>
                      <Collapse in={funnelOpen}>
                        <Box mt={6}>
                          <FunnelWidget
                            parentDashboardId={globalParentId}
                            definitions={globalDefinitions}
                            steps={funnelSteps}
                            targetDcs={funnelTargetDcs}
                          />
                        </Box>
                      </Collapse>
                    </Box>
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
              {activeStoryId && (() => {
                const story = globalStories.find((s) => s.id === activeStoryId);
                if (!story || !dashboardId) return null;
                const childTabs = tabSiblings.filter(
                  (t) => t.dashboard_id !== parentTab?.dashboard_id,
                );
                // Include the parent itself if it's part of the story order
                const allTabs = parentTab ? [parentTab, ...childTabs] : childTabs;
                return (
                  <StoryStepper
                    story={story}
                    childTabs={allTabs}
                    currentTabId={dashboardId}
                    onNavigate={(tabId) => window.location.assign(`/dashboard-beta/${tabId}`)}
                    onExitStory={() => setActiveStory(null)}
                  />
                );
              })()}
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
                  filters={effectiveDeferredFilters}
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
    </>
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
