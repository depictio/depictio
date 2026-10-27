import React from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Code,
  Collapse,
  CopyButton,
  Divider,
  Group,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { StoredMetadata } from '../../api';
import { componentTypeVisual } from '../../componentTypeMeta';
import { useGenomeTracks } from '../jbrowse/genomeTracksStore';
import {
  buildGenomeTracksSummary,
  type GenomeSection,
  type SummaryItem,
} from '../jbrowse/genomeTracksSummary';
import CatalogOrigin from './CatalogOrigin';
import { useTileStats } from './tileStats';

interface MetadataBodyProps {
  metadata: StoredMetadata;
}

/** 10% of an accent, for the icon tile behind it. */
const tint = (hex: string) => `${hex}1A`;

type Row = { label: string; value: string; mono?: boolean };

/** A human-readable, per-type summary of the component's configuration. */
function summaryRows(m: StoredMetadata): Row[] {
  const g = m as Record<string, unknown>;
  const s = (v: unknown): string =>
    v === null || v === undefined || v === '' ? '' : String(v);
  const rows: Row[] = [];
  const push = (label: string, value: unknown, mono?: boolean) => {
    const val = s(value);
    if (val) rows.push({ label, value: val, mono });
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
    case 'jbrowse':
      push('Max tracks', g.max_tracks);
      push('Initial tracks', g.initial_tracks);
      push('Selection column', g.selection_column);
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
  // Outside the switch: a static row filter applies to any component type that
  // reads a data collection, and it is the one setting whose absence from this
  // panel is actively misleading, because a card or a dropdown restricted to a
  // subset looks exactly like one built on the whole collection. Mono because
  // the value is a Polars expression, e.g. col('bill_length_mm') > 50.
  push('Filter expr', g.filter_expr, true);
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

/** A URI on one truncated mono line: full text on hover, one-click copy. */
const UriLine: React.FC<{ value: string }> = ({ value }) => (
  <Group gap={4} wrap="nowrap" style={{ minWidth: 0 }}>
    <Tooltip label={value} multiline maw={420} withArrow openDelay={300} style={{ wordBreak: 'break-all' }}>
      <Code
        fz={11}
        style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}
      >
        {value}
      </Code>
    </Tooltip>
    <CopyButton value={value} timeout={1500}>
      {({ copied, copy }) => (
        <Tooltip label={copied ? 'Copied' : 'Copy'} withArrow>
          <ActionIcon
            size="xs"
            variant="subtle"
            color={copied ? 'teal' : 'gray'}
            onClick={copy}
            aria-label="Copy location"
          >
            <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={12} />
          </ActionIcon>
        </Tooltip>
      )}
    </CopyButton>
  </Group>
);

const GenomeRow: React.FC<{ row: SummaryItem }> = ({ row }) => (
  <KeyValue label={row.label}>
    {row.uri ? <UriLine value={row.value} /> : row.value}
  </KeyValue>
);

const GenomeSectionView: React.FC<{ section: GenomeSection }> = ({ section }) => (
  <Box>
    <Text size="xs" fw={600} mb={3}>
      {section.title}
    </Text>
    <Stack gap={3}>
      {section.rows.map((r, i) => (
        <GenomeRow key={`${r.label}-${i}`} row={r} />
      ))}
      {section.groups?.map((group) => (
        <Box key={group.category}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600} mt={2}>
            {group.category}
          </Text>
          {group.tracks.map((t, i) => (
            <Box key={`${t.name}-${i}`} mb={3}>
              <Text size="xs" style={{ wordBreak: 'break-word' }}>
                {t.name}
                {t.detail && (
                  <Text span size="xs" c="dimmed">
                    {' '}
                    · {t.detail}
                  </Text>
                )}
              </Text>
              {t.origin && <UriLine value={t.origin} />}
              {t.index && <UriLine value={t.index} />}
            </Box>
          ))}
        </Box>
      ))}
      {section.more ? (
        <Text size="xs" c="dimmed">
          +{section.more} more
        </Text>
      ) : null}
    </Stack>
  </Box>
);

/** The genome browser's assembly, location, tracks and data, as last rendered
 *  by the tile (see `genomeTracksStore`); its static config before that. */
const GenomeTracksSection: React.FC<{ metadata: StoredMetadata }> = ({ metadata }) => {
  const entry = useGenomeTracks(String(metadata.index));
  const summary = React.useMemo(
    () =>
      buildGenomeTracksSummary(
        metadata as Record<string, unknown>,
        entry?.payload ?? null,
        entry?.locus ?? null,
      ),
    [metadata, entry],
  );
  return (
    <Box>
      <SectionTitle icon="mdi:dna">Genome tracks</SectionTitle>
      <Stack gap="xs">
        {!summary.loaded && (
          <Text size="xs" c="dimmed">
            Scroll the browser into view to load its tracks.
          </Text>
        )}
        {summary.sections.map((s) => (
          <GenomeSectionView key={s.id} section={s} />
        ))}
      </Stack>
    </Box>
  );
};

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
/** What the tile last drew (rows, lanes, renderer), when it published that. */
function RenderedSection({ index }: { index: string }) {
  const stats = useTileStats(index);
  const entries = Object.entries(stats ?? {});
  if (!entries.length) return null;
  const label = (k: string) => k.charAt(0).toUpperCase() + k.slice(1);
  return (
    <Box>
      <SectionTitle icon="mdi:chart-box-outline">Rendered</SectionTitle>
      <Stack gap={3}>
        {entries.map(([k, v]) => (
          <KeyValue key={k} label={label(k)}>
            {typeof v === 'number' ? v.toLocaleString('en-US') : v}
          </KeyValue>
        ))}
      </Stack>
    </Box>
  );
}

const MetadataBody: React.FC<MetadataBodyProps> = ({ metadata }) => {
  const [rawOpen, setRawOpen] = React.useState(false);
  const json = React.useMemo(() => JSON.stringify(metadata, null, 2), [metadata]);
  const rows = React.useMemo(() => summaryRows(metadata), [metadata]);
  const src = metadata.catalog_source;

  const type = componentTypeVisual(metadata.component_type);
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
            background: tint(type.color),
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <Icon icon={type.icon} width={20} color={type.color} />
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
              <KeyValue key={r.label} label={r.label} mono={r.mono}>{r.value}</KeyValue>
            ))}
          </Stack>
        </Box>
      )}

      {metadata.component_type === 'jbrowse' && <GenomeTracksSection metadata={metadata} />}

      <RenderedSection index={String(metadata.index ?? '')} />

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
