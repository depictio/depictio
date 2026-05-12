import React, { useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Drawer,
  Group,
  Loader,
  Stack,
  Text,
  useMantineColorScheme,
} from '@mantine/core';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';

import ErrorBoundary from '../ErrorBoundary';

interface AdvancedVizFrameProps {
  /** Inner content (the viz itself). */
  children: React.ReactNode;
  /** Optional top-bar controls rendered above the chart (sliders, search, top-N). */
  controls?: React.ReactNode;
  /** Loading state for initial fetch. */
  loading?: boolean;
  /** Error to display in place of children. */
  error?: string | null;
  /** Empty-state message when data fetched but row_count === 0. */
  emptyMessage?: string;
  /**
   * Optional column-oriented row data for the "Show data" drawer. Keys are
   * column names, values are equally-sized arrays of cell values (same shape
   * as the response from /advanced_viz/data).
   */
  dataRows?: Record<string, unknown[]>;
  /** Column ordering (if omitted, uses Object.keys(dataRows)). */
  dataColumns?: string[];
}

/**
 * Shared wrapper for advanced-viz renderers. Provides:
 *  - error boundary
 *  - loading skeleton
 *  - empty-state messaging
 *  - a top-bar slot for builtin Tier-2 controls (sliders, search, top-N)
 *  - a "Show data" button that opens a bottom Drawer with an AG Grid view
 *    of the rows feeding the chart (no layout shift inside the react-grid
 *    item, DOM virtualization handles up to 100k rows without crashing)
 *
 * Chrome (title, fullscreen, download, reset) is added by ComponentRenderer's
 * wrapWithChrome() one level above — same convention as figure/table.
 */
const AdvancedVizFrame: React.FC<AdvancedVizFrameProps> = ({
  children,
  controls,
  loading,
  error,
  emptyMessage,
  dataRows,
  dataColumns,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const tableInfo = useMemo(() => {
    if (!dataRows) return null;
    const cols = dataColumns?.filter((c) => c in dataRows) ?? Object.keys(dataRows);
    if (cols.length === 0) return null;
    const totalRows = dataRows[cols[0]]?.length ?? 0;
    return { cols, totalRows };
  }, [dataRows, dataColumns]);

  // Column-oriented -> row-oriented for AG Grid. Only run when drawer is
  // open so the work isn't done on every refresh of the chart.
  const rowData = useMemo(() => {
    if (!drawerOpen || !tableInfo || !dataRows) return [];
    const out: Record<string, unknown>[] = [];
    for (let i = 0; i < tableInfo.totalRows; i++) {
      const row: Record<string, unknown> = {};
      for (const c of tableInfo.cols) row[c] = dataRows[c][i];
      out.push(row);
    }
    return out;
  }, [drawerOpen, tableInfo, dataRows]);

  const colDefs = useMemo(() => {
    if (!tableInfo) return [];
    return tableInfo.cols.map((c) => ({
      field: c,
      headerName: c,
      sortable: true,
      filter: true,
      resizable: true,
      // Polars columns can contain dots (e.g. `sepal.length`). Without
      // `valueGetter`, AG Grid treats the dot as a path separator.
      valueGetter: (params: { data?: Record<string, unknown> }) => params.data?.[c],
    }));
  }, [tableInfo]);

  const isDark = colorScheme === 'dark';

  return (
    <ErrorBoundary>
      <Stack gap="xs" style={{ width: '100%', height: '100%' }}>
        {controls ? (
          <div style={{ flex: '0 0 auto', padding: '4px 8px' }}>{controls}</div>
        ) : null}
        <div style={{ flex: '1 1 auto', minHeight: 0, position: 'relative' }}>
          {loading ? (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Loader size="sm" />
            </div>
          ) : error ? (
            <Alert color="red" title="Failed to render" variant="light">
              <Text size="xs">{error}</Text>
            </Alert>
          ) : emptyMessage ? (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                color: 'var(--mantine-color-dimmed)',
                fontSize: '0.85rem',
              }}
            >
              {emptyMessage}
            </div>
          ) : (
            children
          )}
        </div>
        {tableInfo && !loading && !error ? (
          <div
            style={{
              flex: '0 0 auto',
              padding: '4px 8px',
              borderTop: '1px solid var(--mantine-color-default-border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 8,
            }}
          >
            <Button
              size="compact-xs"
              variant="subtle"
              color="gray"
              onClick={() => setDrawerOpen(true)}
            >
              ▸ Show data
            </Button>
            <Text size="xs" c="dimmed">
              {tableInfo.totalRows.toLocaleString()} rows × {tableInfo.cols.length} cols
            </Text>
          </div>
        ) : null}
      </Stack>
      {tableInfo ? (
        <Drawer
          opened={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          position="bottom"
          size="70%"
          title={
            <Group gap={8}>
              <Text fw={500}>Underlying data</Text>
              <Text size="xs" c="dimmed">
                {tableInfo.totalRows.toLocaleString()} rows × {tableInfo.cols.length} cols
              </Text>
            </Group>
          }
          withCloseButton
          padding="sm"
          // Keep the drawer above the dashboard grid + plotly toolbars.
          zIndex={2000}
        >
          <div
            className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
            style={{ width: '100%', height: 'calc(100% - 8px)' }}
          >
            <AgGridReact
              rowData={rowData}
              columnDefs={colDefs}
              animateRows={false}
              suppressColumnVirtualisation={false}
              rowBuffer={25}
              cacheQuickFilter
              pagination={tableInfo.totalRows > 1000}
              paginationPageSize={100}
              paginationPageSizeSelector={[50, 100, 250, 500]}
              defaultColDef={{ minWidth: 100, flex: 1 }}
            />
          </div>
        </Drawer>
      ) : null}
    </ErrorBoundary>
  );
};

export default AdvancedVizFrame;
