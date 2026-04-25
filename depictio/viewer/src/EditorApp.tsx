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
  Title,
  Box,
  Paper,
  Stack,
  SimpleGrid,
} from '@mantine/core';
import GridLayout, { Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';

import {
  fetchDashboard,
  fetchAllDashboards,
  bulkComputeCards,
  ComponentRenderer,
} from 'depictio-react-core';
import type {
  DashboardData,
  DashboardSummary,
  InteractiveFilter,
  StoredMetadata,
} from 'depictio-react-core';

import PanelSplitter from './components/PanelSplitter';
import LeftFilterPanel from './components/LeftFilterPanel';
import GridItemEditOverlay from './components/GridItemEditOverlay';
import AddComponentButton from './components/AddComponentButton';

const API_BASE = '/depictio/api/v1';
const SAVE_DEBOUNCE_MS = 500;

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
  const [, setAllDashboards] = useState<DashboardSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<InteractiveFilter[]>([]);
  const [cardValues, setCardValues] = useState<Record<string, unknown>>({});
  const [cardsLoading, setCardsLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');

  const dashboardId = extractDashboardId();
  const bulkCtrl = useRef<AbortController | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Latest dashboard ref so the debounced save uses fresh state.
  const dashboardRef = useRef<DashboardData | null>(null);
  useEffect(() => {
    dashboardRef.current = dashboard;
  }, [dashboard]);

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

  return (
    <AppShell header={{ height: 65 }} padding={0}>
      <AppShell.Header>
        <EditorHeader
          dashboardId={dashboardId}
          dashboard={dashboard}
          saveStatus={saveStatus}
          cardsLoading={cardsLoading}
        />
      </AppShell.Header>

      <AppShell.Main style={{ height: 'calc(100vh - 65px)' }}>
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
          <PanelSplitter
            left={
              <Box p="md" style={{ height: '100%' }}>
                <LeftFilterPanel
                  dashboardId={dashboardId!}
                  interactiveComponents={interactiveComponents}
                  layoutData={dashboard.left_panel_layout_data}
                  filters={filters}
                  onFilterChange={handleFilterChange}
                  onLeftLayoutChange={handleLeftLayoutChange}
                  editMode={true}
                  onDeleteComponent={handleDeleteComponent}
                />
              </Box>
            }
            right={
              <Box p="md" style={{ height: '100%' }}>
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
                />
              </Box>
            }
          />
        )}
      </AppShell.Main>
    </AppShell>
  );
};

export default EditorApp;

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

interface EditorHeaderProps {
  dashboardId: string | null;
  dashboard: DashboardData | null;
  saveStatus: SaveStatus;
  cardsLoading: boolean;
}

const EditorHeader: React.FC<EditorHeaderProps> = ({
  dashboardId,
  dashboard,
  saveStatus,
  cardsLoading,
}) => {
  const title = dashboard?.title || dashboardId || 'Dashboard';
  return (
    <Group h="100%" px="md" justify="space-between" wrap="nowrap">
      <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
        <Title
          order={3}
          style={{
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            minWidth: 0,
          }}
        >
          {title}
        </Title>
        <Text size="xs" c="dimmed">
          (editor)
        </Text>
        {cardsLoading && <Loader size="xs" />}
      </Group>
      <Group gap={8} wrap="nowrap" style={{ flexShrink: 0 }}>
        <SaveIndicator status={saveStatus} />
        {dashboardId && <AddComponentButton dashboardId={dashboardId} />}
      </Group>
    </Group>
  );
};

const SaveIndicator: React.FC<{ status: SaveStatus }> = ({ status }) => {
  if (status === 'saving') {
    return (
      <Group gap={6}>
        <Loader size="xs" />
        <Text size="xs" c="dimmed">
          Saving…
        </Text>
      </Group>
    );
  }
  if (status === 'saved') {
    return (
      <Text size="xs" c="green">
        Saved
      </Text>
    );
  }
  if (status === 'error') {
    return (
      <Text size="xs" c="red">
        Save failed
      </Text>
    );
  }
  return null;
};

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
}

/**
 * The right pane is rendered as a draggable + resizable react-grid-layout.
 * `DashboardGrid` from the shared core hardcodes draggable/resizable=false,
 * so we render `GridLayout` directly here for the editor.
 *
 * Cards are pinned to the top of the grid (auto-flow as 4×3 cells); other
 * components below at 6×4 — same fallback policy as DashboardGrid's
 * `normalizeLayout`. Once `stored_layout_data`/right_panel_layout_data is
 * populated, that takes precedence.
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
}) => {
  const allComponents = useMemo(
    () => [...cardComponents, ...otherComponents],
    [cardComponents, otherComponents],
  );
  const layout = useMemo(
    () => normalizeRightLayout(allComponents, layoutData),
    [allComponents, layoutData],
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

  // Use the parent box width for the grid; fall back to a sensible default.
  const containerWidth =
    typeof window !== 'undefined'
      ? Math.max(640, Math.floor(window.innerWidth * 0.7) - 32)
      : 1000;

  return (
    <>
      {cardComponents.length > 0 && (
        <SimpleGrid
          cols={{ base: 1, xs: 2, md: Math.min(cardComponents.length, 4) }}
          spacing="md"
          mb="md"
        >
          {cardComponents.map((m) => (
            <Box key={m.index} style={{ position: 'relative' }}>
              <GridItemEditOverlay
                dashboardId={dashboardId}
                componentId={m.index}
                editMode={true}
                onDelete={onDeleteComponent}
              />
              <ComponentRenderer
                metadata={m}
                filters={filters}
                cardValue={cardValues?.[m.index]}
                cardLoading={cardsLoading}
              />
            </Box>
          ))}
        </SimpleGrid>
      )}
      {otherComponents.length > 0 && (
        <GridLayout
          className="layout right-component-grid"
          layout={layout.filter((l) =>
            otherComponents.some((c) => c.index === l.i),
          )}
          cols={12}
          rowHeight={50}
          width={containerWidth}
          margin={[12, 12]}
          containerPadding={[0, 0]}
          isDraggable={true}
          isResizable={true}
          compactType="vertical"
          onLayoutChange={(next) => onLayoutChange(next)}
        >
          {otherComponents.map((m) => (
            <div
              key={m.index}
              style={{ position: 'relative', overflow: 'hidden' }}
            >
              <GridItemEditOverlay
                dashboardId={dashboardId}
                componentId={m.index}
                editMode={true}
                onDelete={onDeleteComponent}
              />
              <ComponentRenderer
                metadata={m}
                filters={filters}
                dashboardId={dashboardId}
              />
            </div>
          ))}
        </GridLayout>
      )}
    </>
  );
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractDashboardId(): string | null {
  const path = window.location.pathname;
  const match = path.match(/\/dashboard-beta\/([^/?#]+)/);
  return match?.[1] || null;
}

function stableFilterKey(filters: InteractiveFilter[]): string {
  const sorted = [...filters].sort((a, b) => a.index.localeCompare(b.index));
  return JSON.stringify(sorted.map((f) => [f.index, f.value]));
}

function stripBoxPrefix(id: string): string {
  return id.startsWith('box-') ? id.slice(4) : id;
}

function normalizeRightLayout(
  components: StoredMetadata[],
  layoutData: unknown,
): Layout[] {
  const items = extractLayoutItems(layoutData);
  const indexSet = new Set(components.map((c) => c.index));
  const matched = items
    .map((it) => ({ ...it, i: stripBoxPrefix(it.i) }))
    .filter((it) => indexSet.has(it.i));
  const seen = new Set(matched.map((it) => it.i));
  const fallback = components
    .filter((c) => !seen.has(c.index))
    .map((c, idx) => ({
      i: c.index,
      x: (idx % 2) * 6,
      y: 1000 + Math.floor(idx / 2) * 4,
      w: 6,
      h: 4,
    }));
  return [...matched, ...fallback];
}

function extractLayoutItems(layoutData: unknown): Layout[] {
  if (!layoutData) return [];
  if (Array.isArray(layoutData)) {
    return layoutData.filter(
      (i): i is Layout =>
        Boolean(i) && typeof i === 'object' && 'i' in i && 'x' in i && 'y' in i,
    );
  }
  if (typeof layoutData === 'object') {
    const obj = layoutData as Record<string, unknown>;
    const candidateKey =
      'lg' in obj
        ? 'lg'
        : Object.keys(obj).find((k) => Array.isArray(obj[k])) || '';
    if (candidateKey && Array.isArray(obj[candidateKey])) {
      return (obj[candidateKey] as Layout[]).filter(
        (i) => Boolean(i) && typeof i === 'object' && 'i' in i,
      );
    }
  }
  return [];
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
