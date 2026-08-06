import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import {
  ActionIcon,
  AppShell,
  Button,
  Center,
  Drawer,
  Group,
  Text,
  Loader,
  Stack,
  Title,
  Paper,
  Box,
} from '@mantine/core';
import { useDebouncedValue, useDisclosure, useMediaQuery } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import {
  fetchDashboard,
  fetchAllDashboards,
  bulkComputeCards,
  AvailableFilterValuesProvider,
  DashboardGrid,
  FilterPanel,
  TopPanel,
  mergeFiltersBySource,
  enrichFilterWithDcId,
  useDataCollectionUpdates,
  RealtimeIndicator,
  useRealtimeJournal,
  batchIdsFromPayload,
  fetchProjectFromDashboard,
  fetchIngestionHealth,
  bumpFetchGeneration,
  DashboardLoadingProvider,
  useMapPanel,
  MapPanelControl,
  MapPanelDock,
  MapPanelSurface,
  readFloatingFilters,
  writeFloatingFilters,
  clearFloatingFilters,
  persistableFloatingFilters,
  FILTER_PANEL_RAIL_WIDTH,
  countActiveFilters,
  clearFiltersBySource,
  renderFigure,
  renderTable,
} from 'depictio-react-core';
import {
  AIAnalyzePanel,
  AIKeySection,
  SectionSummaryPanel,
  SummarizeSectionButton,
  trimDigest,
  useAIHealth,
  useSectionSummaries,
} from 'depictio-react-ai';
import type {
  ApplyActionsPayload,
  ResolvedFilter,
  SummaryComponentPayload,
} from 'depictio-react-ai';
import type {
  DashboardData,
  DashboardPermissions,
  DashboardSummary,
  FloatingComponent,
  InteractiveFilter,
  RealtimeMode,
  ActiveHighlight,
  RealtimeJournalEntry,
  IngestionSummary,
} from 'depictio-react-core';
import { parseTemplateOrigin } from './projects/template';

/** localStorage key for the dismissed ingestion banner, scoped per project so
 *  the dismissal sticks across the dashboard's sibling tabs. */
const ingestionBannerKey = (projectId: string) =>
  `depictio:ingestion-banner-dismissed:${projectId}`;

/** How long the filter must hold still before the dashboard re-fetches.
 *
 *  Long enough to swallow a burst of MultiSelect picks or a slider drag, short
 *  enough that a single deliberate change still feels immediate. */
const FILTER_DEBOUNCE_MS = 250;
import { notifications } from '@mantine/notifications';
import { Header, Sidebar, SettingsDrawer } from './chrome';
import { useServerStatus } from './hooks/useServerStatus';
import { useSidebarOpen } from './hooks/useSidebarOpen';
import { useFilterPanelOpen } from './hooks/useFilterPanelOpen';
import { FILTER_PANEL_WIDTH_VAR, useFilterPanelWidth } from './hooks/useFilterPanelWidth';
import { useCurrentUser } from './hooks/useCurrentUser';
import { isDashboardOwner } from './lib/dashboardOwnership';
import FilterPanelResizer, { FILTER_PANEL_RESIZER_WIDTH } from './components/FilterPanelResizer';
import Inspector from './chrome/inspector/Inspector';
import { useInspectorChrome } from './chrome/inspector/useInspectorChrome';
import InspectorProviders from './chrome/inspector/InspectorProviders';
import NotesFooter from './components/NotesFooter';
import DashboardLoadIndicator from './components/DashboardLoadIndicator';
import BootSplash from './components/BootSplash';

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
  // Seed from the floating panel's persisted selection, synchronously. A
  // selection made on the floating map is meant to survive a tab switch, and
  // hydrating in an effect instead would let every grid tile fetch once
  // unfiltered before the seed landed, then again straight after. The seed is
  // validated against the real floating components once they resolve
  // (`handleFloatingResolved`), which is what discards stale entries.
  const [filters, setFilters] = useState<InteractiveFilter[]>(
    () => readFloatingFilters()?.filters ?? [],
  );
  // Indices we hydrated from storage. Only these may be pruned as stale — a
  // selection the viewer makes on a *grid* map during this page load must
  // never be swept up by the validation pass.
  //
  // Lazily, because `useRef`'s argument is evaluated on EVERY render and React
  // keeps only the first: an eager read would re-parse the stored payload — as
  // large as the last lasso — on every keystroke in a filter.
  const hydratedIndicesRef = useRef<Set<string> | null>(null);
  if (hydratedIndicesRef.current === null) {
    hydratedIndicesRef.current = new Set(filters.map((f) => f.index));
  }
  const [floatingIndices, setFloatingIndices] = useState<Set<string> | null>(null);
  const [floatingFamilyId, setFloatingFamilyId] = useState<string | null>(null);
  // Data fetches follow a *settled* filter, not every intermediate value of one.
  // Interactive components keep reading `filters` directly so their own UI stays
  // instant; only the components that hit the API wait for the pause. Without
  // this, picking three values in a MultiSelect fires three full rounds of
  // renders and the first two are obsolete before they land.
  const [deferredFilters] = useDebouncedValue(filters, FILTER_DEBOUNCE_MS);

  // Invalidate whatever the previous filter left queued.
  //
  // This runs during render on purpose. React runs child effects *before*
  // parent effects, so bumping from an effect here would land after the
  // renderers had already queued the new round — and would discard exactly the
  // requests it exists to protect. Rendering happens before any child effect,
  // which is the ordering the queue needs.
  const deferredFilterKey = stableFilterKey(deferredFilters);
  const lastFilterKeyRef = useRef<string | null>(null);
  if (lastFilterKeyRef.current !== deferredFilterKey) {
    lastFilterKeyRef.current = deferredFilterKey;
    bumpFetchGeneration();
  }
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
  const { user: currentUser, inspectorEnabled } = useCurrentUser();
  const isOwner = isDashboardOwner(dashboard, currentUser?.email ?? null);
  // `control` is null while the flag is off, so no provider value reaches the
  // component chrome and no inspect action is rendered anywhere.
  const { control: inspectorControl, aside: inspectorAside } =
    useInspectorChrome(inspectorEnabled);

  const dashboardId = extractDashboardId();

  // Left filter panel chrome. Width first: the collapse swing is the width the
  // content column reclaims, which is everything but the icon rail.
  const {
    width: filterPanelWidth,
    resizing: filterPanelResizing,
    layoutRef: filterPanelLayoutRef,
    beginResize: beginFilterPanelResize,
    nudge: nudgeFilterPanelWidth,
  } = useFilterPanelWidth(dashboardId);
  // The swing spans both variable tracks: collapsing takes the panel down to
  // the rail *and* the drag handle down to nothing. The grid gaps don't move,
  // so they cancel out.
  const [filterPanelOpened, toggleFilterPanel] = useFilterPanelOpen(
    dashboardId,
    filterPanelWidth + FILTER_PANEL_RESIZER_WIDTH - FILTER_PANEL_RAIL_WIDTH,
  );
  // Below `sm` the panel would leave the content column unusable, so it moves
  // into a drawer opened from the header. `getInitialValueInEffect: false`
  // avoids a first frame of desktop layout on a phone.
  const isNarrow = useMediaQuery('(max-width: 48em)', false, { getInitialValueInEffect: false });
  const [filterDrawerOpened, { open: openFilterDrawer, close: closeFilterDrawer }] =
    useDisclosure(false);
  // Widening past the breakpoint unmounts the drawer without closing it, which
  // would leave it primed to reappear the next time the window narrows.
  useEffect(() => {
    if (!isNarrow) closeFilterDrawer();
  }, [isNarrow, closeFilterDrawer]);

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

  // Bulk-compute card values whenever the settled filter changes.
  //
  // The debounce used to live here as a local `setTimeout`; it now comes from
  // `deferredFilters`, shared with every other component. Keeping a second one
  // stacked on top would have delayed cards by twice as long as the figures
  // next to them, so they'd visibly lag behind the rest of the dashboard.
  useEffect(() => {
    if (!dashboard || !dashboardId) return;
    const cardIds = (dashboard.stored_metadata || [])
      .filter((m) => m.component_type === 'card')
      .map((m) => m.index);
    if (cardIds.length === 0) return;

    setCardsLoading(true);
    // Keep the previous card values mounted while the new bulk-compute
    // round-trip is in flight. ``cardsLoading`` is what CardRenderer
    // already consults to dim the value — clearing the values here would
    // snap every card back to ``…`` on every keystroke / drag step.
    if (bulkCtrl.current) bulkCtrl.current.abort();
    bulkCtrl.current = new AbortController();
    bulkComputeCards(dashboardId, deferredFilters, cardIds)
      .then((res) => {
        setCardValues(res.values);
        setCardSecondaryValues(res.secondary_values || {});
      })
      .catch((err) => {
        if (err?.name !== 'AbortError') console.warn('[App] bulk-compute failed:', err);
      })
      .finally(() => setCardsLoading(false));
  }, [dashboard, dashboardId, deferredFilterKey, refreshTick]);

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

  // ---- AI assistant -------------------------------------------------------
  // Everything AI is gated on the server's feature flag: when off, no AI UI
  // mounts anywhere and no /ai request is ever made.
  const { features: serverFeatures } = useServerStatus();
  const aiEnabled = serverFeatures.ai;
  const aiHealth = useAIHealth(aiEnabled);
  const aiServerKeyAvailable = aiHealth?.server_key_configured === true;
  // Human-readable provenance for the currently-applied AI filters, shown in
  // the "AI filters" chip tooltip.
  const [aiFilterDescriptions, setAiFilterDescriptions] = useState<string[]>([]);
  // Transient per-figure dict_kwargs overrides from applied AI plans, keyed by
  // component index. Threaded into the render request; never persisted.
  const [aiFigureOverrides, setAiFigureOverrides] = useState<
    Record<string, Record<string, unknown>>
  >({});

  const handleApplyAIActions = useCallback(
    ({ actions, resolved }: ApplyActionsPayload) => {
      const exprFilters: InteractiveFilter[] = [];
      const widgetUpdates: InteractiveFilter[] = [];
      const descriptions: string[] = [];

      resolved.forEach((f: ResolvedFilter, i: number) => {
        if (f.kind === 'set_widget' && f.component_id) {
          const meta = (dashboard?.stored_metadata as Record<string, unknown>[] | undefined)?.find(
            (m) => m?.index === f.component_id,
          );
          widgetUpdates.push(
            enrichFilterWithDcId(
              {
                index: f.component_id,
                value: f.value,
                column_name: meta?.column_name as string | undefined,
                interactive_component_type: meta?.interactive_component_type as
                  | string
                  | undefined,
              },
              dashboard?.stored_metadata,
            ),
          );
          if (f.description) descriptions.push(f.description);
        } else if (f.kind === 'filter_expr' && f.filter_expr) {
          exprFilters.push({
            // Unique per apply so successive plans don't collide; the whole
            // 'ai_prompt' group is replaced below anyway.
            index: `ai-${Date.now().toString(36)}-${i}`,
            // Sentinel truthy value: expr-only filters carry no widget value,
            // but a null value reads as "cleared" to merge/active-count logic.
            value: true,
            source: 'ai_prompt',
            filter_expr: f.filter_expr,
            metadata: {
              dc_id: f.dc_id ?? undefined,
              filter_expr: f.filter_expr,
            },
          });
          descriptions.push(f.description || f.filter_expr);
        }
      });

      setFilters((prev) => {
        // A new AI plan replaces the previous one's injected filters.
        let next = clearFiltersBySource(prev, 'ai_prompt');
        for (const update of widgetUpdates) next = mergeFiltersBySource(next, update);
        return [...next, ...exprFilters];
      });
      setAiFilterDescriptions(descriptions);

      // Figure mutations: transient dict_kwargs overrides, applied only to
      // components that exist on this dashboard as figures. A new plan
      // replaces the previous overrides wholesale (same semantics as the
      // 'ai_prompt' filter group above).
      const overrides: Record<string, Record<string, unknown>> = {};
      let skippedMutations = 0;
      for (const m of actions?.figure_mutations ?? []) {
        const target = (
          dashboard?.stored_metadata as Record<string, unknown>[] | undefined
        )?.find((c) => c?.index === m.component_id && c?.component_type === 'figure');
        if (
          target &&
          m.dict_kwargs_patch &&
          typeof m.dict_kwargs_patch === 'object' &&
          Object.keys(m.dict_kwargs_patch).length > 0
        ) {
          overrides[m.component_id] = m.dict_kwargs_patch;
        } else {
          skippedMutations += 1;
        }
      }
      setAiFigureOverrides(overrides);
      if (skippedMutations > 0) {
        notifications.show({
          color: 'yellow',
          title: 'AI figure changes partially applied',
          message: `${skippedMutations} proposed figure change(s) referenced components that are not figures on this dashboard and were skipped.`,
        });
      }
    },
    [dashboard],
  );

  const aiFilterCount = useMemo(
    () => filters.filter((f) => f.source === 'ai_prompt').length,
    [filters],
  );
  const handleClearAIFilters = useCallback(() => {
    setFilters((prev) => clearFiltersBySource(prev, 'ai_prompt'));
    setAiFilterDescriptions([]);
  }, []);
  const aiFigureOverrideCount = Object.keys(aiFigureOverrides).length;
  const handleClearAIFigureOverrides = useCallback(() => setAiFigureOverrides({}), []);

  // ---- Floating panel: validate the hydrated cross-tab selection -----------
  // Runs once the family's floating components are known. Anything we seeded
  // from storage that does not correspond to a still-floating map on *this*
  // dashboard family is dropped: the map may have been deleted, moved back
  // into the grid, or the viewer may have navigated to a different dashboard
  // entirely (one browser tab, one storage entry).
  const handleFloatingResolved = useCallback(
    (familyId: string | null, components: FloatingComponent[]) => {
      const indices = new Set(components.map((c) => c.metadata.index));
      setFloatingIndices(indices);
      setFloatingFamilyId(familyId);

      const stored = readFloatingFilters();
      const familyChanged = stored != null && familyId != null && stored.parentDashboardId !== familyId;
      const hydrated = hydratedIndicesRef.current ?? new Set<string>();
      if (hydrated.size === 0) return;

      setFilters((prev) =>
        prev.filter((f) => {
          if (!hydrated.has(f.index) || f.source !== 'map_selection') return true;
          return !familyChanged && indices.has(f.index);
        }),
      );
      hydratedIndicesRef.current = new Set();
      if (familyChanged) clearFloatingFilters();
    },
    [],
  );

  // The dashboard-wide map panel: its own fetch of the tab family's floating
  // maps, its own hidden/floating/docked state, shared by the header control
  // and the panel itself.
  const mapPanel = useMapPanel({
    dashboardId: dashboardId ?? '',
    // Instant filters, not the debounced copy: the badge and the selection
    // summary should not lag behind the click that set them.
    filters,
    onFilterChange: handleFilterChange,
    onComponentsResolved: handleFloatingResolved,
  });

  // Persist the floating subset on every filter change. Deriving it from
  // `filters` rather than tracking writes separately is what makes "Reset all"
  // and "Clear chart selections" clear the stored copy for free.
  useEffect(() => {
    if (!floatingFamilyId || !floatingIndices) return;
    writeFloatingFilters(
      floatingFamilyId,
      persistableFloatingFilters(filters, floatingIndices),
    );
  }, [filters, floatingFamilyId, floatingIndices]);

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

  // The batch currently highlighted across the dashboard. Live arrivals set it
  // transiently (auto-fade); the event log can pin a past batch (sticky). The
  // nonce (monotonic) re-arms the renderers' fade window on every (re-)trigger.
  const [activeHighlight, setActiveHighlight] = useState<ActiveHighlight | null>(null);
  const highlightNonce = useRef(0);
  const applyHighlight = useCallback(
    (batch: { idColumn?: string; ids: string[] }, dcId?: string, sticky = false, batchKey?: string) => {
      highlightNonce.current += 1;
      const nonce = highlightNonce.current;
      setActiveHighlight((prev) => {
        // A live (non-sticky) arrival must not replace a batch the user pinned
        // from the event log — otherwise the next stream event wipes it.
        if (!sticky && prev?.sticky) return prev;
        return { ...batch, dcId, sticky, batchKey, nonce };
      });
    },
    [],
  );
  const handleHighlightBatch = useCallback(
    (entry: RealtimeJournalEntry) => {
      const batch = batchIdsFromPayload(entry.payload);
      if (!batch) return;
      applyHighlight(batch, entry.dataCollectionId, true, entry.receivedAt);
    },
    [applyHighlight],
  );
  const handleClearHighlight = useCallback(() => setActiveHighlight(null), []);

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
        // Glow exactly the rows this batch added (auto-fade). Falls back to the
        // renderers' client-side diff when the payload carries no id list.
        const batch = batchIdsFromPayload(payload);
        if (batch) applyHighlight(batch, event.data_collection_id, false);
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
    [triggerRefresh, appendJournal, applyHighlight],
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
  /**
   * What the filter panel resolves a filter's *name* against.
   *
   * The tab's own `stored_metadata` is not enough. A floating map is declared on
   * one tab and filters every tab, so on any other tab its selection has no
   * component to look up — and the active-filter summary fell back to the raw
   * join column, listing a map selection as "sample". Unioning in the family's
   * floating components gives that row the map's actual title on every tab.
   *
   * `leftComponents` deliberately does not get them: they are not panel controls
   * and must not be rendered as filter rows.
   */
  const summaryMetadata = useMemo(() => {
    const own = dashboard?.stored_metadata || [];
    const seen = new Set(own.map((m) => m.index));
    return [...own, ...mapPanel.components.map((c) => c.metadata).filter((m) => !seen.has(m.index))];
  }, [dashboard, mapPanel.components]);
  const cardComponents = useMemo(
    () => (dashboard?.stored_metadata || []).filter((m) => m.component_type === 'card'),
    [dashboard],
  );
  const otherComponents = useMemo(
    () =>
      (dashboard?.stored_metadata || []).filter(
        (m) =>
          m.component_type !== 'card' &&
          m.component_type !== 'interactive' &&
          // Floating maps are rendered by FloatingPanelHost, not the grid.
          // They also carry no layout entry (see dashboards.py), so leaving
          // them here would make the grid auto-place them on top of a tile.
          !(m.component_type === 'map' && m.placement === 'floating'),
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

  // Same count the panel badges, hoisted so the narrow-screen header button can
  // show it while the panel itself is off screen.
  const activeFilterCount = countActiveFilters(filters);

  // ---- AI section summaries -------------------------------------------------
  // Digests are assembled at summarize time: card values come from local
  // state, figure/table payloads are refetched with the current filters (the
  // render endpoints are what the tiles themselves use, so the digest matches
  // what's on screen). Everything is client-trimmed before upload; the server
  // trims again.
  const buildAIContext = useCallback(
    async (section: string | null) => {
      if (!dashboard || !dashboardId) return { filters: [], components: [] };
      const inSection = rightComponents.filter(
        (m) => ((m.section as string | undefined) ?? null) === section,
      );
      const components: SummaryComponentPayload[] = [];
      for (const m of inSection) {
        const id = m.index;
        const title = (m.title as string) || '';
        const type = String(m.component_type);
        if (type === 'card') {
          components.push({
            id,
            type,
            title,
            digest: trimDigest({
              column: m.column_name,
              aggregation: m.aggregation,
              value: cardValues[id],
              secondary: cardSecondaryValues[id],
            }),
          });
        } else if (type === 'figure') {
          try {
            const res = await renderFigure(dashboardId, id, deferredFilters);
            components.push({
              id,
              type,
              title,
              digest: trimDigest(
                {
                  visu_type: res.metadata?.visu_type ?? m.visu_type,
                  dict_kwargs: m.dict_kwargs,
                  total_rows: res.metadata?.total_data_count,
                  data: res.figure?.data,
                },
                40,
                200,
              ),
            });
          } catch {
            components.push({
              id,
              type,
              title,
              digest: { visu_type: m.visu_type, dict_kwargs: m.dict_kwargs },
            });
          }
        } else if (type === 'table') {
          try {
            const res = await renderTable(dashboardId, id, deferredFilters, 0, 15);
            components.push({
              id,
              type,
              title,
              digest: trimDigest({ total_rows: res.total, rows: res.rows }),
            });
          } catch {
            components.push({ id, type, title, digest: { columns: m.columns } });
          }
        } else {
          // multiqc / map / image / jbrowse / advanced_viz: configuration-level
          // digest only — their payloads are either binary or too large to be
          // meaningful as text.
          components.push({ id, type, title, digest: { component_type: type } });
        }
      }
      return { filters: deferredFilters as unknown[], components };
    },
    [dashboard, dashboardId, rightComponents, cardValues, cardSecondaryValues, deferredFilters],
  );

  const sectionSummaries = useSectionSummaries(
    dashboardId ?? '',
    aiEnabled && Boolean(dashboardId),
    buildAIContext,
  );
  // Client-local staleness: filters changed since this session generated the
  // summary. (Server-side hash comparison would need the digests recomputed on
  // every render — this heuristic is free and errs on the safe side.)
  const [aiSummaryFilterKeys, setAiSummaryFilterKeys] = useState<Record<string, string>>({});
  const handleGenerateSummary = useCallback(
    async (section: string | null, force = false) => {
      const res = await sectionSummaries.generate(section, force);
      if (res) {
        setAiSummaryFilterKeys((prev) => ({ ...prev, [section ?? '']: deferredFilterKey }));
      }
    },
    [sectionSummaries, deferredFilterKey],
  );

  const renderSectionExtras = useCallback(
    (section: string | null) => {
      if (!aiEnabled) return null;
      const key = section ?? '';
      const entry = sectionSummaries.entries[key];
      const pending = sectionSummaries.pendingSection === key;
      const generatedKey = aiSummaryFilterKeys[key];
      const stale = Boolean(entry && generatedKey !== undefined && generatedKey !== deferredFilterKey);
      return {
        trailing: (
          <SummarizeSectionButton
            section={section}
            hasSummary={Boolean(entry)}
            pending={pending}
            onGenerate={(s, force) => void handleGenerateSummary(s, force)}
          />
        ),
        panelTop: entry ? (
          <SectionSummaryPanel
            entry={entry}
            stale={stale}
            pending={pending}
            error={pending ? null : sectionSummaries.error}
            onRegenerate={(s, force) => void handleGenerateSummary(s, force)}
            onDismiss={sectionSummaries.dismiss}
          />
        ) : section === null ? (
          // The unsectioned grid has no header to host the sparkle button, so
          // it gets a discreet right-aligned one above the grid instead.
          <Group justify="flex-end" mb={4}>
            <SummarizeSectionButton
              section={null}
              hasSummary={false}
              pending={pending}
              onGenerate={(s, force) => void handleGenerateSummary(s, force)}
            />
          </Group>
        ) : undefined,
      };
    },
    [aiEnabled, sectionSummaries, aiSummaryFilterKeys, deferredFilterKey, handleGenerateSummary],
  );

  return (
    <AvailableFilterValuesProvider
      dashboardMetadata={dashboard?.stored_metadata}
      projectId={dashboard?.project_id}
    >
      <DashboardLoadingProvider>
      <InspectorProviders control={inspectorControl}>
      <AppShell
      header={{ height: 50 }}
      navbar={{
        width: 250,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      aside={inspectorAside}
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
          onOpenFilters={isNarrow && leftComponents.length > 0 ? openFilterDrawer : undefined}
          filterCount={activeFilterCount}
          cardsLoading={cardsLoading}
          isOwner={isOwner}
          titleExtras={
            dashboard && !loading && !error ? (
              <DashboardLoadIndicator metadataList={rightComponents} cardsLoading={cardsLoading} />
            ) : undefined
          }
          rightExtras={
            <>
              <MapPanelControl panel={mapPanel} />
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
                    onHighlightBatch={handleHighlightBatch}
                    onClearHighlight={handleClearHighlight}
                    activeHighlightKey={activeHighlight?.batchKey}
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
        {/* Dashboard-document fetch: no panels exist yet, so there is nothing
            for the header indicator to count. No prose — the title is already on
            screen, so naming the phase adds nothing. */}
        {loading && <BootSplash />}
        {error && <Text c="red" p="lg">{error}</Text>}
        {dashboard && !loading && !error && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              height: '100%',
              width: '100%',
              overflow: 'hidden',
            }}
          >
          <div
            ref={filterPanelLayoutRef}
            // Cast because `CSSProperties` has no index signature for custom
            // properties, and the name is a constant rather than a literal.
            style={{
              // The panel track comes from a variable so a drag can move it
              // without a React render — see `useFilterPanelWidth`. React owns
              // the value everywhere else, including here on every commit.
              [FILTER_PANEL_WIDTH_VAR]: `${
                filterPanelOpened ? filterPanelWidth : FILTER_PANEL_RAIL_WIDTH
              }px`,
              display: 'grid',
              // Panel | drag handle | content. The handle gets a real column
              // rather than floating over the panel edge, so it can't overlap
              // the controls underneath. The track count stays at three
              // whatever the panel's state, because `grid-template-columns`
              // only animates between templates with matching track counts.
              gridTemplateColumns: isNarrow
                ? '1fr'
                : `var(${FILTER_PANEL_WIDTH_VAR}) ` +
                  `${filterPanelOpened ? FILTER_PANEL_RESIZER_WIDTH : 0}px 1fr`,
              // Matches the panel's own toggle duration so the grid items,
              // which animate on `body.panel-transitioning`, stay in lockstep.
              // Dropped while dragging: the transition is for the collapse
              // toggle, and easing every pointermove over 300ms is what makes
              // the handle feel like it's being towed rather than moved.
              transition: filterPanelResizing
                ? 'none'
                : 'grid-template-columns 300ms ease',
              flex: 1,
              minHeight: 0,
              width: '100%',
              gap: 4,
              overflow: 'hidden',
            } as React.CSSProperties}
          >
            {!isNarrow && (
              <Box
                px={4}
                py={4}
                style={{
                  // The panel scrolls its own filter list, so this wrapper must
                  // not scroll too — that is what keeps the docked map pinned
                  // to the bottom while a long list scrolls past it.
                  height: '100%',
                  minWidth: 0,
                  overflow: 'hidden',
                }}
              >
                <FilterPanel
                  components={leftComponents}
                  allMetadata={summaryMetadata}
                  filters={filters}
                  onFilterChange={handleFilterChange}
                  onResetAllFilters={handleResetAllFilters}
                  layoutData={dashboard.left_panel_layout_data}
                  filterSections={dashboard.filter_sections}
                  dashboardId={dashboardId}
                  refreshTick={refreshTick}
                  collapsed={!filterPanelOpened}
                  onToggleCollapsed={toggleFilterPanel}
                  footer={
                    <MapPanelDock
                      panel={mapPanel}
                      filters={filters}
                      onFilterChange={handleFilterChange}
                      refreshTick={refreshTick}
                    />
                  }
                />
              </Box>
            )}
            {!isNarrow && (
              <FilterPanelResizer
                onPointerDown={beginFilterPanelResize}
                onNudge={nudgeFilterPanelWidth}
                collapsed={!filterPanelOpened}
              />
            )}
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
              {aiEnabled && dashboardId && (
                <>
                  <AIAnalyzePanel
                    dashboardId={dashboardId}
                    activeFilters={deferredFilters}
                    serverKeyAvailable={aiServerKeyAvailable}
                    onApplyActions={handleApplyAIActions}
                  />
                  {(aiFilterCount > 0 || aiFigureOverrideCount > 0) && (
                    <Group gap={6} mb={6}>
                      {aiFilterCount > 0 && (
                        <Button
                          data-testid="ai-filters-chip"
                          size="compact-xs"
                          variant="light"
                          color="violet"
                          leftSection={<Icon icon="mdi:filter-outline" width={12} />}
                          rightSection={<Icon icon="mdi:close" width={12} />}
                          onClick={handleClearAIFilters}
                          title={aiFilterDescriptions.join('\n')}
                        >
                          AI filters ({aiFilterCount})
                        </Button>
                      )}
                      {aiFigureOverrideCount > 0 && (
                        <Button
                          data-testid="ai-figure-overrides-chip"
                          size="compact-xs"
                          variant="light"
                          color="violet"
                          leftSection={<Icon icon="mdi:chart-scatter-plot" width={12} />}
                          rightSection={<Icon icon="mdi:close" width={12} />}
                          onClick={handleClearAIFigureOverrides}
                          title="Temporary AI changes to figure settings — click to revert"
                        >
                          AI figure tweaks ({aiFigureOverrideCount})
                        </Button>
                      )}
                    </Group>
                  )}
                </>
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
                          href={`/dashboard-edit/${dashboardId}`}
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
                    gridSections={dashboard.grid_sections}
                    filters={deferredFilters}
                    onFilterChange={handleFilterChange}
                    cardValues={cardValues}
                    cardSecondaryValues={cardSecondaryValues}
                    cardValuesLoading={cardsLoading}
                    refreshTick={refreshTick}
                    activeHighlight={activeHighlight}
                    isDraggable={false}
                    isResizable={false}
                    editMode={false}
                    renderSectionExtras={aiEnabled ? renderSectionExtras : undefined}
                    figureOverrides={aiFigureOverrideCount > 0 ? aiFigureOverrides : undefined}
                  />
                )}
              </Box>
            </Box>
          </div>
          {/* Full-width footer spanning both the filter panel and the content
              column. Hosts top-placement interactive controls (the Timeline
              scrubber) as an always-visible global filter, pinned below the
              scrollable columns. */}
          {topComponents.length > 0 && (
            <Box
              px="md"
              py={6}
              style={{
                flexShrink: 0,
                width: '100%',
                borderTop: '1px solid var(--mantine-color-default-border)',
                background: 'var(--mantine-color-body)',
              }}
            >
              <TopPanel
                components={topComponents}
                filters={filters}
                onFilterChange={handleFilterChange}
                refreshTick={refreshTick}
              />
            </Box>
          )}
          </div>
        )}
        {/* Narrow screens: the panel the grid no longer has room for. No
            collapse control inside — the drawer's own close is the way out. */}
        {dashboard && isNarrow && (
          <Drawer
            opened={filterDrawerOpened}
            onClose={closeFilterDrawer}
            position="left"
            size="min(320px, 85vw)"
            title="Filters"
          >
            <FilterPanel
              components={leftComponents}
              allMetadata={summaryMetadata}
              filters={filters}
              onFilterChange={handleFilterChange}
              onResetAllFilters={handleResetAllFilters}
              layoutData={dashboard.left_panel_layout_data}
              filterSections={dashboard.filter_sections}
              dashboardId={dashboardId}
              refreshTick={refreshTick}
            />
          </Drawer>
        )}
        {dashboard && dashboardId && !inspectorEnabled && (
          <NotesFooter
            dashboardId={dashboardId}
            initialContent={(dashboard.notes_content as string) ?? ''}
            permissions={dashboard.permissions as DashboardPermissions | undefined}
          />
        )}
        {dashboard && dashboardId && (
          <MapPanelSurface
            panel={mapPanel}
            filters={filters}
            onFilterChange={handleFilterChange}
            refreshTick={refreshTick}
          />
        )}
      </AppShell.Main>

      {inspectorEnabled && (
        <AppShell.Aside p={0}>
          <Inspector dashboard={dashboard} dashboardId={dashboardId} />
        </AppShell.Aside>
      )}

      <SettingsDrawer
        opened={settingsOpened}
        onClose={closeSettings}
        dashboard={dashboard}
        extraSection={
          aiEnabled && serverFeatures.ai_user_keys && dashboardId ? (
            <AIKeySection dashboardId={dashboardId} />
          ) : undefined
        }
      />
    </AppShell>
      </InspectorProviders>
      </DashboardLoadingProvider>
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
