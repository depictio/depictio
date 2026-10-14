/**
 * Bioimage properties: the store format (as the server lists them), the
 * NGFF version it must be, whether the images are uploaded or only
 * referenced, and which image of a store is read (required for SpatialData).
 */
import React from 'react';
import { Autocomplete, Group, Select, Stack, Switch, Text } from '@mantine/core';

import { BUILDER_BIOIMAGE_FORMATS } from 'depictio-react-core';
import type {
  BuilderBioimageFormat,
  BuilderBioimageProps,
  BuilderCapabilities,
  BuilderStoreSummary,
} from 'depictio-react-core';

import { MONO } from './shared';

const FORMAT_LABELS: Record<BuilderBioimageFormat, string> = {
  'ome-zarr': 'OME-Zarr',
  'ome-tiff': 'OME-TIFF',
  spatialdata: 'SpatialData',
};

export const BioimageForm: React.FC<{
  props: BuilderBioimageProps;
  onChange: (props: BuilderBioimageProps) => void;
  capabilities: BuilderCapabilities;
  /** What `/suggest` read of the picked store, if one is picked. */
  store: BuilderStoreSummary | null;
}> = ({ props, onChange, capabilities, store }) => {
  const offered = capabilities.bioimage?.formats ?? [...BUILDER_BIOIMAGE_FORMATS];
  const formats = BUILDER_BIOIMAGE_FORMATS.filter((f) => offered.includes(f) || f === props.format);
  const zarr = props.format !== 'ome-tiff';
  const spatial = props.format === 'spatialdata';
  const missingImage = spatial && !props.image_path?.trim();
  return (
    <Stack gap="xs">
      <Group grow align="flex-start">
        <Select
          label="Format"
          value={props.format}
          data={formats.map((f) => ({ value: f, label: FORMAT_LABELS[f] }))}
          allowDeselect={false}
          onChange={(v) => v && onChange({ ...props, format: v as BuilderBioimageFormat })}
          data-testid="builder-props-bioimage-format"
        />
        <Select
          label="NGFF version"
          description="The OME-Zarr version the stores must be"
          value={props.ngff_version ?? 'any'}
          data={[
            { value: 'any', label: 'Any' },
            { value: '0.4', label: '0.4' },
            { value: '0.5', label: '0.5' },
          ]}
          allowDeselect={false}
          disabled={!zarr}
          onChange={(v) => onChange({ ...props, ngff_version: v === '0.4' || v === '0.5' ? v : null })}
        />
      </Group>
      {zarr && (
        <Autocomplete
          label="Image"
          description={
            spatial ? "The store's image to show (images/<name>)" : 'Optional: one image of a multi-image store'
          }
          placeholder="images/..."
          data={store?.images ?? []}
          value={props.image_path ?? ''}
          onChange={(image_path) => onChange({ ...props, image_path })}
          error={missingImage ? 'Required for a SpatialData store' : undefined}
          styles={MONO}
          data-testid="builder-props-bioimage-image"
        />
      )}
      <Switch
        label="Upload the images"
        description={
          props.upload === false
            ? 'Reference only: the server must see the same path'
            : 'Copied to the server’s storage at ingest'
        }
        checked={props.upload !== false}
        onChange={(e) => onChange({ ...props, upload: e.currentTarget.checked })}
        data-testid="builder-props-bioimage-upload"
      />
      {store && (
        <Text size="xs" c="dimmed">
          The picked store is {FORMAT_LABELS[store.format]}
          {store.ngff_version ? `, NGFF ${store.ngff_version}` : ''}.
        </Text>
      )}
    </Stack>
  );
};
