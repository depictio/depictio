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
  FunnelView,
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
  useCrossTabComponents,
  PersistentSectionsHost,
  readCrossTabFilters,
  writeCrossTabFilters,
  clearCrossTabFilters,
  persistableCrossTabFilters,
  FILTER_PANEL_RAIL_WIDTH,
  countActiveFilters,
} from 'depictio-react-core';
import type {
  DashboardData,
  DashboardPermissions,
  DashboardSummary,
  CrossTabComponentsResponse,
  InteractiveFilter,
  RealtimeMode,
  ActiveHighlight,
  RealtimeJournalEntry,
  IngestionSummary,
  StoredMetadata,
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
  // Seed from the persisted cross-tab filters, synchronously. A selection made
  // on the floating map or a value set in a persistent filter section is meant
  // to survive a tab switch, and hydrating in an effect instead would let
  // every grid tile fetch once unfiltered before the seed landed, then again
  // straight after. The seed is validated against the real cross-tab
  // components once they resolve (`handleCrossTabResolved`), which is what
  // discards stale entries.
  const [filters, setFilters] = useState<InteractiveFilter[]>(
    () => readCrossTabFilters()?.filters ?? [],
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
  // Data fetches follow a *settled* filter, not every intermediate value of one.
  // Interactive components keep reading `filters` directly so their own UI stays
  // instant; only the components that hit the API wait for the pause. Without
  // this, picking three values in a MultiSelect fires three full rounds of
  // renders and the first two are obsolete before they land.
  const [deferredFilters] = useDebouncedValue(filters, FILTER_DEBOUNCE_MS);

  // Funnel filtering (issue #939). The dashboard's `funnel_filtering` field is
  // the author's default; the panel button flips it for this page view only
  // (viewers may lack edit rights, so the button never writes back). The field
  // defaults to on, so only an explicit `false` disables it: a dashboard saved
  // before the field existed has no value and must still get the funnel.
  const [funnelEnabled, setFunnelEnabled] = useState(true);
  const [funnelViewOpen, setFunnelViewOpen] = useState(false);
  const funnelDefault = dashboard?.funnel_filtering !== false;
  useEffect(() => {
    setFunnelEnabled(funnelDefault);
  }, [funnelDefault]);

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

  // ---- Cross-tab components: validate the hydrated filters -----------------
  // Runs once the family's floating maps and persistent sections are known.
  // Anything we seeded from storage that does not correspond to a
  // still-floating map or a still-persistent filter control on *this*
  // dashboard family is dropped: the component may have been deleted, its
  // section un-marked persistent, or the viewer may have navigated to a
  // different dashboard entirely (one browser tab, one storage entry).
  const handleCrossTabResolved = useCallback((res: CrossTabComponentsResponse) => {
    const familyId = res.parent_dashboard_id;
    const floatIndices = new Set(res.floating.map((c) => c.metadata.index));
    const persistentControls = new Map<string, StoredMetadata>();
    for (const s of res.persistent_sections) {
      if (s.kind !== 'filter') continue;
      for (const c of s.components) persistentControls.set(c.metadata.index, c.metadata);
    }

    const stored = readCrossTabFilters();
    const familyChanged =
      stored != null && familyId != null && stored.parentDashboardId !== familyId;
    const hydrated = hydratedIndicesRef.current ?? new Set<string>();
    if (hydrated.size === 0) return;

    setFilters((prev) =>
      prev.filter((f) => {
        if (!hydrated.has(f.index)) return true;
        if (familyChanged) return false;
        if (f.source === 'map_selection') return floatIndices.has(f.index);
        // Only sourceless control values and map selections are ever
        // persisted; anything else that got hydrated is a stale shape.
        if (f.source !== undefined) return false;
        const control = persistentControls.get(f.index);
        if (!control) return false;
        // The author may have re-pointed the control at another column or DC
        // since the value was stored — a mismatched value must not keep
        // filtering under the old meaning.
        const storedDc = f.metadata?.dc_id;
        if (storedDc && control.dc_id && storedDc !== control.dc_id) return false;
        const storedCol = f.column_name ?? f.metadata?.column_name;
        if (storedCol && control.column_name && storedCol !== control.column_name) return false;
        return true;
      }),
    );
    hydratedIndicesRef.current = new Set();
    if (familyChanged) clearCrossTabFilters();
  }, []);

  // One request per page load for everything this tab renders on behalf of its
  // siblings: floating maps + persistent sections.
  const crossTab = useCrossTabComponents(dashboardId ?? '', handleCrossTabResolved);

  const floatingIndices = useMemo(
    () => new Set(crossTab.floating.map((c) => c.metadata.index)),
    [crossTab.floating],
  );
  const persistentFilterIndices = useMemo(
    () =>
      new Set(
        crossTab.persistentSections
          .filter((s) => s.kind === 'filter')
          .flatMap((s) => s.components.map((c) => c.metadata.index)),
      ),
    [crossTab.persistentSections],
  );
  // Persistent sections owned by *other* tabs. The current tab's own persistent
  // sections render natively (grid ones in DashboardGrid, filter ones in the
  // panel) — fanning them out too would draw them twice.
  const foreignPersistentSections = useMemo(
    () => crossTab.persistentSections.filter((s) => s.owner_dashboard_id !== dashboardId),
    [crossTab.persistentSections, dashboardId],
  );
  const foreignFilterSections = useMemo(
    () => foreignPersistentSections.filter((s) => s.kind === 'filter'),
    [foreignPersistentSections],
  );
  // Grid sections split by the edge their author pinned them to. `pin` is
  // unset on sections written before it existed, and 'top' is what they got.
  const foreignGridSections = useMemo(
    () => foreignPersistentSections.filter((s) => s.kind === 'grid'),
    [foreignPersistentSections],
  );
  const topGridSections = useMemo(
    () => foreignGridSections.filter((s) => s.spec.pin !== 'bottom'),
    [foreignGridSections],
  );
  const bottomGridSections = useMemo(
    () => foreignGridSections.filter((s) => s.spec.pin === 'bottom'),
    [foreignGridSections],
  );

  /**
   * What filter names, dc_ids and available-values are resolved against.
   *
   * The tab's own `stored_metadata` is not enough. A floating map or a
   * persistent section is declared on one tab and present on every tab, so on
   * any other tab its filters would have no component to look up — the
   * active-filter summary fell back to the raw join column, and
   * `enrichFilterWithDcId` could not attach the dc_id cross-DC link resolution
   * needs. Unioning in the family's cross-tab components fixes all of that.
   *
   * `leftComponents` deliberately gets only the persistent *filter* members:
   * grid members and maps are not panel controls and must not render as
   * filter rows.
   */
  const summaryMetadata = useMemo(() => {
    const own = dashboard?.stored_metadata || [];
    const seen = new Set(own.map((m) => m.index));
    const extras: StoredMetadata[] = [];
    for (const c of crossTab.floating) {
      if (seen.has(c.metadata.index)) continue;
      seen.add(c.metadata.index);
      extras.push(c.metadata);
    }
    for (const s of crossTab.persistentSections) {
      for (const c of s.components) {
        if (seen.has(c.metadata.index)) continue;
        seen.add(c.metadata.index);
        extras.push(c.metadata);
      }
    }
    return extras.length ? [...own, ...extras] : own;
  }, [dashboard, crossTab.floating, crossTab.persistentSections]);

  const handleFilterChange = useCallback(
    (update: InteractiveFilter) => {
      // Looked up against the family-wide union, not just this tab's own
      // metadata: a control fanned out from a persistent filter section has no
      // entry in `dashboard.stored_metadata` here.
      const enriched = enrichFilterWithDcId(update, summaryMetadata);
      // Dedupe by (index, source) so chart selections coexist with the same
      // component's other filters. Mirrors mergeFiltersBySource in
      // packages/depictio-react-core/src/selection.ts.
      setFilters((prev) => mergeFiltersBySource(prev, enriched));
    },
    [summaryMetadata],
  );

  const handleResetAllFilters = useCallback(() => setFilters([]), []);

  // The dashboard-wide map panel: the tab family's floating maps, its own
  // hidden/floating/docked state, shared by the header control and the panel
  // itself.
  const mapPanel = useMapPanel({
    components: crossTab.floating,
    familyId: crossTab.familyId,
    // Instant filters, not the debounced copy: the badge and the selection
    // summary should not lag behind the click that set them.
    filters,
    onFilterChange: handleFilterChange,
  });

  // Persist the cross-tab subset on every filter change. Deriving it from
  // `filters` rather than tracking writes separately is what makes "Reset all"
  // and "Clear chart selections" clear the stored copy for free.
  useEffect(() => {
    if (!crossTab.resolved || !crossTab.familyId) return;
    writeCrossTabFilters(
      crossTab.familyId,
      persistableCrossTabFilters(filters, floatingIndices, persistentFilterIndices),
    );
  }, [filters, crossTab.resolved, crossTab.familyId, floatingIndices, persistentFilterIndices]);

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
  const leftComponents = useMemo(() => {
    const own = interactiveComponents.filter((m) => m.placement !== 'top');
    const seen = new Set(own.map((m) => m.index));
    // Controls fanned out from sibling tabs' persistent filter sections render
    // as ordinary panel rows: their renderers fetch options by dc_id/column,
    // not by dashboard id, so no further plumbing is needed.
    const foreign = foreignFilterSections
      .flatMap((s) => s.components.map((c) => c.metadata))
      .filter((m) => !seen.has(m.index) && m.placement !== 'top');
    return foreign.length ? [...own, ...foreign] : own;
  }, [interactiveComponents, foreignFilterSections]);
  // Section chrome for the panel: the tab's own specs plus the foreign
  // persistent ones its fanned-out controls belong to. Own specs win on a name
  // clash — the members bucket by name either way.
  const panelFilterSections = useMemo(() => {
    const own = dashboard?.filter_sections ?? [];
    const names = new Set(own.map((s) => s.name));
    const foreign = foreignFilterSections
      .map((s) => s.spec)
      .filter((s) => !names.has(s.name));
    return foreign.length ? [...own, ...foreign] : own;
  }, [dashboard, foreignFilterSections]);
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

  return (
    <AvailableFilterValuesProvider
      dashboardMetadata={summaryMetadata}
      projectId={dashboard?.project_id}
      funnel={
        dashboardId
          ? { enabled: funnelEnabled, dashboardId, filters: deferredFilters }
          : undefined
      }
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
                  filterSections={panelFilterSections}
                  dashboardId={dashboardId}
                  refreshTick={refreshTick}
                  collapsed={!filterPanelOpened}
                  onToggleCollapsed={toggleFilterPanel}
                  funnel={{
                    enabled: funnelEnabled,
                    onToggle: () => setFunnelEnabled((v) => !v),
                    onOpenView: () => setFunnelViewOpen(true),
                  }}
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
              {/* Persistent grid sections owned by sibling tabs — the
                  "always in view" slot a metadata table lands in on every tab.
                  `pin: top` opens the tab with the family-wide context;
                  `pin: bottom` puts it after this tab's own content, so a
                  shared reference block does not precede the tab's own
                  introduction. Sections this tab owns render inside
                  DashboardGrid below, where they stay editable. */}
              {topGridSections.length > 0 && (
                <PersistentSectionsHost
                  sections={topGridSections}
                  familyId={crossTab.familyId}
                  slot="top"
                  filters={deferredFilters}
                  onFilterChange={handleFilterChange}
                  refreshTick={refreshTick}
                />
              )}
              {/* Only claims the leftover height when nothing follows it —
                  otherwise a short grid would push the bottom-pinned sections
                  to the fold with a gap above them. */}
              <Box style={{ flex: bottomGridSections.length > 0 ? '0 0 auto' : 1, minHeight: 0 }}>
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
                  />
                )}
              </Box>
              {bottomGridSections.length > 0 && (
                <PersistentSectionsHost
                  sections={bottomGridSections}
                  familyId={crossTab.familyId}
                  slot="bottom"
                  filters={deferredFilters}
                  onFilterChange={handleFilterChange}
                  refreshTick={refreshTick}
                />
              )}
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
              filterSections={panelFilterSections}
              dashboardId={dashboardId}
              refreshTick={refreshTick}
              funnel={{
                enabled: funnelEnabled,
                onToggle: () => setFunnelEnabled((v) => !v),
                onOpenView: () => setFunnelViewOpen(true),
              }}
            />
          </Drawer>
        )}
        {dashboardId && (
          <FunnelView
            opened={funnelViewOpen}
            onClose={() => setFunnelViewOpen(false)}
            dashboardId={dashboardId}
            filters={deferredFilters}
          />
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
