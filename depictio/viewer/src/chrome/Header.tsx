import React from 'react';
import { ActionIcon, Badge, Box, Button, Group, Loader, Menu, Title, Tooltip, useMantineColorScheme } from '@mantine/core';
import { BRAND_PALETTES, useBrandAccent, useBranding } from 'depictio-react-core';
import { Icon } from '@iconify/react';
import { AI_ICON } from 'depictio-react-ai';

import type { BrandTheme, DashboardData, DashboardSummary } from 'depictio-react-core';
import PoweredBy from './PoweredBy';

/** True for path-like icon values (PNG/SVG file URLs) — these came from the
 *  Dash YAML and aren't valid Iconify names. */
function isImagePath(s: string | null | undefined): boolean {
  if (!s) return false;
  return /^(\/|https?:\/\/|data:)/.test(s) || /\.(png|svg|jpe?g|webp)$/i.test(s);
}

function isMultiqcIcon(path: string | null | undefined): boolean {
  if (!path) return false;
  return /\/assets\/images\/logos\/multiqc(\.png|_icon_(dark|white|color)\.svg)$/i.test(path);
}

/** Map any MultiQC logo path (legacy PNG or new SVGs) to the SPA-served
 *  themed SVG. Mirrors the same helper in Sidebar.tsx. */
function rewriteMultiqcIcon(path: string, theme: 'light' | 'dark'): string {
  if (!isMultiqcIcon(path)) return path;
  return theme === 'dark'
    ? '/dashboard/logos/multiqc_icon_white.svg'
    : '/dashboard/logos/multiqc_icon_dark.svg';
}

/** Dash precedence: `tab.tab_icon || tab.icon`, `tab.tab_icon_color || tab.icon_color`. */
function resolveTabIcon(tab: DashboardSummary | null | undefined): string | null {
  return (tab?.tab_icon || tab?.icon) ?? null;
}
function resolveTabColor(
  tab: DashboardSummary | null | undefined,
  brand: BrandTheme | null,
): string | null {
  // Match the Sidebar rule: MultiQC tabs render in neutral dark, regardless
  // of whatever colour the YAML/seed stamped.
  if (isMultiqcIcon(tab?.tab_icon) || isMultiqcIcon(tab?.icon)) return 'dark';
  // Same precedence as the sidebar pill this title names: the author's colour
  // wins, and a tab that states none takes the brand. Still `null` when there
  // is no brand — an unbranded deployment kept a colourless tab's title as
  // plain body text, and this is not the place to change that.
  return (
    tab?.tab_icon_color || tab?.icon_color || (brand?.tertiary ? BRAND_PALETTES.tertiary : null)
  );
}

interface HeaderProps {
  dashboardId: string | null;
  dashboard: DashboardData | null;
  /** The active tab in the sibling family (parent or current child). */
  activeTab: DashboardSummary | null;
  /** The parent dashboard (used for "Parent / Child" breadcrumb). */
  parentTab?: DashboardSummary | null;
  mobileOpened: boolean;
  desktopOpened: boolean;
  onToggleMobile: () => void;
  onToggleDesktop: () => void;
  onOpenSettings: () => void;
  cardsLoading?: boolean;
  /** 'view' (default) shows Edit; 'edit' shows View + Add + Save. */
  mode?: 'view' | 'edit';
  /** Edit-mode only: opens the component builder. */
  onAddComponent?: () => void;
  /** Edit-mode only: when set, the "Component" entry becomes a submenu with a
   *  "With AI…" entry invoking this. Omitted ⇒ plain entry (AI off). */
  onAddWithAI?: () => void;
  /** Edit-mode only: opens the add-section dialog. The "Add" menu is add-only —
   *  editing sections happens from the "…" on each section header. */
  onAddSection?: () => void;
  /** Edit-mode only: invoked when the user clicks "Save". Should force-flush any pending debounced save. */
  onSave?: () => void;
  /** True when the current user owns this dashboard. When false, the
   *  Edit / Add / Save buttons render disabled with a tooltip
   *  explaining why — the backend enforces the same rule with 403s. The
   *  default is `true` so callers that haven't been migrated keep working,
   *  matching prior behavior. */
  isOwner?: boolean;
  /** Optional element rendered next to the action group (e.g. RealtimeIndicator). */
  rightExtras?: React.ReactNode;
  /** Optional element rendered right after the title (e.g. the dashboard load
   *  indicator). Replaces the bare `cardsLoading` spinner when provided, since
   *  an indicator of its own already accounts for the card group. */
  titleExtras?: React.ReactNode;
  /** Below `sm` the filter panel moves into a drawer; this opens it. Omitted
   *  (with the button hidden) when there are no filters to show. */
  onOpenFilters?: () => void;
  /** Active filter count, badged on the filters button so a filtered dashboard
   *  never looks unfiltered on a phone. */
  filterCount?: number;
}

/**
 * Replaces the contents of `<AppShell.Header>`. Three regions:
 *   Left:  Burgers + active-tab icon + dashboard title (with parent breadcrumb)
 *   Right: PoweredBy | Edit | Settings (Reset lives in the Filters panel now).
 *
 * Visual parity with `depictio/dash/layouts/header.py:design_header`.
 */
const Header: React.FC<HeaderProps> = ({
  dashboardId,
  dashboard,
  activeTab,
  parentTab,
  mobileOpened,
  desktopOpened,
  onToggleMobile,
  onToggleDesktop,
  onOpenSettings,
  cardsLoading = false,
  mode = 'view',
  onAddComponent,
  onAddWithAI,
  onAddSection,
  onSave,
  isOwner = true,
  rightExtras,
  titleExtras,
  onOpenFilters,
  filterCount = 0,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';

  const tabIconRaw = resolveTabIcon(activeTab);
  const tabIconIsImage = isImagePath(tabIconRaw);
  // Image path → swap MultiQC PNG/SVG variants to the SPA-served themed SVG.
  // Iconify names (mdi:..., bx:...) pass through unchanged.
  const tabIconImageSrc =
    tabIconIsImage && tabIconRaw ? rewriteMultiqcIcon(tabIconRaw, theme) : null;
  // The header's three actions, as brand roles. The literals are what an
  // unbranded deployment has always shown; an instance that names a brand gets
  // its own hues here in either tint mode.
  const brand = useBranding();
  const addColor = useBrandAccent('primary', 'green');
  const saveColor = useBrandAccent('secondary', 'teal');
  const editColor = useBrandAccent('primary', 'blue');
  const resolvedColor = resolveTabColor(activeTab, brand);
  const tabIconColor = resolvedColor || 'gray';
  // Title text color:
  //   - 'dark' (the MultiQC neutral scheme) → page text color (`#1a1b1e`
  //     light / `#e9ecef` dark) so it stays readable in both schemes.
  //     `dark.6` is near-black and would be invisible on the dark page.
  //   - any other named color → shade 6 in light, shade 4 in dark.
  const titleColorVar = !resolvedColor
    ? undefined
    : resolvedColor === 'dark'
      ? 'var(--mantine-color-text)'
      : theme === 'dark'
        ? `var(--mantine-color-${resolvedColor}-4)`
        : `var(--mantine-color-${resolvedColor}-6)`;

  // Breadcrumb format: `<dashboard name> / <active tab label>` for every tab.
  // - prefix is the parent dashboard's `title` (e.g. "nf-core/ampliseq")
  // - active label is the tab's pill label: `main_tab_name` for the parent
  //   pill (e.g. "MultiQC"), `title` for child pills (e.g. "Variants").
  // Falls back gracefully if any field is missing.
  const isChild = Boolean(activeTab?.parent_dashboard_id);
  const dashboardName = parentTab?.title || dashboard?.title;
  const activeLabel = isChild
    ? activeTab?.title || dashboardId || 'Dashboard'
    : activeTab?.main_tab_name ||
      activeTab?.title ||
      dashboard?.title ||
      dashboardId ||
      'Dashboard';
  const titleText = dashboardName
    ? `${dashboardName} / ${activeLabel}`
    : activeLabel;

  const handleEdit = () => {
    if (dashboardId) {
      window.location.assign(`/dashboard-edit/${dashboardId}`);
    }
  };

  const handleViewMode = () => {
    if (dashboardId) {
      window.location.assign(`/dashboard/${dashboardId}`);
    }
  };

  return (
    <Group h="100%" px="md" justify="space-between" wrap="nowrap">
      {/* Left region — custom hamburger ActionIcons (always ||| icon, no
        cross-on-open animation per user request). */}
      <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="md"
          onClick={onToggleMobile}
          hiddenFrom="sm"
          aria-label="Toggle navigation (mobile)"
        >
          <Icon icon="mdi:menu" width={22} />
        </ActionIcon>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="md"
          onClick={onToggleDesktop}
          visibleFrom="sm"
          aria-label="Toggle tab sidebar"
        >
          <Icon icon="mdi:menu" width={22} />
        </ActionIcon>
        {/* Only below `sm`, where the filter panel has moved into a drawer.
            Above it the panel is on screen and this would be a second way to
            do the same thing. */}
        {onOpenFilters && (
          <Button
            variant="light"
            size="compact-sm"
            hiddenFrom="sm"
            onClick={onOpenFilters}
            leftSection={<Icon icon="mdi:filter-variant" width={14} />}
            rightSection={
              filterCount > 0 ? (
                <Badge size="xs" variant="filled" circle>
                  {filterCount}
                </Badge>
              ) : undefined
            }
          >
            Filters
          </Button>
        )}
        {tabIconImageSrc ? (
          <img
            src={tabIconImageSrc}
            alt=""
            style={{ width: 20, height: 20, objectFit: 'contain' }}
          />
        ) : tabIconRaw ? (
          <Icon
            icon={tabIconRaw}
            width={20}
            style={{
              color:
                tabIconColor === 'dark'
                  ? 'var(--mantine-color-text)'
                  : theme === 'dark'
                    ? `var(--mantine-color-${tabIconColor}-4)`
                    : `var(--mantine-color-${tabIconColor}-6)`,
            }}
          />
        ) : null}
        <Title
          order={3}
          style={{
            color: titleColorVar,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            minWidth: 0,
          }}
        >
          {titleText}
        </Title>
        {titleExtras ?? (cardsLoading && <Loader size="xs" />)}
      </Group>

      {/* Spacer */}
      <Box style={{ flex: 1, minWidth: 0 }} />

      {/* Right region — colors mirror depictio/dash/layouts/header.py */}
      <Group gap={8} wrap="nowrap" style={{ flexShrink: 0 }}>
        <PoweredBy withRightBorder />
        {/* One Add menu rather than a button per thing that can be added: the
            two entries name what appears, and the menu stays add-only. An
            existing section is edited from the "…" on its own header. */}
        {mode === 'edit' && onAddComponent && (
          <Menu shadow="md" width={200} position="bottom-end">
            <Menu.Target>
              {/* Tooltip inside the target, around the button: `Menu.Target`
                  and `Tooltip` both need a ref-able child, and a `Menu` is a
                  function component — wrapping the Menu in the Tooltip drops
                  the ref and the menu stops opening. */}
              <Tooltip
                label="You can only edit dashboards you own. Duplicate this one to get your own copy."
                disabled={isOwner}
                withArrow
              >
                <Button
                  leftSection={<Icon icon="mdi:plus-circle" width={14} />}
                  rightSection={<Icon icon="mdi:chevron-down" width={14} />}
                  color={addColor}
                  variant="filled"
                  size="xs"
                  disabled={!dashboardId || !isOwner}
                  data-tour-id="editor-add-component"
                >
                  Add
                </Button>
              </Tooltip>
            </Menu.Target>
            <Menu.Dropdown>
              {onAddWithAI ? (
                /* Mantine 7 has no public Menu.Sub — a nested hover Menu
                   anchored on a Menu.Item is the supported way to get a
                   second level ("Component ▸ Manually / With AI…"). */
                <Menu
                  trigger="click-hover"
                  position="right-start"
                  offset={4}
                  shadow="md"
                  withinPortal
                >
                  <Menu.Target>
                    <Menu.Item
                      closeMenuOnClick={false}
                      leftSection={<Icon icon="mdi:view-grid-plus-outline" width={14} />}
                      rightSection={<Icon icon="mdi:chevron-right" width={14} />}
                      data-testid="add-component-submenu"
                    >
                      Component
                    </Menu.Item>
                  </Menu.Target>
                  <Menu.Dropdown>
                    <Menu.Item
                      leftSection={<Icon icon="mdi:pencil-outline" width={14} />}
                      onClick={onAddComponent}
                      data-testid="add-component"
                    >
                      Manually
                    </Menu.Item>
                    <Menu.Item
                      leftSection={<Icon icon={AI_ICON} width={14} />}
                      onClick={onAddWithAI}
                      data-testid="add-with-ai"
                    >
                      With AI…
                    </Menu.Item>
                  </Menu.Dropdown>
                </Menu>
              ) : (
                <Menu.Item
                  leftSection={<Icon icon="mdi:view-grid-plus-outline" width={14} />}
                  onClick={onAddComponent}
                  data-testid="add-component"
                >
                  Component
                </Menu.Item>
              )}
              {onAddSection && (
                <Menu.Item
                  leftSection={<Icon icon="mdi:format-list-group" width={14} />}
                  onClick={onAddSection}
                  data-testid="add-section"
                >
                  Section
                </Menu.Item>
              )}
            </Menu.Dropdown>
          </Menu>
        )}
        {mode === 'edit' && onSave && (
          <Tooltip
            label="You can only save dashboards you own. Duplicate this one to get your own copy."
            disabled={isOwner}
            withArrow
          >
            <Button
              leftSection={<Icon icon="mdi:content-save" width={14} />}
              color={saveColor}
              variant="filled"
              size="xs"
              onClick={onSave}
              disabled={!dashboardId || !isOwner}
              data-tour-id="editor-save"
            >
              Save
            </Button>
          </Tooltip>
        )}
        {/* Analysis sits between Save and Edit / Exit Edit. It is a way of
            *reading* the dashboard rather than changing it, so it stays clear of
            Settings and of the mode switch; putting it after Save also keeps
            the primary action leftmost in edit mode. In view mode the Save
            block is absent, so this lands immediately left of Edit. */}
        {rightExtras}
        {mode === 'view' ? (
          <Tooltip
            label="You can only edit dashboards you own. Duplicate this one to get your own copy."
            disabled={isOwner}
            withArrow
          >
            <Button
              leftSection={<Icon icon="mdi:pencil" width={14} />}
              color={editColor}
              variant="filled"
              size="xs"
              onClick={handleEdit}
              disabled={!dashboardId || !isOwner}
              data-tour-id="enter-edit-mode"
            >
              Edit
            </Button>
          </Tooltip>
        ) : (
          <Button
            leftSection={<Icon icon="mdi:eye" width={14} />}
            color="gray"
            variant="filled"
            size="xs"
            onClick={handleViewMode}
            disabled={!dashboardId}
          >
            Exit Edit
          </Button>
        )}
        <Button
          leftSection={<Icon icon="ic:baseline-settings" width={14} />}
          color="gray"
          variant="filled"
          size="xs"
          onClick={onOpenSettings}
        >
          Settings
        </Button>
      </Group>
    </Group>
  );
};

export default Header;
