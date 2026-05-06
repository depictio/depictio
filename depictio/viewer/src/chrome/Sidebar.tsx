import React, { useState } from 'react';
import {
  ActionIcon,
  Anchor,
  Box,
  Divider,
  Group,
  Menu,
  ScrollArea,
  Stack,
  Tabs,
  Text,
  useMantineColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardSummary } from 'depictio-react-core';
import ThemeToggle from './ThemeToggle';
import ServerStatusBadge from './ServerStatusBadge';
import ProfileBadge from './ProfileBadge';
import AuthModeBadge from './AuthModeBadge';
import './chrome.css';

/** True for path-like icon values (PNG/SVG file URLs) — these came from the
 * Dash YAML and aren't valid Iconify names. */
function isImagePath(s: string | null | undefined): boolean {
  if (!s) return false;
  return /^(\/|https?:\/\/|data:)/.test(s) || /\.(png|svg|jpe?g|webp)$/i.test(s);
}

/** True when the tab metadata points at a MultiQC logo (legacy PNG or any of
 *  the new SVG variants). */
function isMultiqcIcon(path: string | null | undefined): boolean {
  if (!path) return false;
  return /\/assets\/images\/logos\/multiqc(\.png|_icon_(dark|white|color)\.svg)$/i.test(path);
}

/** Many legacy YAML/seed entries point at the old MultiQC PNG
 * (`/assets/images/logos/multiqc.png`). Swap those to the new official icon
 * (https://github.com/MultiQC/logo) served via the SPA's `/dashboard-beta/logos/`
 * mount.
 *
 *   - Active tab → always white SVG (sits on a filled gray background, white
 *     gives the right contrast in both light & dark modes).
 *   - Otherwise → dark SVG on light theme, white SVG on dark theme.
 */
function rewriteLegacyMultiqcIcon(
  path: string,
  theme: 'light' | 'dark',
  isActive = false,
): string {
  if (!isMultiqcIcon(path)) return path;
  if (isActive) return '/dashboard-beta/logos/multiqc_icon_white.svg';
  return theme === 'dark'
    ? '/dashboard-beta/logos/multiqc_icon_white.svg'
    : '/dashboard-beta/logos/multiqc_icon_dark.svg';
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
  // MultiQC tabs always render in a neutral grey/black scheme — the YAML
  // currently stamps `orange` on the parent MultiQC tab, but the official
  // logo is monochrome so a coloured fill clashes with the icon. Force
  // `dark` so light mode gets a near-black active fill and dark mode gets
  // the same near-black fill (Mantine `dark.6` ≈ `#25262b`).
  if (isMultiqcIcon(tab.tab_icon) || isMultiqcIcon(tab.icon)) return 'dark';
  return tab.tab_icon_color || tab.icon_color || (isParent ? 'orange' : 'blue');
}

/** Reserved sentinel value — clicking the trailing pill triggers `onAddTab`
 *  rather than navigating. Mirrors Dash's `__add_tab__` (`tab_callbacks.py:148-161`). */
const ADD_TAB_VALUE = '__add_tab__';

export type TabMoveDirection = 'up' | 'down';

interface SidebarProps {
  tabs: DashboardSummary[];
  activeId: string | null;
  /** When 'edit', renders per-tab "..." menu + trailing "+ Add tab" pill.
   *  Defaults to 'view' (read-only). */
  mode?: 'view' | 'edit';
  /** Edit-mode handlers — required when mode === 'edit'. */
  onEditTab?: (tab: DashboardSummary) => void;
  onDeleteTab?: (tab: DashboardSummary) => void;
  onMoveTab?: (tab: DashboardSummary, direction: TabMoveDirection) => void;
  onAddTab?: () => void;
}

/**
 * Replaces the contents of `<AppShell.Navbar>`. Vertical layout, three rows:
 *   1. Top: back-to-dashboards link (PoweredBy lives in the header, not here)
 *   2. Middle (scrollable): vertical pill tabs (parent + children, optional "+" pill)
 *   3. Bottom: theme toggle / server status / profile
 *
 * Visual parity with `depictio/dash/layouts/sidebar.py:create_static_navbar_content`.
 */
const Sidebar: React.FC<SidebarProps> = ({
  tabs,
  activeId,
  mode = 'view',
  onEditTab,
  onDeleteTab,
  onMoveTab,
  onAddTab,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';
  const isEdit = mode === 'edit';

  // Lift the per-tab menu open-state up here so only ONE "..." menu can be
  // open at a time. Each child Menu was previously self-contained, so opening
  // tab B's menu didn't close tab A's (Mantine's outside-click detection
  // doesn't fire when the user clicks another menu's trigger inside the same
  // tab list).
  const [openMenuTabId, setOpenMenuTabId] = useState<string | null>(null);

  // Pre-compute first/last child indices so Move up/down can be disabled
  // appropriately. Main tab (no parent_dashboard_id) is always at the top
  // and never moves, so it doesn't count toward "first child".
  const childTabs = tabs.filter((t) => t.parent_dashboard_id);
  const firstChildId = childTabs[0]?.dashboard_id ?? null;
  const lastChildId = childTabs[childTabs.length - 1]?.dashboard_id ?? null;

  const handleTabChange = (value: string | null) => {
    if (!value) return;
    if (value === ADD_TAB_VALUE) {
      onAddTab?.();
      return;
    }
    if (value === activeId) return;
    // Preserve the current mode (view ↔ edit) when switching tabs so users
    // don't bounce back to read-only every time they change tab in the editor.
    const isEditPath = window.location.pathname.startsWith('/dashboard-beta-edit/');
    const target = isEditPath
      ? `/dashboard-beta-edit/${value}`
      : `/dashboard-beta/${value}`;
    window.location.assign(target);
  };

  return (
    <Stack gap="sm" h="100%" justify="space-between">
      {/* Top region — centered, grey back link to match Dash sidebar */}
      <Stack gap="sm" align="stretch">
        <Anchor
          href="/dashboards-beta"
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
                // `width: '100%'` makes the vertical list fill the navbar
                // column. Mantine's vertical Tabs root is `flex-direction:
                // row` (list + panel side-by-side), so without an explicit
                // width the list shrinks to content and ~25px of sidebar
                // chrome goes unused on the right.
                list: { gap: 4, border: 'none', width: '100%' },
                tab: { justifyContent: 'flex-start', width: '100%' },
                // `flex: 1` on the label is what pushes a `rightSection`
                // (the per-tab "..." menu in edit mode) to the far-right
                // edge of the pill. Without this the right section sits
                // next to the label, not flush against the pill border.
                tabLabel: { flex: 1, minWidth: 0 },
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
                  const yamlImageRaw =
                    d.tab_icon && isImagePath(d.tab_icon) ? d.tab_icon : null;
                  const yamlImage = yamlImageRaw
                    ? rewriteLegacyMultiqcIcon(yamlImageRaw, theme, isActive)
                    : null;
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
                        src={
                          yamlImage.startsWith('/dashboard-beta/')
                            ? yamlImage
                            : resolveAssetUrl(yamlImage)
                        }
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

                  // In edit mode, the "..." menu lives in Mantine's
                  // `rightSection` slot — that's the only way to get it
                  // truly right-aligned, since the default `tabLabel` span
                  // is auto-width and a flex Group inside it only takes
                  // content width.
                  const rightSection = isEdit ? (
                    <TabMenu
                      tab={d}
                      isParent={isParent}
                      isFirstChild={d.dashboard_id === firstChildId}
                      isLastChild={d.dashboard_id === lastChildId}
                      opened={openMenuTabId === d.dashboard_id}
                      onOpen={() => setOpenMenuTabId(d.dashboard_id)}
                      onClose={() =>
                        setOpenMenuTabId((cur) =>
                          cur === d.dashboard_id ? null : cur,
                        )
                      }
                      onEditTab={onEditTab}
                      onDeleteTab={onDeleteTab}
                      onMoveTab={onMoveTab}
                    />
                  ) : undefined;

                  return (
                    <Tabs.Tab
                      key={d.dashboard_id}
                      value={d.dashboard_id}
                      color={iconColor}
                      leftSection={leftSection}
                      rightSection={rightSection}
                      pl="xs"
                      pr={isEdit ? 4 : undefined}
                    >
                      <span className="depictio-chrome-tab-label">{label}</span>
                    </Tabs.Tab>
                  );
                })}

                {/* Trailing "+ Add tab" pill — visible only in edit mode.
                    Mirrors Dash `_create_add_tab_button` (`tab_callbacks.py:148-161`).
                    Click intercepts via ADD_TAB_VALUE in `handleTabChange`. */}
                {isEdit && onAddTab && (
                  <Tabs.Tab
                    key={ADD_TAB_VALUE}
                    value={ADD_TAB_VALUE}
                    leftSection={
                      <Icon
                        icon="mdi:plus"
                        width={18}
                        height={18}
                        style={{ flexShrink: 0 }}
                      />
                    }
                    pl="xs"
                  >
                    <span className="depictio-chrome-tab-label">Add tab</span>
                  </Tabs.Tab>
                )}
              </Tabs.List>
            </Tabs>
          )}
        </Stack>
      </ScrollArea>

      {/* Bottom region — centered stack, original Dash order: theme,
        server, profile. AuthModeBadge sits above the avatar to surface the
        active server mode (Demo / Public / Single User), matching
        `depictio/dash/layouts/sidebar.py:create_sidebar_footer`. */}
      <Stack gap="xs" align="center">
        <Divider w="100%" />
        <ThemeToggle />
        <ServerStatusBadge />
        <AuthModeBadge />
        <ProfileBadge />
      </Stack>
    </Stack>
  );
};

interface TabMenuProps {
  tab: DashboardSummary;
  isParent: boolean;
  isFirstChild: boolean;
  isLastChild: boolean;
  /** Controlled open state — ensures only one tab menu is open at a time. */
  opened: boolean;
  onOpen: () => void;
  onClose: () => void;
  onEditTab?: (tab: DashboardSummary) => void;
  onDeleteTab?: (tab: DashboardSummary) => void;
  onMoveTab?: (tab: DashboardSummary, direction: TabMoveDirection) => void;
}

/**
 * Per-tab edit menu rendered inline with the tab label in edit mode.
 *
 * Mirrors `depictio/viewer/src/components/GridItemEditOverlay.tsx` — same
 * ActionIcon (dots-vertical) + Menu.Dropdown with Edit / Move up / Move down
 * / Delete. Move/Delete are hidden for the parent (main) tab since the
 * backend rejects those operations on main tabs.
 *
 * Open state is controlled by the parent so only one menu can be open at a
 * time across the full tab list — Mantine's per-Menu outside-click detection
 * doesn't fire when the user clicks another tab's "..." trigger directly.
 *
 * Click handlers stop propagation to prevent the surrounding Tabs.Tab from
 * navigating when the user opens the menu.
 */
const TabMenu: React.FC<TabMenuProps> = ({
  tab,
  isParent,
  isFirstChild,
  isLastChild,
  opened,
  onOpen,
  onClose,
  onEditTab,
  onDeleteTab,
  onMoveTab,
}) => {
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();

  return (
    <Box
      // The Tabs.Tab parent treats any click as a navigation request — wrap
      // the trigger in a stopPropagation guard so opening the menu doesn't
      // also switch tab.
      onClick={stop}
      onMouseDown={stop}
      style={{ display: 'inline-flex', alignItems: 'center' }}
    >
      <Menu
        position="bottom-end"
        withinPortal
        shadow="md"
        width={170}
        opened={opened}
        onChange={(o) => (o ? onOpen() : onClose())}
        closeOnItemClick
      >
        <Menu.Target>
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            aria-label="Tab actions"
          >
            <Icon icon="tabler:dots-vertical" width={16} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item
            leftSection={<Icon icon="tabler:edit" width={14} />}
            onClick={() => onEditTab?.(tab)}
          >
            Edit
          </Menu.Item>
          {!isParent && (
            <>
              <Menu.Item
                leftSection={<Icon icon="tabler:arrow-up" width={14} />}
                disabled={isFirstChild}
                onClick={() => onMoveTab?.(tab, 'up')}
              >
                Move up
              </Menu.Item>
              <Menu.Item
                leftSection={<Icon icon="tabler:arrow-down" width={14} />}
                disabled={isLastChild}
                onClick={() => onMoveTab?.(tab, 'down')}
              >
                Move down
              </Menu.Item>
              <Menu.Divider />
              <Menu.Item
                color="red"
                leftSection={<Icon icon="tabler:trash" width={14} />}
                onClick={() => onDeleteTab?.(tab)}
              >
                Delete
              </Menu.Item>
            </>
          )}
        </Menu.Dropdown>
      </Menu>
    </Box>
  );
};

export default Sidebar;
