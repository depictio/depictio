import React, { useEffect, useState, useMemo } from 'react';
import { Paper, Loader, Text, Stack } from '@mantine/core';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type { ColDef } from 'ag-grid-community';

import { renderTable, InteractiveFilter, StoredMetadata } from '../api';

interface TableRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
}

/**
 * Renders a table component via AG Grid. Backend route POSTs filters and
 * returns paginated rows. For the MVP we fetch the first 200 rows; full
 * server-side row model can be wired later via AG Grid's infinite row model.
 */
const TableRenderer: React.FC<TableRendererProps> = ({
  dashboardId,
  metadata,
  filters,
}) => {
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null);
  const [colDefs, setColDefs] = useState<ColDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    renderTable(dashboardId, metadata.index, filters, 0, 200)
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setColDefs(
          res.columns.map((c) => ({
            field: c.field,
            headerName: c.headerName,
            sortable: true,
            filter: true,
            resizable: true,
            type: c.type === 'numericColumn' ? 'numericColumn' : undefined,
          })),
        );
        setTotal(res.total);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err?.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, JSON.stringify(filters)]);

  const defaultColDef = useMemo<ColDef>(
    () => ({ flex: 1, minWidth: 100, resizable: true }),
    [],
  );

  return (
    <Paper p="sm" withBorder radius="md">
      {metadata.title && (
        <Text fw={600} size="sm" mb="xs">
          {metadata.title}
          {total > 0 && (
            <Text component="span" c="dimmed" size="xs" ml="xs">
              ({total} rows{total > 200 ? `, showing first 200` : ''})
            </Text>
          )}
        </Text>
      )}
      {loading && (
        <Stack align="center" justify="center" gap="xs" mih={200}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">Loading rows…</Text>
        </Stack>
      )}
      {error && !loading && (
        <Stack mih={200} justify="center" align="center">
          <Text size="sm" c="red">Table failed: {error}</Text>
        </Stack>
      )}
      {rows && !loading && !error && (
        <div className="ag-theme-alpine" style={{ width: '100%', height: 400 }}>
          <AgGridReact
            rowData={rows}
            columnDefs={colDefs}
            defaultColDef={defaultColDef}
            pagination
            paginationPageSize={20}
          />
        </div>
      )}
    </Paper>
  );
};

export default TableRenderer;
