/**
 * "You are looking at a past version" bar.
 *
 * Sticky and full-bleed rather than an inline block, so it does not disturb
 * the viewer's `height: 100%` grid math, and deliberately **not dismissible**:
 * a preview renders through the same components as the live dashboard, which
 * is what makes it trustworthy and also what makes it indistinguishable at a
 * glance. Dismissing the bar would leave a dashboard that silently
 * misrepresents itself.
 *
 * It also states how much of the past is actually on screen. Layout and
 * components come from the version (the server overlays them), and the data
 * is pinned to what the version recorded (`previewDataRequest`), but only for
 * collections whose data version was stamped. Anything else reads current
 * data, and saying so is the difference between a reproducible view and one
 * that merely looks it.
 */

import React from 'react';
import { Alert, Button, Group, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { Z_LAYERS } from 'depictio-react-core';
import type { DashboardPreviewInfo } from 'depictio-react-core';

import { absTime, dataCoverage, relTime } from './format';

interface VersionPreviewBannerProps {
  preview: DashboardPreviewInfo;
  /** Shown only to someone who could actually carry the restore out. */
  canRestore?: boolean;
  onRestore?: () => void;
}

function describe(preview: DashboardPreviewInfo): string {
  const name = preview.label?.trim() || `version ${preview.seq}`;
  const when = preview.created_at ? relTime(preview.created_at) : null;
  const who = preview.author_email;

  const parts = [`Viewing ${name}`];
  if (when) parts.push(`saved ${when}`);
  if (who) parts.push(`by ${who}`);
  return parts.join(' · ');
}

/** Which parts of the screen belong to the version, and which are current. */
function describeData(kinds: Record<string, number> | null | undefined): string {
  // A server that sends no coverage: say what is certain and no more.
  if (!kinds) {
    return 'Layout and components are from this version; data is pinned wherever this version recorded it.';
  }
  const { pinned, total } = dataCoverage(kinds);
  if (total === 0) return 'Layout and components are from this version.';
  const plural = total === 1 ? '' : 's';
  if (pinned === total) {
    return `Layout, components and data are all from this version (${total} data collection${plural}).`;
  }
  if (pinned === 0) {
    return 'Layout and components are from this version; the data shown is current.';
  }
  return `Layout and components are from this version. ${pinned} of ${total} data collections are pinned to the data of the time; the rest read current data.`;
}

/** Drop the `version` param, keeping everything else about the URL intact. */
function exitPreview(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete('version');
  window.location.assign(url.toString());
}

const VersionPreviewBanner: React.FC<VersionPreviewBannerProps> = ({
  preview,
  canRestore = false,
  onRestore,
}) => (
  <Alert
    color="yellow"
    variant="filled"
    radius={0}
    icon={<Icon icon="mdi:history" width={18} />}
    style={{ position: 'sticky', top: 0, zIndex: Z_LAYERS.furniture }}
    data-testid="version-banner"
  >
    <Group justify="space-between" align="center" wrap="nowrap" gap="sm">
      <Stack gap={2} style={{ minWidth: 0 }}>
        <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
          <Tooltip
            label={preview.created_at ? absTime(preview.created_at) : 'unknown time'}
            withArrow
            withinPortal
          >
            <Text size="sm" fw={600} truncate>
              {describe(preview)}
            </Text>
          </Tooltip>
          {preview.pinned && <Icon icon="mdi:pin" width={15} aria-label="pinned" />}
          <Text size="xs" style={{ opacity: 0.85 }} visibleFrom="sm">
            · read-only
          </Text>
        </Group>
        <Text size="xs" style={{ opacity: 0.85 }} data-testid="version-banner-data">
          {describeData(preview.data_version_kinds)}
        </Text>
      </Stack>

      <Group gap={8} wrap="nowrap">
        {canRestore && onRestore && (
          <Button
            size="xs"
            variant="white"
            color="yellow"
            leftSection={<Icon icon="mdi:backup-restore" width={14} />}
            onClick={onRestore}
            data-testid="version-banner-restore"
          >
            Restore
          </Button>
        )}
        <Button
          size="xs"
          variant="white"
          color="yellow"
          onClick={exitPreview}
          data-testid="version-banner-exit"
        >
          Back to current
        </Button>
      </Group>
    </Group>
  </Alert>
);

export default VersionPreviewBanner;
