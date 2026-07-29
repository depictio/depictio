/**
 * "You are looking at a past version" banner.
 *
 * A preview renders through the same components as the live dashboard, which
 * is what makes it trustworthy and also what makes it indistinguishable at a
 * glance. This is the only thing that tells them apart, so it is deliberately
 * unmissable rather than a subtle chip.
 *
 * It also states the one thing the snapshot cannot promise: components are
 * restored exactly, but the data underneath them is whatever the collections
 * hold right now. Claiming otherwise would be worse than saying nothing.
 */

import React from 'react';
import { Alert, Anchor, Badge, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DashboardVersionDetail } from 'depictio-react-core';

interface VersionPreviewBannerProps {
  version: DashboardVersionDetail;
  /** Where "back to current" goes — the same dashboard without `?version=`. */
  liveHref: string;
}

/** Human label for the timestamp, in the browser's locale. */
function when(raw?: string | null): string {
  if (!raw) return 'unknown time';
  // The API emits offset-less UTC stamps; the monitoring helpers exist for
  // this, but a banner should not pull in that module for one string.
  const iso = /[zZ]|[+-]\d{2}:\d{2}$/.test(raw) ? raw : `${raw}Z`;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? raw : d.toLocaleString();
}

const VersionPreviewBanner: React.FC<VersionPreviewBannerProps> = ({ version, liveHref }) => {
  const pinnedData = (version.data_collections || []).filter(
    (stamp) => stamp.version_kind !== 'none',
  ).length;
  const totalData = (version.data_collections || []).length;

  return (
    <Alert
      color="yellow"
      variant="light"
      radius={0}
      icon={<Icon icon="mdi:history" width={20} />}
      data-testid="version-preview-banner"
    >
      <Group gap="xs" wrap="wrap">
        <Text size="sm" fw={600}>
          Previewing {version.label?.trim() || `version v${version.seq}`}
        </Text>
        <Badge size="sm" variant="light" color="yellow">
          Read-only
        </Badge>
        <Text size="sm" c="dimmed">
          saved {when(version.created_at)}
          {version.author_email ? ` by ${version.author_email}` : ''}
        </Text>
        <Anchor href={liveHref} size="sm" fw={500}>
          Back to the current version
        </Anchor>
      </Group>
      <Text size="xs" c="dimmed" mt={4}>
        {totalData === 0
          ? 'Layout and components are from this version.'
          : pinnedData === totalData
            ? `Layout and components are from this version. All ${totalData} data collection${totalData === 1 ? '' : 's'} recorded a data version, but charts still read today's data.`
            : `Layout and components are from this version. Charts read today's data — ${pinnedData} of ${totalData} data collections recorded a data version at the time.`}
      </Text>
    </Alert>
  );
};

export default VersionPreviewBanner;
