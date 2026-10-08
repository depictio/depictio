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
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { Z_LAYERS, type DataVersionPins, type StoredMetadata } from 'depictio-react-core';

import { buildDataVersionOptions, LIVE, withPin } from './dataVersionChoice';
import { absDateTime } from './format';
import { useDatasetHistories } from './useDatasetHistories';

interface DatasetVersionPickerProps {
  metadata: StoredMetadata[] | undefined;
  pins: DataVersionPins;
  onPinsChange: (pins: DataVersionPins) => void;
}

/** Fetches every collection's history on mount. It lives in the settings'
 *  Data version section, whose modal (or drawer) unmounts it while closed, so
 *  closed settings cost nothing. */
const DatasetVersionPicker: React.FC<DatasetVersionPickerProps> = ({
  metadata,
  pins,
  onPinsChange,
}) => {
  const { histories, loading } = useDatasetHistories(metadata, true);

  if (loading && histories.length === 0) {
    return (
      <Group justify="center" py="sm" role="status" aria-label="Loading data versions">
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
        const isPinned = typeof pinned === 'number';
        const pinnedCommit = isPinned
          ? history.commits.find((c) => c.version === pinned)
          : undefined;
        const options = buildDataVersionOptions({
          commits: history.commits,
          currentVersion: history.currentVersion,
        });

        return (
          <Paper key={history.dcId} withBorder radius="md" p="sm">
            <Stack gap={6}>
              <Group justify="space-between" wrap="nowrap" gap="xs">
                <Text size="sm" fw={600} style={{ minWidth: 0 }} truncate>
                  {history.label}
                </Text>
                {/* Says "pinned" in words: the badge's colour alone would be
                    the only sign this collection is not on its latest data. */}
                {isPinned && (
                  <Badge
                    size="sm"
                    color="yellow"
                    variant="light"
                    leftSection={<Icon icon="mdi:pin" width={11} />}
                    style={{ flexShrink: 0 }}
                  >
                    Pinned v{pinned}
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
                    value={isPinned ? String(pinned) : LIVE}
                    onChange={(value) => onPinsChange(withPin(pins, history.dcId, value))}
                    // Rendered inside the Settings drawer or modal: the
                    // dropdown has to clear that layer, not open behind it.
                    comboboxProps={{ withinPortal: true, zIndex: Z_LAYERS.tooltip }}
                    allowDeselect={false}
                    searchable={options.length > 8}
                    aria-label={`Data version for ${history.label}`}
                  />
                  {pinnedCommit?.timestamp && (
                    <Text size="xs" c="dimmed">
                      written {absDateTime(pinnedCommit.timestamp)}
                      {pinnedCommit.by_email ? ` by ${pinnedCommit.by_email}` : ''}
                    </Text>
                  )}
                  {history.degraded && (
                    <Text size="xs" c="orange">
                      Partial history: the object store could not be reached.
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
