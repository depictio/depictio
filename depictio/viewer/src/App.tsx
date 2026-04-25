import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import {
  AppShell,
  Group,
  Text,
  Loader,
  Anchor,
  Stack,
  Title,
  Grid,
  Paper,
  SimpleGrid,
  Divider,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';

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
} from 'depictio-react-core';
import { Header, Sidebar, SettingsDrawer } from './chrome';

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
  const [cardsLoading, setCardsLoading] = useState(false);
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure();
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);
  const [settingsOpened, { open: openSettings, close: closeSettings }] = useDisclosure(false);

  const dashboardId = extractDashboardId();
  const bulkCtrl = useRef<AbortController | null>(null);

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

  // Bulk-compute card values whenever filters change
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
          if (err?.name !== 'AbortError') console.warn('[App] bulk-compute failed:', err);
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

  const handleResetAllFilters = useCallback(() => setFilters([]), []);

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

  return (
    <AppShell
      header={{ height: 65 }}
      navbar={{
        width: 250,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      padding="md"
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
        />
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <Sidebar tabs={tabSiblings} activeId={dashboardId} />
      </AppShell.Navbar>

      <AppShell.Main>
        {loading && (
          <Group p="lg">
            <Loader size="sm" />
            <Text>Loading dashboard…</Text>
          </Group>
        )}
        {error && <Text c="red" p="lg">{error}</Text>}
        {dashboard && !loading && !error && (
          <Grid gutter="md">
            {/* LEFT 1/3 — interactive components stacked */}
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Paper p="md" withBorder radius="md" style={{ height: '100%' }}>
                <Title order={5} mb="sm">
                  Filters
                </Title>
                <Stack gap="sm">
                  {interactiveComponents.length === 0 && (
                    <Text size="sm" c="dimmed">No interactive components.</Text>
                  )}
                  {interactiveComponents.map((m) => (
                    <ComponentRenderer
                      key={m.index}
                      metadata={m}
                      filters={filters}
                      onFilterChange={handleFilterChange}
                    />
                  ))}
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
            </Grid.Col>

            {/* RIGHT 2/3 — cards row + other components */}
            <Grid.Col span={{ base: 12, md: 8 }}>
              <Stack gap="md">
                {cardComponents.length > 0 && (
                  <SimpleGrid
                    cols={{ base: 1, xs: 2, md: cardComponents.length }}
                    spacing="md"
                  >
                    {cardComponents.map((m) => (
                      <ComponentRenderer
                        key={m.index}
                        metadata={m}
                        filters={filters}
                        cardValue={cardValues?.[m.index]}
                        cardLoading={cardsLoading}
                      />
                    ))}
                  </SimpleGrid>
                )}

                {otherComponents.length > 0 && (
                  <>
                    {cardComponents.length > 0 && <Divider />}
                    <Stack gap="md">
                      {otherComponents.map((m) => (
                        <ComponentRenderer
                          key={m.index}
                          metadata={m}
                          filters={filters}
                          dashboardId={dashboardId!}
                        />
                      ))}
                    </Stack>
                  </>
                )}
              </Stack>
            </Grid.Col>
          </Grid>
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

export default App;

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
