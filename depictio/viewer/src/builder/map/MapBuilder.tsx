/**
 * Map builder. Mirrors design_map() in
 * depictio/dash/modules/map_component/design_ui.py — Plotly Express
 * scatter_map / density_map / choropleth_map with lat/lon/color/size pickers,
 * hover columns, map style, opacity, and cross-filter selection toggle.
 */
import React, { useEffect, useState } from 'react';
import {
  MultiSelect,
  SegmentedControl,
  Select,
  Slider,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { fetchDataCollectionConfig } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import ColumnSelect from '../shared/ColumnSelect';
import CrossFilterSection from '../shared/CrossFilterSection';
import DesignShell from '../shared/DesignShell';
import { BuilderSection, BuilderSections, Field } from '../shared/BuilderSections';
import PlacementSection from '../shared/PlacementSection';
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

const PLACEMENTS = [
  { value: 'grid', label: 'In grid' },
  { value: 'floating', label: 'Floating panel' },
];

const FLOATING_INITIAL_STATES = [
  { value: 'compact', label: 'Compact card' },
  { value: 'expanded', label: 'Expanded card' },
  { value: 'docked', label: 'Docked in the filter panel' },
  { value: 'hidden', label: 'Hidden' },
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
    lat_column?: string;
    lon_column?: string;
    color_column?: string;
    size_column?: string;
    hover_columns?: string[];
    map_style?: string;
    opacity?: number;
    selection_enabled?: boolean;
    selection_column?: string;
    placement?: string;
    floating_initial_state?: string;
  };
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const cols = useBuilderStore((s) => s.cols);
  const dcId = useBuilderStore((s) => s.dcId);

  // When the picked DC has lat_column / lon_column hints (because it was
  // created via the Coordinates tab in CreateDataCollectionModal), pre-fill
  // the Latitude / Longitude pickers — only if the user hasn't already chosen
  // values. Mirrors how the MultiQC builder reads DC-level config defaults.
  const [autofilledFromDc, setAutofilledFromDc] = useState(false);
  useEffect(() => {
    setAutofilledFromDc(false);
    if (!dcId) return;
    let cancelled = false;
    fetchDataCollectionConfig(dcId).then((cfg) => {
      if (cancelled) return;
      const props = cfg?.dc_specific_properties as
        | Record<string, unknown>
        | undefined;
      const latHint = props?.lat_column as string | undefined;
      const lonHint = props?.lon_column as string | undefined;
      // Re-read fresh config from the store so a column the user picked while
      // this fetch was in flight isn't clobbered by the stale closure value.
      const current = useBuilderStore.getState().config as {
        lat_column?: string;
        lon_column?: string;
      };
      const updates: { lat_column?: string; lon_column?: string } = {};
      if (latHint && !current.lat_column) updates.lat_column = latHint;
      if (lonHint && !current.lon_column) updates.lon_column = lonHint;
      if (Object.keys(updates).length > 0) {
        patchConfig(updates);
        setAutofilledFromDc(true);
      }
    });
    return () => {
      cancelled = true;
    };
    // Intentionally key only on `dcId` so we don't loop after patching `config`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dcId]);

  const mapType = config.map_type ?? 'scatter_map';
  const mapStyle = config.map_style ?? 'carto-positron';
  const opacity = typeof config.opacity === 'number' ? config.opacity : 0.8;
  const selectionEnabled = !!config.selection_enabled;
  const placement = config.placement ?? 'grid';

  const allColumnOptions = cols.map((c) => ({
    value: c.name,
    label: `${c.name} (${c.type})`,
  }));

  const form = (
    <BuilderSections builder="map" required={['coordinates']}>
      <BuilderSection
        value="coordinates"
        icon="mdi:map-marker-radius"
        title="Map & coordinates"
        subtitle="The kind of map and the latitude / longitude columns"
      >
        <Stack gap="md">
          <Select
            label="Map type"
            data={MAP_TYPES}
            value={mapType}
            onChange={(val) => patchConfig({ map_type: val })}
            allowDeselect={false}
          />

          <ColumnSelect
            label="Latitude Column"
            value={config.lat_column}
            onChange={(name) => patchConfig({ lat_column: name })}
            numericOnly
            required
          />

          <ColumnSelect
            label="Longitude Column"
            value={config.lon_column}
            onChange={(name) => patchConfig({ lon_column: name })}
            numericOnly
            required
          />

          {autofilledFromDc && (
            <Text size="xs" c="dimmed" mt={-8}>
              Pre-filled from data collection metadata
            </Text>
          )}
        </Stack>
      </BuilderSection>

      <BuilderSection
        value="marks"
        icon="mdi:map-marker-multiple-outline"
        title="Marks"
        subtitle="Colour, size and the hover tooltip's columns"
      >
        <Stack gap="md">
          <ColumnSelect
            label="Color Column"
            value={config.color_column}
            onChange={(name) => patchConfig({ color_column: name })}
            clearable
          />

          {mapType === 'scatter_map' && (
            <ColumnSelect
              label="Size Column"
              value={config.size_column}
              onChange={(name) => patchConfig({ size_column: name })}
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
        </Stack>
      </BuilderSection>

      <BuilderSection
        value="appearance"
        icon="mdi:palette-outline"
        title="Appearance"
        subtitle="Title, base map style and marker opacity"
      >
        <Stack gap="md">
          <TextInput
            label="Title"
            value={config.title ?? ''}
            onChange={(e) => patchConfig({ title: e.currentTarget.value })}
          />

          <Field label="Map Style" description="The base map drawn under the marks.">
            <SegmentedControl
              data={MAP_STYLES}
              value={mapStyle}
              onChange={(val) => patchConfig({ map_style: val })}
              fullWidth
            />
          </Field>

          <Field label="Opacity" description="How opaque the marks are over the base map.">
            <Slider
              min={0.1}
              max={1.0}
              step={0.1}
              value={opacity}
              onChange={(val) => patchConfig({ opacity: val })}
              marks={OPACITY_MARKS}
              mb="md"
            />
          </Field>
        </Stack>
      </BuilderSection>

      <BuilderSection
        value="display"
        icon="mdi:dock-window"
        title="Display"
        subtitle="A tile in the grid, or a floating panel on every tab"
      >
        <Field
          label="Shown as"
          description={
            placement === 'floating'
              ? 'The map leaves the grid and becomes a panel reachable from every tab of this dashboard, through the map button in the header. Viewers can float it, dock it in the filter panel or hide it.'
              : 'The map is a normal dashboard tile on this tab.'
          }
        >
          <SegmentedControl
            data={PLACEMENTS}
            value={placement}
            onChange={(val) => patchConfig({ placement: val })}
            fullWidth
          />
          {placement === 'floating' && (
            <Select
              label="Initial state"
              description="What viewers see on their first visit. Their own choice is remembered afterwards."
              data={FLOATING_INITIAL_STATES}
              value={config.floating_initial_state ?? 'compact'}
              onChange={(val) => val && patchConfig({ floating_initial_state: val })}
              allowDeselect={false}
            />
          )}
        </Field>
      </BuilderSection>

      <CrossFilterSection
        enabled={selectionEnabled}
        onEnabledChange={(checked) =>
          patchConfig({ selection_enabled: checked })
        }
        column={config.selection_column}
        onColumnChange={(name) => patchConfig({ selection_column: name })}
        columnDescription="Column to extract from selected points"
      />

      <PlacementSection />
    </BuilderSections>
  );

  return <DesignShell formSlot={form} previewSlot={<MapPreview />} />;
};

export default MapBuilder;
