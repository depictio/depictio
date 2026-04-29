/**
 * Data Collection Information card. Mirrors the table inside
 * depictio/dash/layouts/stepper_parts/part_one.py:_render_data_collection_info.
 *
 * 9-row definition table: workflow id, dc id, type, metatype, name, description,
 * delta version, rows, columns. Type renders the MultiQC SVG inline when type=multiqc.
 */
import React from 'react';
import { Card, Stack, Table, Text } from '@mantine/core';

export interface DataCollectionInfo {
  workflowId: string;
  dataCollectionId: string;
  type: string; // table | multiqc | jbrowse | ...
  metaType: string; // Regular | Joined
  name: string;
  description: string;
  deltaVersion: string;
  numRows: number | null | undefined;
  numColumns: number | null | undefined;
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
                    src="/dashboard-beta/logos/multiqc_icon_dark.svg"
                    alt="MultiQC"
                    className="multiqc-icon-themed"
                    style={{ width: 24, height: 24, objectFit: 'contain' }}
                  />
                  <Text size="sm">{cap(info.type)}</Text>
                </Stack>
              ) : (
                <Text size="sm">{cap(info.type)}</Text>
              )
            }
          />
          <Row label="MetaType" value={<Text size="sm">{cap(info.metaType)}</Text>} />
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
