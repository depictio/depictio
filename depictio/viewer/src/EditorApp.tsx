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
} from 'react';
import {
  AppShell,
  Group,
  Text,
  Loader,
  Box,
  Paper,
  Stack,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import type { Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';

import {
  fetchDashboard,
  fetchAllDashboards,
  bulkComputeCards,
  DashboardGrid,
} from 'depictio-react-core';
import type {
  DashboardData,
  DashboardSummary,
  InteractiveFilter,
  StoredMetadata,
} from 'depictio-react-core';

import LeftFilterPanel from './components/LeftFilterPanel';
import GridItemEditOverlay from './components/GridItemEditOverlay';
import { Header, Sidebar, SettingsDrawer } from './chrome';
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

/** Local POST wrapper for layout/component persistence. */
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
    throw new Error(`Failed to save dashboard: ${res.status}`);
  }
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

const EditorApp: React.FC = () => {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [allDashboards, setAllDashboards] = useState<DashboardSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<InteractiveFilter[]>([]);
  const [cardValues, setCardValues] = useState<Record<string, unknown>>({});
  const [cardsLoading, setCardsLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(false);
  const [settingsOpened, { open: openSettings, close: closeSettings }] = useDisclosure(false);

  const dashboardId = extractDashboardId();
  const bulkCtrl = useRef<AbortController | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Latest dashboard ref so the debounced save uses fresh state.
  const dashboardRef = useRef<DashboardData | null>(null);
  useEffect(() => {
    dashboardRef.current = dashboard;
  }, [dashboard]);

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
        setDashboard(dash);
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
      // Reset card values so each card shows its individual loader while the
      // bulk-compute round-trip is in flight (instead of keeping stale values
      // visible until the response).
      setCardValues({});
      if (bulkCtrl.current) bulkCtrl.current.abort();
      bulkCtrl.current = new AbortController();
      bulkComputeCards(dashboardId, filters, cardIds)
        .then((res) => setCardValues(res.values))
        .catch((err) => {
          if (err?.name !== 'AbortError') {
            console.warn('[EditorApp] bulk-compute failed:', err);
          }
        })
        .finally(() => setCardsLoading(false));
    }, 150);
    return () => clearTimeout(timer);
  }, [dashboard, dashboardId, stableFilterKey(filters)]);

  const handleFilterChange = useCallback((update: InteractiveFilter) => {
    setFilters((prev) => {
      const without = prev.filter((f) => f.index !== update.index);
      const hasValue = Array.isArray(update.value)
        ? update.value.length > 0
        : update.value != null && update.value !== '';
      return hasValue ? [...without, update] : without;
    });
  }, []);

  /** Debounced save: schedule a POST 500ms after the last layout mutation. */
  const scheduleSave = useCallback(
    (next: DashboardData) => {
      if (!dashboardId) return;
      setDashboard(next);
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
    [dashboardId],
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
      setDashboard(next);
      setSaveStatus('saving');
      try {
        await saveDashboard(dashboardId, next);
        const fresh = await fetchDashboard(dashboardId);
        setDashboard(fresh);
        setSaveStatus('saved');
      } catch (err) {
        console.error('[EditorApp] delete failed:', err);
        setSaveStatus('error');
      }
    },
    [dashboardId],
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
      setDashboard(next);
      setSaveStatus('saving');
      try {
        await saveDashboard(dashboardId, next);
        const fresh = await fetchDashboard(dashboardId);
        setDashboard(fresh);
        setSaveStatus('saved');
      } catch (err) {
        console.error('[EditorApp] duplicate failed:', err);
        setSaveStatus('error');
      }
    },
    [dashboardId],
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

  const handleAddComponent = useCallback(() => {
    if (!dashboardId) return;
    const newId =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : fallbackUuid();
    window.location.assign(
      `${dashOrigin()}/dashboard-edit/${dashboardId}/component/add/${newId}`,
    );
  }, [dashboardId]);

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
    <AppShell
      header={{ height: 50 }}
      navbar={{
        width: 250,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      padding={0}
    >
      <AppShell.Header>
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
          onSave={handleForceSave}
        />
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <Sidebar tabs={tabSiblings} activeId={dashboardId} />
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
              }}
            >
              <RightComponentGrid
                dashboardId={dashboardId!}
                cardComponents={cardComponents}
                otherComponents={otherComponents}
                layoutData={dashboard.right_panel_layout_data}
                filters={filters}
                cardValues={cardValues}
                cardsLoading={cardsLoading}
                onLayoutChange={handleRightLayoutChange}
                onDeleteComponent={handleDeleteComponent}
                onDuplicateComponent={handleDuplicateComponent}
              />
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
  cardValues: Record<string, unknown>;
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
  cardValues,
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
      cardValues={cardValues}
      cardValuesLoading={cardsLoading}
      isDraggable={true}
      isResizable={true}
      editMode={true}
      onLayoutChange={onLayoutChange}
      renderItemOverlay={(componentId) => (
        <GridItemEditOverlay
          dashboardId={dashboardId}
          componentId={componentId}
          editMode={true}
          onDelete={onDeleteComponent}
          onDuplicate={onDuplicateComponent}
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
  const sorted = [...filters].sort((a, b) => a.index.localeCompare(b.index));
  return JSON.stringify(sorted.map((f) => [f.index, f.value]));
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
