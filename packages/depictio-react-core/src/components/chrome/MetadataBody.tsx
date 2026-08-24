import React from 'react';
import { Badge, Box, Code, Collapse, Divider, Group, Stack, Text, Tooltip, UnstyledButton, ActionIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';
import CatalogOrigin from './CatalogOrigin';

interface MetadataBodyProps {
  metadata: StoredMetadata;
}

// Per-type icon + label + accent, mirroring the builder's component grid so the
// inspector reads as the same visual system as the creation flow.
const TYPE_META: Record<string, { icon: string; label: string; color: string }> = {
  figure:       { icon: 'mdi:graph-box',                    label: 'Figure',       color: 'grape' },
  card:         { icon: 'formkit:number',                   label: 'Card',         color: 'teal' },
  interactive:  { icon: 'bx:slider-alt',                    label: 'Interactive',  color: 'lime' },
  table:        { icon: 'octicon:table-24',                 label: 'Table',        color: 'blue' },
  multiqc:      { icon: 'mdi:chart-line',                   label: 'MultiQC',      color: 'orange' },
  image:        { icon: 'mdi:image-area',                   label: 'Image',        color: 'pink' },
  map:          { icon: 'mdi:map-marker-multiple',          label: 'Map',          color: 'violet' },
  text:         { icon: 'mdi:text-box-edit',                label: 'Text',         color: 'pink' },
  advanced_viz: { icon: 'mdi:chart-scatter-plot-hexbin',    label: 'Advanced viz', color: 'grape' },
};

type Row = { label: string; value: string };

/** A human-readable, per-type summary of the component's configuration. */
function summaryRows(m: StoredMetadata): Row[] {
  const g = m as Record<string, unknown>;
  const s = (v: unknown): string =>
    v === null || v === undefined || v === '' ? '' : String(v);
  const rows: Row[] = [];
  const push = (label: string, value: unknown) => {
    const val = s(value);
    if (val) rows.push({ label, value: val });
  };

  switch (m.component_type) {
    case 'card':
      push('Column', g.column_name);
      push('Aggregation', g.aggregation);
      push('Layout', g.secondary_layout);
      break;
    case 'figure': {
      push('Mode', g.mode);
      push('Chart', g.visu_type);
      const dk = (g.dict_kwargs as Record<string, unknown>) || {};
      for (const key of ['x', 'y', 'color', 'size', 'facet_col', 'facet_row']) {
        push(key, dk[key]);
      }
      break;
    }
    case 'interactive':
      push('Control', g.interactive_component_type);
      push('Column', g.column_name);
      break;
    case 'table': {
      const cols = g.cols_json as Record<string, unknown> | undefined;
      if (cols) push('Columns', Object.keys(cols).length);
      if (g.row_selection_enabled) push('Row selection', g.row_selection_column);
      break;
    }
    case 'multiqc':
      push('Module', g.selected_module);
      push('Plot', g.selected_plot);
      push('Dataset', g.selected_dataset);
      break;
    case 'image':
      push('Image column', g.image_column);
      push('S3 folder', g.s3_base_folder);
      break;
    case 'map':
      push('Type', g.map_type);
      push('Lat', g.lat_column);
      push('Lon', g.lon_column);
      push('Color', g.color_column);
      break;
    case 'text':
      push('Alignment', g.alignment);
      push('Order', g.order);
      break;
    case 'advanced_viz': {
      push('Kind', g.viz_kind);
      const cfg = (g.config as Record<string, unknown>) || {};
      const roles = Object.entries(cfg)
        .filter(([k, v]) => k.endsWith('_col') && v)
        .map(([k, v]) => `${k.replace(/_col$/, '')}=${String(v)}`);
      if (roles.length) push('Roles', roles.join(', '));
      break;
    }
  }
  return rows;
}

const SectionTitle: React.FC<{ icon: string; children: React.ReactNode; color?: string }> = ({
  icon,
  children,
  color = 'dimmed',
}) => (
  <Group gap={6} mb={6} wrap="nowrap">
    <Icon icon={icon} width={13} color={`var(--mantine-color-${color === 'dimmed' ? 'gray-6' : `${color}-6`})`} />
    <Text size="xs" fw={700} c={color} tt="uppercase">
      {children}
    </Text>
  </Group>
);

const KeyValue: React.FC<{ label: string; children: React.ReactNode; mono?: boolean }> = ({
  label,
  children,
  mono,
}) => (
  <Group gap={8} wrap="nowrap" align="flex-start">
    <Text size="xs" c="dimmed" w={78} style={{ flexShrink: 0 }}>
      {label}
    </Text>
    {mono ? (
      <Code fz={11} style={{ wordBreak: 'break-all' }}>{children}</Code>
    ) : (
      <Text size="xs" style={{ lineHeight: 1.4, wordBreak: 'break-word' }}>
        {children}
      </Text>
    )}
  </Group>
);

/**
 * The component-metadata view, without the surface it is shown on.
 *
 * `MetadataPopover` renders this inside a popover; the inspector's Info tab
 * renders the same thing docked. Extracted rather than duplicated so the two
 * can't drift — which is exactly what happened to the filter panel before it
 * became one shared component.
 *
 * Read-only. Structured: component identity, a human-readable per-type config
 * summary, data source, a catalog-origin section (with the `use:` snippet)
 * when the component was added from the tools catalog, and the raw
 * stored_metadata tucked into a collapsible "Advanced" block.
 */
const MetadataBody: React.FC<MetadataBodyProps> = ({ metadata }) => {
  const [rawOpen, setRawOpen] = React.useState(false);
  const json = React.useMemo(() => JSON.stringify(metadata, null, 2), [metadata]);
  const rows = React.useMemo(() => summaryRows(metadata), [metadata]);
  const src = metadata.catalog_source;

  const type = TYPE_META[metadata.component_type] ?? {
    icon: 'mdi:puzzle',
    label: metadata.component_type,
    color: 'gray',
  };
  const title = (metadata.title as string) || '';

  return (
    <Stack gap="sm">
      {/* Identity header */}
      <Group gap="sm" wrap="nowrap" align="center">
        <Box
          style={{
            width: 34,
            height: 34,
            borderRadius: 8,
            background: `var(--mantine-color-${type.color}-light)`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <Icon icon={type.icon} width={20} color={`var(--mantine-color-${type.color}-6)`} />
        </Box>
        <Box style={{ minWidth: 0 }}>
          <Group gap={6} wrap="nowrap">
            <Text size="sm" fw={700} lineClamp={1}>
              {title || type.label}
            </Text>
            {src && (
              <Badge size="xs" color="violet" variant="light" radius="sm" tt="none">
                Catalog
              </Badge>
            )}
          </Group>
          <Text size="xs" c="dimmed">{type.label}</Text>
        </Box>
      </Group>

      {/* Config summary */}
      {rows.length > 0 && (
        <Box>
          <SectionTitle icon="mdi:tune-variant">Configuration</SectionTitle>
          <Stack gap={3}>
            {rows.map((r) => (
              <KeyValue key={r.label} label={r.label}>{r.value}</KeyValue>
            ))}
          </Stack>
        </Box>
      )}

      {/* Data source */}
      {(metadata.dc_id || metadata.wf_id) && (
        <Box>
          <SectionTitle icon="mdi:database-outline">Data source</SectionTitle>
          <Stack gap={3}>
            {metadata.wf_id && <KeyValue label="Workflow" mono>{metadata.wf_id}</KeyValue>}
            {metadata.dc_id && <KeyValue label="Collection" mono>{metadata.dc_id}</KeyValue>}
          </Stack>
        </Box>
      )}

      {/* Catalog origin */}
      {src && <CatalogOrigin source={src} />}

      <Divider my={2} />

      {/* Raw JSON (collapsible) */}
      <Box>
        <UnstyledButton onClick={() => setRawOpen((o) => !o)} w="100%">
          <Group gap={6} wrap="nowrap">
            <Icon
              icon={rawOpen ? 'mdi:chevron-down' : 'mdi:chevron-right'}
              width={14}
              color="var(--mantine-color-dimmed)"
            />
            <Text size="xs" fw={700} c="dimmed" tt="uppercase">
              Advanced · raw metadata
            </Text>
          </Group>
        </UnstyledButton>
        <Collapse in={rawOpen}>
          <Code block mt={6} style={{ fontSize: 11, lineHeight: 1.4 }}>
            {json}
          </Code>
        </Collapse>
      </Box>
    </Stack>
  );
};

export default MetadataBody;
