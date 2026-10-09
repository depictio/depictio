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
 * components come from the version (the server overlays them and reads each
 * definition from it). Data is a per-collection matter: the server reports
 * which collections are on the version's data, which on their latest data and
 * which recorded no data version (`dataVersionStatus.ts`), and the bar names
 * them rather than claiming all of it.
 *
 * Read-only, like the rest of the viewer: restoring is a write, and lives in
 * the editor's History. Someone who could restore gets a way there instead.
 */

import React from 'react';
import { Alert, Button, Group, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { Z_LAYERS } from 'depictio-react-core';
import type { DashboardPreviewInfo } from 'depictio-react-core';

import { currentDataOnlyNote, describeDataVersionStatus } from './dataVersionStatus';
import { absTime, dataCoverage, relTime } from './format';
import { exitPreview } from './preview';
import { useDataVersionStatus } from './useDataVersionStatus';

interface VersionPreviewBannerProps {
  preview: DashboardPreviewInfo;
  /** The tab being previewed, to ask which of its collections are pinned. */
  dashboardId: string | null;
  /** The editor of this tab, for someone who can edit it; restoring a
   *  version is done from its History. Null hides the link. */
  editHref?: string | null;
  /** Tiles on this tab that never read a pin, each badged "Current data". */
  currentDataOnly?: number;
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

/** What can still be said without the per-collection status: counts only. */
function coverageFallback(kinds: Record<string, number> | null | undefined): string {
  if (!kinds) return 'Could not check which data collections it pinned.';
  const { pinned, total } = dataCoverage(kinds);
  if (total === 0) return 'It recorded no data collection.';
  return `${pinned} of ${total} data collection${total === 1 ? '' : 's'} recorded a data version.`;
}

const VersionPreviewBanner: React.FC<VersionPreviewBannerProps> = ({
  preview,
  dashboardId,
  editHref = null,
  currentDataOnly = 0,
}) => {
  const { collections, error } = useDataVersionStatus(dashboardId, {
    as_of_version: preview.version_id,
  });

  let data: string;
  if (collections) data = describeDataVersionStatus(collections);
  else if (error) data = coverageFallback(preview.data_version_kinds);
  else data = 'Checking which data collections it pinned…';
  const note = currentDataOnlyNote(currentDataOnly);

  return (
    <Alert
      color="yellow"
      variant="filled"
      radius={0}
      icon={<Icon icon="mdi:history" width={18} />}
      role="status"
      aria-label="Past version preview"
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
            {preview.pinned && <Icon icon="mdi:pin" width={15} role="img" aria-label="Pinned version" />}
            <Text size="xs" style={{ opacity: 0.85 }} visibleFrom="sm">
              · read-only
            </Text>
          </Group>
          <Text size="xs" style={{ opacity: 0.85 }} data-testid="version-banner-data">
            {['Layout and components are from this version.', data, note]
              .filter(Boolean)
              .join(' ')}
          </Text>
        </Stack>

        <Group gap={8} wrap="nowrap">
          {editHref && (
            <Tooltip label="Restore this version from the editor's History" withArrow withinPortal>
              <Button
                component="a"
                href={editHref}
                size="xs"
                variant="white"
                color="yellow"
                leftSection={<Icon icon="mdi:pencil" width={14} />}
                data-testid="version-banner-open-editor"
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
};

export default VersionPreviewBanner;
