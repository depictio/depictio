import React from 'react';
import {
  Anchor,
  Divider,
  Group,
  ScrollArea,
  Stack,
  Tabs,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardSummary } from 'depictio-react-core';
import PoweredBy from './PoweredBy';
import ThemeToggle from './ThemeToggle';
import ServerStatusBadge from './ServerStatusBadge';
import ProfileBadge from './ProfileBadge';
import './chrome.css';

interface SidebarProps {
  tabs: DashboardSummary[];
  activeId: string | null;
}

/** Dash precedence: `tab.tab_icon || tab.icon`, `tab.tab_icon_color || tab.icon_color`. */
function resolveTabIcon(tab: DashboardSummary, isParent: boolean): string {
  return tab.tab_icon || tab.icon || (isParent ? 'mdi:view-dashboard' : 'mdi:tab');
}
function resolveTabColor(tab: DashboardSummary, isParent: boolean): string {
  return tab.tab_icon_color || tab.icon_color || (isParent ? 'orange' : 'gray');
}

/**
 * Replaces the contents of `<AppShell.Navbar>`. Vertical layout, three rows:
 *   1. Top: PoweredBy + back-to-dashboards link
 *   2. Middle (scrollable): vertical pill tabs (parent + children)
 *   3. Bottom: theme toggle / server status / profile
 *
 * Visual parity with `depictio/dash/layouts/sidebar.py:create_static_navbar_content`.
 */
const Sidebar: React.FC<SidebarProps> = ({ tabs, activeId }) => {
  const handleTabChange = (value: string | null) => {
    if (!value || value === activeId) return;
    window.location.assign(`/dashboard-beta/${value}`);
  };

  return (
    <Stack gap="sm" h="100%" justify="space-between">
      {/* Top region */}
      <Stack gap="sm">
        <Group justify="center">
          <PoweredBy />
        </Group>
        <Anchor
          href="/dashboards"
          size="xs"
          c="dimmed"
          underline="hover"
          className="depictio-chrome-link"
        >
          ← Back to Dashboards
        </Anchor>
        <Divider />
      </Stack>

      {/* Middle region — scrollable tab list */}
      <ScrollArea style={{ flex: 1 }} type="auto">
        <Stack gap={4}>
          <Text c="dimmed" size="xs" tt="uppercase" fw={700} mb={4}>
            Tabs
          </Text>
          {tabs.length === 0 && (
            <Text size="xs" c="dimmed">
              No sibling tabs.
            </Text>
          )}
          {tabs.length > 0 && (
            <Tabs
              orientation="vertical"
              variant="pills"
              placement="left"
              value={activeId}
              onChange={handleTabChange}
              styles={{
                list: { gap: 4, border: 'none' },
                tab: { justifyContent: 'flex-start', width: '100%' },
              }}
            >
              <Tabs.List>
                {tabs.map((d) => {
                  const isParent = !d.parent_dashboard_id;
                  const iconName = resolveTabIcon(d, isParent);
                  const iconColor = resolveTabColor(d, isParent);
                  return (
                    <Tabs.Tab
                      key={d.dashboard_id}
                      value={d.dashboard_id}
                      color={iconColor}
                      leftSection={
                        <Icon
                          icon={iconName}
                          width={18}
                          style={{
                            color: `var(--mantine-color-${iconColor}-6)`,
                          }}
                        />
                      }
                      pl={isParent ? 'xs' : 'lg'}
                    >
                      <span className="depictio-chrome-tab-label">
                        {d.title || d.dashboard_id}
                      </span>
                    </Tabs.Tab>
                  );
                })}
              </Tabs.List>
            </Tabs>
          )}
        </Stack>
      </ScrollArea>

      {/* Bottom region — theme toggle, status, profile */}
      <Stack gap="xs" align="center">
        <Divider w="100%" />
        <ThemeToggle />
        <ServerStatusBadge />
        <ProfileBadge />
      </Stack>
    </Stack>
  );
};

export default Sidebar;
