/**
 * The unmissable "this is not current data" banner.
 *
 * A dashboard showing historical data looks exactly like one showing current
 * data — same layout, same components, plausible numbers. That is the whole
 * hazard, and this banner is the only thing standing between a user and
 * quoting last month's figures as today's. It is deliberately loud, always at
 * the top, and always offers one click back to the present.
 *
 * It names collections rather than generalising: which ones are on past data,
 * which stay on their latest data, and which have no data version at all, as
 * the server reports them (`dataVersionStatus.ts`). A banner that said "every
 * value" while a MultiQC tile or an unstamped collection showed today's data
 * would be the very mix-up it exists to prevent.
 */

import React from 'react';
import { Alert, Anchor, Badge, Group, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DataVersionCollectionStatus } from 'depictio-react-core';

import {
  collectionLabel,
  currentDataOnlyNote,
  describeDataVersionStatus,
  type PinnedLabel,
} from './dataVersionStatus';

interface DataVersionBannerProps {
  /** Set when the pins came from "as of" a stored dashboard version. */
  asOfLabel?: string | null;
  /** Per-collection status from the server; null while it loads or failed. */
  collections: DataVersionCollectionStatus[] | null;
  statusError?: string | null;
  /** The editor's own per-collection pins: what the banner can show before
   *  the status arrives. */
  pinned: PinnedLabel[];
  /** Tiles on this tab that never read a pin (MultiQC, JBrowse, advanced
   *  visualisations), each badged "Current data". */
  currentDataOnly?: number;
  onClear: () => void;
}

/** One badge per collection, keyed by id: two collections may share a tag. */
function statusBadge(status: DataVersionCollectionStatus) {
  const label = collectionLabel(status);
  if (status.status === 'pinned') {
    return (
      <Badge key={status.dc_id} size="sm" variant="outline" color="yellow">
        {typeof status.delta_version === 'number' ? `${label} v${status.delta_version}` : label}
      </Badge>
    );
  }
  return (
    <Badge
      key={status.dc_id}
      size="sm"
      variant="outline"
      color="gray"
      title={status.reason ?? undefined}
    >
      {status.status === 'live' ? `${label} latest` : `${label} not versioned`}
    </Badge>
  );
}

const DataVersionBanner: React.FC<DataVersionBannerProps> = ({
  asOfLabel,
  collections,
  statusError = null,
  pinned,
  currentDataOnly = 0,
  onClear,
}) => {
  if (pinned.length === 0 && !asOfLabel) return null;

  let detail: string;
  if (collections) detail = describeDataVersionStatus(collections);
  else if (statusError) detail = 'Could not check which data collections are on past data.';
  else detail = 'Checking which data collections are on past data…';
  const note = currentDataOnlyNote(currentDataOnly);

  return (
    <Alert
      color="yellow"
      variant="light"
      radius={0}
      icon={<Icon icon="mdi:database-clock" width={20} />}
      role="status"
      aria-label="Historical data in use"
      data-testid="data-version-banner"
    >
      <Group gap="xs" wrap="wrap">
        <Text size="sm" fw={600}>
          {asOfLabel ? `Showing data as of ${asOfLabel}` : 'Showing historical data'}
        </Text>
        <Badge size="sm" variant="light" color="yellow">
          Not current
        </Badge>
        {collections
          ? collections.map(statusBadge)
          : pinned.map((p) => (
              <Badge
                key={p.dcId}
                size="sm"
                variant="outline"
                color={p.version === null ? 'gray' : 'yellow'}
              >
                {p.version === null ? `${p.label} latest` : `${p.label} v${p.version}`}
              </Badge>
            ))}
        <Anchor component="button" type="button" size="sm" fw={500} onClick={onClear}>
          Back to current data
        </Anchor>
      </Group>
      <Text size="xs" c="dimmed" mt={4} data-testid="data-version-banner-detail">
        {note ? `${detail} ${note}` : detail}
      </Text>
    </Alert>
  );
};

export default DataVersionBanner;
