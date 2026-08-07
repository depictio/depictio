import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { Badge, CloseButton, Group, Stack, Text, useMantineColorScheme } from '@mantine/core';
import { AgGridReact } from 'ag-grid-react';
import type { ColDef, GridApi, SelectionChangedEvent } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';

import { extractRowSelection } from '../../selection';
import { useUiScale } from '../../uiScale';

/**
 * The "underlying data" grid, shared by every show-data popover.
 *
 * Takes column-oriented rows — the shape both `/advanced_viz/data` and
 * `/dashboards/map_data` answer in — and renders a sortable, filterable AG Grid
 * sized to sit inside a popover dropdown. The popover itself (trigger icon,
 * dismissal rules, how the data is fetched) belongs to each caller; this is only
 * the body.
 */

// Row-count thresholds.
//   ≤ PAGINATION_THRESHOLD → single scrollable view (DOM virtualization handles it).
//   > PAGINATION_THRESHOLD → AG Grid paginates (default page size 100).
// The data endpoints cap well below the point where the SSRM (server-side row
// model) would be needed — client-side virtualization comfortably handles 100k
// rows.
const PAGINATION_THRESHOLD = 1000;

export interface TierAnnotation {
  /** One label per row, same length as any column in `dataRows`. */
  values: string[];
  /** Order in which tier values sort to the top (e.g. ['UP','DN'] before NS).
   *  Tiers not in this list sort below those that are, alphabetically. */
  selectedOrder?: string[];
  /** Optional pretty header for the synthetic tier column. */
  columnLabel?: string;
}

/** Turns the grid into a selection surface: tick rows, filter the dashboard. */
export interface DataGridSelection {
  /** Column whose values are the filter — one value per ticked row, deduped. */
  column: string;
  /** Values currently selected, from wherever they were selected. Ticks the
   *  matching rows, so a selection made elsewhere shows up here. */
  selected: string[];
  onChange: (values: string[]) => void;
}

export interface DataGridBodyProps {
  dataRows: Record<string, unknown[]>;
  dataColumns?: string[];
  tierAnnotation?: TierAnnotation;
  /** Appended after the "N rows · M cols" badge — e.g. a truncation notice. */
  extraBadge?: React.ReactNode;
  /** Omit for a read-only peek at the data. */
  selection?: DataGridSelection;
  /** AG Grid needs a definite height. Popovers keep the fixed pixel default;
   *  the inspector's Data tab passes '100%' to fill its docked panel. */
  height?: number | string;
  /** Puts a close button at the end of the header row. Both callers hold their
   *  popover open through outside clicks (AG Grid portals its column menus to
   *  the body, and the outside-click detector reads those as outside), which
   *  leaves the trigger icon and Escape as the only ways out — neither of them
   *  visible from inside a table that covers most of the screen. */
  onClose?: () => void;
}

const TIER_COLUMN = '__tier';
const ROW_ID_COLUMN = '__rowIndex';

/** Set equality — selection order carries no meaning. */
function sameValues(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const set = new Set(b);
  return a.every((v) => set.has(v));
}

const DataGridBody: React.FC<DataGridBodyProps> = ({
  dataRows,
  dataColumns,
  tierAnnotation,
  extraBadge,
  selection,
  height = 420,
  onClose,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const uiScale = useUiScale();
  const gridApiRef = useRef<GridApi | null>(null);
  const selectable = selection != null;

  const cols = useMemo(
    () => (dataColumns?.filter((c) => c in dataRows) ?? Object.keys(dataRows)) as string[],
    [dataRows, dataColumns],
  );
  const total = cols.length > 0 ? dataRows[cols[0]]?.length ?? 0 : 0;

  // Stabilise references so AG Grid doesn't lose scroll state. Renderers
  // pass `tierAnnotation` as a fresh object literal each render
  // (`tierAnnotation={figure?.tiers ? { values, selectedOrder, columnLabel }
  // : undefined}`), so depending on `tierAnnotation` directly would
  // invalidate rowData/colDefs every parent render. The inner `values`
  // array, however, comes from the renderer's `figure` useMemo and is a
  // stable reference between renders — depend on that instead. Same logic
  // for selectedOrder / columnLabel below.
  const tierValues = tierAnnotation?.values;
  const tierSelectedOrderKey = tierAnnotation?.selectedOrder?.join('|') ?? '';
  const tierColumnLabel = tierAnnotation?.columnLabel ?? 'tier';

  // Column-oriented → row-oriented for AG Grid. The data endpoints cap the row
  // count, so conversion is fast enough to run eagerly and let the popover stay
  // uncontrolled (controlled + manual onClick fought with Mantine's
  // click-outside detector and made the icon require multiple clicks).
  const rowData = useMemo(() => {
    if (cols.length === 0) return [];
    const out: Record<string, unknown>[] = [];
    for (let i = 0; i < total; i++) {
      const row: Record<string, unknown> = { [ROW_ID_COLUMN]: i };
      for (const c of cols) row[c] = dataRows[c][i];
      if (tierValues && tierValues[i] != null) row[TIER_COLUMN] = tierValues[i];
      out.push(row);
    }
    return out;
  }, [cols, dataRows, total, tierValues]);

  // When tiers are present, sort selected rows to the top by default. This is
  // what the user wants: "way to filter/show first those selected rows".
  const tierSortRank = useMemo(() => {
    if (!tierValues) return null;
    const order = tierSelectedOrderKey ? tierSelectedOrderKey.split('|') : [];
    const rank = new Map<string, number>();
    order.forEach((t, i) => rank.set(t, i));
    return rank;
  }, [tierValues, tierSelectedOrderKey]);

  const colDefs = useMemo<ColDef[]>(() => {
    const defs: ColDef[] = [];
    if (tierValues && tierSortRank) {
      defs.push({
        field: TIER_COLUMN,
        headerName: tierColumnLabel,
        sortable: true,
        filter: 'agTextColumnFilter',
        floatingFilter: true,
        resizable: true,
        // `initialPinned` / `initialSort` apply once on grid creation. The
        // controlled equivalents (`pinned`/`sort`) re-assert themselves every
        // time AG Grid re-applies columnDefs, which makes user clicks on
        // other column headers silently no-op (the tier column stays as
        // primary sort) and keeps the filter model stuck on this column.
        initialPinned: 'left',
        initialSort: 'asc',
        width: 100,
        comparator: (valueA, valueB) => {
          const a = (valueA as string) ?? '';
          const b = (valueB as string) ?? '';
          // Rows with a ranked tier sort first (in selectedOrder), the rest
          // fall back to alphabetical so the column stays stable.
          const ra = tierSortRank.has(a) ? tierSortRank.get(a)! : 1000;
          const rb = tierSortRank.has(b) ? tierSortRank.get(b)! : 1000;
          if (ra !== rb) return ra - rb;
          return a.localeCompare(b);
        },
        valueGetter: (params) =>
          (params.data as Record<string, unknown> | undefined)?.[TIER_COLUMN],
        cellStyle: (params) => {
          // Subtle tint per tier. `light-dark()` swaps between the very-light
          // shade-1 (visible against a white grid) and the deeper shade-9 with
          // reduced opacity (visible against the dark grid) — shade-1 alone
          // washes out in dark mode.
          //
          // ``tierSortRank`` carries the user's ``selectedOrder`` (e.g. flipped
          // to ['BELOW'] when the renderer pins highlight=below). Only rows in
          // selectedOrder get a coloured tint; the rest stay neutral so the
          // table emphasis tracks the chips + plot markers.
          const v = params.value as string | undefined;
          if (!v) return null;
          if (tierSortRank && !tierSortRank.has(v)) return null;
          const tint = (name: string) =>
            `light-dark(var(--mantine-color-${name}-1), color-mix(in srgb, var(--mantine-color-${name}-9) 35%, transparent))`;
          if (v === 'UP') return { background: tint('pink'), fontWeight: 600 };
          if (v === 'DN') return { background: tint('blue'), fontWeight: 600 };
          if (v === 'HIT' || v === 'ABOVE')
            return { background: tint('teal'), fontWeight: 600 };
          if (v === 'BELOW') return { background: tint('orange'), fontWeight: 600 };
          return null;
        },
      });
    }
    for (const c of cols) {
      // Pick a numeric-aware filter when the first non-null value is a
      // number — AG Grid's text filter doesn't do range comparisons
      // (>, <, between), which is what makes filtering Manhattan-style
      // position / score columns actually useful.
      const firstVal = dataRows[c]?.find((v) => v != null);
      const isNumeric = typeof firstVal === 'number';
      defs.push({
        field: c,
        headerName: c,
        sortable: true,
        filter: isNumeric ? 'agNumberColumnFilter' : 'agTextColumnFilter',
        floatingFilter: true,
        resizable: true,
        // Polars columns can carry dots (e.g. ``sepal.length``); without a
        // valueGetter AG Grid treats the dot as a nested-path separator.
        valueGetter: (params) =>
          (params.data as Record<string, unknown> | undefined)?.[c],
      });
    }
    // Checkboxes ride the leading column, AG Grid's usual place for them. On a
    // map that is the selection column itself: `map_data` returns it first
    // precisely so the table opens on what the map is about.
    if (selectable && defs.length > 0) {
      defs[0] = {
        ...defs[0],
        checkboxSelection: true,
        // Ticks/unticks everything the grid's own column filters have left
        // visible, which is the useful bulk gesture: narrow the table down to a
        // region, then take all of it.
        headerCheckboxSelection: true,
        headerCheckboxSelectionFilteredOnly: true,
      };
    }
    return defs;
  }, [cols, dataRows, tierValues, tierSortRank, tierColumnLabel, selectable]);

  // Tick the rows whose value is already selected — the selection is shared
  // with the map, so opening the table after lassoing has to show that lasso.
  // Runs on first render of the data and whenever the selection moves under us.
  const selectedKey = selection ? [...selection.selected].sort().join('\u0000') : '';
  const syncTicks = useCallback(() => {
    const api = gridApiRef.current;
    if (!api || !selection) return;
    const wanted = new Set(selection.selected);
    api.forEachNode((node) => {
      const raw = (node.data as Record<string, unknown> | undefined)?.[selection.column];
      const should = raw != null && wanted.has(String(raw));
      if (node.isSelected() !== should) node.setSelected(should);
    });
    // `selection` is a fresh object each render; the column and the values are
    // what actually matter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection?.column, selectedKey]);

  useEffect(syncTicks, [syncTicks]);

  const onSelectionChanged = (event: SelectionChangedEvent) => {
    if (!selection) return;
    const values = extractRowSelection(
      event.api.getSelectedRows() as Array<Record<string, unknown>>,
      selection.column,
    );
    // `syncTicks` ticking rows fires this event too. Comparing against what is
    // already selected is what stops that echo becoming an update loop — and it
    // holds however AG Grid batches its events, which a "currently applying"
    // flag would not.
    //
    // Re-syncing rather than plain returning covers the other way to arrive
    // here: the filter is a set of VALUES, so when several rows carry the same
    // one, unticking a single row leaves that value selected and the row has to
    // go back. Nothing changes in the common case, so this cannot loop.
    if (sameValues(values, selection.selected)) {
      syncTicks();
      return;
    }
    selection.onChange(values);
  };

  const isDark = colorScheme === 'dark';
  const paginated = total > PAGINATION_THRESHOLD;

  const closeButton = onClose ? (
    <CloseButton size="sm" aria-label="Close the data table" onClick={onClose} />
  ) : null;

  if (cols.length === 0) {
    return (
      <Group gap={6} justify="space-between" wrap="nowrap">
        <Text size="xs" c="dimmed">
          No rows to show.
        </Text>
        {closeButton}
      </Group>
    );
  }

  return (
    <Stack gap="xs">
      <Group gap={6} justify="space-between" wrap="nowrap">
        <Text size="xs" fw={600} c="dimmed">
          Underlying data
        </Text>
        <Group gap={6} wrap="nowrap">
          <Badge size="xs" color="gray" variant="light">
            {total.toLocaleString()} rows · {cols.length} cols
            {paginated ? ' · paginated' : ''}
          </Badge>
          {extraBadge}
          {closeButton}
        </Group>
      </Group>
      {/* AG Grid needs a definite height to render rows — `flex: 1`
          inside a content-sized popover collapses to 0 and the grid
          vanishes. Keep an explicit height; the grid handles its
          own scrolling internally.
          The Alpine CSS-variable overrides shrink rows + font so the
          popover shows ~2× more rows in the same space — the default
          42px row height was too sparse for a quick data peek. */}
      <div
        className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
        style={
          {
            width: '100%',
            height,
            flex: height === '100%' ? 1 : undefined,
            minHeight: 0,
            '--ag-font-size': `${Math.round(11 * uiScale)}px`,
            '--ag-row-height': `${Math.round(24 * uiScale)}px`,
            '--ag-header-height': `${Math.round(28 * uiScale)}px`,
            '--ag-cell-horizontal-padding': '6px',
            '--ag-grid-size': '4px',
            '--ag-list-item-height': `${Math.round(20 * uiScale)}px`,
          } as React.CSSProperties
        }
      >
        <AgGridReact
          // rowHeight/headerHeight are initial-only grid options — remount on
          // font-scale change so the new metrics apply.
          key={`scale-${uiScale}`}
          rowData={rowData}
          columnDefs={colDefs}
          // Stable row identity → AG Grid diffs rows instead of replacing
          // them wholesale, so the user's filter/sort survives any
          // upstream rowData rebuild (e.g. when a tier renderer recomputes
          // `figure.tiers` after a Settings tweak).
          getRowId={(params) =>
            String((params.data as Record<string, unknown> | undefined)?.[ROW_ID_COLUMN] ?? '')
          }
          onGridReady={(e) => {
            gridApiRef.current = e.api;
            syncTicks();
          }}
          rowSelection={selectable ? 'multiple' : undefined}
          // Plain click toggles a row, as in TableRenderer: AG Grid Community
          // otherwise wants Ctrl/Shift, which nobody discovers.
          rowMultiSelectWithClick={selectable || undefined}
          onSelectionChanged={selectable ? onSelectionChanged : undefined}
          animateRows={false}
          rowBuffer={25}
          rowHeight={Math.round(24 * uiScale)}
          headerHeight={Math.round(28 * uiScale)}
          pagination={paginated}
          paginationPageSize={100}
          paginationPageSizeSelector={[50, 100, 250, 500]}
          defaultColDef={{ minWidth: 90, flex: 1, suppressHeaderMenuButton: false }}
          // Render filter / column menus at document.body level so the
          // popover's overflow:auto doesn't clip them (without this the
          // "contains" operator menu had height 0 and appeared to flash
          // open for a frame).
          popupParent={typeof document !== 'undefined' ? document.body : undefined}
        />
      </div>
    </Stack>
  );
};

export default DataGridBody;
