import React, { useEffect, useRef, useState } from 'react';
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
  Tooltip,
  useMantineColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  brandAccent,
  groupTabs,
  isImagePath,
  sameTabGroup,
  tabGroupOf,
  isMultiqcIcon,
  themedIconSrc,
  useBranding,
  Z_LAYERS,
} from 'depictio-react-core';
import type { BrandTheme, DashboardSummary } from 'depictio-react-core';
import BrandLogo from './BrandLogo';
import ThemeToggle from './ThemeToggle';
import ServerStatusBadge from './ServerStatusBadge';
import ProfileBadge from './ProfileBadge';
import AuthModeBadge from './AuthModeBadge';
import { dashboardHref, dashboardLinkClickHandler } from '../dashboards/lib/dashboardLinks';
import './chrome.css';

/**
 * A tab's name, truncated to the sidebar's width, with the full name in a
 * tooltip once it no longer fits.
 *
 * The tooltip is conditional on purpose: a pill wide enough to show its whole
 * name has nothing to reveal, and a tooltip on every tab turns an ordinary
 * mouse path across the sidebar into a trail of popups. `scrollWidth >
 * clientWidth` is the only reliable read of "the ellipsis is showing" — it is
 * re-measured on resize because the sidebar is user-resizable.
 */
/** Where the tab list's scroll offset is parked across a tab navigation. One
 *  key for the whole app: there is only ever one tab sidebar on screen. */
const TAB_SCROLL_KEY = 'depictio.sidebar.tabScroll';

const TabLabel: React.FC<{ label: string }> = ({ label }) => {
  const ref = React.useRef<HTMLSpanElement>(null);
  const [truncated, setTruncated] = useState(false);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setTruncated(el.scrollWidth > el.clientWidth);
    measure();
    // ResizeObserver catches both the sidebar being dragged and the label
    // changing width when the edit-mode "..." menu appears beside it.
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [label]);

  return (
    <Tooltip
      label={label}
      disabled={!truncated}
      withArrow
      openDelay={300}
      position="right"
      // Inline, this tooltip renders inside the tab list's ScrollArea
      // viewport, which clips it: the name it exists to reveal was cut off at
      // the sidebar edge and stacked under the neighbouring pills.
      withinPortal
      zIndex={Z_LAYERS.tooltip}
    >
      <span ref={ref} className="depictio-chrome-tab-label">
        {label}
      </span>
    </Tooltip>
  );
};

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

/**
 * The loadable URL of a tab's YAML-supplied image icon, or null when the tab
 * uses an Iconify name. For the parent (main) tab, mirror the Header's
 * `tab_icon || icon` precedence so a dashboard-level favicon (stored on
 * `icon`, the common single-tab case) shows the SAME image in the sidebar pill
 * as in the header — otherwise the two disagree (header shows the favicon,
 * sidebar falls through to a keyword default). Child tabs deliberately do NOT
 * fall back to `icon`: they inherit the dashboard's generic favicon, which
 * would override their per-tab Iconify defaults and strip their distinct color.
 */
export function tabImageSrc(
  tab: DashboardSummary,
  isParent: boolean,
  isDark: boolean,
  onFilled = false,
): string | null {
  // `tab_icon` wins outright: an Iconify `tab_icon` beside an image `icon` (a
  // template's `mdi:compass-outline` over its pipeline favicon) is drawn by
  // `resolveTabIcon`, not replaced by the favicon.
  const raw = tab.tab_icon
    ? isImagePath(tab.tab_icon)
      ? tab.tab_icon
      : null
    : isParent && tab.icon && isImagePath(tab.icon)
      ? tab.icon
      : null;
  if (!raw) return null;
  const themed = themedIconSrc(raw, isDark, onFilled);
  return themed.startsWith('/dashboard/') ? themed : resolveAssetUrl(themed);
}

/** Dash precedence: `tab.tab_icon || tab.icon`, `tab.tab_icon_color || tab.icon_color`.
 *  When the value is a path/URL (legacy YAML), fall through to a keyword-based
 *  Iconify default since the SPA doesn't proxy Dash's `/assets/` mount. */
export function resolveTabIcon(tab: DashboardSummary, isParent: boolean): string {
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
export function resolveTabColor(
  tab: DashboardSummary,
  isParent: boolean,
  brand: BrandTheme | null,
): string {
  // MultiQC tabs always render in a neutral grey/black scheme — the YAML
  // currently stamps `orange` on the parent MultiQC tab, but the official
  // logo is monochrome so a coloured fill clashes with the icon. Force
  // `dark` so light mode gets a near-black active fill and dark mode gets
  // the same near-black fill (Mantine `dark.6` ≈ `#25262b`).
  if (isMultiqcIcon(tab.tab_icon) || isMultiqcIcon(tab.icon)) return 'dark';
  // A colour the YAML picked is the author's decision and outranks the brand;
  // only the unstated default follows it.
  return (
    tab.tab_icon_color ||
    tab.icon_color ||
    (isParent ? brandAccent(brand, 'tertiary', 'orange') : brandAccent(brand, 'primary', 'blue'))
  );
}

/** Reserved sentinel value — clicking the trailing "+ Add" pill opens the
 *  Add menu (or runs its one action) rather than navigating. Mirrors Dash's
 *  `__add_tab__` (`tab_callbacks.py:148-161`). */
const ADD_TAB_VALUE = '__add_tab__';
/** The Guide's pill: a page of the dashboard rather than a tab of it, so it
 *  takes the list's selection while it is open. */
const GUIDE_VALUE = '__guide__';

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
  /** Edit-mode group handlers. A group is the `tab_group` its tabs share; each
   *  handler is optional, and the matching menu entry is hidden without it. */
  onRenameGroup?: (group: string) => void;
  onMoveGroup?: (group: string, direction: TabMoveDirection) => void;
  onAddTabToGroup?: (group: string) => void;
  onUngroup?: (group: string) => void;
  /** Opens the New group dialog, optionally with tabs already picked. */
  onNewGroup?: (tabIds?: string[]) => void;
  /** Moves one tab into `group` (null: out of any group). */
  onMoveTabToGroup?: (tab: DashboardSummary, group: string | null) => void;
  /** The dashboard's own brand theme. Its logo renders centered at the
   *  bottom of the sidebar, just above the footer divider; when the dashboard
   *  doesn't set one it inherits the instance logo. */
  brandTheme?: BrandTheme | null;
  /** The dashboard Guide's entry, closing the list. Omitted when the author
   *  turned the Guide off. */
  guide?: {
    open: boolean;
    /** The Guide's URL, so the pill is a real link (middle-click, bookmark). */
    href: string;
    onOpen: () => void;
    onClose: () => void;
  };
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
  onRenameGroup,
  onMoveGroup,
  onAddTabToGroup,
  onUngroup,
  onNewGroup,
  onMoveTabToGroup,
  brandTheme,
  guide,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';
  // The brand in force for this subtree — the dashboard's own when it
  // overrides, the instance's otherwise (App/EditorApp nest the context).
  const brand = useBranding();
  const isEdit = mode === 'edit';

  // Lift the per-tab menu open-state up here so only ONE "..." menu can be
  // open at a time. Each child Menu was previously self-contained, so opening
  // tab B's menu didn't close tab A's (Mantine's outside-click detection
  // doesn't fire when the user clicks another menu's trigger inside the same
  // tab list).
  const [openMenuTabId, setOpenMenuTabId] = useState<string | null>(null);

  // Switching tab is a real anchor navigation, so the sidebar is rebuilt from
  // scratch and its tab list came back scrolled to the top. On a dashboard
  // family with more tabs than fit, that threw the reader back to the first
  // tab's neighbourhood every single time they moved. sessionStorage rather
  // than component state for exactly that reason: the component does not
  // survive the navigation, the session does.
  const tabScrollRef = useRef<HTMLDivElement>(null);
  const rememberTabScroll = ({ y }: { x: number; y: number }) => {
    try {
      sessionStorage.setItem(TAB_SCROLL_KEY, String(y));
    } catch {
      // Private browsing and "block site data" both throw here. Losing the
      // scroll position is not worth breaking the sidebar over.
    }
  };
  useEffect(() => {
    const el = tabScrollRef.current;
    if (!el) return;
    let saved: string | null = null;
    try {
      saved = sessionStorage.getItem(TAB_SCROLL_KEY);
    } catch {
      return;
    }
    const y = Number(saved);
    if (!saved || !Number.isFinite(y) || y <= 0) return;
    // Restoring on the next frame is too early: the tab pills, their icons and
    // the fonts all land after that, so the list is still shorter than the
    // offset and the browser clamps it to zero. Watch the viewport instead and
    // apply the offset the moment the content is tall enough to hold it, then
    // stop watching so a later resize never yanks the reader back.
    const apply = () => {
      if (el.scrollHeight - el.clientHeight < y) return false;
      el.scrollTop = y;
      return el.scrollTop > 0;
    };
    if (apply()) return;
    const observer = new ResizeObserver(() => {
      if (apply()) observer.disconnect();
    });
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);
    return () => observer.disconnect();
  }, []);

  // Tabs naming a `tab_group` are drawn together under its name; the main tab
  // and the ungrouped tabs lead, with no heading.
  const sections = groupTabs(tabs);
  const groupNames = sections.flatMap((s) => (s.group ? [s.group] : []));

  // Pre-compute the first/last child of each section so Move up/down can be
  // disabled appropriately. A move stays inside its section (a tab changes
  // group from "Move to group" or the Edit modal), so the bounds are per section. Main tab (no
  // parent_dashboard_id) is always at the top and never moves, so it doesn't
  // count toward "first child".
  const firstChildIds = new Set<string>();
  const lastChildIds = new Set<string>();
  for (const section of sections) {
    const children = section.tabs.filter((t) => t.parent_dashboard_id);
    if (!children.length) continue;
    firstChildIds.add(children[0].dashboard_id);
    lastChildIds.add(children[children.length - 1].dashboard_id);
  }

  // Each tab pill is rendered as an `<a href>` (see `renderRoot` on
  // `Tabs.Tab` below) so middle-click / Cmd+Click / Ctrl+Click open the
  // target tab in a new browser tab natively. Left-click follows the
  // anchor's default navigation, so this onChange only needs to handle the
  // synthetic "+ Add tab" pill — regular tab switches just let the browser
  // follow the link.
  const linkMode: 'view' | 'edit' = window.location.pathname.startsWith(
    '/dashboard-edit/',
  )
    ? 'edit'
    : 'view';

  const handleTabChange = (value: string | null) => {
    // Regular tab clicks are handled by the `<a href>` root element — only the
    // synthetic "+ Add tab" pill needs an in-process handler. (Clicking the
    // already-active tab is a no-op because the anchor navigates to the same
    // URL the browser is on.)
    // With both actions on offer the pill opens the Add menu (its Menu
    // target toggles it); with one, the pill is that action.
    if (value !== ADD_TAB_VALUE || (onAddTab && onNewGroup)) return;
    if (onAddTab) onAddTab();
    else onNewGroup?.();
  };

  const renderTab = (d: DashboardSummary) => {
    const isParent = !d.parent_dashboard_id;
    const iconColor = resolveTabColor(d, isParent, brand);
    const isActive = d.dashboard_id === activeId;
    // The open Guide takes the list's fill, so the current tab draws as any
    // other until it closes.
    const isFilled = isActive && !guide?.open;
    const label = isParent
      ? d.main_tab_name || d.title || d.dashboard_id
      : d.title || d.dashboard_id;
    const yamlImage = tabImageSrc(d, isParent, theme === 'dark', isFilled);
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
          src={yamlImage}
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
          color: isFilled ? 'var(--mantine-color-white)' : `var(--mantine-color-${iconColor}-6)`,
          flexShrink: 0,
        }}
      />
    );

    // In edit mode, the "..." menu lives in Mantine's `rightSection` slot —
    // that's the only way to get it truly right-aligned, since the default
    // `tabLabel` span is auto-width and a flex Group inside it only takes
    // content width.
    const rightSection = isEdit ? (
      <TabMenu
        tab={d}
        isParent={isParent}
        isFirstChild={firstChildIds.has(d.dashboard_id)}
        isLastChild={lastChildIds.has(d.dashboard_id)}
        opened={openMenuTabId === d.dashboard_id}
        onOpen={() => setOpenMenuTabId(d.dashboard_id)}
        onClose={() => setOpenMenuTabId((cur) => (cur === d.dashboard_id ? null : cur))}
        onEditTab={onEditTab}
        onDeleteTab={onDeleteTab}
        onMoveTab={onMoveTab}
        groupNames={groupNames}
        onMoveTabToGroup={onMoveTabToGroup}
        onNewGroup={onNewGroup}
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
        // Render the tab as an anchor so browser-level open-in-new-tab
        // (middle/Cmd+Click) works natively.
        renderRoot={(props) => (
          <a
            {...props}
            href={dashboardHref(d.dashboard_id, linkMode)}
            // With the Guide open, the tab it was opened from is one click
            // away: a plain click closes the Guide rather than reloading the
            // tab underneath it.
            onClick={
              isActive && guide?.open
                ? (e: React.MouseEvent<HTMLAnchorElement>) => {
                    props.onClick?.(e);
                    dashboardLinkClickHandler(guide.onClose)(e);
                  }
                : props.onClick
            }
          />
        )}
      >
        <TabLabel label={label} />
      </Tabs.Tab>
    );
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
      {/* `hover` rather than `auto`: a permanently drawn scrollbar down the
          side of a dozen tabs is chrome the reader never asked for, and it
          sits between the pills and the sidebar edge where it reads as a
          border. It still appears the moment the pointer is over the list. */}
      <ScrollArea
        style={{ flex: 1 }}
        type="hover"
        viewportRef={tabScrollRef}
        onScrollPositionChange={rememberTabScroll}
      >
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
              className="depictio-chrome-tabs"
              orientation="vertical"
              variant="pills"
              placement="left"
              value={guide?.open ? GUIDE_VALUE : activeId}
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
                {sections.map((section) => (
                  <React.Fragment
                    key={section.group === null ? 'ungrouped' : `group:${section.group}`}
                  >
                    {section.group !== null && (
                      <Group
                        gap={4}
                        wrap="nowrap"
                        justify="space-between"
                        mt={6}
                        pr={isEdit ? 4 : undefined}
                        data-testid="sidebar-tab-group"
                      >
                        {/* Same type as the "Tabs" heading above, set in line
                            with the pill icons so it reads as a category. */}
                        <Text
                          c="dimmed"
                          size="xs"
                          tt="uppercase"
                          fw={700}
                          pl="xs"
                          truncate="end"
                          style={{ minWidth: 0 }}
                        >
                          {section.group}
                        </Text>
                        {isEdit && (
                          <GroupMenu
                            group={section.group}
                            isFirst={section.group === groupNames[0]}
                            isLast={section.group === groupNames[groupNames.length - 1]}
                            opened={openMenuTabId === `group:${section.group}`}
                            onOpen={() => setOpenMenuTabId(`group:${section.group}`)}
                            onClose={() =>
                              setOpenMenuTabId((cur) =>
                                cur === `group:${section.group}` ? null : cur,
                              )
                            }
                            onRenameGroup={onRenameGroup}
                            onMoveGroup={onMoveGroup}
                            onAddTabToGroup={onAddTabToGroup}
                            onUngroup={onUngroup}
                          />
                        )}
                      </Group>
                    )}
                    {section.tabs.map(renderTab)}
                  </React.Fragment>
                ))}

                {/* One "+ Add" pill closing the list, edit mode only, with a
                    rule above it so it doesn't read as one more tab. A tab
                    and a group are both things added to this list, so they
                    share the pill: a menu offers either, and with only one
                    on offer the pill is that action. Click intercepts via
                    ADD_TAB_VALUE in `handleTabChange`. */}
                {((isEdit && (onAddTab || onNewGroup)) || guide) && (
                  <Divider my={6} mx="xs" />
                )}
                {isEdit && (onAddTab || onNewGroup) && (
                  <Menu
                    position="right-start"
                    offset={6}
                    width={240}
                    withinPortal
                    disabled={!(onAddTab && onNewGroup)}
                  >
                    <Menu.Target>
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
                        data-testid="sidebar-add"
                      >
                        <span className="depictio-chrome-tab-label">
                          {onAddTab ? 'Add tab' : 'New group'}
                          {onAddTab && onNewGroup ? ' or group' : ''}
                        </span>
                      </Tabs.Tab>
                    </Menu.Target>
                    <Menu.Dropdown>
                      <Menu.Item
                        leftSection={<Icon icon="mdi:tab-plus" width={18} height={18} />}
                        onClick={() => onAddTab?.()}
                        data-testid="sidebar-add-tab"
                      >
                        <Text size="sm">Add tab</Text>
                        <Text size="xs" c="dimmed">
                          A page of components
                        </Text>
                      </Menu.Item>
                      <Menu.Item
                        leftSection={
                          <Icon icon="mdi:folder-plus-outline" width={18} height={18} />
                        }
                        onClick={() => onNewGroup?.()}
                        data-testid="sidebar-new-group"
                      >
                        <Text size="sm">Add group</Text>
                        <Text size="xs" c="dimmed">
                          A heading that gathers tabs
                        </Text>
                      </Menu.Item>
                    </Menu.Dropdown>
                  </Menu>
                )}
                {/* The Guide, under the same rule: about the dashboard, not
                    one more tab of it. A link to the Guide's URL so it can be
                    opened apart or bookmarked; a plain click opens it in
                    place, and closes it again when it is the open page. */}
                {guide && (
                  <Tabs.Tab
                    key={GUIDE_VALUE}
                    value={GUIDE_VALUE}
                    leftSection={
                      <Icon
                        icon="mdi:help-circle-outline"
                        width={18}
                        height={18}
                        style={{ flexShrink: 0 }}
                      />
                    }
                    pl="xs"
                    data-testid="sidebar-guide"
                    renderRoot={(props) => (
                      <a
                        {...props}
                        href={guide.href}
                        onClick={(e: React.MouseEvent<HTMLAnchorElement>) => {
                          props.onClick?.(e);
                          dashboardLinkClickHandler(guide.open ? guide.onClose : guide.onOpen)(e);
                        }}
                      />
                    )}
                  >
                    <span className="depictio-chrome-tab-label">Guide</span>
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
        {/* Dashboard logo — centered, right above the footer divider.
            Falls through to the instance logo, then to nothing.

            Sized generously: on a dashboard this is the one place the brand
            appears, and a logo small enough to be mistaken for an icon reads
            as an afterthought. The cap is a height so a wide wordmark and a
            square badge both land at a similar visual weight. */}
        <BrandLogo
          theme={brandTheme}
          fallback="none"
          testId="dashboard-logo"
          style={{ maxWidth: '92%', maxHeight: 130, margin: '0 auto' }}
        />
        {/* No attribution here — the dashboard's single slot for it is the
            header, and carrying it in both places showed it twice. */}
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
  /** The family's groups, for the "Move to group" page. */
  groupNames: string[];
  onMoveTabToGroup?: (tab: DashboardSummary, group: string | null) => void;
  onNewGroup?: (tabIds?: string[]) => void;
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
 *
 * "Move to group" is a second page of the same dropdown, as "Move to section"
 * is on a component's menu (`GridItemEditOverlay`): the family's groups, "No
 * group", and "New group…", which opens the New group dialog with this tab
 * already picked.
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
  groupNames,
  onMoveTabToGroup,
  onNewGroup,
}) => {
  const [page, setPage] = useState<'actions' | 'groups'>('actions');
  const currentGroup = tabGroupOf(tab);
  const stop = (e: React.SyntheticEvent) => {
    // Stop the click bubbling to the Tabs.Tab (which would switch tab) AND
    // cancel the default action: `renderRoot` renders the tab as an
    // `<a href>` for native open-in-new-tab support, so without
    // `preventDefault` clicking "..." follows the href and refreshes the URL
    // instead of opening the menu.
    e.stopPropagation();
    e.preventDefault();
  };

  return (
    <Box
      // The Tabs.Tab parent treats any click as a navigation request — wrap
      // the trigger in a stopPropagation + preventDefault guard so opening the
      // menu doesn't also switch tab or trigger the anchor navigation.
      onClick={stop}
      onMouseDown={stop}
      style={{ display: 'inline-flex', alignItems: 'center' }}
    >
      <Menu
        position="bottom-end"
        withinPortal
        zIndex={Z_LAYERS.tooltip}
        shadow="md"
        width={210}
        opened={opened}
        onChange={(o) => {
          if (o) onOpen();
          else {
            onClose();
            setPage('actions');
          }
        }}
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
          {page === 'groups' ? (
            <>
              <Menu.Item
                closeMenuOnClick={false}
                leftSection={<Icon icon="mdi:chevron-left" width={14} />}
                onClick={() => setPage('actions')}
              >
                Back
              </Menu.Item>
              <Menu.Divider />
              <Menu.Label>Move to group</Menu.Label>
              <ScrollArea.Autosize mah={240} type="auto">
                {groupNames.map((g) => {
                  const current = sameTabGroup(g, currentGroup);
                  return (
                    <Menu.Item
                      key={g}
                      disabled={current}
                      leftSection={
                        <Icon
                          icon={current ? 'mdi:check' : 'mdi:folder-outline'}
                          width={14}
                        />
                      }
                      onClick={() => onMoveTabToGroup?.(tab, g)}
                    >
                      {g}
                    </Menu.Item>
                  );
                })}
              </ScrollArea.Autosize>
              <Menu.Item
                disabled={currentGroup === null}
                leftSection={
                  <Icon
                    icon={currentGroup === null ? 'mdi:check' : 'mdi:folder-off-outline'}
                    width={14}
                  />
                }
                onClick={() => onMoveTabToGroup?.(tab, null)}
              >
                No group
              </Menu.Item>
              {onNewGroup && (
                <>
                  <Menu.Divider />
                  <Menu.Item
                    leftSection={<Icon icon="mdi:folder-plus-outline" width={14} />}
                    onClick={() => onNewGroup([tab.dashboard_id])}
                  >
                    New group…
                  </Menu.Item>
                </>
              )}
            </>
          ) : (
            <>
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
                  {onMoveTabToGroup && (
                    <Menu.Item
                      // Opens the second page, so the menu has to stay open.
                      closeMenuOnClick={false}
                      leftSection={<Icon icon="mdi:folder-move-outline" width={14} />}
                      rightSection={<Icon icon="mdi:chevron-right" width={14} />}
                      onClick={() => setPage('groups')}
                    >
                      Move to group
                    </Menu.Item>
                  )}
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
            </>
          )}
        </Menu.Dropdown>
      </Menu>
    </Box>
  );
};

interface GroupMenuProps {
  group: string;
  isFirst: boolean;
  isLast: boolean;
  opened: boolean;
  onOpen: () => void;
  onClose: () => void;
  onRenameGroup?: (group: string) => void;
  onMoveGroup?: (group: string, direction: TabMoveDirection) => void;
  onAddTabToGroup?: (group: string) => void;
  onUngroup?: (group: string) => void;
}

/**
 * The "..." menu on a group heading (edit mode), styled like the per-tab one.
 * Moving a group moves its whole block of tabs among the other groups; the
 * ungrouped tabs, main tab included, always stay above the groups.
 */
const GroupMenu: React.FC<GroupMenuProps> = ({
  group,
  isFirst,
  isLast,
  opened,
  onOpen,
  onClose,
  onRenameGroup,
  onMoveGroup,
  onAddTabToGroup,
  onUngroup,
}) => (
  <Menu
    position="bottom-end"
    withinPortal
    zIndex={Z_LAYERS.tooltip}
    shadow="md"
    width={210}
    opened={opened}
    onChange={(o) => (o ? onOpen() : onClose())}
    closeOnItemClick
  >
    <Menu.Target>
      <ActionIcon
        variant="subtle"
        color="gray"
        size="sm"
        aria-label={`Group actions: ${group}`}
        data-testid="sidebar-tab-group-menu"
      >
        <Icon icon="tabler:dots-vertical" width={16} />
      </ActionIcon>
    </Menu.Target>
    <Menu.Dropdown>
      <Menu.Label>{group}</Menu.Label>
      {onRenameGroup && (
        <Menu.Item
          leftSection={<Icon icon="tabler:edit" width={14} />}
          onClick={() => onRenameGroup(group)}
        >
          Rename group…
        </Menu.Item>
      )}
      {onAddTabToGroup && (
        <Menu.Item
          leftSection={<Icon icon="mdi:plus" width={14} />}
          onClick={() => onAddTabToGroup(group)}
        >
          Add tab to this group
        </Menu.Item>
      )}
      {onMoveGroup && (
        <>
          <Menu.Item
            leftSection={<Icon icon="tabler:arrow-up" width={14} />}
            disabled={isFirst}
            onClick={() => onMoveGroup(group, 'up')}
          >
            Move group up
          </Menu.Item>
          <Menu.Item
            leftSection={<Icon icon="tabler:arrow-down" width={14} />}
            disabled={isLast}
            onClick={() => onMoveGroup(group, 'down')}
          >
            Move group down
          </Menu.Item>
        </>
      )}
      {onUngroup && (
        <>
          <Menu.Divider />
          <Menu.Item
            leftSection={<Icon icon="mdi:folder-off-outline" width={14} />}
            onClick={() => onUngroup(group)}
          >
            Ungroup
          </Menu.Item>
        </>
      )}
    </Menu.Dropdown>
  </Menu>
);

export default Sidebar;
