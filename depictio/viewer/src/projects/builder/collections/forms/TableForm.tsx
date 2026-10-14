/**
 * Table properties: the format (as the server lists them) and the separator
 * of a text table, how a csv/tsv is read, an optional description per column
 * (the columns come from the file preview), map coordinates, and for a
 * SpatialData store which of its elements the table reads.
 */
import React from 'react';
import { Autocomplete, Group, SegmentedControl, Stack, TagsInput, Text, TextInput } from '@mantine/core';

import { DEFAULT_CRS, SPATIALDATA_FORMAT, coordinatesIssue } from 'depictio-react-core';
import type {
  BuilderCapabilities,
  BuilderSpatialDataTableSource,
  BuilderStoreSummary,
  BuilderTableProps,
} from 'depictio-react-core';

import {
  ColumnField,
  ColumnsDescription,
  FoldSection,
  FormatFields,
  MONO,
  OptionsSection,
  ReaderOptionsFields,
} from './shared';

/** The table formats offered, and why SpatialData cannot be picked here. */
export function tableFormatChoices(
  capabilities: BuilderCapabilities,
  remote: boolean,
): { formats: string[]; disabled: Record<string, string> } {
  const disabled: Record<string, string> = {};
  if (remote) disabled[SPATIALDATA_FORMAT] = 'stores are read from local folders';
  return { formats: capabilities.table_formats, disabled };
}

const SpatialDataFields: React.FC<{
  source: BuilderSpatialDataTableSource;
  store: BuilderStoreSummary | null;
  onChange: (source: BuilderSpatialDataTableSource) => void;
}> = ({ source, store, onChange }) => (
  <Stack gap="xs" data-testid="builder-props-spatialdata">
    <Text size="xs" c="dimmed">
      A table read from a SpatialData store: the AnnData table, the image it sits on, and how its
      coordinates are found.
    </Text>
    <Group grow align="flex-start">
      <Autocomplete
        label="Table element"
        description="Blank: tables/table"
        placeholder="tables/table"
        data={store?.tables ?? []}
        value={source.table ?? ''}
        onChange={(table) => onChange({ ...source, table })}
        styles={MONO}
        data-testid="builder-props-spatialdata-table"
      />
      <Autocomplete
        label="Image element"
        description="Optional: the image the spots sit on"
        placeholder="images/..."
        data={store?.images ?? []}
        value={source.image ?? ''}
        onChange={(image) => onChange({ ...source, image })}
        styles={MONO}
        data-testid="builder-props-spatialdata-image"
      />
    </Group>
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        Coordinates
      </Text>
      <SegmentedControl
        size="xs"
        value={source.coordinates ?? 'auto'}
        data={[
          { value: 'auto', label: 'Automatic' },
          { value: 'obsm', label: 'obsm (spatial)' },
          { value: 'region', label: 'Region shapes' },
        ]}
        onChange={(v) => onChange({ ...source, coordinates: v as BuilderSpatialDataTableSource['coordinates'] })}
      />
    </Stack>
    <Group grow align="flex-start">
      <TagsInput
        label="Genes"
        description="Optional: genes to read as columns (Enter to add)"
        value={source.genes ?? []}
        onChange={(genes) => onChange({ ...source, genes })}
      />
      <TextInput
        label="Layer"
        description="Optional: the expression layer (blank: X)"
        value={source.layer ?? ''}
        onChange={(e) => onChange({ ...source, layer: e.currentTarget.value })}
        styles={MONO}
      />
    </Group>
  </Stack>
);

export const TableForm: React.FC<{
  props: BuilderTableProps;
  onChange: (props: BuilderTableProps) => void;
  columns: string[];
  capabilities: BuilderCapabilities;
  remote: boolean;
  /** What `/suggest` read of the picked store, if one is picked. */
  store: BuilderStoreSummary | null;
}> = ({ props, onChange, columns, capabilities, remote, store }) => {
  const spatial = props.format === SPATIALDATA_FORMAT;
  const { formats, disabled } = tableFormatChoices(capabilities, remote);
  const coordinates = coordinatesIssue(props);
  return (
    <Stack gap="xs">
      <FormatFields
        format={props.format}
        separator={props.separator}
        formats={formats}
        disabled={disabled}
        onChange={(patch) => {
          const next: BuilderTableProps = { ...props, ...patch };
          if (patch.format === SPATIALDATA_FORMAT && !next.spatialdata) next.spatialdata = {};
          onChange(next);
        }}
      />
      {spatial && (
        <SpatialDataFields
          source={props.spatialdata ?? {}}
          store={store}
          onChange={(spatialdata) => onChange({ ...props, spatialdata })}
        />
      )}
      <OptionsSection>
        {!spatial && (
          <>
            <ReaderOptionsFields
              format={props.format}
              reader={props.reader}
              allowed={capabilities.reader_options}
              onChange={(reader) => onChange({ ...props, reader })}
            />
            <FoldSection
              label="Show rows on a map"
              description="needs a latitude and a longitude column"
              initiallyOpen={Boolean(props.lat_column || props.lon_column)}
              testId="builder-props-coordinates"
            >
              <Text size="xs" c="dimmed">
                Only for a table where each row is a place. Name the column holding its latitude and the one
                holding its longitude, and dashboards can plot the rows on a map. Leave both empty otherwise.
              </Text>
              <Group grow align="flex-start">
                <ColumnField
                  label="Latitude column"
                  value={props.lat_column}
                  columns={columns}
                  error={coordinates && !props.lat_column ? 'Pick both, or neither' : undefined}
                  testId="builder-props-lat-column"
                  onChange={(lat_column) => onChange({ ...props, lat_column })}
                />
                <ColumnField
                  label="Longitude column"
                  value={props.lon_column}
                  columns={columns}
                  error={coordinates && !props.lon_column ? 'Pick both, or neither' : coordinates ?? undefined}
                  testId="builder-props-lon-column"
                  onChange={(lon_column) => onChange({ ...props, lon_column })}
                />
              </Group>
              <TextInput
                label="Coordinate system"
                description={`Blank: ${DEFAULT_CRS} (ordinary latitude and longitude in degrees)`}
                placeholder={DEFAULT_CRS}
                value={props.crs ?? ''}
                onChange={(e) => onChange({ ...props, crs: e.currentTarget.value })}
                disabled={!props.lat_column && !props.lon_column}
                styles={MONO}
              />
            </FoldSection>
          </>
        )}
        <ColumnsDescription
          columns={columns}
          value={props.columns_description}
          onChange={(columns_description) => onChange({ ...props, columns_description })}
        />
      </OptionsSection>
    </Stack>
  );
};
