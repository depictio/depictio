/**
 * Choosing which version of the *data* a dashboard is drawn from.
 *
 * Sits beside the dashboard version timeline because the two answer adjacent
 * questions — "what did this look like?" and "what was the data?" — and are
 * most useful together. Restoring a layout while silently redrawing it with
 * today's numbers is the thing this exists to prevent.
 *
 * Two ways in:
 *
 * **As of a dashboard version** — the one-click path. Reads that version's
 * recorded stamps, so every collection lands on the commit the dashboard was
 * authored against. This is what "show me this dashboard as it was" means.
 *
 * **Per collection** — the manual path, for questions the timeline can't
 * express: "the current layout, but against last month's data". Also the only
 * way to pin a dashboard that has no versions yet.
 *
 * Nothing here writes. Pinning is a *view* state, deliberately not persisted:
 * a dashboard silently stuck on old data is a trap, and the banner that shows
 * while pinned would otherwise be the only clue.
 */

import React from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Divider,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type { DataVersionPins, StoredMetadata } from 'depictio-react-core';

import { absDateTime } from './format';
import { describeCommit, useDatasetHistories } from './useDatasetHistories';

interface DatasetVersionPickerProps {
  metadata: StoredMetadata[] | undefined;
  /** Fetching is gated on this so a closed drawer costs nothing. */
  active: boolean;
  pins: DataVersionPins;
  onPinsChange: (pins: DataVersionPins) => void;
}

/** Sentinel for the "current data" option. Mantine's Select uses string
 *  values, and `null` would be indistinguishable from "nothing selected". */
const LIVE = '__live__';

const DatasetVersionPicker: React.FC<DatasetVersionPickerProps> = ({
  metadata,
  active,
  pins,
  onPinsChange,
}) => {
  const { histories, loading } = useDatasetHistories(metadata, active);

  const setPin = (dcId: string, value: string | null) => {
    const next = { ...pins };
    if (!value || value === LIVE) {
      delete next[dcId];
    } else {
      next[dcId] = Number(value);
    }
    onPinsChange(next);
  };

  if (!active) return null;

  if (loading && histories.length === 0) {
    return (
      <Group justify="center" py="sm">
        <Loader size="sm" />
      </Group>
    );
  }

  if (histories.length === 0) {
    return (
      <Alert color="gray" variant="light" icon={<Icon icon="mdi:database-off" width={16} />}>
        No data collections on this dashboard.
      </Alert>
    );
  }

  return (
    <Stack gap="sm">
      {histories.map((history) => {
        const pinned = pins[history.dcId];
        const options = [
          {
            value: LIVE,
            label:
              history.currentVersion !== null
                ? `Current data (v${history.currentVersion})`
                : 'Current data',
          },
          ...history.commits.map((commit) => {
            const detail = describeCommit(commit);
            return {
              value: String(commit.version),
              label: `v${commit.version}${detail ? ` — ${detail}` : ''}`,
            };
          }),
        ];

        return (
          <Paper key={history.dcId} withBorder radius="md" p="sm">
            <Stack gap={6}>
              <Group justify="space-between" wrap="nowrap" gap="xs">
                <Text size="sm" fw={600} style={{ minWidth: 0 }} truncate>
                  {history.label}
                </Text>
                {typeof pinned === 'number' && (
                  <Badge size="sm" color="yellow" variant="light" style={{ flexShrink: 0 }}>
                    v{pinned}
                  </Badge>
                )}
              </Group>

              {history.error ? (
                <Text size="xs" c="dimmed">
                  {history.error}
                </Text>
              ) : (
                <>
                  <Select
                    size="xs"
                    data={options}
                    value={typeof pinned === 'number' ? String(pinned) : LIVE}
                    onChange={(value) => setPin(history.dcId, value)}
                    comboboxProps={{ withinPortal: true }}
                    allowDeselect={false}
                    aria-label={`Data version for ${history.label}`}
                  />
                  {typeof pinned === 'number' &&
                    (() => {
                      const commit = history.commits.find((c) => c.version === pinned);
                      return commit?.timestamp ? (
                        <Text size="xs" c="dimmed">
                          written {absDateTime(commit.timestamp)}
                          {commit.by_email ? ` by ${commit.by_email}` : ''}
                        </Text>
                      ) : null;
                    })()}
                  {history.degraded && (
                    <Text size="xs" c="orange">
                      Partial history — the object store could not be reached.
                    </Text>
                  )}
                </>
              )}
            </Stack>
          </Paper>
        );
      })}
    </Stack>
  );
};

export default DatasetVersionPicker;

/** The "show everything as of this dashboard version" affordance, rendered on
 *  a timeline row. Separated so the timeline owns its own layout. */
export const AsOfVersionButton: React.FC<{
  active: boolean;
  onToggle: () => void;
  disabled?: boolean;
  /** Collections this version recorded no data provenance for. Shown as a
   *  caveat rather than silently serving them live. */
  unresolvedCount?: number;
}> = ({ active, onToggle, disabled, unresolvedCount = 0 }) => (
  <Box>
    <Button
      size="compact-xs"
      variant={active ? 'filled' : 'light'}
      color={active ? 'yellow' : 'gray'}
      leftSection={<Icon icon="mdi:database-clock-outline" width={13} />}
      onClick={onToggle}
      disabled={disabled}
    >
      {active ? 'Showing this data' : 'Use this data'}
    </Button>
    {active && unresolvedCount > 0 && (
      <>
        <Divider my={4} />
        <Text size="xs" c="dimmed">
          {unresolvedCount} collection{unresolvedCount === 1 ? '' : 's'} had no recorded
          version and {unresolvedCount === 1 ? 'is' : 'are'} showing current data.
        </Text>
      </>
    )}
  </Box>
);
