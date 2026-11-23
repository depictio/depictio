/**
 * "This bundle shows a past version" bar, for a pinned export.
 *
 * The offline twin of the viewer's `VersionPreviewBanner`: a pinned export
 * ships only the version it was exported at (its data and its definitions),
 * and nothing on the page would otherwise say so. Everything it states comes
 * from `manifest.pinned_version`, since a bundle has no API to ask which
 * collections are pinned. Collections the version could not pin read current
 * data; they are listed under a collapsible detail rather than hidden.
 *
 * Not dismissible, for the same reason as the viewer's bar: the page renders
 * through the live components and is indistinguishable from today's state at
 * a glance.
 */

import React from 'react';
import { Alert, Anchor, Collapse, Group, List, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { Z_LAYERS } from 'depictio-react-core';
import type { PinnedVersion, ProjectSummary } from 'depictio-static-core';

import { formatDateTimeVerbose } from '../lib/datetime';

const REASON_TEXT: Record<string, string> = {
  not_in_version: 'added after this version',
  no_version_recorded: 'the version recorded no data version for it',
  not_versioned: 'not versioned',
};

export function pinnedVersionTitle(pinned: PinnedVersion): string {
  const name = pinned.label?.trim() || (pinned.seq != null ? `version v${pinned.seq}` : 'a saved version');
  const when = pinned.created_at ? formatDateTimeVerbose(pinned.created_at, '') : '';
  return when ? `Data from ${name} of ${when}` : `Data from ${name}`;
}

interface PinnedVersionBannerProps {
  pinned: PinnedVersion;
  /** The bundle's project summary, to name collections by tag. */
  project?: Pick<ProjectSummary, 'data_collections'> | null;
  /** Sticky over a full-page app; static in a report's flow. */
  sticky?: boolean;
}

const PinnedVersionBanner: React.FC<PinnedVersionBannerProps> = ({
  pinned,
  project,
  sticky = true,
}) => {
  const [open, setOpen] = React.useState(false);
  const tags = React.useMemo(
    () => new Map((project?.data_collections ?? []).map((dc) => [dc.id, dc.tag])),
    [project],
  );
  const unresolved = pinned.unresolved ?? [];
  return (
    <Alert
      color="yellow"
      variant="light"
      radius={0}
      icon={<Icon icon="mdi:history" width={18} />}
      style={sticky ? { position: 'sticky', top: 0, zIndex: Z_LAYERS.furniture } : undefined}
      data-testid="pinned-version-banner"
    >
      <Stack gap={4}>
        <Group gap="xs" wrap="wrap">
          <Text size="sm" fw={600}>
            {pinnedVersionTitle(pinned)}
          </Text>
          {unresolved.length > 0 && (
            <Anchor
              component="button"
              type="button"
              size="sm"
              onClick={() => setOpen((v) => !v)}
              data-testid="pinned-version-unresolved-toggle"
            >
              {unresolved.length} data collection{unresolved.length === 1 ? '' : 's'} on
              current data {open ? '▴' : '▾'}
            </Anchor>
          )}
        </Group>
        {unresolved.length > 0 && (
          <Collapse in={open}>
            <List size="sm" data-testid="pinned-version-unresolved">
              {unresolved.map((c) => (
                <List.Item key={c.dc_id}>
                  {tags.get(c.dc_id) ?? c.dc_id}: {REASON_TEXT[c.reason] ?? c.reason}
                </List.Item>
              ))}
            </List>
          </Collapse>
        )}
      </Stack>
    </Alert>
  );
};

export default PinnedVersionBanner;
