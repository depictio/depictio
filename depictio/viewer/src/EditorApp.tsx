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
 *   - Read-only viewer: /dashboard-beta/{dashboardId}
 *   - Editor:           /dashboard-beta/{dashboardId}/edit
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
  useDeferredValue,
} from 'react';
import {
  ActionIcon,
  AppShell,
  Box,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { useSidebarOpen } from './hooks/useSidebarOpen';
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
  mergeFiltersBySource,
  useDataCollectionUpdates,
  RealtimeIndicator,
  useRealtimeJournal,
} from 'depictio-react-core';
import type {
  DashboardData,
  DashboardSummary,
  InteractiveFilter,
  StoredMetadata,
  RealtimeMode,
} from 'depictio-react-core';
import { AIAnalyzePanel, AddWithAIModal } from 'depictio-react-ai';
import type { AvailableDataCollection, DashboardActions } from 'depictio-react-ai';

import LeftFilterPanel from './components/LeftFilterPanel';
import GridItemEditOverlay from './components/GridItemEditOverlay';
import { Header, Sidebar, SettingsDrawer, TabModal } from './chrome';
import type { TabModalSubmitPayload } from './chrome';
import { useAuthMode } from './auth/hooks/useAuthMode';
import DemoTour from './demo/DemoTour';
import DemoModeBanner from './components/DemoModeBanner';
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

/** Local helper — uses the same auth pattern as `depictio-react-core/api.ts`. */
function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  try {
    const stored = localStorage.getItem('local-store');
    if (stored) {
      const parsed = JSON.parse(stored);
      if (parsed?.access_token) {
        headers.Authorization = `Bearer ${parsed.access_token}`;
      }
    }
  } catch {
    // ignore
  }
  return headers;
}

/** Local POST wrapper for layout/component persistence. Surfaces the response
 *  body on failure so callers can debug 422 validation errors at the console. */
async function saveDashboard(
  dashboardId: string,
  dashboardData: DashboardData,
): Promise<void> {
  const res = await fetch(`${API_BASE}/dashboards/save/${dashboardId}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(dashboardData),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to save dashboard: ${res.status} ${text}`);
  }
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const EditorApp: React.FC = () => {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [allDashboards, setAllDashboards] = useState<DashboardSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<InteractiveFilter[]>([]);
  // Deferred copy for heavy renderers (figures / tables / maps / image grid)
  // so a slider drag doesn't refetch on every step. See App.tsx for context.
  const deferredFilters = useDeferredValue(filters);
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
  const [addAIOpened, { open: openAddAI, close: closeAddAI }] = useDisclosure(false);
  const auth = useAuthMode();
  const isDemoMode = auth.status?.is_demo_mode === true;
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
      setError('No dashboard ID in URL. Expected /dashboard-beta/<id>/edit.');
      setLoading(false);
      return;
    }
    Promise.all([fetchDashboard(dashboardId), fetchAllDashboards()])
      .then(([dash, all]) => {
        applyDashboard(dash);
        setAllDashboards(all);
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
      bulkComputeCards(dashboardId, filters, cardIds)
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
  }, [dashboard, dashboardId, stableFilterKey(filters)]);

  const handleFilterChange = useCallback((update: InteractiveFilter) => {
    setFilters((prev) => mergeFiltersBySource(prev, update));
  }, []);

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

  const handleLeftLayoutChange = useCallback(
    (newLayout: Layout[]) => {
      const cur = dashboardRef.current;
      if (!cur) return;
      // Skip no-op writes during the initial mount where react-grid-layout
      // emits the layout it was just given.
      const prev = cur.left_panel_layout_data;
      if (layoutsEqual(prev, newLayout)) return;
      scheduleSave({ ...cur, left_panel_layout_data: newLayout });
    },
    [scheduleSave],
  );

  const handleRightLayoutChange = useCallback(
    (newLayout: Layout[]) => {
      const cur = dashboardRef.current;
      if (!cur) return;
      const prev = cur.right_panel_layout_data;
      if (layoutsEqual(prev, newLayout)) return;
      scheduleSave({ ...cur, right_panel_layout_data: newLayout });
    },
    [scheduleSave],
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

  const interactiveComponents = useMemo(
    () =>
      (dashboard?.stored_metadata || []).filter(
        (m) => m.component_type === 'interactive',
      ),
    [dashboard],
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
          m.component_type !== 'card' && m.component_type !== 'interactive',
      ),
    [dashboard],
  );

  // Index → component_type lookup so AI-driven filter mutations can be
  // converted to the correct InteractiveFilter shape (mirrors App.tsx).
  const interactiveTypeByIndex = useMemo(() => {
    const out: Record<string, string> = {};
    for (const m of dashboard?.stored_metadata || []) {
      const meta = m as {
        index?: string;
        component_type?: string;
        interactive_component_type?: string;
        metadata?: { interactive_component_type?: string };
      };
      if (!meta.index) continue;
      const t =
        meta.interactive_component_type ??
        meta.metadata?.interactive_component_type ??
        meta.component_type ??
        '';
      out[meta.index] = String(t);
    }
    return out;
  }, [dashboard?.stored_metadata]);

  const handleApplyActions = useCallback(
    (actions: DashboardActions) => {
      let filterCount = 0;
      for (const f of actions.filters) {
        const componentType = interactiveTypeByIndex[f.component_id];
        handleFilterChange({
          index: f.component_id,
          value: f.value,
          interactive_component_type: componentType,
        });
        filterCount += 1;
      }
      if (filterCount) {
        notifications.show({
          color: 'teal',
          title: 'AI applied filters',
          message: `${filterCount} filter${filterCount === 1 ? '' : 's'} updated.`,
        });
      }
      // Figure mutations of existing components: we have edit access here, but
      // the v1 mutation surface is intentionally narrow — surface them as a
      // notification so the user can hand-apply via the figure editor.
      if (actions.figure_mutations.length) {
        notifications.show({
          color: 'yellow',
          title: 'Figure changes proposed',
          message: `${actions.figure_mutations.length} figure mutation${
            actions.figure_mutations.length === 1 ? '' : 's'
          } proposed — open the figure editor to apply.`,
        });
      }
    },
    [handleFilterChange, interactiveTypeByIndex],
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

  const handleResetAllFilters = useCallback(() => setFilters([]), []);

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
    [triggerRealtimeRefresh, appendJournal],
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
      `/dashboard-beta-edit/${dashboardId}/component/add/${newId}`,
    );
  }, [dashboardId]);

  /** Unique DCs already referenced anywhere on this dashboard. Surface
   *  these to the AI modal so the user can pick which DC to author
   *  against — for v1 we only support DCs already attached (lifting that
   *  would require a separate project-DC fetch). */
  const availableDcs = useMemo<AvailableDataCollection[]>(() => {
    const seen = new Set<string>();
    const out: AvailableDataCollection[] = [];
    for (const m of dashboard?.stored_metadata || []) {
      const meta = m as {
        dc_id?: unknown;
        wf_id?: unknown;
        data_collection_tag?: string;
        workflow_tag?: string;
        metadata?: {
          dc_id?: unknown;
          wf_id?: unknown;
          data_collection_tag?: string;
          workflow_tag?: string;
        };
      };
      const dcId = oidString(meta.dc_id ?? meta.metadata?.dc_id);
      if (!dcId || seen.has(dcId)) continue;
      seen.add(dcId);
      out.push({
        dcId,
        dcTag: meta.data_collection_tag ?? meta.metadata?.data_collection_tag ?? dcId,
        wfId: oidString(meta.wf_id ?? meta.metadata?.wf_id) ?? undefined,
        wfTag: meta.workflow_tag ?? meta.metadata?.workflow_tag,
      });
    }
    return out;
  }, [dashboard?.stored_metadata]);

  /** Stash the AI proposal in sessionStorage under a key tied to the new
   *  component id, then navigate to the stepper page. CreateComponentPage
   *  picks it up on mount, hydrates the builder store, and jumps to the
   *  Design step. Keyed-by-id so two parallel tabs don't collide. */
  const handleAddWithAI = useCallback(
    (
      parsed: Record<string, unknown>,
      componentType: string,
      dc: AvailableDataCollection,
    ) => {
      if (!dashboardId) return;
      const newId =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : fallbackUuid();
      try {
        sessionStorage.setItem(
          `depictio.ai.pending-fill.${newId}`,
          JSON.stringify({
            componentType,
            dcId: dc.dcId,
            wfId: dc.wfId ?? null,
            parsed,
          }),
        );
      } catch {
        // sessionStorage can throw under quota / privacy modes — fall
        // through to navigate anyway; the page will show the empty stepper.
      }
      closeAddAI();
      window.location.assign(
        `/dashboard-beta-edit/${dashboardId}/component/add/${newId}`,
      );
    },
    [dashboardId, closeAddAI],
  );

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
          // `/dashboard-beta-edit/{id}` route we're already on.
          window.location.assign(`/dashboard-beta-edit/${newId}`);
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
          window.location.assign(`/dashboard-beta-edit/${parentId}`);
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
      await saveDashboard(dashboardId, cur);
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
      {isDemoMode && <DemoModeBanner />}
      <DemoTour active={isDemoMode} />
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
          mode="edit"
          onAddComponent={handleAddComponent}
          onAddWithAI={openAddAI}
          onSave={handleForceSave}
          rightExtras={
            <>

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
              display: 'grid',
              // 20vw / remainder. Using viewport units (vs. % of main) so the
              // left panel keeps a fixed visual width regardless of any chrome
              // that might shrink "main". User asked for ~1/5 left, 4/5 right.
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
              <LeftFilterPanel
                dashboardId={dashboardId!}
                interactiveComponents={interactiveComponents}
                layoutData={dashboard.left_panel_layout_data}
                filters={filters}
                onFilterChange={handleFilterChange}
                onLeftLayoutChange={handleLeftLayoutChange}
                editMode={true}
                onDeleteComponent={handleDeleteComponent}
                onDuplicateComponent={handleDuplicateComponent}
              />
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
              {dashboardId && (
                <AIAnalyzePanel
                  dashboardId={dashboardId}
                  onApplyActions={handleApplyActions}
                />
              )}
              <Box style={{ flex: 1, minHeight: 0 }}>
              <RightComponentGrid
                dashboardId={dashboardId!}
                cardComponents={cardComponents}
                otherComponents={otherComponents}
                layoutData={dashboard.right_panel_layout_data}
                filters={deferredFilters}
                onFilterChange={handleFilterChange}
                cardValues={cardValues}
                cardSecondaryValues={cardSecondaryValues}
                cardsLoading={cardsLoading}
                onLayoutChange={handleRightLayoutChange}
                onDeleteComponent={handleDeleteComponent}
                onDuplicateComponent={handleDuplicateComponent}
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

      <TabModal
        opened={tabModalState.open}
        mode={tabModalState.mode}
        tab={tabModalState.target}
        onClose={closeTabModal}
        onSubmit={handleTabModalSubmit}
        submitting={tabModalState.submitting}
      />

      {dashboardId && (
        <AddWithAIModal
          opened={addAIOpened}
          onClose={closeAddAI}
          dashboardId={dashboardId}
          availableDataCollections={availableDcs}
          onApply={handleAddWithAI}
        />
      )}
    </AppShell>
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
  filters: InteractiveFilter[];
  onFilterChange: (filter: InteractiveFilter) => void;
  cardValues: Record<string, unknown>;
  cardSecondaryValues: Record<string, Record<string, unknown>>;
  cardsLoading: boolean;
  onLayoutChange: (newLayout: Layout[]) => void;
  onDeleteComponent: (componentId: string) => void;
  onDuplicateComponent: (componentId: string) => void;
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
  filters,
  onFilterChange,
  cardValues,
  cardSecondaryValues,
  cardsLoading,
  onLayoutChange,
  onDeleteComponent,
  onDuplicateComponent,
}) => {
  const allComponents = useMemo(
    () => [...cardComponents, ...otherComponents],
    [cardComponents, otherComponents],
  );

  // Empty-state fallback so users see SOMETHING before any layout is saved.
  if (allComponents.length === 0) {
    return (
      <Paper p="md" withBorder radius="md" style={{ height: '100%' }}>
        <Stack gap="sm">
          <Title order={5}>Components</Title>
          <Text size="sm" c="dimmed">
            No components yet. Click "Add component" in the header to get
            started.
          </Text>
        </Stack>
      </Paper>
    );
  }

  return (
    <DashboardGrid
      dashboardId={dashboardId}
      metadataList={allComponents}
      layoutData={layoutData}
      filters={filters}
      onFilterChange={onFilterChange}
      cardValues={cardValues}
      cardSecondaryValues={cardSecondaryValues}
      cardValuesLoading={cardsLoading}
      isDraggable={true}
      isResizable={true}
      editMode={true}
      onLayoutChange={onLayoutChange}
      renderItemOverlay={(componentId, metadata) => (
        <GridItemEditOverlay
          dashboardId={dashboardId}
          componentId={componentId}
          editMode={true}
          onDelete={onDeleteComponent}
          onDuplicate={onDuplicateComponent}
          componentType={metadata.component_type}
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
  const match = path.match(/\/dashboard-beta-edit\/([^/?#]+)/);
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

function stripBoxPrefix(id: string): string {
  return id.startsWith('box-') ? id.slice(4) : id;
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

/**
 * Coerce an id field to its string form. The save endpoint round-trips
 * dc_id / wf_id as `{$oid: "..."}` for some sources and as bare strings
 * for others; the AI surface always wants a flat string for the
 * /figure/preview metadata.
 */
function oidString(value: unknown): string | undefined {
  if (typeof value === 'string' && value) return value;
  if (value && typeof value === 'object' && '$oid' in value) {
    const v = (value as { $oid?: unknown }).$oid;
    if (typeof v === 'string' && v) return v;
  }
  return undefined;
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
