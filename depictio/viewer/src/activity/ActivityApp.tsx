import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  AppShell,
  Button,
  Card,
  Center,
  Container,
  Group,
  Loader,
  SegmentedControl,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import {
  EMPTY_INGESTION_FILTERS,
  adminUrl,
  parseAdminUrl,
  type IngestionFilters,
} from 'depictio-react-core';

import { AppSidebar } from '../chrome';
import { GlassPage, useGlassPages } from '../chrome/variants/glass/pages';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { useMigrationUi } from '../hooks/useMigrationUi';
import { usePageTitle } from '../branding';
import { IngestionPane } from '../monitoring/IngestionPane';
import { TasksPane } from '../monitoring/TasksPane';
import { createLiveFeed } from '../monitoring/usePolling';
import type { MonitoringLiveEvent } from 'depictio-react-core';
import { SendsPane } from './SendsPane';

const PAGE_TITLE = 'Activity';
const PAGE_DESCRIPTION = 'Tasks, ingestion runs and sends for the projects you can access';

const PANES = ['tasks', 'ingestion', 'sends'] as const;
type ActivityPane = (typeof PANES)[number];

interface ActivityRoute {
  pane: ActivityPane;
  ingestion: IngestionFilters;
}

/** The view the address bar describes: `/activity/<pane>`, with the Ingestion
 *  filters (`?status=`, `instance`, `project`, `q`) in the query string. The
 *  filters use the admin page's codec, so a link copied from either page
 *  means the same thing on both. */
function readRoute(): ActivityRoute {
  const segment = /^\/activity(?:\/([^/]+))?/.exec(window.location.pathname)?.[1];
  const pane = (PANES as readonly (string | undefined)[]).includes(segment)
    ? (segment as ActivityPane)
    : 'tasks';
  const ingestion =
    pane === 'ingestion'
      ? parseAdminUrl('/admin/ingestion', window.location.search).ingestion
      : { ...EMPTY_INGESTION_FILTERS };
  return { pane, ingestion };
}

function routeUrl({ pane, ingestion }: ActivityRoute): string {
  const path = `/activity/${pane}`;
  if (pane !== 'ingestion') return path;
  const query = adminUrl({ tab: 'monitoring', pane: 'ingestion', ingestion }).split('?')[1];
  return query ? `${path}?${query}` : path;
}

/** A pane switch is a navigation (`push`, so Back returns to it); a filter
 *  change is not (`replace`, so typing in the search box doesn't bury the
 *  previous page). */
function writeRoute(route: ActivityRoute, mode: 'push' | 'replace'): void {
  const next = routeUrl(route);
  if (next === `${window.location.pathname}${window.location.search}`) return;
  const url = `${next}${window.location.hash}`;
  if (mode === 'push') window.history.pushState(window.history.state, '', url);
  else window.history.replaceState(window.history.state, '', url);
}

/**
 * The Activity page: what the instance has been doing for the projects the
 * reader can access, read-only. The same Tasks and Ingestion panes as
 * Administration > Log & Task; the API scopes what they list to the reader's
 * projects (plus their own runs) and redacts the detail for plain viewers of a
 * project. Logs, worker health, the log-level control and the watcher controls
 * stay with the admin.
 *
 * Not offered on public or demo instances, nor to their temporary guests.
 */
const ActivityApp: React.FC = () => {
  const { user, loading, isPublicMode, isDemoMode, isSingleUserMode } = useCurrentUser();
  const migrationUi = useMigrationUi();
  const [route, setRoute] = useState<ActivityRoute>(readRoute);
  const [ingestionFeed] = useState(() => createLiveFeed<MonitoringLiveEvent>());
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);

  usePageTitle(PAGE_TITLE);
  const glass = useGlassPages();

  // Same rule as the API: a real user of an instance with accounts (a personal
  // single-user instance always qualifies).
  const allowed =
    Boolean(user) &&
    !user?.is_temporary &&
    (isSingleUserMode || (!isPublicMode && !isDemoMode));
  // The Sends pane exists only while the instance offers migration.
  const panes = PANES.filter((p) => p !== 'sends' || migrationUi);
  const pane: ActivityPane = panes.includes(route.pane) ? route.pane : 'tasks';

  // Canonicalise the arrival URL (a bare `/activity` gains `/tasks`) and follow
  // Back/Forward.
  useEffect(() => {
    writeRoute(readRoute(), 'replace');
    const onPopState = () => setRoute(readRoute());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const navigate = useCallback((next: ActivityRoute, mode: 'push' | 'replace') => {
    setRoute(next);
    writeRoute(next, mode);
  }, []);

  const body = (() => {
    if (loading) {
      return (
        <Center mih={300}>
          <Loader />
        </Center>
      );
    }
    if (!allowed) {
      return (
        <Center mih={300}>
          <Stack align="center" gap="md" maw={420} ta="center">
            <Icon icon="mdi:pulse" width={56} />
            <Title order={3}>Activity is not available</Title>
            <Text c="dimmed">
              Activity is shown to signed-in users of instances with accounts. It is not offered on
              public or demo instances.
            </Text>
            <Button component="a" href="/dashboards" variant="light">
              Back to dashboards
            </Button>
          </Stack>
        </Center>
      );
    }
    return (
      <Stack gap="md">
        <SegmentedControl
          size="xs"
          w="fit-content"
          value={pane}
          onChange={(v) => navigate({ ...route, pane: v as ActivityPane }, 'push')}
          data={[
            { value: 'tasks', label: 'Tasks' },
            { value: 'ingestion', label: 'Ingestion' },
            ...(migrationUi ? [{ value: 'sends', label: 'Sends' }] : []),
          ]}
          data-testid="activity-panes"
        />
        <Card withBorder radius="md" p="md" data-testid={`activity-pane-${pane}`}>
          {pane === 'tasks' && <TasksPane />}
          {pane === 'ingestion' && (
            <IngestionPane
              feed={ingestionFeed}
              filters={route.ingestion}
              onFiltersChange={(ingestion) => navigate({ ...route, ingestion }, 'replace')}
            />
          )}
          {pane === 'sends' && <SendsPane />}
        </Card>
      </Stack>
    );
  })();

  if (glass) {
    return (
      <GlassPage section="activity" title={PAGE_TITLE} description={PAGE_DESCRIPTION}>
        {body}
      </GlassPage>
    );
  }

  return (
    <AppShell
      data-testid="app-shell"
      layout="alt"
      header={{ height: 64 }}
      navbar={{
        width: 260,
        breakpoint: 'sm',
        collapsed: { mobile: !mobileOpened, desktop: !desktopOpened },
      }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleMobile}
              hiddenFrom="sm"
              aria-label="Toggle navigation (mobile)"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="gray"
              size="md"
              onClick={toggleDesktop}
              visibleFrom="sm"
              aria-label="Toggle navigation"
            >
              <Icon icon="mdi:menu" width={22} />
            </ActionIcon>
            <Icon icon="mdi:pulse" width={26} />
            <Stack gap={0}>
              <Title order={3}>{PAGE_TITLE}</Title>
              <Text size="xs" c="dimmed" visibleFrom="sm">
                {PAGE_DESCRIPTION}
              </Text>
            </Stack>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="activity" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Container size="lg" p="xl" fluid>
          {body}
        </Container>
      </AppShell.Main>
    </AppShell>
  );
};

export default ActivityApp;
