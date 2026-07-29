/**
 * "You are looking at an old version" bar.
 *
 * Sticky and full-bleed rather than an inline block, so it does not disturb
 * the viewer's `height: 100%` grid math, and deliberately **not dismissible**:
 * it changes the meaning of everything below it, so dismissing it would leave
 * a dashboard that silently misrepresents itself.
 */

import React from 'react';
import { Alert, Button, Group, SegmentedControl, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DashboardPreviewInfo } from 'depictio-react-core';

import { absTime, relTime } from './format';

/** Which data the components below the banner are reading. */
export type DataMode = 'authored' | 'current';

interface VersionPreviewBannerProps {
  preview: DashboardPreviewInfo;
  /** Shown only to someone who could actually carry the restore out. */
  canRestore?: boolean;
  onRestore?: () => void;
  /** Present only when this version pinned data that can still be read. */
  dataMode?: DataMode;
  onDataModeChange?: (mode: DataMode) => void;
}

/** Why "as authored" is unavailable, in one sentence, or null if it is.
 *
 *  A disabled control with no reason attached reads as a bug. Every branch here
 *  is a real state the backend reports, not a hypothetical. */
function authoredUnavailableReason(preview: DashboardPreviewInfo): string | null {
  const pinned = preview.data_versions ? Object.keys(preview.data_versions).length : 0;
  if (pinned > 0) return null;

  const warnings = preview.data_warnings ?? [];
  if (warnings.length > 0) {
    const reasons = new Set(warnings.map((w) => w.reason));
    if (reasons.has('vacuumed')) {
      return 'The data files for that version have been vacuumed and no longer exist.';
    }
    if (reasons.has('out_of_range')) {
      return 'That version references a commit this table no longer has.';
    }
    if (reasons.has('not_versioned')) {
      return 'These collections do not keep a commit history that can be replayed.';
    }
    return 'That version’s data could not be read from storage.';
  }
  return 'This version recorded no data provenance, so there is nothing to replay.';
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
  dataMode = 'current',
  onDataModeChange,
}) => {
  const unavailable = authoredUnavailableReason(preview);
  const degraded = (preview.data_warnings ?? []).length > 0;

  return (
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
          {/* The dashboard is always historical; only the data is a choice.
              Saying "the data shown is current" unconditionally was true before
              time travel existed and is a lie once the toggle is set. */}
          {dataMode === 'authored'
            ? '— read-only, showing the data this version was authored on'
            : '— read-only, and the data shown is current'}
        </Text>
      </Group>

      <Group gap={8} wrap="nowrap">
        {onDataModeChange && (
          <Tooltip
            label={
              unavailable ??
              (degraded
                ? 'Some collections could not be read at that version and fall back to current data.'
                : 'Choose whether the data under this version is the data it was authored on.')
            }
            withArrow
            withinPortal
            multiline
            w={260}
          >
            <Group gap={6} wrap="nowrap" data-testid="version-banner-data-mode">
              <Text size="xs" fw={600} visibleFrom="md">
                Data:
              </Text>
              <SegmentedControl
                size="xs"
                color="yellow"
                value={unavailable ? 'current' : dataMode}
                onChange={(value) => onDataModeChange(value as DataMode)}
                data={[
                  {
                    value: 'authored',
                    label: (
                      <Group gap={4} wrap="nowrap">
                        <span>As authored</span>
                        {degraded && !unavailable && (
                          <Icon icon="mdi:alert" width={12} aria-label="partial" />
                        )}
                      </Group>
                    ),
                    disabled: Boolean(unavailable),
                  },
                  { value: 'current', label: 'Current' },
                ]}
              />
            </Group>
          </Tooltip>
        )}
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
};

export default VersionPreviewBanner;
