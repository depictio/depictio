/**
 * Data Collection Information card. Mirrors the table inside
 * depictio/dash/layouts/stepper_parts/part_one.py:_render_data_collection_info.
 *
 * 9-row definition table: workflow id, dc id, type, metatype, name, description,
 * delta version, rows, columns. Type renders the MultiQC SVG inline when type=multiqc,
 * and the project pages' icon + label otherwise (e.g. genomic_tracks → "Genomic
 * tracks", the manifest a genome browser component binds to).
 */
import React from 'react';
import { Badge, Card, Group, Stack, Table, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import { DcTypeIcon, dcTypeMeta } from '../../projects/dcTypeIcon';

/** Join definition surfaced for "joined" DCs — mirrors the project-level
 *  `joins[]` entry minus the workflow plumbing. Used to render Left / Right /
 *  On / How rows in the info card. */
export interface JoinDetails {
  leftDc: string;
  rightDc: string;
  onColumns: string[];
  /** "inner" / "left" / "right" / "full" — straight from the join definition. */
  how: string;
}

export interface DataCollectionInfo {
  workflowId: string;
  dataCollectionId: string;
  type: string; // table | multiqc | image | genomic_tracks | jbrowse2 | ...
  metaType: string; // Regular | Joined
  name: string;
  description: string;
  deltaVersion: string;
  numRows: number | null | undefined;
  numColumns: number | null | undefined;
  /** "native" (ingested) or "joined" (derived from a project-level join). */
  source?: string;
  /** Present when ``source === 'joined'`` — populated from the project's
   *  ``joins[]`` array for the row whose ``result_dc_id`` matches this DC. */
  join?: JoinDetails;
}

const formatInt = (n: number | null | undefined): string =>
  typeof n === 'number' ? n.toLocaleString('en-US') : 'N/A';

const cap = (s: string): string =>
  s ? s.charAt(0).toUpperCase() + s.slice(1) : s;

interface Props {
  info: DataCollectionInfo;
}

const DataCollectionInfoCard: React.FC<Props> = ({ info }) => {
  const isMultiQC = info.type?.toLowerCase() === 'multiqc';
  // Known types read as the project pages name them ("Genomic tracks",
  // "JBrowse2 (legacy)"); anything else falls back to the raw type.
  const typeMeta = dcTypeMeta(info.type);
  const typeLabel = typeMeta.label === info.type ? cap(info.type) : typeMeta.label;
  const isJoined = info.source?.toLowerCase() === 'joined';

  return (
    <Card withBorder radius="md" p="md">
      <Table withRowBorders={false} verticalSpacing="xs" horizontalSpacing="md">
        <Table.Tbody>
          <Row label="Workflow ID" value={<Mono>{info.workflowId}</Mono>} />
          <Row
            label="Data Collection ID"
            value={<Mono>{info.dataCollectionId}</Mono>}
          />
          <Row
            label="Type"
            value={
              isMultiQC ? (
                <Stack gap={4} align="flex-start">
                  <img
                    src="/dashboard/logos/multiqc_icon_dark.svg"
                    alt="MultiQC"
                    className="multiqc-icon-themed"
                    style={{ width: 24, height: 24, objectFit: 'contain' }}
                  />
                  <Text size="sm">{cap(info.type)}</Text>
                </Stack>
              ) : (
                <Group gap={6} wrap="nowrap">
                  <DcTypeIcon type={info.type} size={16} withTooltip={false} />
                  <Text size="sm">{typeLabel}</Text>
                </Group>
              )
            }
          />
          <Row label="MetaType" value={<Text size="sm">{cap(info.metaType)}</Text>} />
          {info.source && (
            <Row
              label="Source"
              value={
                <Badge
                  size="sm"
                  variant="light"
                  color={isJoined ? 'grape' : 'gray'}
                  leftSection={
                    <Icon
                      icon={isJoined ? 'mdi:link-variant' : 'mdi:database-arrow-down'}
                      width={12}
                    />
                  }
                >
                  {cap(info.source)}
                </Badge>
              }
            />
          )}
          {isJoined && info.join && (
            <>
              <Row
                label="Join Inputs"
                value={
                  <Group gap={6} wrap="wrap">
                    <Badge size="sm" variant="light" color="blue">
                      {info.join.leftDc}
                    </Badge>
                    <Text size="sm" c="dimmed" component="span" style={{ lineHeight: 1 }}>
                      ⋈
                    </Text>
                    <Badge size="sm" variant="light" color="blue">
                      {info.join.rightDc}
                    </Badge>
                  </Group>
                }
              />
              <Row
                label="On Columns"
                value={
                  <Group gap={4} wrap="wrap">
                    {info.join.onColumns.map((c) => (
                      <Badge key={c} size="sm" variant="outline" color="grape">
                        {c}
                      </Badge>
                    ))}
                  </Group>
                }
              />
              <Row
                label="Join Type"
                value={<Text size="sm">{cap(info.join.how)}</Text>}
              />
            </>
          )}
          <Row label="Name" value={<Text size="sm">{info.name}</Text>} />
          <Row
            label="Description"
            value={
              <Text size="sm" style={{ whiteSpace: 'normal' }}>
                {info.description || '—'}
              </Text>
            }
          />
          <Row
            label="Delta Table version"
            value={<Text size="sm">{info.deltaVersion}</Text>}
          />
          <Row label="Rows" value={<Text size="sm">{formatInt(info.numRows)}</Text>} />
          <Row
            label="Columns"
            value={<Text size="sm">{formatInt(info.numColumns)}</Text>}
          />
        </Table.Tbody>
      </Table>
    </Card>
  );
};

const Row: React.FC<{ label: string; value: React.ReactNode }> = ({
  label,
  value,
}) => (
  <Table.Tr>
    <Table.Td style={{ width: 200 }}>
      <Text size="sm" fw={600} c="dimmed">
        {label}
      </Text>
    </Table.Td>
    <Table.Td>{value}</Table.Td>
  </Table.Tr>
);

const Mono: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text size="sm" ff="monospace" style={{ wordBreak: 'break-all' }}>
    {children}
  </Text>
);

export default DataCollectionInfoCard;
