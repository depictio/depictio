/**
 * "You are looking at an old version" bar.
 *
 * Sticky and full-bleed rather than an inline block, so it does not disturb
 * the viewer's `height: 100%` grid math, and deliberately **not dismissible**:
 * it changes the meaning of everything below it, so dismissing it would leave
 * a dashboard that silently misrepresents itself.
 *
 * Read-only, like the viewer it sits in: restoring a version is an edit, and
 * time-travel writes live in the editor's version history. An editor gets a
 * link there instead.
 */

import React from 'react';
import { Alert, Button, Group, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { Z_LAYERS, type DashboardPreviewInfo } from 'depictio-react-core';

import { absTime, relTime } from './format';

interface VersionPreviewBannerProps {
  preview: DashboardPreviewInfo;
  /** The dashboard's editor, for someone who may edit it. Omitted otherwise. */
  editHref?: string | null;
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

const VersionPreviewBanner: React.FC<VersionPreviewBannerProps> = ({ preview, editHref }) => (
  <Alert
    color="yellow"
    variant="filled"
    radius={0}
    icon={<Icon icon="mdi:history" width={18} />}
    style={{ position: 'sticky', top: 0, zIndex: Z_LAYERS.furniture }}
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
        {/* Only the dashboard document is overlaid: every chart is still
            rendered from today's component definition and today's data. */}
        <Text size="xs" style={{ opacity: 0.85 }} visibleFrom="sm">
          Read-only. The layout is from this version; charts and data are current.
        </Text>
      </Group>

      <Group gap={8} wrap="nowrap">
        {editHref && (
          <Tooltip label="Restore it from Version history in the editor" withArrow>
            <Button
              component="a"
              href={editHref}
              size="xs"
              variant="white"
              color="yellow"
              leftSection={<Icon icon="mdi:pencil" width={14} />}
              data-testid="version-banner-edit"
            >
              Open in editor
            </Button>
          </Tooltip>
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
