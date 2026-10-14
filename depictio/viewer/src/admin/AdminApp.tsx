import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  AppShell,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Tabs,
  Text,
  Title,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import { ADMIN_TABS, MONITORING_PANES, adminUrl, parseAdminUrl } from 'depictio-react-core';
import type { AdminRoute, AdminTab, MonitoringPane } from 'depictio-react-core';
import {
  ArchiveRestore,
  Database,
  Eye,
  HeartPulse,
  ListChecks,
  Palette,
  ScrollText,
  Settings,
  Users,
  UsersRound,
  Wrench,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { GlassPage, STROKE, useGlassPages } from '../chrome/variants/glass/pages';
import { SECTION_ICON } from '../chrome/variants/glass/pages/GlassPage';
import '../chrome/variants/glass/pages/admin.css';

import { AppSidebar } from '../chrome';
import { useCurrentUser } from '../hooks/useCurrentUser';
import AdminUsersPanel from './AdminUsersPanel';
import AdminGroupsPanel from './AdminGroupsPanel';
import AdminProjectsPanel from './AdminProjectsPanel';
import AdminDashboardsPanel from './AdminDashboardsPanel';
import AdminBrandingPanel from './AdminBrandingPanel';
import AdminBackupsPanel from './AdminBackupsPanel';
import AdminMaintenancePanel from './AdminMaintenancePanel';
import AdminMonitoringPanel from './AdminMonitoringPanel';
import AdminSettingsPanel from './AdminSettingsPanel';
import { canSeeBackups, canSeeMonitoring } from './access';
import { usePageTitle } from '../branding';

/** A page of the Glass admin: a plain tab, or one of the Log & Task panes
 *  (which the address bar names directly, `/admin/tasks`). */
type AdminView = Exclude<AdminTab, 'monitoring'> | MonitoringPane;

interface AdminNavItem {
  view: AdminView;
  label: string;
  icon: LucideIcon;
  /** Projects and Dashboards wear their section's colour, as in the sidebar. */
  hue?: 'projects' | 'dashboards';
  /** Hidden in public / demo mode, like the monitoring panes they open. */
  trusted?: boolean;
}

interface AdminNavGroup {
  label: string;
  items: AdminNavItem[];
}

/** Who has access, what they made, what the instance has been doing, and how
 *  it is set up: the four questions an admin comes with. */
const NAV_GROUPS: AdminNavGroup[] = [
  {
    label: 'People',
    items: [
      { view: 'users', label: 'Users', icon: Users },
      { view: 'groups', label: 'Groups', icon: UsersRound },
    ],
  },
  {
    label: 'Content',
    items: [
      { view: 'projects', label: 'Projects', icon: SECTION_ICON.projects, hue: 'projects' },
      { view: 'dashboards', label: 'Dashboards', icon: SECTION_ICON.dashboards, hue: 'dashboards' },
    ],
  },
  {
    label: 'Activity',
    items: [
      { view: 'tasks', label: 'Tasks', icon: ListChecks, trusted: true },
      { view: 'ingestion', label: 'Ingestion', icon: Database, trusted: true },
      { view: 'watchers', label: 'Watchers', icon: Eye, trusted: true },
      { view: 'logs', label: 'Logs', icon: ScrollText, trusted: true },
      { view: 'health', label: 'Health', icon: HeartPulse, trusted: true },
    ],
  },
  {
    label: 'Instance',
    items: [
      { view: 'branding', label: 'Branding', icon: Palette },
      { view: 'backups', label: 'Backups', icon: ArchiveRestore, trusted: true },
      { view: 'maintenance', label: 'Maintenance', icon: Wrench },
      { view: 'settings', label: 'Settings', icon: Settings },
    ],
  },
];

const isPane = (view: string): view is MonitoringPane =>
  (MONITORING_PANES as readonly string[]).includes(view);

/** Remember the last tab, so a bare `/admin` reopens where the admin left off.
 *  A tab or pane named in the URL always wins. */
const TAB_KEY = 'admin-active-tab';

function readStoredTab(): AdminTab {
  try {
    const raw = localStorage.getItem(TAB_KEY);
    if ((ADMIN_TABS as readonly (string | null)[]).includes(raw)) return raw as AdminTab;
  } catch {
    /* ignore */
  }
  return 'users';
}

/** The view the address bar describes: `/admin/<tab>`, or `/admin/<pane>` for
 *  a Log & Task pane, with the Ingestion filters in the query string (codec:
 *  `adminUrlState` in depictio-react-core). */
function readAdminRoute(): AdminRoute {
  const parsed = parseAdminUrl(window.location.pathname, window.location.search);
  return { ...parsed, tab: parsed.tab ?? readStoredTab() };
}

/** Point the address bar at `route`, keeping the hash. Switching tab or pane
 *  is a navigation (`push`, so Back returns to it); a filter change is not
 *  (`replace`, so typing in the search box doesn't bury the previous page). */
function writeAdminUrl(route: AdminRoute, mode: 'push' | 'replace'): void {
  const next = adminUrl(route);
  if (next === `${window.location.pathname}${window.location.search}`) return;
  const url = `${next}${window.location.hash}`;
  if (mode === 'push') window.history.pushState(window.history.state, '', url);
  else window.history.replaceState(window.history.state, '', url);
}

const AdminApp: React.FC = () => {
  const { user, loading, isPublicMode, isDemoMode, isSingleUserMode } = useCurrentUser();
  // Monitoring is for single- & multi-user (trusted) deployments, and for a
  // signed-in admin of a public one. Single-user always wins — it's a personal
  // admin instance even if public_mode is also set; demo instances and guests
  // never see it.
  const modes = { user, isPublicMode, isDemoMode, isSingleUserMode };
  const showMonitoring = canSeeMonitoring(modes);
  // Full-DB backup/restore is a trusted-deployment tool only.
  const showBackups = canSeeBackups(modes);
  const [mobileOpened, { toggle: toggleMobile }] = useDisclosure(false);
  const [desktopOpened, { toggle: toggleDesktop }] = useDisclosure(true);
  const [route, setRoute] = useState<AdminRoute>(readAdminRoute);
  // A tab that isn't rendered here; a URL naming it falls back to Users
  // instead of an empty panel.
  const activeTab: AdminTab =
    (!showMonitoring && route.tab === 'monitoring') || (!showBackups && route.tab === 'backups')
      ? 'users'
      : route.tab;

  usePageTitle('Administration');
  const glass = useGlassPages();

  // Canonicalise the arrival URL (a bare `/admin` gains the remembered tab,
  // `/admin/monitoring` becomes `/admin/tasks`) and follow Back/Forward.
  useEffect(() => {
    writeAdminUrl(readAdminRoute(), 'replace');
    const onPopState = () => setRoute(readAdminRoute());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(TAB_KEY, route.tab);
    } catch {
      /* ignore */
    }
  }, [route.tab]);

  const navigate = useCallback((next: AdminRoute, mode: 'push' | 'replace') => {
    setRoute(next);
    writeAdminUrl(next, mode);
  }, []);

  const renderBody = () => {
    if (loading) {
      return (
        <Center mih={300}>
          <Loader />
        </Center>
      );
    }
    if (!user || !user.is_admin) {
      return (
        <Center mih={400}>
          <Stack align="center" gap="md" maw={420} ta="center">
            <Icon
              icon="material-symbols:lock-outline"
              width={64}
              color="var(--mantine-color-red-6)"
            />
            <Title order={3}>Forbidden</Title>
            <Text c="dimmed">
              The administration page is only available to system administrators.
            </Text>
            <Button
              component="a"
              href="/dashboards"
              variant="light"
              leftSection={<Icon icon="material-symbols:dashboard" width={16} />}
            >
              Back to dashboards
            </Button>
          </Stack>
        </Center>
      );
    }
    if (glass) {
      const view: AdminView = activeTab === 'monitoring' ? route.pane : activeTab;
      const open = (next: string) =>
        isPane(next)
          ? navigate({ ...route, tab: 'monitoring', pane: next }, 'push')
          : navigate({ ...route, tab: next as AdminTab }, 'push');
      return (
        <Tabs
          value={view}
          onChange={(v) => v && open(v)}
          orientation="vertical"
          variant="unstyled"
          keepMounted={false}
          className="ga-admin"
        >
          <Tabs.List className="ga-nav" aria-label="Administration">
            {NAV_GROUPS.map((group) => {
              const items = group.items.filter((item) =>
                item.view === 'backups' ? showBackups : showMonitoring || !item.trusted,
              );
              if (items.length === 0) return null;
              return (
                <React.Fragment key={group.label}>
                  <div className="ga-nav-group" role="presentation">
                    {group.label}
                  </div>
                  {items.map(({ view: value, label, icon: NavIcon, hue }) => (
                    <Tabs.Tab
                      key={value}
                      value={value}
                      className="ga-tab"
                      data-hue={hue}
                      leftSection={<NavIcon size={17} strokeWidth={STROKE} aria-hidden />}
                      data-testid={
                        value === 'backups' || value === 'settings' ? `admin-tab-${value}` : undefined
                      }
                      // The Log & Task tab of old: the e2e suite and anyone
                      // searching the docs still look for it by that name.
                      aria-label={value === 'tasks' ? 'Log & Task: Tasks' : undefined}
                    >
                      {label}
                    </Tabs.Tab>
                  ))}
                </React.Fragment>
              );
            })}
          </Tabs.List>
          <Tabs.Panel value={view} className="ga-content">
            {view === 'users' && <AdminUsersPanel currentUserEmail={user.email} />}
            {view === 'groups' && <AdminGroupsPanel />}
            {view === 'projects' && <AdminProjectsPanel />}
            {view === 'dashboards' && <AdminDashboardsPanel />}
            {view === 'branding' && <AdminBrandingPanel />}
            {isPane(view) && (
              <AdminMonitoringPanel
                pane={route.pane}
                onPaneChange={(pane) => navigate({ ...route, pane }, 'push')}
                ingestionFilters={route.ingestion}
                onIngestionFiltersChange={(ingestion) =>
                  navigate({ ...route, ingestion }, 'replace')
                }
                showPaneSwitch={false}
              />
            )}
            {view === 'backups' && <AdminBackupsPanel />}
            {view === 'maintenance' && <AdminMaintenancePanel />}
            {view === 'settings' && <AdminSettingsPanel />}
          </Tabs.Panel>
        </Tabs>
      );
    }
    return (
      <Tabs
        value={activeTab}
        onChange={(v) => v && navigate({ ...route, tab: v as AdminTab }, 'push')}
        keepMounted={false}
      >
        <Tabs.List>
          <Tabs.Tab value="users" leftSection={<Icon icon="mdi:account-group" width={16} />}>
            Users
          </Tabs.Tab>
          <Tabs.Tab
            value="groups"
            leftSection={<Icon icon="mdi:account-multiple-outline" width={16} />}
          >
            Groups
          </Tabs.Tab>
          <Tabs.Tab value="projects" leftSection={<Icon icon="mdi:jira" width={16} />}>
            Projects
          </Tabs.Tab>
          <Tabs.Tab
            value="dashboards"
            leftSection={<Icon icon="material-symbols:dashboard" width={16} />}
          >
            Dashboards
          </Tabs.Tab>
          <Tabs.Tab value="branding" leftSection={<Icon icon="mdi:palette-outline" width={16} />}>
            Branding
          </Tabs.Tab>
          {showMonitoring && (
            <Tabs.Tab
              value="monitoring"
              leftSection={<Icon icon="mdi:chart-timeline-variant" width={16} />}
            >
              Log &amp; Task
            </Tabs.Tab>
          )}
          {showBackups && (
            <Tabs.Tab
              value="backups"
              leftSection={<Icon icon="mdi:backup-restore" width={16} />}
              data-testid="admin-tab-backups"
            >
              Backups
            </Tabs.Tab>
          )}
          <Tabs.Tab value="maintenance" leftSection={<Icon icon="mdi:broom" width={16} />}>
            Maintenance
          </Tabs.Tab>
          <Tabs.Tab
            value="settings"
            leftSection={<Icon icon="mdi:cog-outline" width={16} />}
            data-testid="admin-tab-settings"
          >
            Settings
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="users" pt="md">
          <AdminUsersPanel currentUserEmail={user.email} />
        </Tabs.Panel>
        <Tabs.Panel value="groups" pt="md">
          <AdminGroupsPanel />
        </Tabs.Panel>
        <Tabs.Panel value="projects" pt="md">
          <AdminProjectsPanel />
        </Tabs.Panel>
        <Tabs.Panel value="dashboards" pt="md">
          <AdminDashboardsPanel />
        </Tabs.Panel>
        <Tabs.Panel value="branding" pt="md">
          <AdminBrandingPanel />
        </Tabs.Panel>
        {showMonitoring && (
          <Tabs.Panel value="monitoring" pt="md">
            <AdminMonitoringPanel
              pane={route.pane}
              onPaneChange={(pane) => navigate({ ...route, pane }, 'push')}
              ingestionFilters={route.ingestion}
              onIngestionFiltersChange={(ingestion) => navigate({ ...route, ingestion }, 'replace')}
            />
          </Tabs.Panel>
        )}
        {showBackups && (
          <Tabs.Panel value="backups" pt="md">
            <AdminBackupsPanel />
          </Tabs.Panel>
        )}
        <Tabs.Panel value="maintenance" pt="md">
          <AdminMaintenancePanel />
        </Tabs.Panel>
        <Tabs.Panel value="settings" pt="md">
          <AdminSettingsPanel />
        </Tabs.Panel>
      </Tabs>
    );
  };

  const body = (
    <>
      {renderBody()}
    </>
  );

  if (glass) {
    return (
      <GlassPage
        section="admin"
        title="Administration"
        description="Users, content, branding and the health of this instance."
      >
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
            <Icon
              icon="material-symbols:settings"
              width={22}
              color="var(--mantine-color-blue-6)"
            />
            <Title order={3} c="blue">
              Administration
            </Title>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppSidebar active="admin" />
      </AppShell.Navbar>

      <AppShell.Main>
        <Box px="lg" py="md">
          {body}
        </Box>
      </AppShell.Main>
    </AppShell>
  );
};

export default AdminApp;
