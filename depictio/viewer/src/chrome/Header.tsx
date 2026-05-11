import React from 'react';
import { ActionIcon, Box, Button, Group, Loader, Menu, Title, useMantineColorScheme } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData, DashboardSummary } from 'depictio-react-core';
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
    ? '/dashboard-beta/logos/multiqc_icon_white.svg'
    : '/dashboard-beta/logos/multiqc_icon_dark.svg';
}

/** Dash precedence: `tab.tab_icon || tab.icon`, `tab.tab_icon_color || tab.icon_color`. */
function resolveTabIcon(tab: DashboardSummary | null | undefined): string | null {
  return (tab?.tab_icon || tab?.icon) ?? null;
}
function resolveTabColor(tab: DashboardSummary | null | undefined): string | null {
  // Match the Sidebar rule: MultiQC tabs render in neutral dark, regardless
  // of whatever colour the YAML/seed stamped.
  if (isMultiqcIcon(tab?.tab_icon) || isMultiqcIcon(tab?.icon)) return 'dark';
  return (tab?.tab_icon_color || tab?.icon_color) ?? null;
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
  onReset: () => void;
  onOpenSettings: () => void;
  cardsLoading?: boolean;
  /** 'view' (default) shows Edit; 'edit' shows View + Add + Save. */
  mode?: 'view' | 'edit';
  /** Edit-mode only: invoked when the user clicks "Add component". */
  onAddComponent?: () => void;
  /** Edit-mode only: invoked when the user picks "With AI" from the
   *  Add-component dropdown. When omitted, the dropdown isn't shown
   *  (button reverts to a plain "Add component"). */
  onAddWithAI?: () => void;
  /** Edit-mode only: invoked when the user clicks "Save". Should force-flush any pending debounced save. */
  onSave?: () => void;
  /** Optional element rendered next to the action group (e.g. RealtimeIndicator). */
  rightExtras?: React.ReactNode;
}

/**
 * Replaces the contents of `<AppShell.Header>`. Three regions:
 *   Left:  Burgers + active-tab icon + dashboard title (with parent breadcrumb)
 *   Right: PoweredBy | Edit | Reset | Settings
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
  onReset,
  onOpenSettings,
  cardsLoading = false,
  mode = 'view',
  onAddComponent,
  onAddWithAI,
  onSave,
  rightExtras,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';

  const tabIconRaw = resolveTabIcon(activeTab);
  const tabIconIsImage = isImagePath(tabIconRaw);
  // Image path → swap MultiQC PNG/SVG variants to the SPA-served themed SVG.
  // Iconify names (mdi:..., bx:...) pass through unchanged.
  const tabIconImageSrc =
    tabIconIsImage && tabIconRaw ? rewriteMultiqcIcon(tabIconRaw, theme) : null;
  const resolvedColor = resolveTabColor(activeTab);
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
      window.location.assign(`/dashboard-beta-edit/${dashboardId}`);
    }
  };

  const handleViewMode = () => {
    if (dashboardId) {
      window.location.assign(`/dashboard-beta/${dashboardId}`);
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
        {cardsLoading && <Loader size="xs" />}
      </Group>

      {/* Spacer */}
      <Box style={{ flex: 1, minWidth: 0 }} />

      {/* Right region — colors mirror depictio/dash/layouts/header.py */}
      <Group gap={8} wrap="nowrap" style={{ flexShrink: 0 }}>
        <PoweredBy withRightBorder />
        {mode === 'edit' && onAddComponent && onAddWithAI && (
          <Menu shadow="md" position="bottom-end" withinPortal>
            <Menu.Target>
              <Button
                leftSection={<Icon icon="mdi:plus-circle" width={14} />}
                rightSection={<Icon icon="mdi:chevron-down" width={14} />}
                color="green"
                variant="filled"
                size="xs"
                disabled={!dashboardId}
                data-tour-id="add-component-button"
              >
                Add component
              </Button>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item
                leftSection={<Icon icon="mdi:plus-circle" width={14} />}
                onClick={onAddComponent}
              >
                Manually
              </Menu.Item>
              <Menu.Item
                leftSection={
                  <Icon
                    icon="material-symbols:auto-fix"
                    width={14}
                    color="var(--mantine-color-violet-6)"
                  />
                }
                onClick={onAddWithAI}
                data-tour-id="add-with-ai-button"
              >
                With AI…
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        )}
        {mode === 'edit' && onAddComponent && !onAddWithAI && (
          <Button
            leftSection={<Icon icon="mdi:plus-circle" width={14} />}
            color="green"
            variant="filled"
            size="xs"
            onClick={onAddComponent}
            disabled={!dashboardId}
          >
            Add component
          </Button>
        )}
        {mode === 'edit' && onSave && (
          <Button
            leftSection={<Icon icon="mdi:content-save" width={14} />}
            color="teal"
            variant="filled"
            size="xs"
            onClick={onSave}
            disabled={!dashboardId}
          >
            Save
          </Button>
        )}
        {mode === 'view' ? (
          <Button
            leftSection={<Icon icon="mdi:pencil" width={14} />}
            color="blue"
            variant="filled"
            size="xs"
            onClick={handleEdit}
            disabled={!dashboardId}
          >
            Edit
          </Button>
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
          leftSection={<Icon icon="bx:reset" width={14} />}
          color="orange"
          variant="filled"
          size="xs"
          onClick={onReset}
        >
          Reset
        </Button>
        <Button
          leftSection={<Icon icon="ic:baseline-settings" width={14} />}
          color="gray"
          variant="filled"
          size="xs"
          onClick={onOpenSettings}
        >
          Settings
        </Button>
        {rightExtras}
      </Group>
    </Group>
  );
};

export default Header;
