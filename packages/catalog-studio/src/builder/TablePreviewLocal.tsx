/**
 * Client-side ag-grid preview of the parsed fixture. Depictio's real
 * `TablePreview` fetches the backend (`fetchDataCollectionPreview`); since the
 * catalog `table` render carries no config, we render the in-memory rows
 * directly with the same ag-grid look — modeled on
 * `viewer/src/builder/data/DataPreviewTable.tsx`. Reused both as the table
 * component preview and in the Fixture step right after upload.
 *
 * When `respectConfig` is set (the table builder), it reads the builder store's
 * display config (cols_json hide / compact / striped) so the preview reflects
 * the depictio-style form live — even though none of it is persisted.
 */
import { useMemo } from 'react';
import { Stack, Text, useComputedColorScheme } from '@mantine/core';
import { AgGridReact } from 'ag-grid-react';
import type { ColDef } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';
import { useBuilderStore } from 'depictio-builder/store/useBuilderStore';
import type { ParsedFixture } from '../types';

type ColCfg = { hide?: boolean };

export default function TablePreviewLocal({
  fixture,
  height = 420,
  respectConfig = false,
}: {
  fixture: ParsedFixture;
  height?: number;
  /** Read cols_json/compact/striped from the builder store (table builder). */
  respectConfig?: boolean;
}) {
  const scheme = useComputedColorScheme('light');
  // Subscribe to config only when honoring it, so the Fixture-step usage
  // (no builder session) doesn't re-render on unrelated store changes.
  const config = useBuilderStore((s) => (respectConfig ? s.config : null)) as
    | { cols_json?: Record<string, ColCfg>; compact?: boolean; striped?: boolean }
    | null;

  const colsJson = config?.cols_json ?? {};
  const compact = config?.compact ?? false;
  const striped = config?.striped ?? true;

  const columnDefs = useMemo<ColDef[]>(
    () =>
      fixture.columns.map((c) => ({
        // ag-grid treats "." in `field` as a nested path; nf-core / MultiQC
        // outputs have dotted column names, so use a flat-key valueGetter.
        colId: c.name,
        headerName: c.name,
        headerTooltip: `${c.name} · ${c.dtype}`,
        hide: respectConfig ? Boolean(colsJson[c.name]?.hide) : false,
        valueGetter: (params) => (params.data ? (params.data as Record<string, unknown>)[c.name] : undefined),
        // sortable/filter/resizable/minWidth come from defaultColDef below.
        valueFormatter: (params) => {
          const v = params.value;
          if (v == null) return '';
          if (typeof v === 'object') return JSON.stringify(v);
          return String(v);
        },
      })),
    [fixture.columns, respectConfig, colsJson],
  );

  return (
    <Stack gap="xs">
      <div
        className={scheme === 'dark' ? 'ag-theme-quartz-dark' : 'ag-theme-quartz'}
        style={{ width: '100%', height }}
      >
        <AgGridReact
          rowData={fixture.rows}
          columnDefs={columnDefs}
          pagination
          paginationPageSize={10}
          paginationPageSizeSelector={[10, 25, 50, 100]}
          rowHeight={respectConfig && compact ? 28 : undefined}
          getRowStyle={
            respectConfig && striped
              ? (params) =>
                  typeof params.node.rowIndex === 'number' && params.node.rowIndex % 2 === 1
                    ? { background: 'var(--mantine-color-default-hover)' }
                    : undefined
              : undefined
          }
          defaultColDef={{ flex: 1, minWidth: 120, sortable: true, filter: true, resizable: true }}
        />
      </div>
      <Text size="xs" c="dimmed">
        {fixture.rows.length.toLocaleString('en-US')} rows · {fixture.columns.length} columns
      </Text>
    </Stack>
  );
}
