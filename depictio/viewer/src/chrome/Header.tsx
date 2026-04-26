import React from 'react';
import { ActionIcon, Box, Button, Group, Loader, Title } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData, DashboardSummary } from 'depictio-react-core';
import PoweredBy from './PoweredBy';

/** Dash precedence: `tab.tab_icon || tab.icon`, `tab.tab_icon_color || tab.icon_color`. */
function resolveTabIcon(tab: DashboardSummary | null | undefined): string | null {
  return (tab?.tab_icon || tab?.icon) ?? null;
}
function resolveTabColor(tab: DashboardSummary | null | undefined): string | null {
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
  /** Edit-mode only: invoked when the user clicks "Save". Should force-flush any pending debounced save. */
  onSave?: () => void;
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
  onSave,
}) => {
  const tabIcon = resolveTabIcon(activeTab);
  const resolvedColor = resolveTabColor(activeTab);
  const tabIconColor = resolvedColor || 'gray';
  const titleColorVar = resolvedColor
    ? `var(--mantine-color-${resolvedColor}-6)`
    : undefined;

  const isChild = Boolean(activeTab?.parent_dashboard_id);
  const parentTitle = parentTab?.title;
  const childTitle = activeTab?.title || dashboard?.title || dashboardId || 'Dashboard';
  const titleText =
    isChild && parentTitle ? `${parentTitle} / ${childTitle}` : childTitle;

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
        {tabIcon && (
          <Icon
            icon={tabIcon}
            width={20}
            style={{ color: `var(--mantine-color-${tabIconColor}-6)` }}
          />
        )}
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
        {mode === 'edit' && onAddComponent && (
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
            View
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
      </Group>
    </Group>
  );
};

export default Header;
