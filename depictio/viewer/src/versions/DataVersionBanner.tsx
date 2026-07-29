/**
 * The unmissable "this is not current data" banner.
 *
 * A dashboard showing historical data looks exactly like one showing current
 * data — same layout, same components, plausible numbers. That is the whole
 * hazard, and this banner is the only thing standing between a user and
 * quoting last month's figures as today's. It is deliberately loud, always at
 * the top, and always offers one click back to the present.
 */

import React from 'react';
import { Alert, Anchor, Badge, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

interface DataVersionBannerProps {
  /** Per-collection pins currently applied, labelled for display. */
  pinned: Array<{ label: string; version: number }>;
  /** Set when the pin came from "as of" a stored dashboard version. */
  asOfLabel?: string | null;
  /** Collections the chosen version recorded no data version for. They are
   *  showing *current* data while everything around them shows the past —
   *  the one state in this feature that is genuinely mixed, so it has to be
   *  said out loud rather than left to look uniform. */
  unresolved?: string[];
  onClear: () => void;
}

const DataVersionBanner: React.FC<DataVersionBannerProps> = ({
  pinned,
  asOfLabel,
  unresolved = [],
  onClear,
}) => {
  if (pinned.length === 0 && !asOfLabel) return null;

  return (
    <Alert
      color="yellow"
      variant="light"
      radius={0}
      icon={<Icon icon="mdi:database-clock" width={20} />}
      data-testid="data-version-banner"
    >
      <Group gap="xs" wrap="wrap">
        <Text size="sm" fw={600}>
          {asOfLabel
            ? `Showing data as of ${asOfLabel}`
            : 'Showing historical data'}
        </Text>
        <Badge size="sm" variant="light" color="yellow">
          Not current
        </Badge>
        {pinned.map((p) => (
          <Badge key={p.label} size="sm" variant="outline" color="yellow">
            {p.label} v{p.version}
          </Badge>
        ))}
        <Anchor component="button" type="button" size="sm" fw={500} onClick={onClear}>
          Back to current data
        </Anchor>
      </Group>
      <Text size="xs" c="dimmed" mt={4}>
        {unresolved.length === 0
          ? 'Every value on this dashboard is computed from the pinned dataset version, not from the latest ingestion.'
          : `Values are computed from the pinned dataset version, except ${unresolved.length} collection${unresolved.length === 1 ? '' : 's'} with no recorded version (${unresolved.join(', ')}), which still read current data.`}
      </Text>
    </Alert>
  );
};

export default DataVersionBanner;
