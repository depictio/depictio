import React from 'react';
import {
  Anchor,
  Divider,
  ScrollArea,
  Stack,
  Tabs,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardSummary } from 'depictio-react-core';
import ThemeToggle from './ThemeToggle';
import ServerStatusBadge from './ServerStatusBadge';
import ProfileBadge from './ProfileBadge';
import './chrome.css';

interface SidebarProps {
  tabs: DashboardSummary[];
  activeId: string | null;
}

/** True for path-like icon values (PNG/SVG file URLs) — these came from the
 * Dash YAML and aren't valid Iconify names. */
function isImagePath(s: string | null | undefined): boolean {
  if (!s) return false;
  return /^(\/|https?:\/\/|data:)/.test(s) || /\.(png|svg|jpe?g|webp)$/i.test(s);
}

/** Resolve a YAML asset path (e.g. `/assets/images/logos/multiqc.png`) to a
 * loadable URL. The Dash app serves /assets/ on port 5122; the SPA on 8122
 * doesn't proxy them, so we point cross-port in dev. Mirrors `dashOrigin()`
 * used elsewhere. */
function resolveAssetUrl(s: string): string {
  if (/^(https?:\/\/|data:)/.test(s)) return s;
  if (s.startsWith('/')) {
    const env = (import.meta as unknown as { env?: Record<string, string> }).env;
    if (env?.VITE_DASH_ORIGIN) return env.VITE_DASH_ORIGIN.replace(/\/$/, '') + s;
    if (
      typeof window !== 'undefined' &&
      window.location.hostname &&
      window.location.port === '8122'
    ) {
      return `${window.location.protocol}//${window.location.hostname}:5122${s}`;
    }
    return s;
  }
  return s;
}

/** Dash precedence: `tab.tab_icon || tab.icon`, `tab.tab_icon_color || tab.icon_color`.
 *  When the value is a path/URL (legacy YAML), fall through to a keyword-based
 *  Iconify default since the SPA doesn't proxy Dash's `/assets/` mount. */
function resolveTabIcon(tab: DashboardSummary, isParent: boolean): string {
  if (tab.tab_icon && !isImagePath(tab.tab_icon)) return tab.tab_icon;
  if (tab.icon && !isImagePath(tab.icon)) return tab.icon;
  const t = ((tab.main_tab_name || tab.title) || '').toLowerCase();
  if (t.includes('multiqc')) return 'mdi:chart-bar-stacked';
  if (t.includes('variant')) return 'mdi:dna';
  if (t.includes('coverage')) return 'mdi:chart-areaspline';
  if (t.includes('quality') || t.includes('qc')) return 'mdi:check-decagram';
  if (t.includes('overview') || t.includes('summary')) return 'mdi:view-dashboard-outline';
  if (t.includes('community') || t.includes('taxa') || t.includes('species'))
    return 'mdi:bacteria-outline';
  return isParent ? 'mdi:view-dashboard' : 'mdi:tab';
}
function resolveTabColor(tab: DashboardSummary, isParent: boolean): string {
  return tab.tab_icon_color || tab.icon_color || (isParent ? 'orange' : 'blue');
}

/**
 * Replaces the contents of `<AppShell.Navbar>`. Vertical layout, three rows:
 *   1. Top: back-to-dashboards link (PoweredBy lives in the header, not here)
 *   2. Middle (scrollable): vertical pill tabs (parent + children)
 *   3. Bottom: theme toggle / server status / profile
 *
 * Visual parity with `depictio/dash/layouts/sidebar.py:create_static_navbar_content`.
 */
const Sidebar: React.FC<SidebarProps> = ({ tabs, activeId }) => {
  const handleTabChange = (value: string | null) => {
    if (!value || value === activeId) return;
    // Preserve the current mode (view ↔ edit) when switching tabs so users
    // don't bounce back to read-only every time they change tab in the editor.
    const isEdit = window.location.pathname.startsWith('/dashboard-beta-edit/');
    const target = isEdit
      ? `/dashboard-beta-edit/${value}`
      : `/dashboard-beta/${value}`;
    window.location.assign(target);
  };

  return (
    <Stack gap="sm" h="100%" justify="space-between">
      {/* Top region — centered, grey back link to match Dash sidebar */}
      <Stack gap="sm" align="stretch">
        <Anchor
          href="/dashboards"
          size="sm"
          fw={500}
          underline="hover"
          ta="center"
          c="dimmed"
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
                  const iconColor = resolveTabColor(d, isParent);
                  const isActive = d.dashboard_id === activeId;
                  const label = isParent
                    ? d.main_tab_name || d.title || d.dashboard_id
                    : d.title || d.dashboard_id;
                  // Use a YAML-supplied image ONLY when it's explicitly set on
                  // tab_icon. Don't fall back to `icon` for child tabs because
                  // children inherit the dashboard `icon` (a generic favicon),
                  // which would override their per-tab Iconify defaults and
                  // strip their distinct color.
                  const yamlImage =
                    d.tab_icon && isImagePath(d.tab_icon) ? d.tab_icon : null;
                  const iconName = resolveTabIcon(d, isParent);
                  const leftSection = yamlImage ? (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: 18,
                        height: 18,
                        flexShrink: 0,
                      }}
                    >
                      <img
                        src={resolveAssetUrl(yamlImage)}
                        alt=""
                        style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                      />
                    </span>
                  ) : (
                    <Icon
                      icon={iconName}
                      width={18}
                      height={18}
                      style={{
                        color: isActive
                          ? 'var(--mantine-color-white)'
                          : `var(--mantine-color-${iconColor}-6)`,
                        flexShrink: 0,
                      }}
                    />
                  );
                  return (
                    <Tabs.Tab
                      key={d.dashboard_id}
                      value={d.dashboard_id}
                      color={iconColor}
                      leftSection={leftSection}
                      pl="xs"
                    >
                      <span className="depictio-chrome-tab-label">
                        {label}
                      </span>
                    </Tabs.Tab>
                  );
                })}
              </Tabs.List>
            </Tabs>
          )}
        </Stack>
      </ScrollArea>

      {/* Bottom region — centered stack, original Dash order: theme,
        server, profile. */}
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
