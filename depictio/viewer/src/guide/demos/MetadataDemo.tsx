/**
 * The "Label your samples" part's demo: the first rows of this dashboard's own
 * metadata table, with a label column to type into and the groups it makes.
 *
 * The rows are the ones the Metadata panel opens on (same table, same read,
 * shared with the panel through `readAnnotationTable`, so opening it after
 * costs no request). The labels are the demo's own: nothing typed here is
 * saved, nor reaches the panel or Analysis.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  ColorSwatch,
  Group,
  Skeleton,
  Stack,
  Text,
  useComputedColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import { nextGroupColor } from 'depictio-react-core';
import type { AnnotationTable, SelectionGroup } from 'depictio-react-core';

import { readAnnotationTable } from '../../components/annotations/annotationTableRead';
import type { Load } from '../../components/annotations/annotationTableRead';

/** Enough rows to make two groups and leave some to label. */
const DEMO_ROWS = 8;
/** The table's own columns shown beside the key: enough to tell samples apart. */
const CONTEXT_COLUMNS = 3;
/** A column whose values run longer (a path, a free-text note) says little here. */
const MAX_CELL_CHARS = 32;
const LABEL_FIELD = '__label';
const KEY_FIELD = '__key';
/** The example the demo opens with: two groups, and rows left to label. */
const EXAMPLE = ['Batch A', 'Batch A', 'Batch B', 'Batch B'];

type Row = Record<string, unknown> & { [KEY_FIELD]: string; [LABEL_FIELD]: string };

function exampleLabels(keys: string[]): Record<string, string> {
  return Object.fromEntries(keys.slice(0, EXAMPLE.length).map((k, i) => [k, EXAMPLE[i]]));
}

/** Columns that read as short values in the rows shown, key first. */
function contextColumns(columns: string[], rows: Record<string, unknown>[], key: string): string[] {
  return columns
    .filter((c) => c !== key)
    .filter((c) =>
      rows.every((r) => {
        const v = r[c];
        return v === null || v === undefined || String(v).length <= MAX_CELL_CHARS;
      }),
    )
    .slice(0, CONTEXT_COLUMNS);
}

/** Each distinct label, in first-seen order, with its samples and the colour
 *  Analysis would give its group. */
function groupsOf(rows: Row[], labels: Record<string, string>) {
  const order: string[] = [];
  const counts = new Map<string, number>();
  for (const r of rows) {
    const label = labels[r[KEY_FIELD]]?.trim();
    if (!label) continue;
    if (!counts.has(label)) order.push(label);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  const taken: Pick<SelectionGroup, 'color'>[] = [];
  return order.map((label) => {
    const color = nextGroupColor(taken as SelectionGroup[]);
    taken.push({ color });
    return { label, count: counts.get(label) ?? 0, color };
  });
}

const LabelCell: React.FC<ICellRendererParams<Row> & { colorOf: Map<string, string> }> = ({
  value,
  colorOf,
}) => {
  const label = typeof value === 'string' ? value.trim() : '';
  if (!label) {
    return (
      <Text span size="xs" c="dimmed" fs="italic">
        type a label
      </Text>
    );
  }
  return (
    <Group gap={6} wrap="nowrap" align="center" h="100%">
      <ColorSwatch color={colorOf.get(label) ?? 'gray'} size={10} withShadow={false} />
      <Text span size="sm">
        {label}
      </Text>
    </Group>
  );
};

export const MetadataDemo: React.FC<{
  dashboardId: string;
  table: AnnotationTable;
  /** Whether this dashboard compares groups in Analysis. */
  analysis: boolean;
}> = ({ dashboardId, table, analysis }) => {
  const scheme = useComputedColorScheme('light');
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  useEffect(() => {
    let cancelled = false;
    setLoad({ kind: 'loading' });
    void readAnnotationTable({ dashboardId, dcId: table.dc_id, pinned: false }).then((l) => {
      if (!cancelled) setLoad(l);
    });
    return () => {
      cancelled = true;
    };
  }, [dashboardId, table.dc_id]);

  const key = table.key_columns[0] ?? '';
  const read = load.kind === 'ready' ? load.table : null;
  const shown = useMemo(() => {
    if (!read || !key) return null;
    const rows = read.rows.slice(0, DEMO_ROWS);
    return { rows, keys: rows.map((r) => String(r[key] ?? '')), context: contextColumns(read.columns, rows, key) };
  }, [read, key]);

  const [labels, setLabels] = useState<Record<string, string>>({});
  useEffect(() => {
    if (shown) setLabels(exampleLabels(shown.keys));
  }, [shown]);

  const rows: Row[] = useMemo(
    () =>
      (shown?.rows ?? []).map((r, i) => ({
        ...r,
        [KEY_FIELD]: shown?.keys[i] ?? '',
        [LABEL_FIELD]: labels[shown?.keys[i] ?? ''] ?? '',
      })),
    [shown, labels],
  );
  const groups = useMemo(() => groupsOf(rows, labels), [rows, labels]);
  const colorOf = useMemo(() => new Map(groups.map((g) => [g.label, g.color])), [groups]);

  const colDefs = useMemo<ColDef<Row>[]>(
    () => [
      { field: key, headerName: key, pinned: 'left', width: 150 },
      // Beside the key, so it is never scrolled out of view.
      {
        field: LABEL_FIELD,
        headerName: 'Batch (your label)',
        pinned: 'left',
        editable: true,
        singleClickEdit: true,
        width: 170,
        cellRenderer: LabelCell,
        cellRendererParams: { colorOf },
        cellStyle: { background: 'var(--mantine-primary-color-light)' },
      },
      ...(shown?.context ?? []).map<ColDef<Row>>((c) => ({
        field: c,
        headerName: c,
        minWidth: 90,
        flex: 1,
      })),
    ],
    [key, shown, colorOf],
  );

  if (load.kind === 'loading' || load.kind === 'idle') return <Skeleton h={260} radius="md" />;
  if (load.kind === 'refused') {
    return (
      <Text size="sm" c="dimmed">
        {load.message}
      </Text>
    );
  }
  if (!shown || shown.rows.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        This table has no rows to label yet.
      </Text>
    );
  }

  const total = table.row_count ?? read?.rows.length ?? shown.rows.length;
  return (
    <Stack gap="sm" data-testid="guide-metadata-demo">
      <Text size="xs" c="dimmed">
        <b>{table.tag}</b>, its first {shown.rows.length} of {total.toLocaleString()} rows. Click a
        cell of the Batch column and type: rows with the same label form a group.
      </Text>
      <Box className={scheme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'} w="100%">
        <AgGridReact<Row>
          rowData={rows}
          columnDefs={colDefs}
          domLayout="autoHeight"
          defaultColDef={{ resizable: true, sortable: false }}
          getRowId={(p) => p.data[KEY_FIELD]}
          stopEditingWhenCellsLoseFocus
          onCellValueChanged={(e) => {
            const k = e.data[KEY_FIELD];
            setLabels((prev) => ({ ...prev, [k]: String(e.newValue ?? '').trim() }));
          }}
        />
      </Box>
      <Group justify="space-between" align="flex-start" gap="xs" wrap="nowrap">
        <Stack gap={6} style={{ minWidth: 0 }}>
          <Text size="xs" fw={600} c="dimmed" tt="uppercase">
            {groups.length === 1 ? '1 group' : `${groups.length} groups`}
          </Text>
          <Group gap={6} data-testid="guide-metadata-groups">
            {groups.length === 0 ? (
              <Text size="xs" c="dimmed">
                No label yet.
              </Text>
            ) : (
              groups.map((g) => (
                <Group
                  key={g.label}
                  gap={6}
                  wrap="nowrap"
                  px={8}
                  py={2}
                  style={{
                    border: '1px solid var(--mantine-color-default-border)',
                    borderRadius: 'var(--mantine-radius-xl)',
                  }}
                >
                  <ColorSwatch color={g.color} size={10} withShadow={false} />
                  <Text size="xs" fw={500}>
                    {g.label}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {g.count} {g.count === 1 ? 'sample' : 'samples'}
                  </Text>
                </Group>
              ))
            )}
          </Group>
          <Text size="xs" c="dimmed">
            {analysis
              ? 'In the panel, comparing by this column makes each group one you compare in Analysis, in these colours.'
              : 'In the panel, Export downloads the table with these labels added.'}
          </Text>
        </Stack>
        <Button
          size="compact-xs"
          variant="subtle"
          color="gray"
          leftSection={<Icon icon="mdi:restore" width={14} />}
          onClick={() => setLabels(exampleLabels(shown.keys))}
          data-testid="guide-metadata-reset"
        >
          Reset
        </Button>
      </Group>
    </Stack>
  );
};
