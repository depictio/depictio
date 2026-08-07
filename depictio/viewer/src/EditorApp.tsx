/*
 * EditorApp — React SPA root for the editor experience.
 *
 * Data flow:
 *   1. Mount → fetchDashboard(id) + fetchAllDashboards() in parallel.
 *   2. Filter state changes → debounced bulkComputeCards (same as App.tsx).
 *   3. Layout drag (left or right panel) → debounced 500ms POST to
 *      /depictio/api/v1/dashboards/save/{id} with the FULL DashboardData,
 *      mutating only `left_panel_layout_data` / `right_panel_layout_data`.
 *   4. Delete → strip from `stored_metadata` + both layout arrays, POST same
 *      endpoint, then re-fetch dashboard.
 *
 * Cross-app navigation URLs:
 *   - Edit component:   /dashboard-edit/{dashboardId}/component/edit/{componentId}
 *   - Add component:    /dashboard-edit/{dashboardId}/component/add/{newUuid}
 *   - Read-only viewer: /dashboard/{dashboardId}
 *   - Editor:           /dashboard/{dashboardId}/edit
 *
 * TODO (post-MVP): factor shared data-loading into a `useDashboardState` hook
 * so App.tsx and EditorApp.tsx don't drift. For now we duplicate the
 * fetch/debounce wiring deliberately to keep `App.tsx` untouched.
 */
import React, {
  useEffect,
  useState,
  useCallback,
  useRef,
  useMemo,
} from 'react';
import {
  ActionIcon,
  AppShell,
  Button,
  Center,
  Drawer,
  Group,
  Text,
  Loader,
  Box,
  Paper,
  Stack,
  Title,
  Tooltip,
} from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { useSidebarOpen } from './hooks/useSidebarOpen';
import { useFilterPanelOpen } from './hooks/useFilterPanelOpen';
import { FILTER_PANEL_WIDTH_VAR, useFilterPanelWidth } from './hooks/useFilterPanelWidth';
import { useCurrentUser } from './hooks/useCurrentUser';
import { isDashboardOwner } from './lib/dashboardOwnership';
import FilterPanelResizer, { FILTER_PANEL_RESIZER_WIDTH } from './components/FilterPanelResizer';
import Inspector from './chrome/inspector/Inspector';
import { useInspectorChrome } from './chrome/inspector/useInspectorChrome';
import InspectorProviders from './chrome/inspector/InspectorProviders';
import type { Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';

import {
  fetchDashboard,
  fetchAllDashboards,
  bulkComputeCards,
  createTab,
  deleteTab,
  reorderTabs,
  updateTab,
  DashboardGrid,
  FilterPanel,
  TopPanel,
  stripBoxPrefix,
  mergeFiltersBySource,
  enrichFilterWithDcId,
  useDataCollectionUpdates,
  RealtimeIndicator,
  useRealtimeJournal,
  batchIdsFromPayload,
  authFetch,
  useMapPanel,
  useCrossTabComponents,
  PersistentSectionsHost,
  MapPanelControl,
  MapPanelDock,
  MapPanelSurface,
  FILTER_PANEL_RAIL_WIDTH,
  countActiveFilters,
  readEditorFilters,
  writeEditorFilters,
  useSelectionGroups,
  useCategoricalColumns,
  useColorByColumnRender,
  resolveGroupRender,
  SelectionGroupsPanel,
  SaveGroupContext,
} from 'depictio-react-core';
import type {
  DashboardData,
  DashboardPermissions,
  DashboardSummary,
  DashboardThemeSpec,
  FilterSectionSpec,
  PersistentSection,
  InteractiveFilter,
  StoredMetadata,
  RealtimeMode,
  ActiveHighlight,
  RealtimeJournalEntry,
  GroupRenderState,
} from 'depictio-react-core';

import GridItemEditOverlay from './components/GridItemEditOverlay';
import SectionModal from './components/sections/SectionModal';
import GroupingHeaderControl from './components/GroupingHeaderControl';
import SectionsModal from './components/sections/SectionsModal';
import { applySectionOp, groupWith, sectionsFor } from './components/sections/sectionMutations';
import type { SectionKind, SectionOp } from './components/sections/sectionMutations';
import { Header, Sidebar, SettingsDrawer, TabModal } from './chrome';
import type { TabModalSubmitPayload } from './chrome';
import NotesFooter from './components/NotesFooter';
import './chrome/chrome.css';

const API_BASE = '/depictio/api/v1';
const SAVE_DEBOUNCE_MS = 500;

/**
 * Dash app base — the component add/edit pages live in the Dash editor on a
 * different port than the FastAPI-served React SPA. In dev: 5122 (Dash) vs
 * 8122 (FastAPI). In production both are typically behind one reverse proxy
 * and same-origin routing works; in that case the env var is empty and we
 * fall back to the current origin.
 */
function dashOrigin(): string {
  const env = (import.meta as unknown as { env?: Record<string, string> }).env;
  if (env?.VITE_DASH_ORIGIN) return env.VITE_DASH_ORIGIN.replace(/\/$/, '');
  // Dev convention: same hostname, port 5122.
  if (
    typeof window !== 'undefined' &&
    window.location.hostname &&
    window.location.port === '8122'
  ) {
    return `${window.location.protocol}//${window.location.hostname}:5122`;
  }
  return '';
}

/** Local POST wrapper for layout/component persistence. Surfaces the response
 *  body on failure so callers can debug 422 validation errors at the console.
 *  Pass `forceScreenshot=true` for an explicit Save click — the backend bypasses
 *  its 1h auto-save debounce and re-queues a fresh thumbnail. Auto-saves should
 *  omit it so drag/resize/rename bursts don't overwhelm the celery worker.
 *
 *  Goes through ``authFetch`` rather than a hand-rolled Authorization header:
 *  an editor session routinely outlives the 1h access token, and a bare header
 *  read from localStorage would make every autosave 401 ("Invalid token") with
 *  nothing to refresh it — silently dropping the user's work. ``authFetch``
 *  refreshes near expiry and retries once on a 401. */
async function saveDashboard(
  dashboardId: string,
  dashboardData: DashboardData,
  opts: { forceScreenshot?: boolean } = {},
): Promise<void> {
  const url = opts.forceScreenshot
    ? `${API_BASE}/dashboards/save/${dashboardId}?force_screenshot=true`
    : `${API_BASE}/dashboards/save/${dashboardId}`;
  const res = await authFetch(url, {
    method: 'POST',
    body: JSON.stringify(dashboardData),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to save dashboard: ${res.status} ${text}`);
  }
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

/**
 * The "…" a section header carries in the editor.
 *
 * One mark for "this section's settings" wherever a section is drawn — the
 * grid, the filter panel, and a section fanned out from another tab, which
 * differ only in where the click leads and in what the tooltip says.
 */
const SectionActionButton: React.FC<{
  label: string;
  ariaLabel?: string;
  onActivate: () => void;
}> = ({ label, ariaLabel = 'Edit section', onActivate }) => (
  <Tooltip label={label} withArrow multiline w={240}>
    <ActionIcon
      size="sm"
      variant="subtle"
      color="gray"
      aria-label={ariaLabel}
      data-testid="section-edit-actions"
      onClick={(e) => {
        e.stopPropagation();
        onActivate();
      }}
    >
      <Icon icon="mdi:dots-vertical" width={16} />
    </ActionIcon>
  </Tooltip>
);

const EditorApp: React.FC = () => {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [allDashboards, setAllDashboards] = useState<DashboardSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Seed synchronously from the per-tab store so a builder round-trip (add or
  // edit a component — a full page navigation) comes back with the filters
  // still active and every tile's FIRST fetch already filtered (#196). An
  // effect-time hydrate would let the grid fetch once unfiltered first, which
  // is exactly the bug this fixes.
  const [filters, setFilters] = useState<InteractiveFilter[]>(() => {
    const id = extractDashboardId();
    return id ? readEditorFilters(id) : [];
  });
  const [cardValues, setCardValues] = useState<Record<string, unknown>>({});
  const [cardSecondaryValues, setCardSecondaryValues] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [cardsLoading, setCardsLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  // Persist across tab/page navigations (matches App.tsx + Dash app).
  const [desktopOpened, toggleDesktop] = useSidebarOpen();
  const [settingsOpened, { open: openSettings, close: closeSettings }] = useDisclosure(false);
  // Bumped after a plot_theme save lands so figure components refetch and pick
  // up the new dashboard-level template/colorway (the server reads plot_theme
  // from the DB at render time, so the request body doesn't change).
  const [plotThemeTick, setPlotThemeTick] = useState(0);
  const [sectionsOpened, { open: openSections, close: closeSections }] = useDisclosure(false);
  /** The one add/edit dialog. `fromManager` is what sends the user back to the
   *  Sections manager on close — the manager closes while this is open rather
   *  than stacking two dialogs. */
  const [sectionModal, setSectionModal] = useState<{
    open: boolean;
    kind: SectionKind;
    target: FilterSectionSpec | null;
    fromManager: boolean;
  }>({ open: false, kind: 'grid', target: null, fromManager: false });
  const { user: currentUser, loading: userLoading, inspectorEnabled } = useCurrentUser();
  // `control` is null while the flag is off, so no provider value reaches the
  // component chrome and no inspect action is rendered anywhere.
  const { control: inspectorControl, aside: inspectorAside } =
    useInspectorChrome(inspectorEnabled);
  // Tab modal state — `mode` decides between create vs edit. `target` is the
  // tab being edited (or null for create). `submitting` blocks Save while a
  // request is in flight.
  const [tabModalState, setTabModalState] = useState<{
    open: boolean;
    mode: 'create' | 'edit';
    target: DashboardSummary | null;
    submitting: boolean;
  }>({ open: false, mode: 'create', target: null, submitting: false });

  const dashboardId = extractDashboardId();

  // Saved selection groups — same hook and same storage key as the viewer, so
  // groups made in one mode are visible in the other. Groups stay out of the
  // `filters` state and are composed in only where data is fetched. Scoped to
  // the dashboard FAMILY (parent id) so groups carry across tabs — see App.tsx.
  const groupingScopeId = useMemo(() => {
    if (!dashboard) return undefined;
    const parent = dashboard.parent_dashboard_id as string | null | undefined;
    const id = parent || dashboard.dashboard_id || dashboardId;
    return id ? String(id) : undefined;
  }, [dashboard, dashboardId]);
  const groupsApi = useSelectionGroups(groupingScopeId);
  const combinedFilters = useMemo(
    () =>
      groupsApi.groupFilters.length > 0 ? [...filters, ...groupsApi.groupFilters] : filters,
    [filters, groupsApi.groupFilters],
  );

  // Left filter panel chrome — same hooks and same storage keys as the viewer,
  // so collapsing or resizing in one mode carries over to the other.
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
  const isNarrow = useMediaQuery('(max-width: 48em)', false, { getInitialValueInEffect: false });
  const [filterDrawerOpened, { open: openFilterDrawer, close: closeFilterDrawer }] =
    useDisclosure(false);
  // Widening past the breakpoint unmounts the drawer without closing it, which
  // would leave it primed to reappear the next time the window narrows.
  useEffect(() => {
    if (!isNarrow) closeFilterDrawer();
  }, [isNarrow, closeFilterDrawer]);

  const bulkCtrl = useRef<AbortController | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Latest dashboard ref so the debounced save uses fresh state. We update
  // it synchronously alongside setDashboard via `applyDashboard` — relying on
  // a post-render useEffect lets react-grid-layout's onLayoutChange fire with
  // a stale ref, which then re-saves the prior (pre-duplicate/delete) state.
  const dashboardRef = useRef<DashboardData | null>(null);
  const applyDashboard = useCallback((d: DashboardData | null) => {
    dashboardRef.current = d;
    setDashboard(d);
  }, []);

  const isOwner = isDashboardOwner(dashboard, currentUser?.email ?? null);

  // Editor route is owner-only. Visitors who land here without permission
  // (typed the URL, opened a public dashboard, etc.) get bounced to the
  // read-only viewer. We wait for both the dashboard fetch AND the auth
  // probe so the redirect runs against a known answer, not a transient
  // null. Backend enforces with 403s on write endpoints regardless.
  useEffect(() => {
    if (userLoading) return;
    if (!dashboard || !dashboardId) return;
    if (!isOwner) {
      window.location.replace(`/dashboard/${dashboardId}`);
    }
  }, [userLoading, dashboard, dashboardId, isOwner]);

  // Keep the browser tab title in sync with the dashboard name.
  useEffect(() => {
    if (dashboard?.title) {
      document.title = `Depictio — ${dashboard.title}`;
    } else if (dashboardId) {
      document.title = `Depictio — ${dashboardId}`;
    }
  }, [dashboard?.title, dashboardId]);

  // Fetch dashboard + tab list
  useEffect(() => {
    if (!dashboardId) {
      setError('No dashboard ID in URL. Expected /dashboard/<id>/edit.');
      setLoading(false);
      return;
    }
    Promise.all([fetchDashboard(dashboardId), fetchAllDashboards()])
      .then(([dash, all]) => {
        applyDashboard(dash);
        setAllDashboards(all);
        // Drop seeded filters whose emitting component no longer exists (it
        // was deleted while the user was in the builder) — a ghost filter
        // would keep narrowing the grid with nothing on screen to release it.
        // Floating-map selections are exempt: a floating component lives on
        // another tab's stored_metadata, so an unknown index is expected there.
        const known = new Set((dash.stored_metadata || []).map((m) => m.index));
        setFilters((prev) =>
          prev.filter((f) => known.has(f.index) || f.source === 'map_selection'),
        );
      })
      .catch((err) => {
        setError(`Failed to load dashboard: ${err.message || err}`);
      })
      .finally(() => setLoading(false));
  }, [dashboardId]);

  // Bulk-compute card values when filters change (mirrors App.tsx)
  useEffect(() => {
    if (!dashboard || !dashboardId) return;
    const cardIds = (dashboard.stored_metadata || [])
      .filter((m) => m.component_type === 'card')
      .map((m) => m.index);
    if (cardIds.length === 0) return;

    const timer = setTimeout(() => {
      setCardsLoading(true);
      // Keep previous card values mounted while the new bulk-compute is in
      // flight; CardRenderer dims the value via ``cardLoading`` instead of
      // snapping to ``…``. See App.tsx for the matching change.
      if (bulkCtrl.current) bulkCtrl.current.abort();
      bulkCtrl.current = new AbortController();
      bulkComputeCards(
        dashboardId,
        combinedFilters,
        cardIds,
        groupsApi.bulkOptions,
        // See App.tsx: prevents a slow superseded compare-on response from
        // overwriting a newer one.
        bulkCtrl.current.signal,
      )
        .then((res) => {
          setCardValues(res.values);
          setCardSecondaryValues(res.secondary_values || {});
        })
        .catch((err) => {
          if (err?.name !== 'AbortError') {
            console.warn('[EditorApp] bulk-compute failed:', err);
          }
        })
        .finally(() => setCardsLoading(false));
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    dashboard,
    dashboardId,
    stableFilterKey(combinedFilters),
    // Undefined while compare is off, so group edits don't refire the fetch.
    JSON.stringify(groupsApi.bulkOptions ?? null),
  ]);

  // Mirror the live filters into the per-tab store so they survive the
  // builder's full-page round-trip (see editorFilters.ts). Writing on every
  // change (rather than at the navigation sites) keeps AddComponentButton /
  // GridItemEditOverlay free of filter plumbing; clearing all filters removes
  // the entry, so "Reset" leaves nothing behind.
  useEffect(() => {
    if (dashboardId) writeEditorFilters(dashboardId, filters);
  }, [dashboardId, stableFilterKey(filters)]);

  const handleFilterChange = useCallback(
    (update: InteractiveFilter) => {
      const enriched = enrichFilterWithDcId(update, dashboard?.stored_metadata);
      setFilters((prev) => mergeFiltersBySource(prev, enriched));
    },
    [dashboard],
  );

  // In-place "save selection as group" on components with a live selection
  // (mirrors App.tsx).
  // Analysis mode, tracked separately from whether the header panel is open.
  // Mantine dismisses a Popover on mousedown outside it, and that mousedown is
  // the one that starts a lasso — so tying the mode to `analysisOpen` would
  // erase every capability marker exactly when the user acts on one. Opening
  // the panel arms the mode; only the button (or a second click on it) ends it.
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const [analysisArmed, setAnalysisArmed] = useState(false);
  const handleAnalysisOpenChange = useCallback((next: boolean) => {
    setAnalysisOpen(next);
    if (next) setAnalysisArmed(true);
  }, []);
  const handleAnalysisToggle = useCallback(() => {
    const next = !analysisOpen;
    setAnalysisOpen(next);
    setAnalysisArmed(next);
  }, [analysisOpen]);

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

  // Authors see the panel as viewers will. Cross-tab (floating) filter
  // persistence is deliberately viewer-only: an editing session's filter state
  // is scratch across dashboards, and carrying it between tabs would be
  // surprising here. Same-dashboard persistence within this browser tab is a
  // different matter — see editorFilters.ts, which keeps filters alive across
  // the builder round-trip.
  const crossTab = useCrossTabComponents(dashboardId ?? '');

  // Persistent sections owned by *sibling* tabs. They render here exactly as
  // the viewer draws them — read-only, on their own surfaces — so an author
  // laying out this tab sees the space they take. Everything editable stays
  // keyed on this dashboard's own `stored_metadata`: a foreign member must
  // never reach the layout merges that write `left_panel_layout_data` /
  // `right_panel_layout_data`, nor the ⋮ menus that delete or re-section a
  // component this document does not own.
  const foreignPersistentSections = useMemo(
    () => crossTab.persistentSections.filter((s) => s.owner_dashboard_id !== dashboardId),
    [crossTab.persistentSections, dashboardId],
  );
  const foreignFilterSections = useMemo(
    () => foreignPersistentSections.filter((s) => s.kind === 'filter'),
    [foreignPersistentSections],
  );
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
  const mapPanel = useMapPanel({
    components: crossTab.floating,
    familyId: crossTab.familyId,
    filters,
    onFilterChange: handleFilterChange,
  });

  /** Debounced save: schedule a POST 500ms after the last layout mutation. */
  const scheduleSave = useCallback(
    (next: DashboardData) => {
      if (!dashboardId) return;
      applyDashboard(next);
      setSaveStatus('saving');
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        const payload = dashboardRef.current;
        if (!payload) return;
        saveDashboard(dashboardId, payload)
          .then(() => setSaveStatus('saved'))
          .catch((err) => {
            console.error('[EditorApp] save failed:', err);
            setSaveStatus('error');
          });
      }, SAVE_DEBOUNCE_MS);
    },
    [dashboardId, applyDashboard],
  );

  /** The single write path for every section change.
   *
   *  Reduces against `dashboardRef.current` rather than the `dashboard` state
   *  variable so the manager — which may be a render behind — can't clobber a
   *  concurrent layout drag, and vice versa. `scheduleSave` writes the ref
   *  synchronously, so a burst of ops (a rename followed by an update, from one
   *  Save click) composes correctly. */
  const handleSectionOp = useCallback(
    (op: SectionOp) => {
      const cur = dashboardRef.current;
      if (!cur) return;
      const next = applySectionOp(cur, op);
      // Reference equality is the reducer's "rejected" signal (duplicate name,
      // move past an end). Saving anyway would burn a request per no-op.
      if (next === cur) return;
      scheduleSave(next);
    },
    [scheduleSave],
  );

  const handleMoveToSection = useCallback(
    (componentId: string, section: string | null) =>
      handleSectionOp({ op: 'assign', componentId, section }),
    [handleSectionOp],
  );

  /** Layout entries for components this document actually holds.
   *
   *  The read-only rendering already keeps fanned-out members out of the
   *  editable grids, but that rule is spread across a section flag and a merge
   *  skip. This is the boundary where it has to hold no matter what: an entry
   *  keyed on another tab's component would be an orphan in this dashboard's
   *  layout, and the components it belongs to would still live over there. */
  const ownLayoutOnly = useCallback((layout: Layout[], cur: DashboardData) => {
    const own = new Set((cur.stored_metadata ?? []).map((m) => m.index));
    return layout.filter((item) => own.has(stripBoxPrefix(String(item.i))));
  }, []);
  /** Dashboard-level plot theme (#397). Saved immediately (not debounced):
   *  the server resolves `plot_theme` from the DB at figure-render time, so
   *  figures can only refetch once the save has landed. */
  const handlePlotThemeChange = useCallback(
    (spec: DashboardThemeSpec | null) => {
      const cur = dashboardRef.current;
      if (!cur || !dashboardId) return;
      const next = { ...cur, plot_theme: spec };
      applyDashboard(next);
      setSaveStatus('saving');
      saveDashboard(dashboardId, next)
        .then(() => {
          setSaveStatus('saved');
          setPlotThemeTick((t) => t + 1);
        })
        .catch((err) => {
          console.error('[EditorApp] plot theme save failed:', err);
          setSaveStatus('error');
        });
    },
    [dashboardId, applyDashboard],
  );

  const handleLeftLayoutChange = useCallback(
    (newLayout: Layout[]) => {
      const cur = dashboardRef.current;
      if (!cur) return;
      const next = ownLayoutOnly(newLayout, cur);
      // Skip no-op writes during the initial mount where react-grid-layout
      // emits the layout it was just given.
      const prev = cur.left_panel_layout_data;
      if (layoutsEqual(prev, next)) return;
      scheduleSave({ ...cur, left_panel_layout_data: next });
    },
    [scheduleSave, ownLayoutOnly],
  );

  const handleRightLayoutChange = useCallback(
    (newLayout: Layout[]) => {
      const cur = dashboardRef.current;
      if (!cur) return;
      const next = ownLayoutOnly(newLayout, cur);
      const prev = cur.right_panel_layout_data;
      if (layoutsEqual(prev, next)) return;
      scheduleSave({ ...cur, right_panel_layout_data: next });
    },
    [scheduleSave, ownLayoutOnly],
  );

  /** Delete: strip from stored_metadata + both layouts, save, then refetch. */
  const handleDeleteComponent = useCallback(
    async (componentId: string) => {
      if (!dashboardId) return;
      const cur = dashboardRef.current;
      if (!cur) return;
      const next: DashboardData = {
        ...cur,
        stored_metadata: (cur.stored_metadata || []).filter(
          (m) => m.index !== componentId,
        ),
        left_panel_layout_data: stripFromLayout(
          cur.left_panel_layout_data,
          componentId,
        ),
        right_panel_layout_data: stripFromLayout(
          cur.right_panel_layout_data,
          componentId,
        ),
      };
      // Cancel any pending debounced save — we're saving NOW.
      if (saveTimer.current) {
        clearTimeout(saveTimer.current);
        saveTimer.current = null;
      }
      applyDashboard(next);
      setSaveStatus('saving');
      try {
        await saveDashboard(dashboardId, next);
        const fresh = await fetchDashboard(dashboardId);
        applyDashboard(fresh);
        setSaveStatus('saved');
      } catch (err) {
        console.error('[EditorApp] delete failed:', err);
        setSaveStatus('error');
      }
    },
    [dashboardId, applyDashboard],
  );

  /**
   * Persist the dashboard-level funnel-filtering default (issue #939). Same
   * save-now pattern as delete: apply optimistically, POST the full document.
   */
  const handleToggleFunnelFiltering = useCallback(
    async (enabled: boolean) => {
      if (!dashboardId) return;
      const cur = dashboardRef.current;
      if (!cur) return;
      const next = { ...cur, funnel_filtering: enabled };
      if (saveTimer.current) {
        clearTimeout(saveTimer.current);
        saveTimer.current = null;
      }
      applyDashboard(next);
      setSaveStatus('saving');
      try {
        await saveDashboard(dashboardId, next);
        setSaveStatus('saved');
      } catch (err) {
        console.error('[EditorApp] funnel toggle save failed:', err);
        setSaveStatus('error');
      }
    },
    [dashboardId, applyDashboard],
  );

  /**
   * Duplicate: deep-clone the source component's stored_metadata entry, give
   * it a fresh UUID, and stack a layout entry directly below the source in
   * whichever panel (left/right) the source lives in. POSTs the full
   * DashboardData and re-fetches on success — same pattern as delete.
   */
  const handleDuplicateComponent = useCallback(
    async (componentId: string) => {
      if (!dashboardId) return;
      const cur = dashboardRef.current;
      if (!cur) return;
      const source = (cur.stored_metadata || []).find(
        (m) => m.index === componentId,
      );
      if (!source) {
        console.warn(
          '[EditorApp] duplicate: source metadata not found for',
          componentId,
        );
        return;
      }

      const newId =
        typeof crypto !== 'undefined' &&
        typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : fallbackUuid();

      // Deep-clone via structuredClone with a JSON fallback for older runtimes.
      const cloned: StoredMetadata = (typeof structuredClone === 'function'
        ? structuredClone(source)
        : (JSON.parse(JSON.stringify(source)) as StoredMetadata)) as StoredMetadata;
      (cloned as { index: string }).index = newId;
      // Strip any MongoDB-side identifiers that might have ridden along with
      // the source dict — keeping them on the clone makes the backend think
      // we're updating an existing document and triggers either a 422 or a
      // silent overwrite of the source.
      const cloneScratch = cloned as Record<string, unknown>;
      delete cloneScratch._id;
      delete cloneScratch.id;
      // Append " (copy)" to title if present, but don't fail on unusual shapes.
      const maybeTitled = cloned as unknown as { title?: unknown };
      if (typeof maybeTitled.title === 'string' && maybeTitled.title.length) {
        maybeTitled.title = `${maybeTitled.title} (copy)`;
      }

      // Decide which panel the source lives in by scanning layouts for
      // either `box-${id}` or the bare id (matching stripBoxPrefix logic).
      const inLeft = layoutContains(cur.left_panel_layout_data, componentId);
      const inRight = layoutContains(cur.right_panel_layout_data, componentId);
      // Default fallback: interactive components → left, everything else → right.
      const targetPanel: 'left' | 'right' = inLeft
        ? 'left'
        : inRight
        ? 'right'
        : source.component_type === 'interactive'
        ? 'left'
        : 'right';

      const sourceLayoutEntry =
        targetPanel === 'left'
          ? findLayoutEntry(cur.left_panel_layout_data, componentId)
          : findLayoutEntry(cur.right_panel_layout_data, componentId);

      // Stack immediately below the source. compactType="vertical" downstream
      // will resolve any overlap.
      const newLayoutEntry: Layout = {
        i: `box-${newId}`,
        x: sourceLayoutEntry?.x ?? 0,
        y:
          (sourceLayoutEntry?.y ?? 0) +
          (sourceLayoutEntry?.h ?? (targetPanel === 'left' ? 2 : 4)),
        w: sourceLayoutEntry?.w ?? (targetPanel === 'left' ? 1 : 6),
        h: sourceLayoutEntry?.h ?? (targetPanel === 'left' ? 2 : 4),
      };

      const next: DashboardData = {
        ...cur,
        stored_metadata: [...(cur.stored_metadata || []), cloned],
        left_panel_layout_data:
          targetPanel === 'left'
            ? appendToLayout(cur.left_panel_layout_data, newLayoutEntry)
            : cur.left_panel_layout_data,
        right_panel_layout_data:
          targetPanel === 'right'
            ? appendToLayout(cur.right_panel_layout_data, newLayoutEntry)
            : cur.right_panel_layout_data,
      };

      // Cancel any pending debounced save — we're saving NOW.
      if (saveTimer.current) {
        clearTimeout(saveTimer.current);
        saveTimer.current = null;
      }
      applyDashboard(next);
      setSaveStatus('saving');
      try {
        await saveDashboard(dashboardId, next);
        const fresh = await fetchDashboard(dashboardId);
        applyDashboard(fresh);
        setSaveStatus('saved');
        // Scroll the freshly placed component into view + brief highlight pulse
        // so the user can see where it landed (otherwise auto-placed items at
        // the bottom are easy to miss).
        const flashNewComponent = () => {
          const inner = document.querySelector(
            `[data-component-id="${newId}"]`,
          ) as HTMLElement | null;
          // The .react-grid-item ancestor is the absolutely-positioned cell,
          // so we scroll/highlight that — not the inner content wrapper.
          const el = (inner?.closest('.react-grid-item') as HTMLElement | null) || inner;
          if (!el) return;
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          el.classList.add('depictio-duplicate-flash');
          window.setTimeout(
            () => el.classList.remove('depictio-duplicate-flash'),
            1500,
          );
        };
        // Wait two frames so react-grid-layout has positioned the new item.
        requestAnimationFrame(() =>
          requestAnimationFrame(flashNewComponent),
        );
        notifications.show({
          color: 'teal',
          title: 'Component duplicated',
          message: 'Scrolled to the new copy.',
          autoClose: 2000,
        });
      } catch (err) {
        console.error('[EditorApp] duplicate failed:', err);
        setSaveStatus('error');
        notifications.show({
          color: 'red',
          title: 'Duplicate failed',
          message: err instanceof Error ? err.message : String(err),
          autoClose: 5000,
        });
      }
    },
    [dashboardId, applyDashboard],
  );

  /**
   * The same Edit / Delete menu a grid tile carries, for the map in the panel.
   *
   * A map with `placement: floating` claims no grid cell, so it never gets a
   * `renderItemOverlay` — without this there is no way to edit or delete one
   * again short of hand-typing its component id into the edit URL.
   *
   * Only for maps this tab owns. `handleDeleteComponent` strips the component
   * from *this* dashboard's `stored_metadata`, so on a map authored on a
   * sibling tab it would save a document unchanged and look like the delete
   * silently failed. Those are editable from the tab that owns them, which is
   * the tab the panel's own tab strip names.
   */
  const renderMapPanelEditActions = useCallback(
    (componentId: string, ownerDashboardId: string) => {
      if (!dashboardId || ownerDashboardId !== dashboardId) return null;
      return (
        <GridItemEditOverlay
          dashboardId={ownerDashboardId}
          componentId={componentId}
          editMode
          onDelete={handleDeleteComponent}
          componentType="map"
        />
      );
    },
    [dashboardId, handleDeleteComponent],
  );

  const interactiveComponents = useMemo(
    () =>
      (dashboard?.stored_metadata || []).filter(
        (m) => m.component_type === 'interactive',
      ),
    [dashboard],
  );
  // Same placement split as the viewer (App.tsx). Without it, `placement: 'top'`
  // controls render in the left filter column while editing and jump to the
  // bottom strip on save, so the editor never shows the real layout.
  const topComponents = useMemo(
    () => interactiveComponents.filter((m) => m.placement === 'top'),
    [interactiveComponents],
  );
  const leftComponents = useMemo(() => {
    const own = interactiveComponents.filter((m) => m.placement !== 'top');
    const seen = new Set(own.map((m) => m.index));
    // Controls fanned out from a sibling tab's persistent filter section, same
    // as the viewer does: their renderers fetch options by dc_id/column, not by
    // dashboard id. `readOnlyPanelSections` below keeps them out of the panel's
    // editable grid.
    const foreign = foreignFilterSections
      .flatMap((s) => s.components.map((c) => c.metadata))
      .filter((m) => !seen.has(m.index) && m.placement !== 'top');
    return foreign.length ? [...own, ...foreign] : own;
  }, [interactiveComponents, foreignFilterSections]);
  // Section chrome for the panel — own specs plus the foreign persistent ones,
  // own winning a name clash. Distinct from the `filterSections` memo below,
  // which feeds the ⋮ "Move to section" menus and must stay own-only: a
  // component cannot move into a section another tab owns.
  const panelFilterSections = useMemo(() => {
    const own = dashboard?.filter_sections ?? [];
    const names = new Set(own.map((s) => s.name));
    const foreign = foreignFilterSections.map((s) => s.spec).filter((s) => !names.has(s.name));
    return foreign.length ? [...own, ...foreign] : own;
  }, [dashboard?.filter_sections, foreignFilterSections]);
  // Same exclusion as `panelFilterSections`, and it has to be: a section is
  // read-only because a sibling tab owns it, and an own section that happens to
  // share the name is a different section. Without this, declaring a section
  // named like a sibling's persistent one would freeze this tab's own filters —
  // no drag, no per-component menu — and drop them from every later
  // `left_panel_layout_data` write, since the merge skips read-only sections.
  /** Component ids this dashboard document holds, as opposed to the ones fanned
   *  out from sibling tabs. */
  const ownComponentIndices = useMemo(
    () => new Set((dashboard?.stored_metadata ?? []).map((m) => m.index)),
    [dashboard?.stored_metadata],
  );
  const readOnlyPanelSections = useMemo(() => {
    const ownNames = new Set((dashboard?.filter_sections ?? []).map((s) => s.name));
    return foreignFilterSections
      .map((s) => s.spec.name)
      .filter((name) => !ownNames.has(name));
  }, [dashboard?.filter_sections, foreignFilterSections]);
  /** Open the add/edit dialog on one section, by name.
   *
   *  A section a component names but the dashboard never declared has no spec
   *  to patch — `update` maps over the declared list and would be a no-op — so
   *  it is materialised first, exactly as opening the manager does. */
  const openSectionEditor = useCallback(
    (kind: SectionKind, sectionName: string) => {
      const cur = dashboardRef.current;
      const declared = cur
        ? sectionsFor(cur, kind).find((s) => s.name === sectionName)
        : undefined;
      if (!declared) handleSectionOp({ op: 'materialize', kind });
      setSectionModal({
        open: true,
        kind,
        target: declared ?? { name: sectionName },
        fromManager: false,
      });
    },
    [handleSectionOp],
  );
  // A section is edited from where it is seen: its header carries the same "…"
  // a component's chrome does. Named sections only — the unsectioned bucket has
  // no header to host it.
  const renderGridSectionAction = (sectionName: string | null) =>
    sectionName === null ? null : (
      <SectionActionButton
        label={`Edit “${sectionName}”`}
        onActivate={() => openSectionEditor('grid', sectionName)}
      />
    );
  // Filter names and dc_ids are resolved against the family, not just this
  // tab: a fanned-out control has no entry in this dashboard's metadata, so
  // the active-filter summary would fall back to the raw column name.
  const summaryMetadata = useMemo(() => {
    const own = dashboard?.stored_metadata || [];
    const seen = new Set(own.map((m) => m.index));
    const extras = foreignPersistentSections
      .flatMap((s) => s.components.map((c) => c.metadata))
      .filter((m) => !seen.has(m.index));
    return extras.length ? [...own, ...extras] : own;
  }, [dashboard, foreignPersistentSections]);
  // Sections offered by the filter controls' ⋮ menus. Keyed on the spec list
  // rather than the whole dashboard so a card value or layout nudge doesn't
  // re-render every overlay.
  const filterSections = useMemo(
    () => dashboard?.filter_sections ?? [],
    [dashboard?.filter_sections],
  );
  // How many controls move together, per component. Precomputed once instead of
  // per overlay so the callback below can depend on this rather than on the
  // whole `dashboard`.
  const filterGroupSizes = useMemo(() => {
    const sizes = new Map<string, number>();
    const metadata = dashboard?.stored_metadata ?? [];
    for (const m of metadata) {
      if (m.group) sizes.set(m.index, groupWith(metadata, m.index).size);
    }
    return sizes;
  }, [dashboard?.stored_metadata]);

  // Per-filter edit / duplicate / delete menu. FilterPanel injects it into
  // each control's chrome, including controls nested inside a group card.
  const renderFilterItemOverlay = useCallback(
    (component: StoredMetadata) =>
      // A control fanned out from a sibling tab can share a bucket with this
      // tab's own filters when both sections carry the same name. It is not in
      // this document, so none of these actions could reach it.
      !ownComponentIndices.has(component.index) ? null : (
      <GridItemEditOverlay
        dashboardId={dashboardId!}
        componentId={component.index}
        editMode
        onDelete={handleDeleteComponent}
        onDuplicate={handleDuplicateComponent}
        componentType={component.component_type}
        sections={filterSections}
        currentSection={component.section ?? null}
        onMoveToSection={handleMoveToSection}
        groupSize={filterGroupSizes.get(component.index) ?? 1}
      />
    ),
    [
      dashboardId,
      handleDeleteComponent,
      handleDuplicateComponent,
      filterSections,
      handleMoveToSection,
      filterGroupSizes,
      ownComponentIndices,
    ],
  );

  const cardComponents = useMemo(
    () =>
      (dashboard?.stored_metadata || []).filter(
        (m) => m.component_type === 'card',
      ),
    [dashboard],
  );
  const otherComponents = useMemo(
    () =>
      (dashboard?.stored_metadata || []).filter(
        (m) =>
          m.component_type !== 'card' &&
          m.component_type !== 'interactive' &&
          // Floating maps live in FloatingPanelHost, not the grid (see App.tsx).
          !(m.component_type === 'map' && m.placement === 'floating'),
      ),
    [dashboard],
  );

  // Tab family: parent dashboard + its child tabs (mirrors App.tsx).
  const tabSiblings = useMemo(() => {
    if (!dashboard || !allDashboards.length) return [] as DashboardSummary[];
    const dashId = String(
      dashboard.dashboard_id || dashboard._id || dashboardId || '',
    );
    const current = allDashboards.find((d) => d.dashboard_id === dashId);
    const parentId = current?.parent_dashboard_id || dashId;
    const family = allDashboards.filter(
      (d) => d.dashboard_id === parentId || d.parent_dashboard_id === parentId,
    );
    return family.sort((a, b) => {
      // Mirrors depictio/dash/layouts/tab_callbacks.py: parent (tab_order=0) first,
      // then children sorted by tab_order. Title is a stable tiebreaker.
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

  const handleResetAllFilters = useCallback(() => {
    setFilters([]);
    // Mirrors App.tsx: group filters narrow the dashboard too.
    groupsApi.deactivateAllGroupFilters();
  }, [groupsApi.deactivateAllGroupFilters]);

  // Filter-active groups as removable active-filter summary rows.
  const groupSummaryRows = groupsApi.summaryRows;
  // Global "Color by" column discovery + stable palette (mirrors App.tsx).
  const colorByColumns = useCategoricalColumns(dashboard?.stored_metadata);
  const colorByColumnRender = useColorByColumnRender(groupsApi.colorBy, colorByColumns);
  // Memoised for the grid's per-item render memo (mirrors App.tsx).
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

  // The Grouping panel's body, mounted in the header popover (mirrors App.tsx).
  const groupsSection = (
    <SelectionGroupsPanel
      filters={filters}
      components={dashboard?.stored_metadata ?? []}
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

  // ---- Realtime: WebSocket subscription mirrors App.tsx ---------------------
  const [realtimeMode, setRealtimeMode] = useState<RealtimeMode>(() => {
    try {
      const v = localStorage.getItem('depictio.realtime.mode');
      return v === 'auto' ? 'auto' : 'manual';
    } catch {
      return 'manual';
    }
  });
  const [realtimePaused, setRealtimePaused] = useState(false);
  const persistRealtimeMode = useCallback((next: RealtimeMode) => {
    setRealtimeMode(next);
    try {
      localStorage.setItem('depictio.realtime.mode', next);
    } catch {
      // ignore quota / private mode
    }
  }, []);
  const triggerRealtimeRefresh = useCallback(() => {
    setFilters((prev) => [...prev]);
  }, []);
  const [journal, appendJournal, clearJournal] = useRealtimeJournal(50);

  // Per-batch highlight (mirrors App.tsx). Live arrivals glow transiently;
  // the event log can pin a past batch. The nonce re-arms the fade window.
  const [activeHighlight, setActiveHighlight] = useState<ActiveHighlight | null>(null);
  const highlightNonce = useRef(0);
  const applyHighlight = useCallback(
    (batch: { idColumn?: string; ids: string[] }, dcId?: string, sticky = false, batchKey?: string) => {
      highlightNonce.current += 1;
      const nonce = highlightNonce.current;
      setActiveHighlight((prev) => {
        // A live (non-sticky) arrival must not replace a pinned batch.
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
      const payload = event.payload || {};
      const op = payload.operation as string | undefined;
      const tag = payload.data_collection_tag as string | undefined;
      const summary =
        [op && `op=${op}`, tag && `tag=${tag}`].filter(Boolean).join(' ') ||
        event.event_type;
      appendJournal({
        eventType: event.event_type,
        dataCollectionId: event.data_collection_id,
        dashboardId: event.dashboard_id,
        summary,
        payload,
      });
      if (auto) {
        const batch = batchIdsFromPayload(payload);
        if (batch) applyHighlight(batch, event.data_collection_id, false);
        triggerRealtimeRefresh();
        return;
      }
      notifications.show({
        title: 'Data updated',
        message: 'A linked data collection just changed. Click to refresh.',
        color: 'blue',
        autoClose: 8000,
        onClick: () => triggerRealtimeRefresh(),
      });
    },
    [triggerRealtimeRefresh, appendJournal, applyHighlight],
  );
  // Gated on the project's ``realtime.enabled`` flag (project.yaml). Static
  // projects never mount the WebSocket / indicator.
  const realtimeEnabled = Boolean(dashboard?.project_realtime?.enabled);
  const realtime = useDataCollectionUpdates(dashboardId, {
    enabled: realtimeEnabled && Boolean(dashboardId),
    mode: realtimeMode,
    paused: realtimePaused,
    onUpdate: onRealtimeUpdate,
  });

  const handleAddComponent = useCallback(() => {
    if (!dashboardId) return;
    const newId =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : fallbackUuid();
    // React-side stepper page (was: cross-origin Dash editor).
    window.location.assign(
      `/dashboard-edit/${dashboardId}/component/add/${newId}`,
    );
  }, [dashboardId]);

  /** Refetch the global dashboard list so tab edits show up in the sidebar
   *  without a full page reload. */
  const refreshTabList = useCallback(async () => {
    try {
      const all = await fetchAllDashboards();
      setAllDashboards(all);
    } catch (err) {
      console.warn('[EditorApp] refresh tab list failed:', err);
    }
  }, []);

  const openCreateTabModal = useCallback(() => {
    setTabModalState({
      open: true,
      mode: 'create',
      target: null,
      submitting: false,
    });
  }, []);

  const openEditTabModal = useCallback((tab: DashboardSummary) => {
    setTabModalState({
      open: true,
      mode: 'edit',
      target: tab,
      submitting: false,
    });
  }, []);

  const closeTabModal = useCallback(() => {
    setTabModalState((s) => ({ ...s, open: false, submitting: false }));
  }, []);

  const handleTabModalSubmit = useCallback(
    async (payload: TabModalSubmitPayload) => {
      setTabModalState((s) => ({ ...s, submitting: true }));
      try {
        if (tabModalState.mode === 'create') {
          // Resolve parent: the current dashboard is either the parent itself
          // (main tab) or a child whose `parent_dashboard_id` points at it.
          const cur = dashboardRef.current;
          const currentSummary = allDashboards.find(
            (d) => d.dashboard_id === dashboardId,
          );
          const parentId =
            currentSummary?.parent_dashboard_id ||
            String(cur?.dashboard_id || dashboardId || '');
          if (!parentId) throw new Error('No parent dashboard id available.');
          const newId = await createTab(parentId, {
            title: payload.title,
            tab_icon: payload.tab_icon,
            tab_icon_color: payload.tab_icon_color,
          });
          notifications.show({
            color: 'teal',
            title: 'Tab created',
            message: payload.title,
            autoClose: 2000,
          });
          setTabModalState({
            open: false,
            mode: 'create',
            target: null,
            submitting: false,
          });
          // Navigate to the new tab — preserves edit mode via the same
          // `/dashboard-edit/{id}` route we're already on.
          window.location.assign(`/dashboard-edit/${newId}`);
          return;
        }

        const target = tabModalState.target;
        if (!target) throw new Error('No tab to edit.');
        await updateTab(target.dashboard_id, payload);
        notifications.show({
          color: 'teal',
          title: 'Tab updated',
          message: payload.title,
          autoClose: 2000,
        });
        setTabModalState({
          open: false,
          mode: 'edit',
          target: null,
          submitting: false,
        });
        await refreshTabList();
      } catch (err) {
        console.error('[EditorApp] tab modal submit failed:', err);
        notifications.show({
          color: 'red',
          title: 'Tab save failed',
          message: err instanceof Error ? err.message : String(err),
          autoClose: 4000,
        });
        setTabModalState((s) => ({ ...s, submitting: false }));
      }
    },
    [
      tabModalState.mode,
      tabModalState.target,
      dashboardId,
      allDashboards,
      refreshTabList,
    ],
  );

  const handleDeleteTab = useCallback(
    async (tab: DashboardSummary) => {
      // Backend rejects deleting the main tab — guard here too so we never
      // even attempt the call (also keeps the menu intent clear).
      if (!tab.parent_dashboard_id) {
        notifications.show({
          color: 'red',
          title: 'Cannot delete main tab',
          message: 'Delete the parent dashboard from /dashboards instead.',
          autoClose: 3000,
        });
        return;
      }
      if (
        typeof window !== 'undefined' &&
        !window.confirm(`Delete tab "${tab.title || tab.dashboard_id}"?`)
      ) {
        return;
      }
      try {
        await deleteTab(tab.dashboard_id);
        notifications.show({
          color: 'teal',
          title: 'Tab deleted',
          message: tab.title || tab.dashboard_id,
          autoClose: 2000,
        });
        // Navigate to the parent (or first remaining sibling) so we don't
        // sit on a now-deleted dashboard id.
        const parentId = tab.parent_dashboard_id;
        if (tab.dashboard_id === dashboardId && parentId) {
          window.location.assign(`/dashboard-edit/${parentId}`);
        } else {
          await refreshTabList();
        }
      } catch (err) {
        console.error('[EditorApp] delete tab failed:', err);
        notifications.show({
          color: 'red',
          title: 'Delete tab failed',
          message: err instanceof Error ? err.message : String(err),
          autoClose: 4000,
        });
      }
    },
    [dashboardId, refreshTabList],
  );

  const handleMoveTab = useCallback(
    async (tab: DashboardSummary, direction: 'up' | 'down') => {
      // Build the new ordering by swapping `tab` with its neighbor in the
      // child-only list. The main tab keeps tab_order=0 and isn't part of
      // the reorder payload.
      const children = (
        tabSiblings.length
          ? tabSiblings
          : allDashboards.filter(
              (d) => d.parent_dashboard_id === tab.parent_dashboard_id,
            )
      ).filter((t) => t.parent_dashboard_id);
      const idx = children.findIndex((c) => c.dashboard_id === tab.dashboard_id);
      if (idx === -1) return;
      const swapIdx = direction === 'up' ? idx - 1 : idx + 1;
      if (swapIdx < 0 || swapIdx >= children.length) return;

      const reordered = [...children];
      [reordered[idx], reordered[swapIdx]] = [reordered[swapIdx], reordered[idx]];
      const tabOrders = reordered.map((c, i) => ({
        dashboard_id: c.dashboard_id,
        tab_order: i + 1,
      }));
      const parentId = tab.parent_dashboard_id;
      if (!parentId) return;
      try {
        await reorderTabs(parentId, tabOrders);
        await refreshTabList();
      } catch (err) {
        console.error('[EditorApp] reorder tabs failed:', err);
        notifications.show({
          color: 'red',
          title: 'Reorder failed',
          message: err instanceof Error ? err.message : String(err),
          autoClose: 4000,
        });
      }
    },
    [tabSiblings, allDashboards, refreshTabList],
  );

  /** Closing a sections dialog flushes the debounce: the next thing a user does
   *  after touching sections is often "Edit" or "Add", both of which navigate
   *  away with `window.location.assign` and would drop a pending save. */
  const flushSectionSave = useCallback(() => {
    if (!dashboardId) return;
    const cur = dashboardRef.current;
    if (!cur) return;
    if (saveTimer.current) {
      clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
    setSaveStatus('saving');
    saveDashboard(dashboardId, cur)
      .then(() => setSaveStatus('saved'))
      .catch((err) => {
        console.error('[EditorApp] section save failed:', err);
        setSaveStatus('error');
      });
  }, [dashboardId]);

  const handleCloseSections = useCallback(() => {
    closeSections();
    flushSectionSave();
  }, [closeSections, flushSectionSave]);

  /** Cancel and save both land here. Returning to the manager when that is
   *  where the dialog came from is what makes editing several sections in a
   *  row bearable. */
  const handleCloseSectionModal = useCallback(() => {
    // Outside the updater: React re-invokes those in dev, and this one opens a
    // dialog.
    if (sectionModal.fromManager) openSections();
    setSectionModal((prev) => ({ ...prev, open: false }));
    flushSectionSave();
  }, [sectionModal.fromManager, openSections, flushSectionSave]);

  /** "Manage all sections", the other direction of the same swap. */
  const handleManageAllSections = useCallback(() => {
    setSectionModal((prev) => ({ ...prev, open: false, fromManager: false }));
    openSections();
    flushSectionSave();
  }, [openSections, flushSectionSave]);

  const handleManagerAdd = useCallback(
    (kind: SectionKind) => {
      closeSections();
      setSectionModal({ open: true, kind, target: null, fromManager: true });
    },
    [closeSections],
  );
  const handleManagerEdit = useCallback(
    (kind: SectionKind, spec: FilterSectionSpec) => {
      closeSections();
      setSectionModal({ open: true, kind, target: spec, fromManager: true });
    },
    [closeSections],
  );
  /** The header's Add menu: a new grid section, the common case. */
  const handleAddSection = useCallback(
    () => setSectionModal({ open: true, kind: 'grid', target: null, fromManager: false }),
    [],
  );

  /** A persistent section can only be changed where it is declared. Rather
   *  than leave it inert on every other tab, its header carries a jump to the
   *  tab that owns it. Flushes first: the navigation is a full page load and
   *  would drop a pending layout save. */
  const goToOwnerTab = (ownerDashboardId: string) => {
    flushSectionSave();
    window.location.assign(`/dashboard-edit/${ownerDashboardId}`);
  };
  const renderPersistentSectionAction = (section: PersistentSection) => (
    <SectionActionButton
      label={`Owned by ${
        section.owner_tab_title ? `“${section.owner_tab_title}”` : 'another tab'
      } — open that tab to edit it`}
      ariaLabel="Edit on the owning tab"
      onActivate={() => goToOwnerTab(section.owner_dashboard_id)}
    />
  );
  // The panel's list also holds the persistent sections a sibling tab owns.
  // Those get the jump instead of this tab's editor: the modal only knows this
  // dashboard's own specs. The grid needs no such branch — its foreign sections
  // render in `PersistentSectionsHost`, which takes its own action.
  const foreignFilterSectionsByName = new Map(
    foreignFilterSections.map((s) => [s.spec.name, s] as const),
  );
  const renderPanelSectionAction = (sectionName: string | null) => {
    if (sectionName === null) return null;
    const foreign = foreignFilterSectionsByName.get(sectionName);
    if (foreign) return renderPersistentSectionAction(foreign);
    return (
      <SectionActionButton
        label={`Edit “${sectionName}”`}
        onActivate={() => openSectionEditor('filter', sectionName)}
      />
    );
  };

  /** Force-save: cancel any pending debounce and POST current state now.
   *  Mirrors depictio/dash/layouts/save.py:save_dashboard_minimal — uses
   *  Mantine notifications for success/failure feedback (no persistent header
   *  text). */
  const handleForceSave = useCallback(async () => {
    if (!dashboardId) return;
    const cur = dashboardRef.current;
    if (!cur) return;
    if (saveTimer.current) {
      clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
    setSaveStatus('saving');
    const notifId = notifications.show({
      loading: true,
      title: 'Saving dashboard…',
      message: '',
      autoClose: false,
      withCloseButton: false,
    });
    try {
      await saveDashboard(dashboardId, cur, { forceScreenshot: true });
      setSaveStatus('saved');
      notifications.update({
        id: notifId,
        loading: false,
        color: 'teal',
        title: 'Dashboard saved',
        message: '',
        icon: null,
        autoClose: 2000,
        withCloseButton: true,
      });
    } catch (err) {
      console.error('[EditorApp] force-save failed:', err);
      setSaveStatus('error');
      notifications.update({
        id: notifId,
        loading: false,
        color: 'red',
        title: 'Save failed',
        message: err instanceof Error ? err.message : String(err),
        icon: null,
        autoClose: 4000,
        withCloseButton: true,
      });
    }
  }, [dashboardId]);

  return (
    <>
    <InspectorProviders control={inspectorControl}>
    <SaveGroupContext.Provider value={saveGroupApi}>
    <AppShell
      header={{ height: 50 }}
      navbar={{
        width: 250,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      padding={0}
      transitionDuration={300}
      aside={inspectorAside}
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
          filterCount={countActiveFilters(filters) + groupSummaryRows.length}
          cardsLoading={cardsLoading}
          mode="edit"
          onAddComponent={handleAddComponent}
          onAddSection={handleAddSection}
          onSave={handleForceSave}
          isOwner={isOwner}
          rightExtras={
            <>
              {dashboard && (
                <GroupingHeaderControl
                  groupCount={groupsApi.groups.length}
                  colorBy={groupsApi.colorBy}
                  opened={analysisOpen}
                  onOpenedChange={handleAnalysisOpenChange}
                  armed={analysisArmed}
                  onToggle={handleAnalysisToggle}
                >
                  {groupsSection}
                </GroupingHeaderControl>
              )}
              <MapPanelControl panel={mapPanel} />
              {realtimeEnabled && (
                <span data-tour-id="realtime-indicator" style={{ display: 'inline-flex' }}>
                  <RealtimeIndicator
                    status={realtime.status}
                    mode={realtimeMode}
                    paused={realtimePaused}
                    pendingUpdate={realtime.pendingUpdate}
                    onModeChange={persistRealtimeMode}
                    onPausedChange={setRealtimePaused}
                    onAcknowledgePending={() => {
                      realtime.acknowledgePending();
                      triggerRealtimeRefresh();
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
        <Sidebar
          tabs={tabSiblings}
          activeId={dashboardId}
          mode="edit"
          onAddTab={openCreateTabModal}
          onEditTab={openEditTabModal}
          onDeleteTab={handleDeleteTab}
          onMoveTab={handleMoveTab}
        />
      </AppShell.Navbar>

      <AppShell.Main style={{ height: 'calc(100vh - 50px)' }}>
        {loading && (
          <Group p="lg">
            <Loader size="sm" />
            <Text>Loading dashboard…</Text>
          </Group>
        )}
        {error && (
          <Text c="red" p="lg">
            {error}
          </Text>
        )}
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
            // Cast for the custom property — see the same note in App.tsx.
            style={{
              // Written directly by a drag, so the panel edge doesn't wait on a
              // render — see the same note in App.tsx.
              [FILTER_PANEL_WIDTH_VAR]: `${
                filterPanelOpened ? filterPanelWidth : FILTER_PANEL_RAIL_WIDTH
              }px`,
              display: 'grid',
              // Panel | drag handle | content, the same three tracks the viewer
              // uses. The track count stays at three whatever the panel's
              // state, because `grid-template-columns` only animates between
              // templates with matching track counts.
              gridTemplateColumns: isNarrow
                ? '1fr'
                : `var(${FILTER_PANEL_WIDTH_VAR}) ` +
                  `${filterPanelOpened ? FILTER_PANEL_RESIZER_WIDTH : 0}px 1fr`,
              // Off while dragging — see the same note in App.tsx.
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
                  // not scroll too — otherwise the docked map would scroll away
                  // with the filters instead of staying pinned.
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
                  readOnlySections={readOnlyPanelSections}
                  renderSectionActions={renderPanelSectionAction}
                  dashboardId={dashboardId}
                  // No refreshTick: the editor threads no realtime refresh
                  // counter into any of its grids, so the left panel matches
                  // RightComponentGrid rather than inventing state here.
                  editMode
                  renderItemOverlay={renderFilterItemOverlay}
                  onLayoutChange={handleLeftLayoutChange}
                  collapsed={!filterPanelOpened}
                  onToggleCollapsed={toggleFilterPanel}
                  groupSummaryRows={groupSummaryRows}
                  footer={
                    <MapPanelDock
                      panel={mapPanel}
                      // Docked maps render data: include group filters.
                      filters={combinedFilters}
                      onFilterChange={handleFilterChange}
                      renderEditActions={renderMapPanelEditActions}
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
              data-tour-id="editor-grid"
              style={{
                height: '100%',
                minWidth: 0,
                overflowY: 'auto',
                overflowX: 'hidden',
              }}
            >
              {/* The viewer's fan-out, previewed: read-only surfaces of their
                  own, so a foreign section is visible while laying this tab
                  out without ever entering its editable grid. */}
              {topGridSections.length > 0 && (
                <PersistentSectionsHost
                  sections={topGridSections}
                  familyId={crossTab.familyId}
                  slot="top"
                  filters={filters}
                  onFilterChange={handleFilterChange}
                  groupRender={groupRender}
                  bulkOptions={groupsApi.bulkOptions}
                  renderSectionActions={renderPersistentSectionAction}
                />
              )}
              <RightComponentGrid
                dashboardId={dashboardId!}
                cardComponents={cardComponents}
                otherComponents={otherComponents}
                layoutData={dashboard.right_panel_layout_data}
                gridSections={dashboard.grid_sections}
                filters={combinedFilters}
                groupRender={groupRender}
                onFilterChange={handleFilterChange}
                cardValues={cardValues}
                cardSecondaryValues={cardSecondaryValues}
                cardsLoading={cardsLoading}
                onLayoutChange={handleRightLayoutChange}
                onDeleteComponent={handleDeleteComponent}
                onDuplicateComponent={handleDuplicateComponent}
                onAddComponent={handleAddComponent}
                activeHighlight={activeHighlight}
                onMoveToSection={handleMoveToSection}
                renderSectionActions={renderGridSectionAction}
                refreshTick={plotThemeTick}
              />
              {bottomGridSections.length > 0 && (
                <PersistentSectionsHost
                  sections={bottomGridSections}
                  familyId={crossTab.familyId}
                  slot="bottom"
                  filters={filters}
                  onFilterChange={handleFilterChange}
                  groupRender={groupRender}
                  bulkOptions={groupsApi.bulkOptions}
                  renderSectionActions={renderPersistentSectionAction}
                />
              )}
            </Box>
          </div>
          {/* Mirrors the viewer's footer strip so `placement: 'top'` controls
              sit where they will actually render, instead of appearing in the
              left column only while editing. */}
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
              />
            </Box>
          )}
          </div>
        )}
        {/* Narrow screens: the panel the grid no longer has room for. Not in
            `editMode` — drag-reordering needs a stable panel width to lay its
            grid out against, and a transient drawer on a phone is neither the
            place nor the input device for authoring. */}
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
              groupSummaryRows={groupSummaryRows}
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
            // Floating maps render data: include group filters.
            filters={combinedFilters}
            onFilterChange={handleFilterChange}
            renderEditActions={renderMapPanelEditActions}
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
        onToggleFunnelFiltering={handleToggleFunnelFiltering}
        onChangePlotTheme={handlePlotThemeChange}
      />

      <TabModal
        opened={tabModalState.open}
        mode={tabModalState.mode}
        tab={tabModalState.target}
        onClose={closeTabModal}
        onSubmit={handleTabModalSubmit}
        submitting={tabModalState.submitting}
      />

      <SectionsModal
        opened={sectionsOpened}
        onClose={handleCloseSections}
        dashboard={dashboard}
        onOp={handleSectionOp}
        onAdd={handleManagerAdd}
        onEdit={handleManagerEdit}
      />

      <SectionModal
        opened={sectionModal.open}
        target={sectionModal.target}
        kind={sectionModal.kind}
        dashboard={dashboard}
        onOp={handleSectionOp}
        onClose={handleCloseSectionModal}
        onManageAll={handleManageAllSections}
      />
    </AppShell>
    </SaveGroupContext.Provider>
    </InspectorProviders>
    </>
  );
};

export default EditorApp;

// ---------------------------------------------------------------------------
// Right grid
// ---------------------------------------------------------------------------

interface RightComponentGridProps {
  dashboardId: string;
  cardComponents: StoredMetadata[];
  otherComponents: StoredMetadata[];
  layoutData: unknown;
  gridSections?: FilterSectionSpec[];
  filters: InteractiveFilter[];
  onFilterChange: (filter: InteractiveFilter) => void;
  cardValues: Record<string, unknown>;
  cardSecondaryValues: Record<string, Record<string, unknown>>;
  cardsLoading: boolean;
  onLayoutChange: (newLayout: Layout[]) => void;
  onDeleteComponent: (componentId: string) => void;
  onDuplicateComponent: (componentId: string) => void;
  onAddComponent: () => void;
  activeHighlight?: ActiveHighlight | null;
  groupRender?: GroupRenderState;
  /** Fired by each cell's "Move to section" action. The names on offer are
   *  derived from `gridSections`, which this component already receives. */
  onMoveToSection: (componentId: string, section: string | null) => void;
  /** Per-section header action — the "…" that opens that section's settings. */
  renderSectionActions?: (sectionName: string | null) => React.ReactNode;
  /** Bumped when the dashboard plot theme changes, so figures refetch. */
  refreshTick?: number;
}

/**
 * The right pane in the editor: a single draggable + resizable grid that
 * holds every right-panel component (cards + figures + tables + ...). All
 * items live in `right_panel_layout_data` so they can be rearranged together.
 * Rendered via the shared `DashboardGrid` with `isDraggable` / `isResizable` /
 * `editMode` enabled and a `renderItemOverlay` callback that injects the
 * per-cell edit menu.
 */
const RightComponentGrid: React.FC<RightComponentGridProps> = ({
  dashboardId,
  cardComponents,
  otherComponents,
  layoutData,
  gridSections,
  filters,
  onFilterChange,
  cardValues,
  cardSecondaryValues,
  cardsLoading,
  onLayoutChange,
  onDeleteComponent,
  onDuplicateComponent,
  onAddComponent,
  activeHighlight,
  groupRender,
  onMoveToSection,
  renderSectionActions,
  refreshTick,
}) => {
  const allComponents = useMemo(
    () => [...cardComponents, ...otherComponents],
    [cardComponents, otherComponents],
  );

  if (allComponents.length === 0) {
    return (
      <Center style={{ height: '100%', minHeight: 320 }}>
        <Stack align="center" gap="md" maw={400}>
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
            <Title order={4} fw={700} ta="center">No components yet</Title>
            <Text size="sm" c="dimmed" ta="center">
              Add your first component to start building this dashboard.
            </Text>
          </Stack>
          <Button
            leftSection={<Icon icon="mdi:plus-circle" width={18} />}
            color="green"
            variant="filled"
            size="md"
            onClick={onAddComponent}
          >
            Add component
          </Button>
        </Stack>
      </Center>
    );
  }

  return (
    <DashboardGrid
      dashboardId={dashboardId}
      metadataList={allComponents}
      layoutData={layoutData}
      gridSections={gridSections}
      filters={filters}
      onFilterChange={onFilterChange}
      cardValues={cardValues}
      cardSecondaryValues={cardSecondaryValues}
      cardValuesLoading={cardsLoading}
      activeHighlight={activeHighlight}
      groupRender={groupRender}
      refreshTick={refreshTick}
      isDraggable={true}
      isResizable={true}
      editMode={true}
      renderSectionActions={renderSectionActions}
      onLayoutChange={onLayoutChange}
      renderItemOverlay={(componentId, metadata) => (
        <GridItemEditOverlay
          dashboardId={dashboardId}
          componentId={componentId}
          editMode={true}
          onDelete={onDeleteComponent}
          onDuplicate={onDuplicateComponent}
          componentType={metadata.component_type}
          sections={gridSections}
          currentSection={metadata.section ?? null}
          onMoveToSection={onMoveToSection}
        />
      )}
    />
  );
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractDashboardId(): string | null {
  const path = window.location.pathname;
  const match = path.match(/\/dashboard-edit\/([^/?#]+)/);
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

/** Strip a single component id from a layout array (or breakpoint dict). */
function stripFromLayout(layoutData: unknown, componentId: string): unknown {
  if (!layoutData) return layoutData;
  if (Array.isArray(layoutData)) {
    return layoutData.filter(
      (it) =>
        !(
          it &&
          typeof it === 'object' &&
          stripBoxPrefix(String((it as Layout).i)) === componentId
        ),
    );
  }
  if (typeof layoutData === 'object') {
    const obj = layoutData as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
      if (Array.isArray(v)) {
        out[k] = (v as Layout[]).filter(
          (it) =>
            !(
              it &&
              typeof it === 'object' &&
              stripBoxPrefix(String(it.i)) === componentId
            ),
        );
      } else {
        out[k] = v;
      }
    }
    return out;
  }
  return layoutData;
}

/** Cheap structural compare for layout arrays — avoids unnecessary saves. */
function layoutsEqual(a: unknown, b: unknown): boolean {
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}

/** RFC4122-ish v4 UUID for runtimes lacking crypto.randomUUID. */
function fallbackUuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** Yield each layout entry from either an array or breakpoint-keyed dict. */
function eachLayoutEntry(layoutData: unknown): Layout[] {
  if (!layoutData) return [];
  if (Array.isArray(layoutData)) {
    return layoutData.filter(
      (it): it is Layout =>
        Boolean(it) && typeof it === 'object' && 'i' in it,
    );
  }
  if (typeof layoutData === 'object') {
    const obj = layoutData as Record<string, unknown>;
    const out: Layout[] = [];
    for (const v of Object.values(obj)) {
      if (Array.isArray(v)) {
        for (const it of v) {
          if (it && typeof it === 'object' && 'i' in it) out.push(it as Layout);
        }
      }
    }
    return out;
  }
  return [];
}

function layoutContains(layoutData: unknown, componentId: string): boolean {
  return eachLayoutEntry(layoutData).some(
    (it) => stripBoxPrefix(String(it.i)) === componentId,
  );
}

function findLayoutEntry(
  layoutData: unknown,
  componentId: string,
): Layout | undefined {
  return eachLayoutEntry(layoutData).find(
    (it) => stripBoxPrefix(String(it.i)) === componentId,
  );
}

/**
 * Append a new layout entry to either an array layout or each breakpoint of a
 * dict layout. Preserves the original container shape so downstream code keeps
 * working without a normalization step.
 */
function appendToLayout(layoutData: unknown, entry: Layout): unknown {
  if (!layoutData || Array.isArray(layoutData)) {
    return [...((layoutData as Layout[] | null) || []), entry];
  }
  if (typeof layoutData === 'object') {
    const obj = layoutData as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
      out[k] = Array.isArray(v) ? [...(v as Layout[]), entry] : v;
    }
    return out;
  }
  return [entry];
}
