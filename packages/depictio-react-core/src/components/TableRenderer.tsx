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
  SelectionChangedEvent,
  SortChangedEvent,
} from 'ag-grid-community';

import { renderTable, InteractiveFilter, StoredMetadata } from '../api';
import { extractRowSelection } from '../selection';
import { useInView } from '../hooks/useInView';
import { useNewItemIds } from '../hooks/useNewItemIds';
import { useTransientFlag } from '../hooks/useTransientFlag';
import RefetchOverlay from './RefetchOverlay';

interface TableRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  /** When provided, the grid api is mirrored to this ref so the chrome's
   *  Download button can call `exportDataAsCsv` without prop-drilling. */
  agGridApiRef?: React.RefObject<GridApi | null>;
  /** Receives a filter entry with ``source="table_selection"`` whenever rows
   *  are checked / unchecked. ``value: []`` clears. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Counter to force refetch on realtime updates even when filters are unchanged. */
  refreshTick?: number;
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
  onFilterChange,
  refreshTick,
}) => {
  const [colDefs, setColDefs] = useState<ColDef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [ready, setReady] = useState(false);
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const [containerRef, inView] = useInView<HTMLDivElement>('200px');

  // The table must NOT filter itself by its own row-selection — otherwise
  // checking a row shrinks the grid to that row and the user can't see / un-
  // select the rest. Strip our own ``table_selection`` entry before fetching.
  // Other components still see it in their filters[] and narrow accordingly.
  const filtersForFetch = useMemo(
    () =>
      filters.filter(
        (f) => !(f.index === metadata.index && f.source === 'table_selection'),
      ),
    [filters, metadata.index],
  );

  const gridApiRef = useRef<GridApi | null>(null);
  // Stable ref to current filters so the IDatasource closure always reads the
  // latest value without us having to recreate the datasource on every render.
  const filtersRef = useRef<InteractiveFilter[]>(filtersForFetch);
  filtersRef.current = filtersForFetch;
  // Server-side sort state — populated either by the bootstrap response
  // (server's default acquisition-timestamp pick) or by the user clicking a
  // column header. We mirror it through a ref so the long-lived datasource
  // closure picks up the latest value without being recreated.
  const sortRef = useRef<{ sortBy: string | null; sortDir: 'asc' | 'desc' }>({
    sortBy: null,
    sortDir: 'desc',
  });

  // One-shot bootstrap: fetch column defs + total row count via a tiny
  // (start=0, limit=1) call. The infinite row model then takes over for
  // paging. Once ``ready`` flips on, we keep the grid mounted across
  // subsequent filter changes / realtime ticks — only the row cache is
  // purged (see effect below) and ``total`` is refreshed in the
  // ``datasource.getRows`` callback. We deliberately DON'T re-issue
  // ``setColDefs`` on filter / tick changes: that would replace the
  // ``columnDefs`` prop, which AG Grid treats as a full schema swap and
  // resets any user-applied sort the user clicked on a header. Schema
  // changes during a live session are exceedingly rare in this product
  // and require a full reload anyway.
  useEffect(() => {
    if (!inView || ready) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    renderTable(dashboardId, metadata.index, filtersForFetch, 0, 1)
      .then((res) => {
        if (cancelled) return;
        const selectionOn =
          Boolean(metadata.row_selection_enabled) && !!onFilterChange;
        // Default sort: prefer whatever column the server picked (it does
        // its own ``acquisition*`` lookup so ingest order matches the image
        // grid). Fall back to the same heuristic client-side in case an
        // older API responds without a ``sort_by`` field.
        const defaultSortField =
          (res.sort_by as string | null | undefined) ??
          res.columns
            .map((c) => c.field)
            .find(
              (f) =>
                /acquisition/i.test(f) && /(time|date|stamp)/i.test(f),
            ) ??
          null;
        const defaultSortDir =
          (res.sort_dir as 'asc' | 'desc' | undefined) ?? 'desc';
        sortRef.current = { sortBy: defaultSortField, sortDir: defaultSortDir };
        setColDefs(
          res.columns.map((c, i) => {
            const isNumeric = c.type === 'numericColumn';
            const isDefaultSort = c.field === defaultSortField;
            // ``type: 'numericColumn'`` is a built-in AG Grid type alias that
            // requires registering ``columnTypes`` on the grid options. We
            // don't, so passing it caused AG Grid to fall back to a no-op
            // type and the cells rendered blank for numeric data. Express
            // the same intent via concrete props instead: right-aligned
            // header/cell, number filter, no fancy formatter.
            return {
              field: c.field,
              headerName: c.headerName,
              sortable: true,
              filter: isNumeric ? 'agNumberColumnFilter' : true,
              resizable: true,
              cellClass: isNumeric ? 'ag-right-aligned-cell' : undefined,
              headerClass: isNumeric ? 'ag-right-aligned-header' : undefined,
              sort: isDefaultSort ? defaultSortDir : undefined,
              sortIndex: isDefaultSort ? 0 : undefined,
              // Surface the selection checkbox in the first column so users
              // see immediately the table is multi-selectable. ``headerCheckboxSelection``
              // gives a header-level select-all toggle.
              checkboxSelection: selectionOn && i === 0 ? true : undefined,
              headerCheckboxSelection: selectionOn && i === 0 ? true : undefined,
            };
          }),
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
  }, [dashboardId, metadata.index, inView, ready]);

  const showInitialLoader = !inView || (!ready && loading);
  const showRefetchOverlay = ready && loading;

  // When filters change after the grid is mounted, purge the cache so the
  // grid re-requests rows with the new filter state. Watch ``filtersForFetch``
  // (excludes our own row selection) so toggling a row doesn't trigger a
  // self-narrowing refetch.
  useEffect(() => {
    if (gridApiRef.current && ready) {
      gridApiRef.current.purgeInfiniteCache();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filtersForFetch), ready, refreshTick]);

  // ── New-row highlight pipeline ────────────────────────────────────────────
  // Snapshot the first page's IDs (by ``row_selection_column`` if defined,
  // else fallback to ``selection_column``) on every ``refreshTick`` change.
  // ``useNewItemIds`` only updates its prev-snapshot when the snapshotKey
  // changes, so filter edits don't produce false positives.
  const rowIdColumn =
    typeof metadata.row_selection_column === 'string'
      ? (metadata.row_selection_column as string)
      : typeof metadata.selection_column === 'string'
        ? (metadata.selection_column as string)
        : undefined;
  const [snapshotIds, setSnapshotIds] = useState<string[]>([]);
  useEffect(() => {
    if (!rowIdColumn || !ready) return;
    let cancelled = false;
    const pageSize =
      typeof metadata.page_size === 'number'
        ? Math.min(Math.max(metadata.page_size as number, 1), 200)
        : 50;
    renderTable(dashboardId, metadata.index, filtersForFetch, 0, pageSize)
      .then((res) => {
        if (cancelled) return;
        const ids: string[] = [];
        for (const row of res.rows as Array<Record<string, unknown>>) {
          const v = row?.[rowIdColumn!];
          if (v !== null && v !== undefined) ids.push(String(v));
        }
        setSnapshotIds(ids);
      })
      .catch(() => {
        // Highlight is best-effort — failure here is silent.
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, ready, rowIdColumn, JSON.stringify(filtersForFetch), refreshTick]);

  const newRowIds = useNewItemIds(snapshotIds, refreshTick);
  const highlightDurationMs =
    typeof metadata.highlight_duration_ms === 'number'
      ? (metadata.highlight_duration_ms as number)
      : 3000;
  const highlightActive = useTransientFlag(refreshTick, highlightDurationMs);

  const getRowClass = useMemo(() => {
    if (!rowIdColumn || !highlightActive || newRowIds.size === 0) return undefined;
    return (params: { data?: Record<string, unknown> }) => {
      const v = params.data?.[rowIdColumn];
      if (v === null || v === undefined) return undefined;
      return newRowIds.has(String(v)) ? 'depictio-row-new' : undefined;
    };
  }, [rowIdColumn, highlightActive, newRowIds]);

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
          sortRef.current.sortBy,
          sortRef.current.sortDir,
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

  // When the user clicks a header to sort (or clears a sort), capture the
  // new state into ``sortRef`` and purge the infinite cache so the next
  // ``getRows`` call re-fetches from row 0 with the server-side sort. The
  // header click itself doesn't reorder rows because the infinite row model
  // doesn't have all rows loaded — we MUST go back to the server.
  const onSortChanged = (event: SortChangedEvent) => {
    const sorted = event.api.getColumnState().find((c) => c.sort);
    sortRef.current = {
      sortBy: sorted?.colId ?? null,
      sortDir: (sorted?.sort as 'asc' | 'desc' | null) ?? 'desc',
    };
    event.api.purgeInfiniteCache();
  };

  const onGridReady = (event: GridReadyEvent) => {
    gridApiRef.current = event.api;
    if (agGridApiRef) {
      // RefObject's `.current` is readonly in TS but writable at runtime.
      (agGridApiRef as React.MutableRefObject<GridApi | null>).current = event.api;
    }
    // Apply the default sort via the column-state API so the header chevron
    // actually renders. ``colDef.sort`` is supposed to do this implicitly,
    // but with the infinite row model AG Grid sometimes drops the visual
    // indicator on first paint — explicit applyColumnState is the supported
    // workaround. Skipped when the user has already sorted (sortChanged
    // would have run before grid-ready in that case, vanishingly rare).
    if (sortRef.current.sortBy) {
      event.api.applyColumnState({
        state: [
          {
            colId: sortRef.current.sortBy,
            sort: sortRef.current.sortDir,
            sortIndex: 0,
          },
        ],
        defaultState: { sort: null },
      });
    }
    event.api.setGridOption('datasource', datasource);
  };

  const selectionEnabled = Boolean(metadata.row_selection_enabled) && !!onFilterChange;
  const selectionColumn =
    typeof metadata.row_selection_column === 'string'
      ? (metadata.row_selection_column as string)
      : undefined;

  const onSelectionChanged = (event: SelectionChangedEvent) => {
    if (!selectionEnabled || !selectionColumn || !onFilterChange) return;
    const selectedRows = event.api.getSelectedRows() as Array<Record<string, unknown>>;
    const values = extractRowSelection(selectedRows, selectionColumn);
    onFilterChange({
      index: metadata.index,
      value: values,
      source: 'table_selection',
      column_name: selectionColumn,
      interactive_component_type: 'MultiSelect',
      metadata: {
        dc_id: metadata.dc_id,
        column_name: selectionColumn,
        interactive_component_type: 'MultiSelect',
        selection_column: selectionColumn,
      },
    });
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
      {showInitialLoader && (
        <Stack align="center" justify="center" gap="xs" style={{ flex: 1 }}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">Loading rows…</Text>
        </Stack>
      )}
      {error && !ready && (
        <Stack style={{ flex: 1 }} justify="center" align="center">
          <Text size="sm" c="red">Table failed: {error}</Text>
        </Stack>
      )}
      {ready && (
        <div
          className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
          style={{ width: '100%', flex: 1, minHeight: 0, position: 'relative' }}
        >
          <AgGridReact
            columnDefs={colDefs}
            defaultColDef={defaultColDef}
            rowModelType="infinite"
            cacheBlockSize={CACHE_BLOCK_SIZE}
            maxBlocksInCache={MAX_BLOCKS_IN_CACHE}
            rowHeight={metadata.compact ? 28 : undefined}
            headerHeight={metadata.compact ? 32 : undefined}
            onGridReady={onGridReady}
            getRowClass={getRowClass}
            getRowId={
              rowIdColumn
                ? (params: { data?: Record<string, unknown> }) =>
                    String(params.data?.[rowIdColumn] ?? '')
                : undefined
            }
            // Polars columns can contain ``.`` (iris: ``sepal.length``,
            // ``petal.width``). Without this, AG Grid treats the dot as a
            // path separator and tries ``row.sepal.length`` (nested), which
            // fails because the row has flat keys → empty cells.
            suppressFieldDotNotation
            rowSelection={selectionEnabled ? 'multiple' : undefined}
            // Plain click adds/removes from the selection set — without this
            // AG Grid Community requires Ctrl/Shift modifiers, which is not
            // discoverable. The checkbox column rendered on the first column
            // (configured in ``setColDefs`` above) gives users a visual cue.
            rowMultiSelectWithClick={selectionEnabled || undefined}
            suppressRowClickSelection={selectionEnabled ? false : undefined}
            onSelectionChanged={selectionEnabled ? onSelectionChanged : undefined}
            onSortChanged={onSortChanged}
          />
          <RefetchOverlay visible={showRefetchOverlay} />
        </div>
      )}
    </Paper>
  );
};

export default TableRenderer;
