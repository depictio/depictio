import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Paper, Loader, Text, Stack, useMantineColorScheme } from '@mantine/core';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type {
  ColDef,
  GridReadyEvent,
  IDatasource,
  IGetRowsParams,
  GridApi,
} from 'ag-grid-community';

import { renderTable, InteractiveFilter, StoredMetadata } from '../api';
import { useInView } from '../hooks/useInView';

interface TableRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  /** When provided, the grid api is mirrored to this ref so the chrome's
   *  Download button can call `exportDataAsCsv` without prop-drilling. */
  agGridApiRef?: React.RefObject<GridApi | null>;
}

const CACHE_BLOCK_SIZE = 100;
const MAX_BLOCKS_IN_CACHE = 10;

/**
 * Renders a table component via AG Grid using the infinite row model. The
 * grid pulls pages on demand from the backend via `renderTable`, which already
 * accepts `start` + `limit` query params — no client-side prefetch of all rows.
 *
 * Filter changes purge the infinite cache so the grid re-fetches from row 0
 * with the new filter state.
 */
const TableRenderer: React.FC<TableRendererProps> = ({
  dashboardId,
  metadata,
  filters,
  agGridApiRef,
}) => {
  const [colDefs, setColDefs] = useState<ColDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [ready, setReady] = useState(false);
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const [containerRef, inView] = useInView<HTMLDivElement>('200px');

  const gridApiRef = useRef<GridApi | null>(null);
  // Stable ref to current filters so the IDatasource closure always reads the
  // latest value without us having to recreate the datasource on every render.
  const filtersRef = useRef<InteractiveFilter[]>(filters);
  filtersRef.current = filters;

  // One-shot bootstrap: fetch column defs + total row count via a tiny
  // (start=0, limit=1) call. The infinite row model then takes over for paging.
  useEffect(() => {
    if (!inView) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setReady(false);
    renderTable(dashboardId, metadata.index, filters, 0, 1)
      .then((res) => {
        if (cancelled) return;
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
        setReady(true);
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
  }, [dashboardId, metadata.index, JSON.stringify(filters), inView]);

  // When filters change after the grid is mounted, purge the cache so the
  // grid re-requests rows with the new filter state. The bootstrap effect
  // above also re-runs to refresh `total`.
  useEffect(() => {
    if (gridApiRef.current && ready) {
      gridApiRef.current.purgeInfiniteCache();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters), ready]);

  const datasource = useMemo<IDatasource>(
    () => ({
      getRows: (params: IGetRowsParams) => {
        const start = params.startRow;
        const limit = params.endRow - params.startRow;
        renderTable(
          dashboardId,
          metadata.index,
          filtersRef.current,
          start,
          limit,
        )
          .then((res) => {
            // lastRow tells the grid the total — required so the scrollbar is
            // accurate and the grid stops asking past the end.
            const lastRow =
              typeof res.total === 'number' && res.total >= 0
                ? res.total
                : undefined;
            params.successCallback(res.rows, lastRow);
            if (typeof res.total === 'number') setTotal(res.total);
          })
          .catch((err) => {
            setError(err?.message || String(err));
            params.failCallback();
          });
      },
    }),
    [dashboardId, metadata.index],
  );

  const onGridReady = (event: GridReadyEvent) => {
    gridApiRef.current = event.api;
    if (agGridApiRef) {
      // RefObject's `.current` is readonly in TS but writable at runtime.
      (agGridApiRef as React.MutableRefObject<GridApi | null>).current = event.api;
    }
    event.api.setGridOption('datasource', datasource);
  };

  const defaultColDef = useMemo<ColDef>(
    () => ({ flex: 1, minWidth: 100, resizable: true }),
    [],
  );

  return (
    <Paper
      ref={containerRef}
      p="sm"
      withBorder
      radius="md"
      style={{
        flex: 1,
        minHeight: 0,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {metadata.title && (
        <Text fw={600} size="sm" mb="xs">
          {metadata.title}
          {total > 0 && (
            <Text component="span" c="dimmed" size="xs" ml="xs">
              ({total} rows)
            </Text>
          )}
        </Text>
      )}
      {(!inView || loading) && (
        <Stack align="center" justify="center" gap="xs" style={{ flex: 1 }}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">Loading rows…</Text>
        </Stack>
      )}
      {error && !loading && (
        <Stack style={{ flex: 1 }} justify="center" align="center">
          <Text size="sm" c="red">Table failed: {error}</Text>
        </Stack>
      )}
      {ready && !loading && !error && (
        <div
          className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
          style={{ width: '100%', flex: 1, minHeight: 0 }}
        >
          <AgGridReact
            columnDefs={colDefs}
            defaultColDef={defaultColDef}
            rowModelType="infinite"
            cacheBlockSize={CACHE_BLOCK_SIZE}
            maxBlocksInCache={MAX_BLOCKS_IN_CACHE}
            onGridReady={onGridReady}
          />
        </div>
      )}
    </Paper>
  );
};

export default TableRenderer;
