import React from 'react';
import { Box, Burger, Button, Group, Loader, Title } from '@mantine/core';
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
      window.location.assign(`/dashboard-edit/${dashboardId}`);
    }
  };

  return (
    <Group h="100%" px="md" justify="space-between" wrap="nowrap">
      {/* Left region */}
      <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
        <Burger
          opened={mobileOpened}
          onClick={onToggleMobile}
          hiddenFrom="sm"
          size="sm"
          aria-label="Toggle navigation (mobile)"
        />
        <Burger
          opened={desktopOpened}
          onClick={onToggleDesktop}
          visibleFrom="sm"
          size="sm"
          aria-label="Toggle tab sidebar"
        />
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

      {/* Right region */}
      <Group gap={8} wrap="nowrap" style={{ flexShrink: 0 }}>
        <PoweredBy withRightBorder />
        <Button
          leftSection={<Icon icon="mdi:pencil" width={16} />}
          color="blue"
          variant="filled"
          size="sm"
          onClick={handleEdit}
          disabled={!dashboardId}
        >
          Edit
        </Button>
        <Button
          leftSection={<Icon icon="bx:reset" width={16} />}
          color="orange"
          variant="light"
          size="sm"
          onClick={onReset}
        >
          Reset
        </Button>
        <Button
          leftSection={<Icon icon="ic:baseline-settings" width={16} />}
          color="gray"
          variant="light"
          size="sm"
          onClick={onOpenSettings}
        >
          Settings
        </Button>
      </Group>
    </Group>
  );
};

export default Header;
