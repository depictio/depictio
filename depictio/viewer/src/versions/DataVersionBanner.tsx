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
  onClear: () => void;
}

const DataVersionBanner: React.FC<DataVersionBannerProps> = ({
  pinned,
  asOfLabel,
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
        Every value on this dashboard is computed from the pinned dataset
        version, not from the latest ingestion.
      </Text>
    </Alert>
  );
};

export default DataVersionBanner;
