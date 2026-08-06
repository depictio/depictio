import React from 'react';
import { Button, Divider, Drawer, Group, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardData } from 'depictio-react-core';
import { useIsStaticBundle } from 'depictio-react-core';
import DashboardInfoBody from './DashboardInfoBody';

/** Shown both as the disabled button's tooltip and, when the gate is closed,
 *  as the always-visible caption underneath it — a tooltip on a disabled
 *  Mantine button never fires, and the whole point of disabling (rather than
 *  hiding) is that the reason stays discoverable. */
const OWNER_GATE_HINT =
  'You can only export dashboards you own. Duplicate this one to get your own copy.';

interface SettingsDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboard: DashboardData | null;
  /** Needed by the Export static action; omit it (with `onExportStatic`) on
   *  surfaces that have no export affordance, e.g. the editor. */
  dashboardId?: string | null;
  /** Opens the owner-gated "Export static" modal. When omitted the Actions
   *  section is not rendered at all — that is how the editor (edit mode) keeps
   *  the export out. Also suppressed inside static bundles, which have no
   *  backend to build from. */
  onExportStatic?: () => void;
  /** False renders the export action disabled (never hidden) with the
   *  owner-gate explanation. Defaults to `true` so callers that don't pass it
   *  keep the previous behaviour. */
  isOwner?: boolean;
}

/**
 * Right-side drawer with read-only metadata about the current dashboard, plus
 * the dashboard-level actions that don't warrant permanent header real estate.
 *
 * The metadata lives in `DashboardInfoBody`, shared with the inspector's Info
 * tab — which is what the inspector replaces this drawer with when enabled.
 * Actions stay *here* rather than in that shared body: the inspector's Info tab
 * is a read-only pane, and the drawer's own "what is this dashboard / what can
 * I do with it" top-to-bottom reading order puts them last, behind a labelled
 * divider that mirrors the body's own "Identifiers" section idiom.
 */
const SettingsDrawer: React.FC<SettingsDrawerProps> = ({
  opened,
  onClose,
  dashboard,
  dashboardId,
  onExportStatic,
  isOwner = true,
}) => {
  // Static bundles are offline snapshots: there is no API to preflight or build
  // against, so the action is absent rather than disabled. Inert (false) in
  // server builds.
  const isStaticBundle = useIsStaticBundle();
  const showExport = Boolean(onExportStatic) && !isStaticBundle;

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="md"
      title={
        <Group gap="xs">
          <Icon icon="mdi:cog" width={20} />
          <Text fw={600}>Dashboard settings</Text>
        </Group>
      }
    >
      <Stack gap="md">
        <DashboardInfoBody dashboard={dashboard} active={opened} />

        {showExport && (
          <>
            <Divider label="Actions" labelPosition="left" my="xs" />
            <Stack gap="xs">
              {/* The button sizes to its label; only the caption spans the
                  drawer, so it stays readable instead of wrapping at button
                  width. */}
              <Group>
                <Tooltip label={OWNER_GATE_HINT} disabled={isOwner} withArrow>
                  <Button
                    leftSection={<Icon icon="mdi:export-variant" width={16} />}
                    color="violet"
                    variant="light"
                    size="sm"
                    onClick={onExportStatic}
                    disabled={!dashboardId || !isOwner}
                    data-testid="export-static-btn"
                  >
                    Export static
                  </Button>
                </Tooltip>
              </Group>
              <Text size="xs" c="dimmed">
                {isOwner
                  ? 'Builds a single self-contained HTML file of this dashboard that opens without a server.'
                  : OWNER_GATE_HINT}
              </Text>
            </Stack>
          </>
        )}
      </Stack>
    </Drawer>
  );
};

export default SettingsDrawer;
