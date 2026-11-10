/**
 * The pieces of the data collection viewer: a line of key figures, the
 * columns a table holds, its links, and the details nobody needs at a glance.
 * Each reads the collection document as it comes from the API and shows only
 * what that document holds.
 */
import React, { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  CopyButton,
  Group,
  Pill,
  ScrollArea,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  ThemeIcon,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { useListingAccents } from '../../lib/useListingAccents';
import { DcTypeIcon } from '../dcTypeIcon';

type Doc = Record<string, unknown>;

const obj = (v: unknown): Doc | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Doc) : null);
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** The newest aggregation, whichever shape the document stores it in. */
export function lastAggregation(dc: Doc): Doc | null {
  const la = dc.last_aggregation;
  if (Array.isArray(la)) return obj(la[la.length - 1]);
  return obj(la);
}

export function dcProps(dc: Doc): Doc {
  return obj(obj(dc.config)?.dc_specific_properties) ?? {};
}

export interface ColumnSpec {
  name: string;
  type: string | null;
  description: string | null;
  distinct: number | null;
}

/** The columns recorded at the last aggregation, with the descriptions the
 *  project gives them. */
export function dcColumns(dc: Doc): ColumnSpec[] {
  const specs = lastAggregation(dc)?.aggregation_columns_specs;
  const described = obj(dcProps(dc).columns_description) ?? {};
  if (!Array.isArray(specs)) return [];
  return specs
    .map(obj)
    .filter((s): s is Doc => !!s && !!str(s.name))
    .map((s) => ({
      name: s.name as string,
      type: str(s.type),
      description: str(s.description) ?? str(described[s.name as string]),
      distinct: num(obj(s.specs)?.nunique),
    }));
}

/** A stored timestamp in the reader's time. Most are naive UTC; a few
 *  (aggregation and run times, written with `datetime.now()`) are the
 *  server's local time and pass `utc: false`. */
export function formatTimestamp(value: unknown, { utc = true }: { utc?: boolean } = {}): string | null {
  const s = str(value);
  if (!s) return null;
  const iso = s.includes('T') ? s : s.replace(' ', 'T');
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) || !utc ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return s;
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const ORIGIN: Record<string, [string, string]> = {
  run: ['Run folder', 'mdi:folder-play-outline'],
  upload: ['Upload', 'mdi:upload-outline'],
  folder: ['Folder', 'mdi:folder-outline'],
  s3: ['S3', 'mdi:bucket-outline'],
  url: ['URL', 'mdi:link-variant'],
  manifest: ['Manifest', 'mdi:file-document-multiple-outline'],
};

export function dcOrigin(
  dc: Doc,
): { label: string; icon: string; location: string | null; addedAt: string | null } | null {
  const o = obj(obj(dc.config)?.origin);
  const kind = str(o?.kind);
  if (!o || !kind) return null;
  return {
    label: ORIGIN[kind]?.[0] ?? kind,
    icon: ORIGIN[kind]?.[1] ?? 'mdi:help-circle-outline',
    location: str(o.location),
    addedAt: formatTimestamp(o.added_at),
  };
}

export interface Fact {
  label: string;
  icon: string;
  value: React.ReactNode;
  hint?: string | null;
  testId?: string;
  /** The tile leads somewhere else on the page. */
  onClick?: () => void;
}

/** Key figures as small tiles: a light icon, what it is, its value. */
export const DcFacts: React.FC<{ facts: Fact[] }> = ({ facts }) => {
  const accent = useListingAccents('projects');
  return (
    <Group gap="xl" wrap="wrap" style={{ rowGap: 'var(--mantine-spacing-sm)' }} data-testid="dc-viewer-facts">
      {facts.map((f) => {
        const body = (
          <Group key={f.label} gap={10} wrap="nowrap" data-testid={f.onClick ? undefined : f.testId}>
            <ThemeIcon variant="light" color={accent.secondary} size={34} radius="md">
              <Icon icon={f.icon} width={18} />
            </ThemeIcon>
            <Stack gap={0}>
              <Text size="xs" c="dimmed" lh={1.3}>
                {f.label}
              </Text>
              <Text size="sm" fw={600} lh={1.3} style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                {f.value}
              </Text>
            </Stack>
          </Group>
        );
        const tile = f.onClick ? (
          <UnstyledButton key={f.label} onClick={f.onClick} data-testid={f.testId}>
            {body}
          </UnstyledButton>
        ) : (
          body
        );
        return f.hint ? (
          <Tooltip key={f.label} label={f.hint} multiline maw={420} withArrow style={{ wordBreak: 'break-all', whiteSpace: 'pre-line' }}>
            {tile}
          </Tooltip>
        ) : (
          tile
        );
      })}
    </Group>
  );
};

/** The advanced charts this collection has the columns for, as quiet pills. */
export const DcSuggestedCharts: React.FC<{ kinds: string[] }> = ({ kinds }) => (
  <Group gap={6} wrap="wrap" data-testid="dc-viewer-viz">
    <Tooltip
      label="Advanced charts this collection has the columns for, offered first when you add one to a dashboard."
      multiline
      maw={320}
      withArrow
    >
      <Group gap={4} wrap="nowrap">
        <Icon icon="mdi:chart-box-outline" width={14} style={{ opacity: 0.6 }} />
        <Text size="xs" c="dimmed">
          Recommended advanced charts
        </Text>
      </Group>
    </Tooltip>
    {kinds.map((k) => (
      <Pill key={k} size="sm">
        {k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, ' ')}
      </Pill>
    ))}
  </Group>
);

/** A short id with a copy button: the whole id is rarely read, often pasted. */
export const CopyId: React.FC<{ id: string }> = ({ id }) => (
  <CopyButton value={id} timeout={1500}>
    {({ copied, copy }) => (
      <Tooltip label={copied ? 'Copied' : `Copy the id ${id}`} withArrow>
        <Badge
          variant="default"
          radius="sm"
          tt="none"
          fw={500}
          ff="monospace"
          style={{ cursor: 'pointer' }}
          onClick={copy}
          rightSection={<Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={12} />}
          data-testid="dc-viewer-copy-id"
        >
          {`…${id.slice(-8)}`}
        </Badge>
      </Tooltip>
    )}
  </CopyButton>
);

/** Columns Depictio adds to every table it ingests. */
const SYSTEM_COLUMNS = new Set(['depictio_run_id', 'aggregation_time']);

export const userColumns = (columns: ColumnSpec[]) => columns.filter((c) => !SYSTEM_COLUMNS.has(c.name));

/** Rows and columns of a collection's last aggregation, for a short summary. */
export function dcShape(dc: Doc): { rows: number | null; columns: number | null } {
  const rows = num(lastAggregation(dc)?.rows_total);
  const columns = userColumns(dcColumns(dc)).length;
  return { rows, columns: columns > 0 ? columns : null };
}

/** A storage type, in words, with an icon. */
function columnKind(type: string | null): [string, string] {
  const t = (type ?? '').toLowerCase();
  if (/^(u?int|i\d|u\d)/.test(t) || t.includes('int')) return ['Integer', 'mdi:numeric'];
  if (t.includes('float') || t.includes('decimal') || t.includes('double') || /^f\d/.test(t))
    return ['Decimal', 'mdi:decimal'];
  if (t.includes('bool')) return ['Boolean', 'mdi:toggle-switch-outline'];
  if (t.includes('date') || t.includes('time')) return ['Date', 'mdi:calendar-outline'];
  if (t.includes('list') || t.includes('array')) return ['List', 'mdi:code-brackets'];
  if (t === 'object' || t.includes('str') || t.includes('utf8') || t.includes('categor'))
    return ['Text', 'mdi:format-text'];
  return [type ?? 'Unknown', 'mdi:help-circle-outline'];
}

const TH = (props: React.ComponentProps<typeof Table.Th>) => (
  <Table.Th fz="xs" fw={600} c="dimmed" style={{ whiteSpace: 'nowrap' }} {...props} />
);

export const DcColumnsTable: React.FC<{ columns: ColumnSpec[]; rows: number | null }> = ({ columns, rows }) => {
  const shown = userColumns(columns);
  const system = columns.filter((c) => SYSTEM_COLUMNS.has(c.name));
  return (
    <Stack gap={6} data-testid="dc-viewer-columns">
      <Table.ScrollContainer minWidth={560}>
        <Table verticalSpacing={6} horizontalSpacing="sm" highlightOnHover layout="auto">
          <Table.Thead>
            <Table.Tr>
              <TH>Column</TH>
              <TH>Type</TH>
              <TH ta="right">Distinct values</TH>
              <TH w="100%">Description</TH>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {shown.map((c) => {
              const [kind, icon] = columnKind(c.type);
              const unique = rows != null && c.distinct != null && c.distinct === rows;
              return (
                <Table.Tr key={c.name}>
                  <Table.Td style={{ whiteSpace: 'nowrap' }}>
                    <Text size="sm" fw={600} ff="monospace">
                      {c.name}
                    </Text>
                  </Table.Td>
                  <Table.Td style={{ whiteSpace: 'nowrap' }}>
                    <Tooltip label={c.type ?? kind} withArrow>
                      <Group gap={6} wrap="nowrap" w="fit-content">
                        <ThemeIcon variant="light" color="gray" size={22} radius="sm">
                          <Icon icon={icon} width={14} />
                        </ThemeIcon>
                        <Text size="sm">{kind}</Text>
                      </Group>
                    </Tooltip>
                  </Table.Td>
                  <Table.Td ta="right" style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                    {c.distinct == null ? (
                      <Text size="sm" c="dimmed">
                        —
                      </Text>
                    ) : (
                      <Text size="sm">
                        {c.distinct.toLocaleString()}
                        {unique && (
                          <Text span size="xs" c="dimmed" ml={6}>
                            all unique
                          </Text>
                        )}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c={c.description ? undefined : 'dimmed'}>
                      {c.description ?? '—'}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {system.length > 0 && (
        <Text size="xs" c="dimmed">
          {`Depictio also adds ${system.map((c) => c.name).join(' and ')} to every row.`}
        </Text>
      )}
    </Stack>
  );
};

export interface DcLinkRow {
  key: string;
  /** The column of this collection the link reads (several for a join);
   *  null when it matches on sample names rather than a column. */
  here: string | null;
  other: { tag: string; type: string };
  /** The other collection's column, or null when it matches on its own key. */
  otherField: string | null;
  kind: 'out' | 'in' | 'join';
  enabled: boolean;
  /** A link's id; a join has none and offers neither mapping nor editing. */
  linkId?: string;
}

const LINK_KIND: Record<DcLinkRow['kind'], [string, string]> = {
  out: ['mdi:arrow-right', 'Filters'],
  in: ['mdi:arrow-left', 'Filtered by'],
  join: ['mdi:table-merge-cells', 'Joined with'],
};

/** A column name, or how a link without one matches. */
const FieldCell: React.FC<{ field: string | null }> = ({ field }) =>
  field ? (
    <Text size="sm" fw={600} ff="monospace">
      {field}
    </Text>
  ) : (
    <Text size="sm" c="dimmed">
      by sample name
    </Text>
  );

/** What this collection is linked to: its column, the way, the other side. */
export const DcLinksTable: React.FC<{
  rows: DcLinkRow[];
  /** The link whose value mapping shows under its row. */
  inspecting: string | null;
  onInspect: (linkId: string | null) => void;
  /** The mapping itself, the same view the project's links section opens. */
  mapping: (linkId: string) => React.ReactNode;
  onEdit?: (linkId: string) => void;
  canEdit: boolean;
}> = ({ rows, inspecting, onInspect, mapping, onEdit, canEdit }) => (
  <Table.ScrollContainer minWidth={560} data-testid="dc-viewer-links">
    <Table verticalSpacing={6} horizontalSpacing="sm" highlightOnHover layout="auto">
      <Table.Thead>
        <Table.Tr>
          <TH>Column here</TH>
          <TH>Link</TH>
          <TH>Collection</TH>
          <TH w="100%">Its column</TH>
          <TH />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((r) => {
          const [icon, word] = LINK_KIND[r.kind];
          const open = !!r.linkId && inspecting === r.linkId;
          return (
            <React.Fragment key={r.key}>
            <Table.Tr style={r.enabled ? undefined : { opacity: 0.55 }}>
              <Table.Td style={{ whiteSpace: 'nowrap' }}>
                <FieldCell field={r.here} />
              </Table.Td>
              <Table.Td style={{ whiteSpace: 'nowrap' }}>
                <Group gap={6} wrap="nowrap">
                  <Icon icon={icon} width={14} style={{ opacity: 0.6 }} />
                  <Text size="sm" c="dimmed">
                    {r.enabled ? word : `${word} (off)`}
                  </Text>
                </Group>
              </Table.Td>
              <Table.Td style={{ whiteSpace: 'nowrap' }}>
                <Group gap={6} wrap="nowrap">
                  <DcTypeIcon type={r.other.type} size={14} withTooltip={false} />
                  <Text size="sm">{r.other.tag}</Text>
                </Group>
              </Table.Td>
              <Table.Td>
                <FieldCell field={r.otherField} />
              </Table.Td>
              <Table.Td style={{ whiteSpace: 'nowrap' }}>
                {r.linkId && (
                  <Group gap={2} wrap="nowrap" justify="flex-end">
                    <Tooltip label={open ? 'Hide the value mapping' : 'Show which values match'} withArrow>
                      <ActionIcon
                        variant={open ? 'light' : 'subtle'}
                        color="gray"
                        size="sm"
                        onClick={() => onInspect(open ? null : (r.linkId as string))}
                        aria-label="Value mapping"
                        data-testid={`dc-link-mapping-${r.linkId}`}
                      >
                        <Icon icon="mdi:eye-outline" width={16} />
                      </ActionIcon>
                    </Tooltip>
                    {onEdit && (
                      <Tooltip label={canEdit ? 'Edit this link' : 'Owner permission required'} withArrow>
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          size="sm"
                          disabled={!canEdit}
                          onClick={() => onEdit(r.linkId as string)}
                          aria-label="Edit link"
                          data-testid={`dc-link-edit-${r.linkId}`}
                        >
                          <Icon icon="mdi:pencil-outline" width={16} />
                        </ActionIcon>
                      </Tooltip>
                    )}
                  </Group>
                )}
              </Table.Td>
            </Table.Tr>
            {open && (
              <Table.Tr>
                <Table.Td colSpan={5} p="sm">
                  {mapping(r.linkId as string)}
                </Table.Td>
              </Table.Tr>
            )}
            </React.Fragment>
          );
        })}
      </Table.Tbody>
    </Table>
  </Table.ScrollContainer>
);

export interface DetailItem {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}

/** Label and value pairs in two columns; an empty value is left out. */
export const DcDetailsGrid: React.FC<{ items: DetailItem[] }> = ({ items }) => (
  <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="lg" verticalSpacing="sm" data-testid="dc-viewer-details">
    {items
      .filter((i) => i.value != null && i.value !== '')
      .map((i) => (
        <Stack key={i.label} gap={0} style={{ minWidth: 0 }}>
          <Text size="xs" c="dimmed">
            {i.label}
          </Text>
          <Group gap={4} wrap="nowrap" align="flex-start">
            <Text size="sm" ff={i.mono ? 'monospace' : undefined} style={{ wordBreak: 'break-all' }}>
              {i.value}
            </Text>
            {i.mono && (
              <CopyButton value={i.value as string} timeout={1500}>
                {({ copied, copy }) => (
                  <ActionIcon size="xs" variant="subtle" color="gray" onClick={copy} aria-label={`Copy ${i.label}`}>
                    <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={12} />
                  </ActionIcon>
                )}
              </CopyButton>
            )}
          </Group>
        </Stack>
      ))}
  </SimpleGrid>
);

/** What the type adds to a collection: the columns a track manifest or a map
 *  reads, the column holding image paths, how a tree is drawn. */
export function typeDetails(dc: Doc, type: string): DetailItem[] {
  const p = dcProps(dc);
  const s = (k: string) => (p[k] == null || p[k] === '' ? null : String(p[k]));
  switch (type) {
    case 'genomic_tracks':
      return [
        { label: 'Assembly', value: s('assembly') },
        { label: 'Track file column', value: s('uri_column'), mono: true },
        { label: 'Track id column', value: s('track_id_column'), mono: true },
        { label: 'Sample column', value: s('sample_column'), mono: true },
        { label: 'Category column', value: s('category_column'), mono: true },
      ];
    case 'image':
      return [
        { label: 'Image column', value: s('image_column'), mono: true },
        { label: 'Images stored in', value: s('s3_base_folder') ?? s('local_images_path'), mono: true },
        { label: 'Thumbnail size', value: s('thumbnail_size') && `${s('thumbnail_size')} px` },
      ];
    case 'phylogeny':
      return [
        { label: 'Tree format', value: s('format') },
        { label: 'Tip labels from', value: s('tip_label_strategy') },
        { label: 'Tip metadata', value: s('metadata_dc_tag'), mono: true },
        { label: 'Ladderized', value: p.ladderize == null ? null : p.ladderize ? 'Yes' : 'No' },
      ];
    case 'geojson':
      return [{ label: 'Feature id key', value: s('feature_id_key'), mono: true }];
    default:
      return [
        { label: 'Latitude column', value: s('lat_column'), mono: true },
        { label: 'Longitude column', value: s('lon_column'), mono: true },
      ];
  }
}

/** Where the files were read from: one file, or the pattern a scan matched. */
export function scanSource(dc: Doc): string | null {
  const scan = obj(obj(dc.config)?.scan);
  const params = obj(scan?.scan_parameters);
  return (
    str(params?.filename) ??
    str(obj(params?.regex_config)?.pattern) ??
    str(params?.url) ??
    str(params?.manifest_url) ??
    null
  );
}

/** Sortable column header — click to toggle asc/desc; shows the active arrow. */
export const SortableTh: React.FC<{
  label: string;
  sortKey: string;
  activeKey: string;
  dir: 'asc' | 'desc';
  onSort: (k: string) => void;
  w?: number | string;
}> = ({ label, sortKey, activeKey, dir, onSort, w }) => (
  <Table.Th
    w={w}
    style={{ cursor: 'pointer', whiteSpace: 'nowrap', userSelect: 'none' }}
    onClick={() => onSort(sortKey)}
  >
    <Group gap={2} wrap="nowrap">
      <Text size="sm" fw={600}>
        {label}
      </Text>
      <Icon
        icon={
          activeKey === sortKey
            ? dir === 'asc'
              ? 'mdi:menu-up'
              : 'mdi:menu-down'
            : 'mdi:unfold-more-horizontal'
        }
        width={14}
        color={activeKey === sortKey ? undefined : 'var(--mantine-color-gray-5)'}
      />
    </Group>
  </Table.Th>
);
