import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import {
  AppShell,
  Group,
  Text,
  Loader,
  Anchor,
  Burger,
  NavLink,
  Stack,
  Title,
  ScrollArea,
  Grid,
  Paper,
  SimpleGrid,
  Divider,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';

import {
  fetchDashboard,
  fetchAllDashboards,
  bulkComputeCards,
  DashboardData,
  DashboardSummary,
  InteractiveFilter,
  StoredMetadata,
} from './api';
import ComponentRenderer from './components/ComponentRenderer';

/**
 * Top-level SPA. Layout (per user spec):
 *
 *   ┌──────── Header (65px) ─────────┐
 *   │ Burger | Depictio | Tab title  │
 *   ├────────┬───────────────────────┤
 *   │ Tabs   │ Main: 1/3 + 2/3       │
 *   │ navbar │ ┌─────┬─────────────┐ │
 *   │ collap │ │ 1/3 │  Cards row  │ │
 *   │ sible  │ │ inter│────────────│ │
 *   │        │ │ active│ figures   │ │
 *   │        │ │      │ tables ... │ │
 *   │        │ └─────┴─────────────┘ │
 *
 * Sidebar shows the parent dashboard + sibling tabs.
 * Left panel (1/3) holds all interactive components stacked vertically.
 * Right panel (2/3) shows the 4 cards in a single row, then any figures/tables.
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

  // Group tabs: parent dashboard + all its child tabs. Works whether the
  // current view is the parent or one of its children.
  //   - If current is the parent (no parent_dashboard_id) → include self
  //     + every dashboard whose parent_dashboard_id === self.dashboard_id
  //   - If current is a child → include the parent + every dashboard with
  //     the same parent_dashboard_id
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
  }, [dashboard, allDashboards]);

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
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger
              opened={mobileOpened}
              onClick={toggleMobile}
              hiddenFrom="sm"
              size="sm"
            />
            <Burger
              opened={desktopOpened}
              onClick={toggleDesktop}
              visibleFrom="sm"
              size="sm"
              aria-label="Toggle tab sidebar"
            />
            <Text fw={700} style={{ fontFamily: 'Virgil, sans-serif' }}>
              Depictio
            </Text>
            <Text c="dimmed" size="sm">/</Text>
            <Text size="sm">{dashboard?.title || dashboardId || 'Dashboard'}</Text>
            <Text c="dimmed" size="xs" ml="xs">(beta viewer)</Text>
            {cardsLoading && <Loader size="xs" ml="xs" />}
          </Group>
          {dashboardId && (
            <Anchor href={`/dashboard/${dashboardId}`} size="sm">
              ← Back to classic viewer
            </Anchor>
          )}
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <ScrollArea style={{ flex: 1 }}>
          <Stack gap={2}>
            <Text c="dimmed" size="xs" tt="uppercase" fw={700} mb={4}>
              Tabs
            </Text>
            {tabSiblings.length === 0 && (
              <Text size="xs" c="dimmed">No sibling tabs.</Text>
            )}
            {tabSiblings.map((d) => {
              const isCurrent = d.dashboard_id === dashboardId;
              const isParent = !d.parent_dashboard_id;
              return (
                <NavLink
                  key={d.dashboard_id}
                  active={isCurrent}
                  label={d.title || d.dashboard_id}
                  leftSection={
                    <Icon
                      icon={isParent ? 'mdi:view-dashboard' : 'mdi:tab'}
                      width={16}
                    />
                  }
                  href={`/dashboard-beta/${d.dashboard_id}`}
                  variant={isCurrent ? 'filled' : 'light'}
                  pl={isParent ? 8 : 24}
                />
              );
            })}
          </Stack>
        </ScrollArea>
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
                      onClick={() => setFilters([])}
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
