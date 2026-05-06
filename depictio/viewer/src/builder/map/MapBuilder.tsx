/**
 * Map builder. Mirrors design_map() in
 * depictio/dash/modules/map_component/design_ui.py — Plotly Express
 * scatter_map / density_map / choropleth_map with lat/lon/color/size pickers,
 * hover columns, map style, opacity, and cross-filter selection toggle.
 */
import React from 'react';
import {
  Group,
  MultiSelect,
  SegmentedControl,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useBuilderStore } from '../store/useBuilderStore';
import ColumnSelect from '../shared/ColumnSelect';
import DesignShell from '../shared/DesignShell';
import MapPreview from './MapPreview';

const MAP_TYPES = [
  { value: 'scatter_map', label: 'Scatter (markers)' },
  { value: 'density_map', label: 'Density / heat' },
  { value: 'choropleth_map', label: 'Choropleth' },
];

const MAP_STYLES = [
  { value: 'open-street-map', label: 'OpenStreetMap' },
  { value: 'carto-positron', label: 'Carto Light' },
  { value: 'carto-darkmatter', label: 'Carto Dark' },
];

const OPACITY_MARKS = [
  { value: 0.2, label: '0.2' },
  { value: 0.5, label: '0.5' },
  { value: 0.8, label: '0.8' },
  { value: 1.0, label: '1.0' },
];

const MapBuilder: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    map_type?: string;
    title?: string;
    lat?: string;
    lon?: string;
    color?: string;
    size?: string;
    hover_columns?: string[];
    map_style?: string;
    opacity?: number;
    selection_enabled?: boolean;
    selection_column?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const cols = useBuilderStore((s) => s.cols);

  const mapType = config.map_type ?? 'scatter_map';
  const mapStyle = config.map_style ?? 'carto-positron';
  const opacity = typeof config.opacity === 'number' ? config.opacity : 0.8;
  const selectionEnabled = !!config.selection_enabled;

  const allColumnOptions = cols.map((c) => ({
    value: c.name,
    label: `${c.name} (${c.type})`,
  }));

  const form = (
    <Stack gap="md">
      <Title order={6}>Map Configuration</Title>

      <Group grow>
        <Select
          label="Map type"
          data={MAP_TYPES}
          value={mapType}
          onChange={(val) => patchConfig({ map_type: val })}
          allowDeselect={false}
        />
        <TextInput
          label="Title"
          value={config.title ?? ''}
          onChange={(e) => patchConfig({ title: e.currentTarget.value })}
        />
      </Group>

      <ColumnSelect
        label="Latitude Column"
        value={config.lat}
        onChange={(name) => patchConfig({ lat: name })}
        numericOnly
        required
      />

      <ColumnSelect
        label="Longitude Column"
        value={config.lon}
        onChange={(name) => patchConfig({ lon: name })}
        numericOnly
        required
      />

      <ColumnSelect
        label="Color Column"
        value={config.color}
        onChange={(name) => patchConfig({ color: name })}
        clearable
      />

      {mapType === 'scatter_map' && (
        <ColumnSelect
          label="Size Column"
          value={config.size}
          onChange={(name) => patchConfig({ size: name })}
          numericOnly
          clearable
        />
      )}

      <MultiSelect
        label="Hover Columns"
        description="Columns to show on hover tooltip"
        data={allColumnOptions}
        value={config.hover_columns ?? []}
        onChange={(vals) => patchConfig({ hover_columns: vals })}
        searchable
        clearable
      />

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Map Style
        </Text>
        <SegmentedControl
          data={MAP_STYLES}
          value={mapStyle}
          onChange={(val) => patchConfig({ map_style: val })}
          fullWidth
        />
      </Stack>

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Opacity
        </Text>
        <Slider
          min={0.1}
          max={1.0}
          step={0.1}
          value={opacity}
          onChange={(val) => patchConfig({ opacity: val })}
          marks={OPACITY_MARKS}
        />
      </Stack>

      <Switch
        label="Enable cross-filtering selection"
        checked={selectionEnabled}
        onChange={(e) =>
          patchConfig({ selection_enabled: e.currentTarget.checked })
        }
        mt="sm"
      />

      <ColumnSelect
        label="Selection Column"
        description="Column to extract from selected points"
        value={config.selection_column}
        onChange={(name) => patchConfig({ selection_column: name })}
        clearable
        disabled={!selectionEnabled}
      />
    </Stack>
  );

  return <DesignShell formSlot={form} previewSlot={<MapPreview />} />;
};

export default MapBuilder;
