import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import {
  ActionIcon,
  Button,
  Center,
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
  hasLiveValues,
  AlwaysSelectedPickers,
  ScopeBanner,
  scopeUnits,
  AvailableFilterValuesProvider,
  DataVersionProvider,
  dataVersionBody,
  isCurrentDataOnlyType,
  DashboardGrid,
  FilterPanel,
  FunnelView,
  TopPanel,
  mergeFiltersBySource,
  withInteractiveDefaults,
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
  partitionFloating,
  isFloatingComponent,
  useCrossTabComponents,
  PersistentSectionsHost,
  readCrossTabFilters,
  writeCrossTabFilters,
  clearCrossTabFilters,
  persistableCrossTabFilters,
  readFiltersFromLocation,
  syncFiltersToLocation,
  sanitizeRestoredFilters,
  fetchDashboardFilterState,
  saveDashboardFilterState,
  FILTER_PANEL_RAIL_WIDTH,
  countActiveFilters,
  useSelectionGroups,
  useCategoricalColumns,
  useColorByColumnRender,
  resolveGroupRender,
  SelectionGroupsPanel,
  SaveGroupContext,
  BrandScope,
  tabLinkKey,
  buildGuideModel,
  resolveGuideSettings,
  CategoryColorsContext,
  barSectionNames,
  filtersInScope,
  hasSectionBar,
  isBarMember,
  isBarSection,
  mergeFilterScopes,
  planScopedRequests,
  sectionFilterScopes,
  AdvancedVizPlacementDefaultProvider,
  HighlightProvider,
} from 'depictio-react-core';
import type {
  DashboardData,
  FilterSectionSpec,
  DashboardPermissions,
  DashboardSummary,
  CrossTabComponentsResponse,
  InteractiveFilter,
  RealtimeMode,
  ActiveHighlight,
  RealtimeJournalEntry,
  IngestionSummary,
  StoredMetadata,
  CommentViewState,
} from 'depictio-react-core';
import { parseTemplateOrigin } from './projects/template';
import { extractPreviewVersionId, previewDataRequest } from './versions/preview';

/** localStorage key for the dismissed ingestion banner, scoped per project so
 *  the dismissal sticks across the dashboard's sibling tabs. */
const ingestionBannerKey = (projectId: string) =>
  `depictio:ingestion-banner-dismissed:${projectId}`;

/** How long the filter must hold still before the dashboard re-fetches.
 *
 *  Long enough to swallow a burst of MultiSelect picks or a slider drag, short
 *  enough that a single deliberate change still feels immediate. */
const FILTER_DEBOUNCE_MS = 250;

/** Debounce for the per-user server-side filter-state write. Longer than the
 *  fetch debounce: persistence has no visible latency to hide, so it can wait
 *  out a whole burst of interaction. */
const SAVE_FILTER_STATE_DEBOUNCE_MS = 800;
import { notifications } from '@mantine/notifications';
import { Sidebar, RunParametersHost, SettingsDrawer, TabIntro } from './chrome';
import type { HeaderAction } from './chrome/Header';
import ShellHost from './chrome/shell/ShellHost';
import type { FilterPanelOptions } from './chrome/shell/types';
import { useChromeVariant } from './chrome/variants';
import TabLinkProvider from './chrome/TabLinkProvider';
import { useSidebarOpen } from './hooks/useSidebarOpen';
import { useContentScaleStyle } from './hooks/useUiScalePref';
import { setContentWidthScope, useContentMaxWidth } from './hooks/useContentWidthPref';
import { useFilterPanelOpen } from './hooks/useFilterPanelOpen';
import { FILTER_PANEL_WIDTH_VAR, useFilterPanelWidth } from './hooks/useFilterPanelWidth';
import { useCurrentUser } from './hooks/useCurrentUser';
import { isDashboardOwner } from './lib/dashboardOwnership';
import {
  readLocalFilterState,
  writeLocalFilterState,
  clearLocalFilterState,
  readRememberToggle,
  writeRememberToggle,
} from './lib/filterStateStorage';
import { FILTER_PANEL_RESIZER_WIDTH } from './components/FilterPanelResizer';
import GroupingHeaderControl, {
  ANALYSIS_PANEL_WIDTH_PX,
} from './components/GroupingHeaderControl';
import Inspector from './chrome/inspector/Inspector';
import { useInspectorChrome } from './chrome/inspector/useInspectorChrome';
import InspectorProviders from './chrome/inspector/InspectorProviders';
import { CommentsHeaderButton, CommentsProvider } from './components/comments';
import ComponentExportProvider from './components/export/ComponentExportProvider';
import NotesFooter from './components/NotesFooter';
import DashboardLoadIndicator from './components/DashboardLoadIndicator';
import BootSplash from './components/BootSplash';
import { usePageTitle } from './branding';
import { DashboardGuide, useGuideRoute } from './guide';
import { LandingHint, useLandingHint } from './landing';
import { DashboardSpotlight } from './spotlight';
import { useLayoutOverride } from './layoutOverride';
import type { SettingsSectionKey } from './chrome/SettingsDrawer';
import VersionPreviewBanner from './versions/VersionPreviewBanner';
import { dashboardHref } from './dashboards/lib/dashboardLinks';

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
  // Seed synchronously from three sources merged per (index, source) key, in
  // ascending priority: this dashboard's remembered filters (localStorage, when
  // "Remember my filters" is on) -> the cross-tab selection (floating map,
  // persistent sections) -> a `#filters=` share-link fragment, consumed once
  // and stripped from the address bar. Hydrating in an effect instead would
  // let every grid tile fetch once unfiltered before the seed landed, then
  // again straight after. The cross-tab entries are validated against the real
  // cross-tab components once they resolve (`handleCrossTabResolved`); the
  // rest against the dashboard's own components (`restoredPruned` below).
  //
  // Lazily, because `useRef`'s argument is evaluated on EVERY render and the
  // hydration reads storage and decodes the URL fragment.
  const hydrationRef = useRef<InitialFilterHydration | null>(null);
  if (hydrationRef.current === null) {
    hydrationRef.current = hydrateInitialFilters(extractDashboardId(), extractPreviewVersionId());
  }
  const [filters, setFilters] = useState<InteractiveFilter[]>(hydrationRef.current.filters);
  // Indices we hydrated from the cross-tab store. Only these may be pruned by
  // the cross-tab validation pass — a selection the viewer makes on a *grid*
  // map during this page load, or a filter restored from this dashboard's own
  // remembered state, must never be swept up by it.
  const hydratedIndicesRef = useRef<Set<string> | null>(null);
  if (hydratedIndicesRef.current === null) {
    hydratedIndicesRef.current = new Set(hydrationRef.current.crossTabIndices);
  }
  // Saved selection groups ("select & compare"): annotation state kept apart
  // from `filters` — the user's filter list stays theirs, and the active
  // groups are only *composed in* at the fetch boundary below. That keeps
  // group entries out of mergeFiltersBySource / the clear-chip path, where a
  // derived filter could not be cleared meaningfully.
  //
  // Scoped to the dashboard FAMILY (parent id), not the tab: a multi-tab
  // dashboard's tabs share the same data collections, so groups saved on one
  // tab apply on the others — same reasoning as the floating map's cross-tab
  // filters. Undefined until the dashboard loads; the hook re-hydrates when
  // the scope id lands.
  const groupingScopeId = useMemo(() => {
    if (!dashboard) return undefined;
    const parent = dashboard.parent_dashboard_id as string | null | undefined;
    const id = parent || dashboard.dashboard_id || extractDashboardId();
    return id ? String(id) : undefined;
  }, [dashboard]);
  const groupsApi = useSelectionGroups(groupingScopeId);
  const combinedFilters = useMemo(
    () =>
      groupsApi.groupFilters.length > 0 ? [...filters, ...groupsApi.groupFilters] : filters,
    [filters, groupsApi.groupFilters],
  );
  // Data fetches follow a *settled* filter, not every intermediate value of one.
  // Interactive components keep reading `filters` directly so their own UI stays
  // instant; only the components that hit the API wait for the pause. Without
  // this, picking three values in a MultiSelect fires three full rounds of
  // renders and the first two are obsolete before they land.
  const [deferredFilters] = useDebouncedValue(combinedFilters, FILTER_DEBOUNCE_MS);

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
  const [settingsOpened, { open: openSettings, close: closeSettings }] = useDisclosure(false);
  const [searchOpened, { open: openSearch, close: closeSearch }] = useDisclosure(false);
  // The section the settings open on when something asks for one (the Guide's
  // "Open Your view"); unset, they open on the one last visited.
  const [settingsSection, setSettingsSection] = useState<SettingsSectionKey | undefined>();
  const openSettingsAt = useCallback(
    (section?: SettingsSectionKey) => {
      setSettingsSection(section);
      openSettings();
    },
    [openSettings],
  );
  const contentScaleStyle = useContentScaleStyle();
  const contentMaxWidth = useContentMaxWidth();
  const {
    user: currentUser,
    inspectorEnabled,
    embedEnabled,
    embedFramingEnabled,
    isPublicMode,
    isDemoMode,
    loading: userLoading,
  } = useCurrentUser();
  const isOwner = isDashboardOwner(dashboard, currentUser?.email ?? null);
  // `control` is null while the flag is off, so no provider value reaches the
  // component chrome and no inspect action is rendered anywhere.
  const { control: inspectorControl, aside: inspectorAside } =
    useInspectorChrome(inspectorEnabled);

  const dashboardId = extractDashboardId();
  // Read once per mount: a tab switch is a full navigation, so this cannot
  // change without remounting.
  const previewVersionId = extractPreviewVersionId();
  // Edit affordances are gated on this rather than `isOwner`: editing a past
  // version makes no sense, and the editor would autosave it over the live
  // dashboard. House style is visible-but-disabled, which the Header's
  // existing tooltip already handles.
  const canEditNow = isOwner && !previewVersionId;

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
  // siblings: floating maps + persistent sections. In a `?version=` preview,
  // as they were in that version: today's parent sections drawn over the
  // version's data would be a view that never existed.
  const crossTab = useCrossTabComponents(
    dashboardId ?? '',
    handleCrossTabResolved,
    previewVersionId,
  );

  // Panel chrome state is scoped to the dashboard *family*: a tab switch is a
  // full page navigation to a sibling dashboard document, so per-dashboard
  // keys would reset the panel on every switch. Until the family id resolves
  // (one fetch, see useCrossTabComponents) the tab's own id stands in, and the
  // hooks re-read storage when the key changes underneath them.
  const panelScopeId = crossTab.familyId ?? dashboardId;

  // Tab sidebar (desktop): open by default, remembered per dashboard family.
  const [desktopOpened, toggleDesktop] = useSidebarOpen(panelScopeId);

  // Left filter panel chrome. Width first: the collapse swing is the width the
  // content column reclaims, which is everything but the icon rail.
  const {
    width: filterPanelWidth,
    resizing: filterPanelResizing,
    layoutRef: filterPanelLayoutRef,
    beginResize: beginFilterPanelResize,
    nudge: nudgeFilterPanelWidth,
  } = useFilterPanelWidth(panelScopeId);
  // The swing spans both variable tracks: collapsing takes the panel down to
  // the rail *and* the drag handle down to nothing. The grid gaps don't move,
  // so they cancel out.
  const [filterPanelOpened, toggleFilterPanel] = useFilterPanelOpen(
    panelScopeId,
    filterPanelWidth + FILTER_PANEL_RESIZER_WIDTH - FILTER_PANEL_RAIL_WIDTH,
    dashboard?.filter_panel_default === 'collapsed',
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

  // Data time travel, read-only in the viewer.
  //
  // Choosing which data to draw from is an editing act and lives in the
  // editor. The one case the viewer owns is a `?version=` preview: the server
  // overlays the version's content, and every render request then has to carry
  // that version's data pins and its definition version too, or the preview is
  // a past layout drawn through today's definitions over today's numbers.
  // `previewDataRequest` is null for the live dashboard, which keeps every
  // request byte-identical to what it was without this feature.
  const previewRequest = useMemo(() => previewDataRequest(dashboard), [dashboard]);
  // Request fragment + a stable dependency key. The key has to reach every
  // fetch effect: without it the body would change while the effect never
  // re-ran, leaving stale numbers under a new label.
  const versionBody = useMemo(
    () => (previewRequest ? dataVersionBody(previewRequest) : {}),
    [previewRequest],
  );
  const versionKey = JSON.stringify(versionBody);

  const bulkCtrl = useRef<AbortController | null>(null);

  // Ingestion-health banner: for template-derived dashboards, surface a
  // prominent prompt when a required data collection was not found during
  // ingestion (or things came in partial). Best-effort — never blocks the view.
  const [ingestionHealth, setIngestionHealth] = useState<IngestionSummary | null>(null);
  const [ingestionProjectId, setIngestionProjectId] = useState<string | null>(null);
  const [ingestionBannerDismissed, setIngestionBannerDismissed] = useState(false);

  // Keep the browser tab title in sync with the dashboard name.
  usePageTitle(dashboard?.title || dashboardId);

  // Fetch dashboard + tab list in parallel.
  //
  // With `?version=<id>` the server overlays that version's content onto the
  // live document (identity and access stay live), so every component path
  // below is unchanged. Read-only by construction: Edit is withheld while a
  // version is previewed.
  useEffect(() => {
    if (!dashboardId) {
      setError('No dashboard ID in URL. Expected /dashboard/<id>.');
      setLoading(false);
      return;
    }
    Promise.all([fetchDashboard(dashboardId, previewVersionId), fetchAllDashboards()])
      .then(([dash, all]) => {
        setDashboard(dash);
        // Declared filter defaults (`default_value` / `default_range`) land in
        // the same batch as the dashboard, so the first render is already
        // filtered. Values hydrated from storage keep precedence.
        setFilters((prev) => withInteractiveDefaults(prev, dash.stored_metadata));
        setAllDashboards(all);
      })
      .catch((err) => {
        setError(`Failed to load dashboard: ${err.message || err}`);
      })
      .finally(() => setLoading(false));
  }, [dashboardId, previewVersionId]);

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

  // Which filters belong to a section's own bar, and so reach that section's
  // components only (see `filterScope.ts`): this tab's section bars, plus those
  // of the persistent sections its siblings fan out here. Every fetch below
  // goes through it — the grid's cells, the cards, the funnel, the maps.
  const filterScopes = useMemo(
    () =>
      mergeFilterScopes(
        sectionFilterScopes(dashboard?.stored_metadata, dashboard?.grid_sections),
        ...crossTab.persistentSections
          .filter(
            (s) =>
              s.kind === 'grid' && s.owner_dashboard_id !== dashboardId && hasSectionBar(s.spec),
          )
          .map((s) =>
            sectionFilterScopes(
              s.components.map((c) => c.metadata),
              [s.spec],
              s.owner_dashboard_id,
            ),
          ),
      ),
    [dashboard?.stored_metadata, dashboard?.grid_sections, crossTab.persistentSections, dashboardId],
  );

  // Bulk-compute card values whenever the settled filter changes.
  //
  // The debounce used to live here as a local `setTimeout`; it now comes from
  // `deferredFilters`, shared with every other component. Keeping a second one
  // stacked on top would have delayed cards by twice as long as the figures
  // next to them, so they'd visibly lag behind the rest of the dashboard.
  //
  // One request per distinct filter set: a card in a section with a bar of its
  // own is computed under that bar's filters, every other card without them
  // (`planScopedRequests`). With no section bar filtering, that is the single
  // request it always was.
  useEffect(() => {
    if (!dashboard || !dashboardId) return;
    // Text tiles with live values (`{{name}}`, `{{param:KEY}}`) ride along.
    const cards = (dashboard.stored_metadata || [])
      .filter((m) => m.component_type === 'card' || hasLiveValues(m))
      .map((m) => ({ id: m.index, scope: typeof m.section === 'string' ? m.section : null }));
    if (cards.length === 0) return;

    setCardsLoading(true);
    // Keep the previous card values mounted while the new bulk-compute
    // round-trip is in flight. ``cardsLoading`` is what CardRenderer
    // already consults to dim the value — clearing the values here would
    // snap every card back to ``…`` on every keystroke / drag step.
    if (bulkCtrl.current) bulkCtrl.current.abort();
    bulkCtrl.current = new AbortController();
    const signal = bulkCtrl.current.signal;
    Promise.all(
      planScopedRequests(cards, deferredFilters, filterScopes).map((req) =>
        bulkComputeCards(
          dashboardId,
          req.filters,
          req.ids,
          groupsApi.bulkOptions,
          // Wired to the abort above: without it a slow superseded response
          // (e.g. compare-on forces real Delta loads) could land after a fast
          // newer one and resurrect stale card strips.
          signal,
          // A `?version=` preview computes cards from the version's data and
          // definitions, like every other renderer under DataVersionProvider.
          versionBody,
        ),
      ),
    )
      .then((responses) => {
        const values: Record<string, unknown> = {};
        const secondary: Record<string, Record<string, unknown>> = {};
        for (const res of responses) {
          Object.assign(values, res.values);
          Object.assign(secondary, res.secondary_values || {});
        }
        setCardValues(values);
        setCardSecondaryValues(secondary);
      })
      .catch((err) => {
        if (err?.name !== 'AbortError') console.warn('[App] bulk-compute failed:', err);
      })
      .finally(() => {
        if (!signal.aborted) setCardsLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    dashboard,
    dashboardId,
    deferredFilterKey,
    filterScopes,
    refreshTick,
    // Undefined while compare is off, so group edits don't refire the fetch.
    JSON.stringify(groupsApi.bulkOptions ?? null),
    versionKey,
  ]);


  const floatingIndices = useMemo(
    () => new Set(crossTab.floating.map((c) => c.metadata.index)),
    [crossTab.floating],
  );
  // Grid sections with a filter bar (drawn as one, or carrying their own):
  // their interactive components render in the grid, not in the filter panel.
  const barNames = useMemo(
    () => barSectionNames(dashboard?.grid_sections as FilterSectionSpec[] | undefined),
    [dashboard?.grid_sections],
  );
  const persistentFilterIndices = useMemo(
    () =>
      new Set([
        ...crossTab.persistentSections
          .filter((s) => s.kind === 'filter')
          .flatMap((s) => s.components.map((c) => c.metadata.index)),
        // A persistent filter bar's controls are filters on every tab too. The
        // fan-out lists them under their grid section; this tab's own are added
        // here as well, so they persist even against a server that predates
        // filter bars and so does not list them.
        ...crossTab.persistentSections
          .filter((s) => s.kind === 'grid' && isBarSection(s.spec))
          .flatMap((s) => s.components.map((c) => c.metadata))
          .filter((m) => m.component_type === 'interactive')
          .map((m) => m.index),
        ...(dashboard?.stored_metadata ?? [])
          .filter((m) => {
            if (!isBarMember(m, barNames)) return false;
            const spec = (dashboard?.grid_sections ?? []).find((g) => g.name === m.section);
            return Boolean(spec?.persistent);
          })
          .map((m) => m.index),
      ]),
    [crossTab.persistentSections, dashboard, barNames],
  );
  // Persistent sections owned by *other* tabs. The current tab's own persistent
  // sections render natively (grid ones in DashboardGrid, filter ones in the
  // panel) — fanning them out too would draw them twice.
  // The width preference is per tab, opening at the author's
  // `content_width_default` until the viewer picks one.
  useEffect(() => {
    setContentWidthScope(dashboardId ?? null, dashboard?.content_width_default);
  }, [dashboardId, dashboard?.content_width_default]);
  // The tab's displayed name, which `exclude_tabs` lists: the parent answers to
  // its main-tab label, a child to its title.
  const currentTabKey = useMemo(() => {
    if (!dashboard) return '';
    const mainName = (dashboard as { main_tab_name?: unknown }).main_tab_name;
    const name = dashboard.parent_dashboard_id
      ? dashboard.title
      : (typeof mainName === 'string' && mainName) || dashboard.title;
    return name ? tabLinkKey(name) : '';
  }, [dashboard]);
  const excludedHere = useCallback(
    (spec: FilterSectionSpec | null | undefined) =>
      Boolean(
        currentTabKey &&
          spec?.persistent &&
          spec.exclude_tabs?.some((t) => tabLinkKey(t) === currentTabKey),
      ),
    [currentTabKey],
  );
  const foreignPersistentSections = useMemo(
    () =>
      crossTab.persistentSections.filter(
        (s) => s.owner_dashboard_id !== dashboardId && !excludedHere(s.spec),
      ),
    [crossTab.persistentSections, dashboardId, excludedHere],
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

  // Persistent grid sections owned by sibling tabs — the "always in view"
  // slot a metadata table lands in on every tab. `pin: top` renders through
  // DashboardGrid's `beforeSections` slot: after the tab's own unsectioned
  // components (its title / intro text) but before its named sections — the
  // same order the owning tab draws. `pin: bottom` stays a sibling after the
  // whole grid. Sections this tab owns render inside DashboardGrid itself,
  // where they stay editable.
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
  // Tiles a preview badges "Current data" (they never read a pin), so the
  // banner can say so once rather than leave each badge to be found.
  const currentDataOnlyCount = useMemo(
    () => summaryMetadata.filter((m) => isCurrentDataOnlyType(m.component_type)).length,
    [summaryMetadata],
  );

  // True once the viewer has changed a filter this page load. Gates the server
  // reconcile (never replace what they are actively doing) and the debounced
  // server write (never round-trip a state that is only the hydration echoed
  // back).
  const userTouchedRef = useRef(false);

  const handleFilterChange = useCallback(
    (update: InteractiveFilter) => {
      userTouchedRef.current = true;
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

  // A bar's "Reset": its own controls go back to their declared defaults, as
  // "Reset all" does for the whole tab; everything else stays.
  const handleResetFilterIndices = useCallback(
    (indices: string[]) => {
      userTouchedRef.current = true;
      const drop = new Set(indices);
      const barMetadata = summaryMetadata.filter((m) => drop.has(m.index));
      setFilters((prev) =>
        withInteractiveDefaults(
          prev.filter((f) => !(drop.has(f.index) && f.source === undefined)),
          barMetadata,
        ),
      );
    },
    [summaryMetadata],
  );
  // What filters the tab as a whole: everything but the section bars'. For the
  // components that sit in no section — the floating and docked maps, the
  // funnel overview.
  const tabFilters = useMemo(
    () => filtersInScope(combinedFilters, filterScopes, null),
    [combinedFilters, filterScopes],
  );
  const tabDeferredFilters = useMemo(
    () => filtersInScope(deferredFilters, filterScopes, null),
    [deferredFilters, filterScopes],
  );

  /**
   * Restore the view a comment was written against: its filters replace the
   * current ones, each through the same dc_id enrichment and (index, source)
   * dedupe as a live filter change. The attached selection's raw filters are
   * merged too, so a thread that only kept its selection still restores it.
   */
  const handleApplyViewState = useCallback(
    (viewState: CommentViewState) => {
      userTouchedRef.current = true;
      const incoming = [
        ...(viewState.filters ?? []),
        ...((viewState.selection?.filters as InteractiveFilter[] | undefined) ?? []),
      ];
      setFilters(
        incoming.reduce<InteractiveFilter[]>(
          (acc, f) => mergeFiltersBySource(acc, enrichFilterWithDcId(f, summaryMetadata)),
          [],
        ),
      );
      // Group filters narrow the dashboard outside the filter list, and a
      // thread's view does not record them: release them, as "Reset all"
      // does, so the restored view matches what the author saw.
      groupsApi.deactivateAllGroupFilters();
    },
    [summaryMetadata, groupsApi.deactivateAllGroupFilters],
  );

  const handleResetAllFilters = useCallback(() => {
    userTouchedRef.current = true;
    // "Reset all" returns to the author's initial view: declared defaults
    // come back, everything else is cleared.
    setFilters(withInteractiveDefaults([], dashboard?.stored_metadata));
    // Group filters live outside the filter list but narrow the dashboard all
    // the same — "Reset all" must release them too or the data stays filtered
    // with no visible chip explaining why.
    groupsApi.deactivateAllGroupFilters();
  }, [groupsApi.deactivateAllGroupFilters, dashboard?.stored_metadata]);

  // The dashboard-wide floating panels, one per kind of thing that can float:
  // the family's floating maps, and its floating 3D structures. Each has its own
  // hidden/floating/docked state, shared by its header control and the panel
  // itself.
  const floatingByKind = useMemo(() => partitionFloating(crossTab.floating), [crossTab.floating]);
  const mapPanel = useMapPanel({
    components: floatingByKind.map,
    familyId: crossTab.familyId,
    // Instant filters, not the debounced copy: the badge and the selection
    // summary should not lag behind the click that set them.
    filters,
    onFilterChange: handleFilterChange,
  });
  const structurePanel = useMapPanel({
    kind: 'structure',
    components: floatingByKind.structure,
    familyId: crossTab.familyId,
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

  // ---- Remembered filters (issue #936) --------------------------------------
  // Hybrid: localStorage restores instantly (hydrated in the useState
  // initializer above), the per-user server copy reconciles asynchronously so
  // the view follows the viewer across browsers. Every filter level rides
  // along: panel controls and scatter / table / map / image selections all
  // live in the one `filters` array being persisted. A `?version=` preview is
  // a read-only view of the past: it neither restores nor remembers anything.
  const remembering = Boolean(dashboardId) && !previewVersionId;
  const [rememberFilters, setRememberFilters] = useState<boolean>(() =>
    dashboardId ? readRememberToggle(dashboardId) : true,
  );

  // Mirror of `filters` for callbacks that must not rebuild per keystroke.
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  const handleRememberFiltersChange = useCallback(
    (on: boolean) => {
      setRememberFilters(on);
      if (!dashboardId) return;
      writeRememberToggle(dashboardId, on);
      if (on) {
        writeLocalFilterState(dashboardId, filtersRef.current);
        void saveDashboardFilterState(dashboardId, filtersRef.current, true);
      } else {
        // Forget the stored state but keep what is on screen: switching this
        // off is about the next visit, not this one. A PUT rather than a
        // DELETE, so the OFF preference roams to the viewer's other browsers.
        clearLocalFilterState(dashboardId);
        void saveDashboardFilterState(dashboardId, [], false);
      }
    },
    [dashboardId],
  );

  // Drop restored entries (local state, share link) that no longer match a
  // component of this dashboard family: stale storage, a deleted tile, a link
  // minted on another tab. Waits for the family-wide metadata (this tab's
  // components plus the cross-tab ones) so a restored map selection is judged
  // against the floating maps too. Cross-tab entries are not touched here:
  // `handleCrossTabResolved` owns them.
  const restoredPrunedRef = useRef(false);
  useEffect(() => {
    if (!dashboard || !crossTab.resolved || restoredPrunedRef.current) return;
    restoredPrunedRef.current = true;
    const restored = hydrationRef.current?.restoredIndices;
    if (!restored || restored.size === 0) return;
    const known = new Set(summaryMetadata.map((m) => m.index));
    setFilters((prev) =>
      prev.filter(
        (f) =>
          !restored.has(f.index) || hydratedIndicesRef.current?.has(f.index) || known.has(f.index),
      ),
    );
  }, [dashboard, crossTab.resolved, summaryMetadata]);

  // Whether the current filters are the viewer's own view rather than the
  // dashboard's declared defaults, which are not worth remembering or writing
  // into the address bar: they were changed, restored, or arrived in a link.
  const viewIsTheirs = () =>
    userTouchedRef.current ||
    serverStateAppliedRef.current ||
    Boolean(hydrationRef.current?.urlConsumed) ||
    (hydrationRef.current?.restoredIndices.size ?? 0) > 0;

  // Local write, derived from `filters` on every change (like the cross-tab
  // write above), so "Reset all" empties the stored copy for free.
  useEffect(() => {
    if (!remembering || !dashboardId || !rememberFilters || !viewIsTheirs()) return;
    writeLocalFilterState(dashboardId, filters);
  }, [filters, dashboardId, rememberFilters, remembering]);

  // The address bar carries the view: `#filters=` follows the filters, so the
  // page's own URL can be copied and pasted as the link. Debounced, because
  // browsers throttle history writes and a slider drag is a burst.
  useEffect(() => {
    if (!remembering) return;
    if (!rememberFilters) {
      // Not remembering: a fragment left from before would mislead.
      syncFiltersToLocation([]);
      return;
    }
    if (!viewIsTheirs()) return;
    const timer = window.setTimeout(() => syncFiltersToLocation(filters), 300);
    return () => window.clearTimeout(timer);
  }, [filters, remembering, rememberFilters]);

  // Server write: debounced, and only once the viewer has changed a filter.
  const serverSaveTimer = useRef<number | null>(null);
  const pendingServerSave = useRef<InteractiveFilter[] | null>(null);
  useEffect(() => {
    if (!remembering || !dashboardId || !rememberFilters || !userTouchedRef.current) return;
    pendingServerSave.current = filters;
    if (serverSaveTimer.current) window.clearTimeout(serverSaveTimer.current);
    serverSaveTimer.current = window.setTimeout(() => {
      pendingServerSave.current = null;
      void saveDashboardFilterState(dashboardId, filters, true);
    }, SAVE_FILTER_STATE_DEBOUNCE_MS);
    return () => {
      if (serverSaveTimer.current) window.clearTimeout(serverSaveTimer.current);
    };
  }, [filters, dashboardId, rememberFilters, remembering]);

  // A tab switch is a full page navigation, so a click right after a filter
  // change would lose the debounced write. `keepalive` lets it outlive the page.
  useEffect(() => {
    if (!dashboardId) return;
    const flush = () => {
      if (pendingServerSave.current === null) return;
      void saveDashboardFilterState(dashboardId, pendingServerSave.current, true, {
        keepalive: true,
      });
      pendingServerSave.current = null;
    };
    window.addEventListener('pagehide', flush);
    return () => window.removeEventListener('pagehide', flush);
  }, [dashboardId]);

  // Server reconcile: fetched once per dashboard, applied only when it is the
  // best information available: saved, newer than what localStorage restored,
  // no share link in play, and the viewer has not started interacting.
  const [serverFilterState, setServerFilterState] = useState<InteractiveFilter[] | null>(null);
  const serverStateAppliedRef = useRef(false);
  useEffect(() => {
    if (!remembering || !dashboardId) return;
    let cancelled = false;
    (async () => {
      const res = await fetchDashboardFilterState(dashboardId);
      if (cancelled || !res || !res.persisted) return;
      if (res.enabled === false) {
        // Switched off in another browser: adopt it here.
        setRememberFilters(false);
        writeRememberToggle(dashboardId, false);
        clearLocalFilterState(dashboardId);
        return;
      }
      if (!readRememberToggle(dashboardId)) return;
      if (hydrationRef.current?.urlConsumed) return;
      const serverAt = res.updated_at ? Date.parse(res.updated_at) : 0;
      if (Number.isNaN(serverAt) || serverAt <= (hydrationRef.current?.localUpdatedAt ?? 0)) {
        return;
      }
      if (res.filters.length > 0) setServerFilterState(res.filters);
    })();
    return () => {
      cancelled = true;
    };
  }, [dashboardId, remembering]);
  useEffect(() => {
    if (!serverFilterState || !dashboard || !crossTab.resolved || serverStateAppliedRef.current) {
      return;
    }
    serverStateAppliedRef.current = true;
    if (userTouchedRef.current) return;
    const sane = sanitizeRestoredFilters(
      serverFilterState,
      new Set(summaryMetadata.map((m) => m.index)),
    );
    if (sane.length === 0) return;
    setFilters((prev) => sane.reduce((acc, f) => mergeFiltersBySource(acc, f), prev));
  }, [serverFilterState, dashboard, crossTab.resolved, summaryMetadata]);

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
  // Never while previewing a past version: a live data push would refresh the
  // grid underneath a historical view, which is incoherent.
  const realtimeEnabled = Boolean(dashboard?.project_realtime?.enabled) && !previewVersionId;
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
      // Parent (tab_order=0) first, then children by `tab_order` — the order the
      // dashboard YAML authored and the editor already honours. Sorting by title
      // instead, as this did, meant a viewer never saw the reading order the
      // author laid out: on the ampliseq template it put "Sampling Campaign"
      // (tab_order 1) last, behind every alphabetically earlier analysis tab.
      // Title stays as the tiebreaker for tabs that carry no order.
      const ao = a.tab_order ?? (a.parent_dashboard_id ? 1 : 0);
      const bo = b.tab_order ?? (b.parent_dashboard_id ? 1 : 0);
      if (ao !== bo) return ao - bo;
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
  // The reader's chrome style (Glass or Classic, see chrome/variants).
  useChromeVariant();

  const interactiveComponents = useMemo(
    () => (dashboard?.stored_metadata || []).filter((m) => m.component_type === 'interactive'),
    [dashboard],
  );
  const topComponents = useMemo(
    () => interactiveComponents.filter((m) => m.placement === 'top'),
    [interactiveComponents],
  );
  const leftComponents = useMemo(() => {
    const own = interactiveComponents.filter(
      (m) => m.placement !== 'top' && !isBarMember(m, barNames),
    );
    const seen = new Set(own.map((m) => m.index));
    // Controls fanned out from sibling tabs' persistent filter sections render
    // as ordinary panel rows: their renderers fetch options by dc_id/column,
    // not by dashboard id, so no further plumbing is needed.
    const foreign = foreignFilterSections
      .flatMap((s) => s.components.map((c) => c.metadata))
      .filter((m) => !seen.has(m.index) && m.placement !== 'top');
    return foreign.length ? [...own, ...foreign] : own;
  }, [interactiveComponents, foreignFilterSections, barNames]);
  // The filter bars' controls, drawn by the grid in their section.
  const barComponents = useMemo(
    () => interactiveComponents.filter((m) => isBarMember(m, barNames)),
    [interactiveComponents, barNames],
  );
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
  // Filter-active groups as removable active-filter summary rows.
  const groupSummaryRows = groupsApi.summaryRows;
  // Categorical columns offered by the global "Color by" select, and the
  // stable palette for the currently selected column (built from the column's
  // unfiltered universe so colors survive filtering).
  const colorByColumns = useCategoricalColumns(dashboard?.stored_metadata);
  const colorByColumnRender = useColorByColumnRender(groupsApi.colorBy, colorByColumns);
  // Memoised: the grid keys its per-item render memo on this object's
  // identity, so a fresh one per render would rebuild every cell.
  const groupRender = useMemo(
    () =>
      resolveGroupRender(
        groupsApi.colorBy,
        groupsApi.renderGroups,
        colorByColumnRender,
        groupsApi.displayMode,
        groupsApi.showOther,
      ),
    [
      groupsApi.colorBy,
      groupsApi.renderGroups,
      colorByColumnRender,
      groupsApi.displayMode,
      groupsApi.showOther,
    ],
  );

  // Persistent grid sections owned by sibling tabs — the "always in view" slot
  // a metadata table lands in on every tab. Handed to DashboardGrid as
  // `beforeSections` so a `pin: top` section renders after this tab's own
  // unsectioned components (its title and intro) rather than ahead of them.
  // Declared here, below `groupRender` and `handleFilterChange`: it reads both.
  const topSectionsHost =
    topGridSections.length > 0 ? (
      <div>
        <PersistentSectionsHost
          sections={topGridSections}
          familyId={crossTab.familyId}
          slot="top"
          filters={deferredFilters}
          controlFilters={filters}
          filterScopes={filterScopes}
          onFilterChange={handleFilterChange}
          refreshTick={refreshTick}
          groupRender={groupRender}
          bulkOptions={groupsApi.bulkOptions}
          onResetFilters={handleResetAllFilters}
          onResetBarFilters={handleResetFilterIndices}
          autofit={dashboard?.autofit !== false}
        />
      </div>
    ) : null;

  // The Grouping panel's body. Mounted once, inside the header "Analysis"
  // popover (GroupingHeaderControl) — the panel is dashboard-family state and
  // has to stay reachable when the per-tab filter panel is collapsed.
  const groupsSection = (
    <SelectionGroupsPanel
      filters={filters}
      components={summaryMetadata}
      groups={groupsApi.groups}
      colorBy={groupsApi.colorBy}
      colorByColumns={colorByColumns}
      compareInCards={groupsApi.compareInCards}
      onCreateGroup={groupsApi.createGroupFromFilter}
      onClearSelection={handleFilterChange}
      onUpdateGroup={groupsApi.updateGroup}
      onDeleteGroup={groupsApi.deleteGroup}
      onToggleGroupFilter={groupsApi.toggleGroupFilter}
      onColorByChange={groupsApi.setColorBy}
      onCompareInCardsChange={groupsApi.setCompareInCards}
      displayMode={groupsApi.displayMode}
      onDisplayModeChange={groupsApi.setDisplayMode}
      showOther={groupsApi.showOther}
      onShowOtherChange={groupsApi.setShowOther}
      showOverall={groupsApi.showOverall}
      onShowOverallChange={groupsApi.setShowOverall}
      onResetAnalysis={groupsApi.resetAnalysis}
    />
  );
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
          // Floating maps and 3D structures are drawn by the floating panels,
          // not the grid. They also carry no layout entry (see dashboards.py),
          // so leaving them here would make the grid auto-place them on top of
          // a tile.
          !isFloatingComponent(m),
      ),
    [dashboard],
  );

  // View mode uses the SAME DashboardGrid + saved-layout source as the editor;
  // only `editMode`/`isDraggable`/`isResizable` differ. Identical visual output
  // for any given dashboard, regardless of which URL the user lands on.
  // A persistent section this tab owns but is excluded from (`exclude_tabs`)
  // drops out here: the owner draws its own sections natively, not through the
  // cross-tab host that filters the foreign ones.
  const excludedOwnSections = useMemo(
    () =>
      new Set(
        ((dashboard?.grid_sections as FilterSectionSpec[] | undefined) || [])
          .filter((s) => excludedHere(s))
          .map((s) => s.name),
      ),
    [dashboard, excludedHere],
  );
  const rightComponents = useMemo(
    () =>
      [...cardComponents, ...otherComponents, ...barComponents].filter(
        (m) => !(typeof m.section === 'string' && excludedOwnSections.has(m.section)),
      ),
    [cardComponents, otherComponents, barComponents, excludedOwnSections],
  );

  // Same count the panel badges, hoisted so the narrow-screen header button can
  // show it while the panel itself is off screen. Active group filters count
  // too — one per group, matching the panel badge and the summary rows (the
  // projected `groupFilters` merge same-column groups and would undercount).
  const activeFilterCount = countActiveFilters(filters) + groupSummaryRows.length;

  // In-place "save selection as group" on any component with a live selection
  // (chart lasso, table rows, map polygon) — same create/clear flow as the
  // Analysis panel, without the trip to the header.
  // Analysis mode, tracked separately from whether the header panel is open.
  // Mantine dismisses a Popover on mousedown outside it, and that mousedown is
  // the one that starts a lasso — so tying the mode to `analysisOpen` would
  // erase every capability marker exactly when the user acts on one. Opening
  // the panel arms the mode; only the button (or a second click on it) ends it.
  // `armed` is persisted with the groups (a tab switch is a full page
  // navigation, so local state would drop the mode on every tab the groups
  // survive into); `open` stays local, since restoring an open popover on
  // arrival would be worse than closing it.
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const { analysisArmed, setAnalysisArmed } = groupsApi;
  const handleAnalysisOpenChange = useCallback(
    (next: boolean) => {
      setAnalysisOpen(next);
      if (next) setAnalysisArmed(true);
    },
    [setAnalysisArmed],
  );
  const handleAnalysisToggle = useCallback(() => {
    const next = !analysisOpen;
    setAnalysisOpen(next);
    setAnalysisArmed(next);
  }, [analysisOpen, setAnalysisArmed]);

  const saveGroupApi = useMemo(
    () => ({
      groups: groupsApi.groups,
      createGroup: groupsApi.createGroupFromFilter,
      clearSelection: handleFilterChange,
      // "Engaged" spans both ways into analysis: the panel being open (the user
      // is looking for where to act) and a grouping mode being on (the
      // dashboard is already repainted by one). Outside those, capable
      // components stay unmarked so ordinary viewing is unchanged.
      analysisEngaged: analysisArmed || groupsApi.colorBy.kind !== 'none',
    }),
    [
      groupsApi.groups,
      groupsApi.createGroupFromFilter,
      handleFilterChange,
      analysisArmed,
      groupsApi.colorBy.kind,
    ],
  );

  // ---- Guide --------------------------------------------------------------
  // On unless the author turned it off on the main tab. Its page is drawn over
  // the canvas, which stays mounted underneath (see guide/guide.css).
  const guideSettings = useMemo(
    () => resolveGuideSettings(dashboard, tabSiblings),
    [dashboard, tabSiblings],
  );
  const guide = useGuideRoute(Boolean(dashboard) && !loading && !error && guideSettings.enabled);
  const guideModel = useMemo(
    () =>
      guide.open && dashboard
        ? buildGuideModel({
            tabs: tabSiblings,
            currentId: dashboardId,
            components: rightComponents,
            gridSections: dashboard.grid_sections as FilterSectionSpec[] | undefined,
            fannedOutSections: foreignGridSections,
            panelComponents: leftComponents,
            panelSections: panelFilterSections,
            floating: crossTab.floating,
            // The header's own condition for the Analysis button.
            analysisAvailable: Boolean(dashboard),
            inspector: Boolean(inspectorControl),
            mode: 'view',
          })
        : null,
    [
      guide.open,
      dashboard,
      tabSiblings,
      dashboardId,
      rightComponents,
      foreignGridSections,
      leftComponents,
      panelFilterSections,
      crossTab.floating,
      inspectorControl,
    ],
  );
  // ---- Landing hint -------------------------------------------------------
  // A guest on a public instance (the demo keeps its tour) lands on the Overview
  // with one small callout beside the Guide. Opening the Guide, by the hint or
  // the sidebar, is the answer to it: it is dismissed for good.
  const landingEligible =
    Boolean(dashboard) &&
    !loading &&
    !error &&
    !userLoading &&
    isPublicMode &&
    !isDemoMode &&
    Boolean(currentUser?.is_temporary) &&
    !(activeTab?.parent_dashboard_id ?? dashboard?.parent_dashboard_id) &&
    !previewVersionId &&
    guideSettings.enabled;
  const landing = useLandingHint(landingEligible && !guide.open);
  const dismissLanding = landing.dismiss;
  useEffect(() => {
    if (guide.open && landingEligible) dismissLanding();
  }, [guide.open, landingEligible, dismissLanding]);
  // The dashboard's own line (the main tab's `subtitle` is its identity line,
  // as on the listing card), else its name.
  const landingDescription =
    (typeof dashboard?.subtitle === 'string' ? dashboard.subtitle.trim() : '') ||
    (parentTab?.title || dashboard?.title || '').trim() ||
    null;
  // On a phone the sidebar is an overlay: leave it open over the Guide and the
  // Guide is behind it.
  const openGuideFromSidebar = useCallback(() => {
    guide.openGuide();
    if (isNarrow && mobileOpened) toggleMobile();
  }, [guide, isNarrow, mobileOpened, toggleMobile]);
  const closeGuideFromSidebar = useCallback(() => {
    guide.closeGuide();
    if (isNarrow && mobileOpened) toggleMobile();
  }, [guide, isNarrow, mobileOpened, toggleMobile]);
  // The Analysis panel is docked beside the canvas: the Guide takes its place.
  useEffect(() => {
    if (guide.open) setAnalysisOpen(false);
  }, [guide.open]);
  // Before the dashboard search lands on something of this tab: the Guide and,
  // on a phone, the tab list both cover the canvas, and a filter lives in a
  // drawer there.
  const uncoverForSearch = useCallback(
    (index: string | null) => {
      if (guide.open) guide.closeGuide();
      if (isNarrow && mobileOpened) toggleMobile();
      if (index && isNarrow && leftComponents.some((m) => m.index === index)) openFilterDrawer();
    },
    [guide, isNarrow, mobileOpened, toggleMobile, leftComponents, openFilterDrawer],
  );

  // The tab's scope: its `always_selected` filters, shown in a banner under
  // the header.
  const scope = useMemo(() => scopeUnits(summaryMetadata, filterScopes), [summaryMetadata, filterScopes]);
  // `?layout=classic|dock`: view a workbench section as a plain section or as
  // a docked column, to compare the arrangements on the same tab.
  const layoutOverride = useLayoutOverride();

  // The page's regions, handed to the active chrome style's Shell (see
  // chrome/shell/types.ts), which decides where each one goes.
  const ready = Boolean(dashboard) && !loading && !error;
  const headerActions: HeaderAction[] = [];
  if (dashboard) {
    headerActions.push({ id: 'comments', group: 'read', node: <CommentsHeaderButton /> });
    headerActions.push({
      id: 'analysis',
      group: 'read',
      node: (
        <GroupingHeaderControl
          groupCount={groupsApi.groups.length}
          colorBy={groupsApi.colorBy}
          opened={analysisOpen}
          onOpenedChange={handleAnalysisOpenChange}
          armed={analysisArmed}
          onToggle={handleAnalysisToggle}
          pushesContent={!isNarrow}
        >
          {groupsSection}
        </GroupingHeaderControl>
      ),
    });
  }
  if (realtimeEnabled) {
    headerActions.push({
      id: 'realtime',
      group: 'read',
      node: (
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
      ),
    });
  }
  const guideEntry =
      guideSettings.enabled && dashboard
        ? {
            open: guide.open,
            href: guide.href,
            onOpen: openGuideFromSidebar,
            onClose: closeGuideFromSidebar,
          }
        : undefined;
  const filterPanel = (opts?: FilterPanelOptions) =>
    dashboard ? (
      <FilterPanel
        components={leftComponents}
        allMetadata={summaryMetadata}
        filters={filters}
        onFilterChange={handleFilterChange}
        onResetAllFilters={handleResetAllFilters}
        shareLink={remembering}
        layoutData={dashboard.left_panel_layout_data}
        filterSections={panelFilterSections}
        dashboardId={dashboardId}
        stateScopeId={panelScopeId}
        headerActions={
          <>
            <MapPanelControl panel={mapPanel} />
            <MapPanelControl panel={structurePanel} />
          </>
        }
        refreshTick={refreshTick}
        collapsed={opts?.docked ? !filterPanelOpened : undefined}
        onToggleCollapsed={opts?.docked ? toggleFilterPanel : undefined}
        funnel={{
          enabled: funnelEnabled,
          onToggle: () => setFunnelEnabled((v) => !v),
          onOpenView: () => setFunnelViewOpen(true),
        }}
        groupSummaryRows={groupSummaryRows}
        footer={
          opts?.docked ? (
            <>
              <MapPanelDock
                panel={mapPanel}
                // Docked maps render data, so they must see active group
                // filters too (instant copy: group toggles are single clicks,
                // no debounce needed). Tab-wide only: a section bar's filters
                // stay with its section.
                filters={tabFilters}
                onFilterChange={handleFilterChange}
                refreshTick={refreshTick}
                followedByDock={structurePanel.docked}
              />
              <MapPanelDock
                panel={structurePanel}
                // A structure fetches its residue table like any tile, so it
                // follows the settled filters the grid does, the tab's only.
                filters={tabDeferredFilters}
                onFilterChange={handleFilterChange}
                refreshTick={refreshTick}
              />
            </>
          ) : undefined
        }
      />
    ) : null;
  const boot = (
    <>
      {dashboard?.preview && (
        <VersionPreviewBanner
          preview={dashboard.preview}
          dashboardId={dashboardId}
          // Restoring is a write, so it lives in the editor's History; an
          // owner gets the way there. The editor route is owner-only.
          editHref={isOwner && dashboardId ? dashboardHref(dashboardId, 'edit') : null}
          currentDataOnly={currentDataOnlyCount}
        />
      )}
      {ready && <ScopeBanner units={scope} filters={filters} onFilterChange={handleFilterChange} />}
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
    </>
  );
  const canvas =
    ready && dashboard ? (
      <Box
        data-testid="dashboard-content"
        // Under the Guide: kept mounted (and its figures loaded) for when
        // the Guide closes, but neither painted nor in the focus order.
        // Only the canvas: the filter panel stays on screen beside the
        // Guide, so its "Show me" rings the real panel in place.
        aria-hidden={guide.open || undefined}
        style={{
          visibility: guide.open ? 'hidden' : undefined,
          // Page-width preference: the canvas centres in what the
          // filter panel leaves, the panel staying by the sidebar.
          padding: 4,
          ...(contentMaxWidth !== null
            ? {
                paddingInline: `max(4px, calc((100% - ${contentMaxWidth}px) / 2))`,
                transition: 'padding 200ms ease',
              }
            : null),
          height: '100%',
          minWidth: 0,
          overflowY: 'auto',
          overflowX: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          // Content font-size preference — scales the dashboard tiles
          // below, never the surrounding chrome (header, sidebar, panel).
          ...contentScaleStyle,
        }}
      >
        {landing.visible && (
          <LandingHint
            description={landingDescription}
            onOpenGuide={guide.openGuide}
            onDismiss={landing.dismiss}
          />
        )}
        {/* The tab's own description, ahead of everything the canvas
            holds — including a foreign `pin: top` section, which would
            otherwise introduce another tab before this one is named. */}
        <TabIntro dashboard={dashboard} activeTab={activeTab} />
        {/* Only claims the leftover height when nothing follows it —
            otherwise a short grid would push the bottom-pinned sections
            to the fold with a gap above them. */}
        <Box style={{ flex: bottomGridSections.length > 0 ? '0 0 auto' : 1, minHeight: 0 }}>
          {rightComponents.length === 0 ? (
            <>
            {topSectionsHost}
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
                    {canEditNow && ' Start editing to add visualizations, tables, and more.'}
                  </Text>
                </Stack>
                {canEditNow && (
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
            </>
          ) : (
            <DashboardGrid
              dashboardId={dashboardId!}
              metadataList={rightComponents}
              layoutOverride={layoutOverride}
              layoutData={dashboard.right_panel_layout_data}
              gridSections={dashboard.grid_sections}
              beforeSections={topSectionsHost}
              filters={deferredFilters}
              controlFilters={filters}
              filterScopes={filterScopes}
              onResetFilters={handleResetFilterIndices}
              onFilterChange={handleFilterChange}
              cardValues={cardValues}
              cardSecondaryValues={cardSecondaryValues}
              cardValuesLoading={cardsLoading}
              refreshTick={refreshTick}
              activeHighlight={activeHighlight}
              groupRender={groupRender}
              isDraggable={false}
              isResizable={false}
              editMode={false}
              autofit={dashboard?.autofit !== false}
            />
          )}
        </Box>
        {bottomGridSections.length > 0 && (
          <div style={{ flexShrink: 0 }}>
            <PersistentSectionsHost
              sections={bottomGridSections}
              familyId={crossTab.familyId}
              slot="bottom"
              filters={deferredFilters}
              controlFilters={filters}
              filterScopes={filterScopes}
              onResetBarFilters={handleResetFilterIndices}
              onFilterChange={handleFilterChange}
              refreshTick={refreshTick}
              groupRender={groupRender}
              bulkOptions={groupsApi.bulkOptions}
              onResetFilters={handleResetAllFilters}
              autofit={dashboard?.autofit !== false}
            />
          </div>
        )}
      </Box>
    ) : null;
  // Full-width footer spanning both the filter panel and the content column.
  // Hosts top-placement interactive controls (the Timeline scrubber) as an
  // always-visible global filter, pinned below the scrollable columns.
  const topStrip =
    ready && topComponents.length > 0 ? (
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
        <Box style={contentScaleStyle}>
          <TopPanel
            components={topComponents}
            filters={filters}
            onFilterChange={handleFilterChange}
            refreshTick={refreshTick}
          />
        </Box>
      </Box>
    ) : null;
  const overlays = (
    <>
      {dashboardId && (
        <FunnelView
          opened={funnelViewOpen}
          onClose={() => setFunnelViewOpen(false)}
          dashboardId={dashboardId}
          filters={tabDeferredFilters}
          groups={groupsApi.groups}
        />
      )}
      {/* The page's fixed furniture sits above the Guide's layer; hidden
          with the canvas while the Guide is up. */}
      <div style={guide.open ? { visibility: 'hidden' } : undefined}>
        {/* Unmounted while previewing. It would start from the snapshot's
            notes, and `saveDashboardNotes` writes the editor's text onto the
            live dashboard it re-reads, so a save here would put a past
            version's notes over the live ones. */}
        {dashboard && dashboardId && !inspectorEnabled && !previewVersionId && (
          <NotesFooter
            dashboardId={dashboardId}
            initialContent={(dashboard.notes_content as string) ?? ''}
            permissions={dashboard.permissions as DashboardPermissions | undefined}
          />
        )}
        {dashboard && dashboardId && (
          <MapPanelSurface
            panel={mapPanel}
            // Floating maps render data: give them group filters too (see the
            // docked MapPanelDock above), and the tab's only.
            filters={tabFilters}
            onFilterChange={handleFilterChange}
            refreshTick={refreshTick}
          />
        )}
        {dashboard && dashboardId && (
          <MapPanelSurface
            panel={structurePanel}
            // The same settled, tab-wide filters the docked structure reads.
            filters={tabDeferredFilters}
            onFilterChange={handleFilterChange}
            refreshTick={refreshTick}
          />
        )}
      </div>
      {guide.open && guideModel && dashboard && dashboardId && (
        <DashboardGuide
          model={guideModel}
          dashboardId={dashboardId}
          dashboard={dashboard}
          components={rightComponents}
          tabs={tabSiblings}
          persistentSections={crossTab.persistentSections}
          dashboardName={parentTab?.title || dashboard.title || 'Dashboard'}
          tabName={guideModel.tabs.current?.label ?? dashboard.title ?? 'the tab'}
          intro={guideSettings.intro}
          mode="view"
          canEdit={canEditNow}
          onClose={guide.closeGuide}
          onOpenYourView={() => openSettingsAt('view')}
        />
      )}
    </>
  );
  const outside = (
    <>
      <SettingsDrawer
        opened={settingsOpened}
        onClose={closeSettings}
        dashboard={dashboard}
        initialSection={settingsSection}
        filters={
          remembering
            ? {
                current: filters,
                activeCount: countActiveFilters(filters),
                remember: rememberFilters,
                onRememberChange: handleRememberFiltersChange,
              }
            : undefined
        }
      />
      {/* Opens on a dashboard's `params:` links. */}
      <RunParametersHost dashboard={dashboard} />
      {/* Cmd/Ctrl+K and the header's magnifier: search every tab. */}
      <DashboardSpotlight
        opened={searchOpened}
        onOpen={openSearch}
        onClose={closeSearch}
        tabs={tabSiblings}
        currentId={dashboardId}
        dashboard={dashboard}
        mode="view"
        ready={Boolean(dashboard) && !loading && !error}
        onBeforeFocus={uncoverForSearch}
      />
    </>
  );

  return (
    // Every renderer reads its pin from here rather than taking it as a prop:
    // the fetch happens deep in the shared component package, and the decision
    // is made up here. Outermost, so the filter options' availability reads
    // the previewed version's values too.
    <DataVersionProvider
      asOfVersionId={previewRequest?.asOfVersionId}
      definitionVersionId={previewRequest?.definitionVersionId}
      dashboardId={dashboardId}
    >
    <AvailableFilterValuesProvider
      dashboardMetadata={summaryMetadata}
      projectId={dashboard?.project_id}
      funnel={
        dashboardId
          ? { enabled: funnelEnabled, dashboardId, filters: deferredFilters, scopes: filterScopes }
          : undefined
      }
    >
      {/* `always_selected` Selects take their first option here, whether or
          not their control is on screen (panel collapsed, section folded,
          phone drawer closed). Renders nothing. */}
      <AlwaysSelectedPickers
        components={summaryMetadata}
        filters={filters}
        onFilterChange={handleFilterChange}
      />
      <DashboardLoadingProvider>
      {/* One hover bus for the whole view: pinned sections rendered outside
          DashboardGrid share it (the grid's own provider reuses this one). */}
      <HighlightProvider>
      <InspectorProviders control={inspectorControl}>
      {/* Dashboard-wide default for where advanced-viz tiles draw their
          controls. No config sink in the viewer: a reader can still pin a
          tile's controls open, and it stays local to their session. */}
      <AdvancedVizPlacementDefaultProvider value={dashboard?.advanced_viz_controls}>
      <SaveGroupContext.Provider value={saveGroupApi}>
      {/* A dashboard that overrides the instance branding retints its own page
          and nothing else — /dashboards and /admin stay on the instance look. */}
      <BrandScope theme={dashboard?.brand_theme ?? dashboard?.inherited_brand_theme}>
      {/* `category_colors` for the filter bar's chips and anything else that
          colours a category: one value, one colour, on every surface. */}
      <CategoryColorsContext.Provider value={dashboard}>
      <TabLinkProvider tabs={tabSiblings}>
      {/* Only while the server's export API is on: otherwise the provider
          renders its children alone and no tile shows "Export / embed". */}
      <ComponentExportProvider
        enabled={embedEnabled}
        framingEnabled={embedFramingEnabled}
        isPublic={Boolean(dashboard?.is_public)}
      >
      {/* Editors and owners only: for anyone else the provider renders its
          children alone, so no comment badge, button or drawer appears. */}
      <CommentsProvider
        dashboardId={dashboardId}
        metadata={summaryMetadata}
        filters={filters}
        onApplyViewState={handleApplyViewState}
        currentUser={currentUser}
      >
      <ShellHost
        mode="view"
        isNarrow={Boolean(isNarrow)}
        ready={ready}
        headerProps={{
          dashboardId,
          dashboard,
          activeTab,
          parentTab,
          mobileOpened,
          desktopOpened,
          onToggleMobile: toggleMobile,
          onToggleDesktop: toggleDesktop,
          onOpenSettings: () => openSettingsAt(),
          onOpenFilters: isNarrow && leftComponents.length > 0 ? openFilterDrawer : undefined,
          filterCount: activeFilterCount,
          onOpenSearch: dashboard ? openSearch : undefined,
          cardsLoading,
          isOwner: canEditNow,
          titleExtras:
            dashboard && !loading && !error ? (
              <DashboardLoadIndicator metadataList={rightComponents} cardsLoading={cardsLoading} />
            ) : undefined,
          extraActions: headerActions,
        }}
        nav={{
          node: (
            <Sidebar
              tabs={tabSiblings}
              activeId={dashboardId}
              versionId={previewVersionId}
              brandTheme={dashboard?.brand_theme ?? dashboard?.inherited_brand_theme}
              guide={guideEntry}
            />
          ),
          tabs: tabSiblings,
          activeId: dashboardId,
          guide: guideEntry,
          versionId: previewVersionId,
          mobileOpened,
          desktopOpened,
          toggleMobile,
          toggleDesktop,
        }}
        boot={boot}
        canvas={canvas}
        topStrip={topStrip}
        filters={{
          members: leftComponents,
          values: filters,
          onChange: handleFilterChange,
          reset: handleResetAllFilters,
          count: activeFilterCount,
          panel: filterPanel,
          docked: {
            opened: filterPanelOpened,
            toggle: toggleFilterPanel,
            width: filterPanelWidth,
            widthVar: FILTER_PANEL_WIDTH_VAR,
            layoutRef: filterPanelLayoutRef,
            resizing: filterPanelResizing,
            beginResize: beginFilterPanelResize,
            nudge: nudgeFilterPanelWidth,
          },
          drawer: { opened: filterDrawerOpened, open: openFilterDrawer, close: closeFilterDrawer },
        }}
        overlays={overlays}
        outside={outside}
        inspector={{
          enabled: inspectorEnabled,
          node: <Inspector dashboard={dashboard} dashboardId={dashboardId} />,
          aside: inspectorAside,
        }}
        analysis={{ open: analysisOpen, widthPx: ANALYSIS_PANEL_WIDTH_PX }}
        guideOpen={guide.open}
      />
      </CommentsProvider>
      </ComponentExportProvider>
      </TabLinkProvider>
      </CategoryColorsContext.Provider>
      </BrandScope>
      </SaveGroupContext.Provider>
      </AdvancedVizPlacementDefaultProvider>
      </InspectorProviders>
      </HighlightProvider>
      </DashboardLoadingProvider>
    </AvailableFilterValuesProvider>
    </DataVersionProvider>
  );
};

export default App;

// ---------------------------------------------------------------------------

function extractDashboardId(): string | null {
  const path = window.location.pathname;
  const match = path.match(/\/dashboard\/([^/?#]+)/);
  return match?.[1] || null;
}

interface InitialFilterHydration {
  filters: InteractiveFilter[];
  /** Indices that came from the cross-tab store: `handleCrossTabResolved`
   *  validates those. */
  crossTabIndices: Set<string>;
  /** Indices restored from this dashboard's remembered state or a share link:
   *  pruned against the dashboard's own components once they are known. */
  restoredIndices: Set<string>;
  /** A `#filters=` fragment was decoded and applied: the URL wins over the
   *  async server reconcile for this page load. */
  urlConsumed: boolean;
  /** `updatedAt` of the local state as read BEFORE this load's writes refresh
   *  it, so the server reconcile compares against the previous visit and not
   *  against the write this mount just made. */
  localUpdatedAt: number;
}

/** Merge the remembered / cross-tab / share-link filter sources in ascending
 *  priority, so a URL entry replaces a remembered one for the same
 *  (index, source) key while the entries it does not mention survive. A
 *  version preview restores nothing of its own: it is a view of the past. */
function hydrateInitialFilters(
  dashboardId: string | null,
  previewVersionId: string | null,
): InitialFilterHydration {
  // Once per page load. React's dev StrictMode renders the component body
  // twice on mount and keeps the second pass; reading the share-link fragment
  // strips it from the address bar, so a second read would find nothing and
  // the link would silently apply no filters.
  const key = `${dashboardId ?? ''}|${previewVersionId ?? ''}`;
  const cached = hydrationCache.get(key);
  if (cached) return cached;
  const hydration = readInitialFilters(dashboardId, previewVersionId);
  hydrationCache.set(key, hydration);
  return hydration;
}

const hydrationCache = new Map<string, InitialFilterHydration>();

function readInitialFilters(
  dashboardId: string | null,
  previewVersionId: string | null,
): InitialFilterHydration {
  const crossTab = readCrossTabFilters()?.filters ?? [];
  const crossTabIndices = new Set(crossTab.map((f) => f.index));
  if (previewVersionId) {
    return {
      filters: crossTab,
      crossTabIndices,
      restoredIndices: new Set(),
      urlConsumed: false,
      localUpdatedAt: 0,
    };
  }
  const url = readFiltersFromLocation();
  const local =
    dashboardId && readRememberToggle(dashboardId) ? readLocalFilterState(dashboardId) : null;
  const restored = [...(local?.filters ?? []), ...(url ?? [])];
  let merged: InteractiveFilter[] = [];
  for (const f of [...(local?.filters ?? []), ...crossTab, ...(url ?? [])]) {
    merged = mergeFiltersBySource(merged, f);
  }
  return {
    filters: merged,
    crossTabIndices,
    restoredIndices: new Set(restored.map((f) => f.index)),
    urlConsumed: url !== null,
    localUpdatedAt: local?.updatedAt ?? 0,
  };
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
