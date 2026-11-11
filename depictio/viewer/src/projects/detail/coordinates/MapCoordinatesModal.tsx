/**
 * Mark which columns of a table hold latitude and longitude, so the table is
 * offered as a Map source (DCTableCoordinatesConfig). Its own window, opened
 * from the table's page; the server checks the columns are numbers in range.
 */
import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Center,
  Group,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { setTableCoordinates, useBrandAccents } from 'depictio-react-core';

import CoordinatesMapPreview from '../CoordinatesMapPreview';
import { detectCoordinatesColumns } from '../extendedTableCategories';
import { GEO_ICON } from '../../dcTypeIcon';

interface DcLike {
  _id?: string;
  id?: string;
  data_collection_tag?: string;
  config?: { dc_specific_properties?: Record<string, unknown> };
}

const asColumn = (value: unknown): string | null =>
  typeof value === 'string' && value ? value : null;

const MapCoordinatesModal: React.FC<{
  opened: boolean;
  onClose: () => void;
  dc: DcLike;
  /** The table's user columns, in order. */
  columns: string[];
  /** Saved or removed: the page reloads the table. */
  onChanged: () => void;
}> = ({ opened, onClose, dc, columns, onChanged }) => {
  const accent = useBrandAccents();
  const dcId = (dc._id ?? dc.id) as string;
  const props = dc.config?.dc_specific_properties;
  const currentLat = asColumn(props?.lat_column);
  const currentLon = asColumn(props?.lon_column);
  const marked = !!currentLat && !!currentLon;

  const [lat, setLat] = useState<string | null>(null);
  const [lon, setLon] = useState<string | null>(null);
  const [busy, setBusy] = useState<'save' | 'remove' | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Each opening starts from the stored marking, else from a guess.
  useEffect(() => {
    if (!opened) return;
    const guess = marked ? null : detectCoordinatesColumns(columns);
    setLat(currentLat ?? guess?.latColumn ?? null);
    setLon(currentLon ?? guess?.lonColumn ?? null);
    setError(null);
    // Only on opening: the columns and the marking are read then.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  const pairReady = !!lat && !!lon && lat !== lon;
  const unchanged = lat === currentLat && lon === currentLon;

  const submit = async (kind: 'save' | 'remove') => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === 'save') await setTableCoordinates(dcId, lat, lon);
      else await setTableCoordinates(dcId, null, null);
      notifications.show({
        color: 'teal',
        title: kind === 'save' ? 'Map coordinates saved' : 'Map coordinates removed',
        message:
          kind === 'save'
            ? `${dc.data_collection_tag ?? 'This table'} can now feed a Map.`
            : `${dc.data_collection_tag ?? 'This table'} is a plain table again.`,
      });
      onChanged();
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const options = columns.map((c) => ({ value: c, label: c }));

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={null}
      withCloseButton
      size="lg"
      centered
      padding="xl"
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
      aria-label="Map coordinates"
      data-testid="table-coordinates-modal"
    >
      <Stack gap="md">
        <Stack gap={4} align="center">
          <Center>
            <Group gap="xs">
              <Icon icon={GEO_ICON} width={28} color={`var(--mantine-color-${accent.secondary}-6)`} />
              <Title order={2} c={accent.secondary} style={{ fontFamily: 'Virgil', fontWeight: 400 }}>
                Map coordinates
              </Title>
            </Group>
          </Center>
          <Text size="sm" c="dimmed" ta="center">
            Pick the columns that hold latitude and longitude (decimal degrees, WGS84) to place
            each row on a Map.
          </Text>
        </Stack>

        <SimpleGrid cols={2} spacing="sm">
          <Select
            label="Latitude"
            placeholder="Pick a column"
            data={options}
            value={lat}
            onChange={setLat}
            searchable
            clearable
            comboboxProps={{ withinPortal: true }}
            data-testid="table-coordinates-lat"
          />
          <Select
            label="Longitude"
            placeholder="Pick a column"
            data={options}
            value={lon}
            onChange={setLon}
            searchable
            clearable
            comboboxProps={{ withinPortal: true }}
            data-testid="table-coordinates-lon"
          />
        </SimpleGrid>

        <Box data-testid="table-coordinates-preview">
          {pairReady ? (
            <CoordinatesMapPreview
              dc={{ ...dc, config: { dc_specific_properties: { lat_column: lat, lon_column: lon } } }}
            />
          ) : (
            <Text size="sm" c="dimmed" ta="center" py="lg">
              {lat && lat === lon
                ? 'Latitude and longitude must be two different columns.'
                : 'Pick both columns to preview the points.'}
            </Text>
          )}
        </Box>

        {error && (
          <Alert
            color="red"
            variant="light"
            icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
            data-testid="table-coordinates-error"
          >
            {error}
          </Alert>
        )}

        <Group justify="space-between">
          <Box>
            {marked && (
              <Button
                variant="subtle"
                color="red"
                leftSection={<Icon icon="mdi:map-marker-off-outline" width={16} />}
                onClick={() => submit('remove')}
                loading={busy === 'remove'}
                disabled={busy !== null}
                data-testid="table-coordinates-remove"
              >
                Remove
              </Button>
            )}
          </Box>
          <Group gap="xs">
            <Button variant="default" onClick={onClose} disabled={busy !== null}>
              Cancel
            </Button>
            <Button
              color={accent.secondary}
              onClick={() => submit('save')}
              loading={busy === 'save'}
              disabled={!pairReady || unchanged || busy !== null}
              data-testid="table-coordinates-save"
            >
              Save
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
};

export default MapCoordinatesModal;
