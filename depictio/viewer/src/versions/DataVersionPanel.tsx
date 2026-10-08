/**
 * The settings' Data version section: which data the editor draws from.
 *
 * Two ways in, the coarse one first:
 *
 * **As of a dashboard version**: every collection goes back to the commit
 * that version recorded. Picking it closes the settings, because the point is
 * to look at the dashboard, and the banner above the grid then says what is on
 * screen and offers the way back.
 *
 * **One collection** (`DatasetVersionPicker`): pin a single collection to one
 * of its commits, for questions a dashboard version cannot express ("today's
 * layout against last month's data"). Applied as it is picked.
 *
 * Nothing here writes. Time travel is view state, never saved with the
 * dashboard, and gone on reload: a dashboard silently stuck on old data is a
 * trap.
 */

import React, { useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Group,
  Paper,
  Select,
  Stack,
  Text,
  ThemeIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  fetchDashboardVersion,
  Z_LAYERS,
  type DashboardVersionSummary,
  type DataVersionPins,
  type StoredMetadata,
} from 'depictio-react-core';

import { Field } from '../components/settings/SettingsSections';
import DatasetVersionPicker from './DatasetVersionPicker';
import { absDateTime, versionTitle } from './format';
import type { VersionHistory } from './useVersionHistory';

interface DataVersionPanelProps {
  /** Components of the tab being edited: where its collections come from. */
  metadata: StoredMetadata[] | undefined;
  /** The editor's shared timeline state, for the version select. */
  history: VersionHistory;
  /** Per-collection pins currently applied. */
  pins: DataVersionPins;
  /** The same pins, named for display. */
  pinnedLabels: Array<{ label: string; version: number }>;
  onPinsChange: (pins: DataVersionPins) => void;
  /** Stored version whose data stamps are driving the view, if any. */
  asOfVersionId: string | null;
  asOfLabel: string | null;
  /** `label` names the version in the banner; `unresolved` names the
   *  collections that version recorded no data version for, which keep
   *  showing current data and which the banner has to say so about. */
  onAsOfChange: (versionId: string, label: string, unresolved: string[]) => void;
  /** Back to current data everywhere. */
  onClear: () => void;
  /** Close the settings, once a version's data is chosen. */
  onDone: () => void;
}

/** Only a version that recorded a Delta commit can be travelled to; offering
 *  one that did not would promise a pin the backend has to decline. */
const hasPinnableData = (version: DashboardVersionSummary) =>
  (version.data_version_kinds?.delta ?? 0) > 0;

/** The status line's headline. */
function statusTitle(travelling: boolean, asOfLabel: string | null): string {
  if (!travelling) return 'Showing current data';
  if (asOfLabel) return `Showing data as of ${asOfLabel}`;
  return 'Showing historical data';
}

/** The collections a version recorded no Delta commit for. Fetched from the
 *  version's detail because the summary carries only counts. A failure is not
 *  worth blocking on: the server resolves the stamps either way, and the
 *  banner is merely less specific. */
async function unresolvedCollections(versionId: string): Promise<string[]> {
  try {
    const detail = await fetchDashboardVersion(versionId);
    return (detail.data_collections || [])
      .filter((stamp) => stamp.version_kind !== 'delta')
      .map((stamp) => stamp.data_collection_tag || String(stamp.dc_id));
  } catch {
    return [];
  }
}

const DataVersionPanel: React.FC<DataVersionPanelProps> = ({
  metadata,
  history,
  pins,
  pinnedLabels,
  onPinsChange,
  asOfVersionId,
  asOfLabel,
  onAsOfChange,
  onClear,
  onDone,
}) => {
  const { versions, hasMore } = history;
  const [selected, setSelected] = useState<string | null>(asOfVersionId);
  const [resolving, setResolving] = useState(false);

  const options = useMemo(
    () =>
      versions.filter(hasPinnableData).map((version) => ({
        value: version.version_id,
        label: [
          `${versionTitle(version)}${version.label ? ` (v${version.seq})` : ''}`,
          absDateTime(version.created_at),
        ].join(' · '),
      })),
    [versions],
  );

  const travelling = Boolean(asOfVersionId) || pinnedLabels.length > 0;

  const applyVersionData = async () => {
    const version = versions.find((v) => v.version_id === selected);
    if (!version) return;
    setResolving(true);
    const unresolved = await unresolvedCollections(version.version_id);
    setResolving(false);
    onAsOfChange(version.version_id, versionTitle(version), unresolved);
    onDone();
  };

  return (
    <Stack gap="lg" data-testid="data-version-panel">
      <Paper withBorder radius="md" p="sm" data-testid="data-version-status">
        <Group justify="space-between" wrap="wrap" gap="sm">
          <Group
            gap="sm"
            wrap="nowrap"
            align="flex-start"
            style={{ minWidth: 0, flex: '1 1 240px' }}
          >
            <ThemeIcon
              variant="light"
              color={travelling ? 'yellow' : 'teal'}
              size="md"
              radius="xl"
              aria-hidden
            >
              <Icon
                icon={travelling ? 'mdi:database-clock' : 'mdi:database-check'}
                width={14}
              />
            </ThemeIcon>
            <Stack gap={4} style={{ minWidth: 0 }}>
              <Text size="sm" fw={600}>
                {statusTitle(travelling, asOfLabel)}
              </Text>
              <Text size="xs" c="dimmed">
                {travelling
                  ? 'Only what you see here changes. Saving still writes the layout and ' +
                    'components, never the data.'
                  : 'Every collection shows its latest ingested data.'}
              </Text>
              {pinnedLabels.length > 0 && (
                <Group gap={4} wrap="wrap">
                  {pinnedLabels.map((pin) => (
                    <Badge key={pin.label} size="sm" variant="light" color="yellow">
                      {pin.label} v{pin.version}
                    </Badge>
                  ))}
                </Group>
              )}
            </Stack>
          </Group>
          {travelling && (
            <Button
              variant="light"
              size="xs"
              leftSection={<Icon icon="mdi:database-arrow-right-outline" width={14} />}
              onClick={() => {
                onClear();
                setSelected(null);
              }}
              data-testid="data-version-clear"
            >
              Back to current data
            </Button>
          )}
        </Group>
      </Paper>

      <Field
        label="As of a dashboard version"
        description={
          'Every collection goes back to the data that version was saved with. ' +
          'Only versions that recorded a data version are listed.'
        }
        testId="data-version-as-of"
      >
        <Group gap="xs" wrap="wrap" align="flex-start">
          <Select
            size="xs"
            aria-label="Dashboard version to take the data from"
            placeholder={options.length > 0 ? 'Pick a version' : 'No version recorded its data'}
            data={options}
            value={selected}
            onChange={setSelected}
            disabled={options.length === 0}
            searchable={options.length > 8}
            nothingFoundMessage="No version matches"
            comboboxProps={{ zIndex: Z_LAYERS.tooltip }}
            style={{ flex: '1 1 240px', minWidth: 0 }}
            data-testid="data-version-select"
          />
          <Button
            size="xs"
            leftSection={<Icon icon="mdi:database-clock-outline" width={14} />}
            onClick={() => void applyVersionData()}
            loading={resolving}
            disabled={!selected || selected === asOfVersionId}
            data-testid="data-version-use"
          >
            {selected && selected === asOfVersionId ? 'In use' : 'Use this data'}
          </Button>
        </Group>
        {hasMore && (
          <Text size="xs" c="dimmed">
            Only the {versions.length} newest versions are listed. Load older ones from History.
          </Text>
        )}
      </Field>

      <Field
        label="One collection"
        description={
          "Pin a single collection to one of its commits, such as today's layout against " +
          "last month's data. Applied as you pick, and wins over the version above for " +
          'that collection.'
        }
        testId="data-version-per-collection"
      >
        <DatasetVersionPicker metadata={metadata} pins={pins} onPinsChange={onPinsChange} />
      </Field>

      <Text size="xs" c="dimmed">
        Nothing here is saved: reloading the editor returns to current data.
      </Text>
    </Stack>
  );
};

export default DataVersionPanel;
