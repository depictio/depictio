/**
 * "You are looking at an old version" bar.
 *
 * Sticky and full-bleed rather than an inline block, so it does not disturb
 * the viewer's `height: 100%` grid math, and deliberately **not dismissible**:
 * it changes the meaning of everything below it, so dismissing it would leave
 * a dashboard that silently misrepresents itself.
 */

import React from 'react';
import { Alert, Button, Group, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DashboardPreviewInfo } from 'depictio-react-core';

import { absTime, relTime } from './format';

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
    style={{ position: 'sticky', top: 0, zIndex: 200 }}
    data-testid="version-banner"
  >
    <Group justify="space-between" align="center" wrap="nowrap" gap="sm">
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
        {preview.pinned && (
          <Icon icon="mdi:pin" width={15} aria-label="pinned" />
        )}
        <Text size="xs" style={{ opacity: 0.85 }} visibleFrom="sm">
          — read-only, and the data shown is current
        </Text>
      </Group>

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
