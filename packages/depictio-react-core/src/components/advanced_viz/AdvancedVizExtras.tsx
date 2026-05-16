import React, { createContext, useMemo } from 'react';
import {
  ActionIcon,
  Badge,
  Group,
  Popover,
  Stack,
  Text,
  useMantineColorScheme,
} from '@mantine/core';
import { AgGridReact } from 'ag-grid-react';
import type { ColDef } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import { Icon } from '@iconify/react';

/**
 * Bridges the per-renderer Settings + Show-data popovers into ComponentChrome's
 * `extraActions` slot — that way the ActionIcons sit in the same hover-revealed
 * row as metadata/fullscreen/download/reset and match their Mantine styling
 * (variant=light, size=sm), instead of floating in the panel header.
 *
 * Wiring:
 *  - ComponentRenderer's advanced_viz dispatch holds the React node state and
 *    renders an <AdvancedVizExtrasProvider> around the renderer.
 *  - AdvancedVizFrame, when given controls / dataRows, builds the two
 *    Popovers and calls `publish(jsx)`. ComponentRenderer threads the
 *    published JSX into `extraActions` so chrome renders them.
 *
 * The popovers themselves use Mantine's Floating-UI-backed Popover which
 * portals the dropdown to document.body — so even when the chrome action
 * row fades out on mouseleave (the action row is opacity-gated), an OPEN
 * dropdown stays visible. Closing requires a click outside (closeOnClickOutside).
 */

// Row-count thresholds for the Show-data popover.
//   ≤ PAGINATION_THRESHOLD → single scrollable view (DOM virtualization handles it).
//   > PAGINATION_THRESHOLD → AG Grid paginates (default page size 100).
// The data endpoint /advanced_viz/data caps at 100k rows so we never need
// the SSRM (server-side row model) here — client-side virtualization
// comfortably handles 100k rows.
const PAGINATION_THRESHOLD = 1000;

type Publisher = (jsx: React.ReactNode) => void;

export const AdvancedVizExtrasContext = createContext<Publisher | null>(null);

interface ProviderProps {
  children: React.ReactNode;
  /** Receives the latest JSX the framed renderer wants to publish. */
  onChange: (jsx: React.ReactNode) => void;
}

export const AdvancedVizExtrasProvider: React.FC<ProviderProps> = ({ children, onChange }) => (
  <AdvancedVizExtrasContext.Provider value={onChange}>{children}</AdvancedVizExtrasContext.Provider>
);

interface SettingsPopoverProps {
  controls: React.ReactNode;
}

export const AdvancedVizSettingsPopover: React.FC<SettingsPopoverProps> = ({ controls }) => {
  // Tooltip wraps Popover.Target's child via a sibling span — putting Tooltip
  // *inside* Popover.Target wraps the ActionIcon, which breaks Mantine's
  // ref-forwarding and produces a multi-click open bug (the click-outside
  // detector sees the cloned wrapper as "outside" and closes the popover on
  // the very mousedown that opened it). Native HTML `title` keeps a hover
  // label without an extra wrapper.
  //
  // closeOnClickOutside is disabled here because the controls inside the
  // dropdown include Mantine Selects whose own dropdown menus are portaled
  // to document.body — clicking those was firing the outer popover's
  // "click outside" detector and closing Settings before `onChange` could
  // commit (so users couldn't change the embedding compute method). The
  // popover can still be dismissed by clicking the settings icon again
  // (Mantine toggles on target click) or by pressing Escape.
  //
  // trapFocus is also off: with it on, clicking the chevron up/down buttons
  // inside a Mantine NumberInput moves focus to the buttons, and Mantine's
  // focus trap then races against React's event re-rendering — the user
  // sees the popover "freeze" (still visible but no click registers).
  // Without trapFocus, the popover behaves like a normal floating panel.
  return (
    <Popover
      position="bottom-end"
      shadow="md"
      withArrow
      closeOnClickOutside={false}
      closeOnEscape
    >
      <Popover.Target>
        <ActionIcon
          variant="light"
          color="teal"
          size="sm"
          aria-label="Viz settings"
          title="Viz settings"
        >
          <Icon icon="tabler:adjustments-horizontal" width={16} height={16} />
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown p="sm" style={{ maxWidth: 380 }}>
        <Stack gap="xs">
          <Text size="xs" fw={600} c="dimmed">
            Viz controls
          </Text>
          {controls}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

/** Per-row threshold annotation (UP/DN/NS for volcano, HIT/MISS for
 *  manhattan, etc.). Values must be aligned with the dataRows arrays. */
export interface TierAnnotation {
  /** One label per row, same length as any column in `dataRows`. */
  values: string[];
  /** Order in which tier values sort to the top (e.g. ['UP','DN'] before NS).
   *  Tiers not in this list sort below those that are, alphabetically. */
  selectedOrder?: string[];
  /** Optional pretty header for the synthetic tier column. */
  columnLabel?: string;
}

interface DataPopoverProps {
  dataRows: Record<string, unknown[]>;
  dataColumns?: string[];
  tierAnnotation?: TierAnnotation;
}

const TIER_COLUMN = '__tier';
const ROW_ID_COLUMN = '__rowIndex';

export const AdvancedVizDataPopover: React.FC<DataPopoverProps> = ({
  dataRows,
  dataColumns,
  tierAnnotation,
}) => {
  const { colorScheme } = useMantineColorScheme();

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

  // Column-oriented → row-oriented for AG Grid. The data endpoint caps at
  // 100k rows; conversion is fast enough to run eagerly so the popover can
  // stay uncontrolled (controlled + manual onClick fought with Mantine's
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
          const v = params.value as string | undefined;
          if (!v) return null;
          const tint = (name: string) =>
            `light-dark(var(--mantine-color-${name}-1), color-mix(in srgb, var(--mantine-color-${name}-9) 35%, transparent))`;
          if (v === 'UP') return { background: tint('pink'), fontWeight: 600 };
          if (v === 'DN') return { background: tint('blue'), fontWeight: 600 };
          if (v === 'HIT' || v === 'ABOVE')
            return { background: tint('teal'), fontWeight: 600 };
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
    return defs;
  }, [cols, dataRows, tierValues, tierSortRank, tierColumnLabel]);

  if (cols.length === 0) return null;

  const isDark = colorScheme === 'dark';
  const paginated = total > PAGINATION_THRESHOLD;

  // closeOnClickOutside disabled for the same reason as the Settings popover:
  // AG Grid's column menu + filter operator dropdown ("contains", "equals",
  // …) is rendered in its own portal at document.body level. When users
  // clicked those, the popover's outside-click detector saw them as outside
  // and closed the table — the dropdown flashed for ~100ms before everything
  // disappeared, and sorting / filtering became impossible. Dismiss via the
  // icon (toggle) or Escape.
  return (
    <Popover
      position="bottom-end"
      shadow="md"
      withArrow
      closeOnClickOutside={false}
      closeOnEscape
    >
      <Popover.Target>
        <ActionIcon
          variant="light"
          color="violet"
          size="sm"
          aria-label="Show underlying data"
          title="Show data"
        >
          <Icon icon="tabler:table" width={16} height={16} />
        </ActionIcon>
      </Popover.Target>
      <Popover.Dropdown
        p="sm"
        style={{
          width: 'min(820px, 88vw)',
          // Cap the dropdown so it never extends past the viewport;
          // overflow:auto lets users scroll the whole popover when the grid
          // pushes content below the bottom of the screen.
          maxHeight: '85vh',
          overflow: 'auto',
        }}
      >
        <Stack gap="xs">
          <Group gap={6} justify="space-between">
            <Text size="xs" fw={600} c="dimmed">
              Underlying data
            </Text>
            <Badge size="xs" color="gray" variant="light">
              {total.toLocaleString()} rows · {cols.length} cols
              {paginated ? ' · paginated' : ''}
            </Badge>
          </Group>
          {/* AG Grid needs a definite height to render rows — `flex: 1`
              inside a content-sized popover collapses to 0 and the grid
              vanishes. Keep an explicit pixel height; the grid handles its
              own scrolling internally.
              The Alpine CSS-variable overrides shrink rows + font so the
              popover shows ~2× more rows in the same space — the default
              42px row height was too sparse for a quick data peek. */}
          <div
            className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
            style={
              {
                width: '100%',
                height: 420,
                '--ag-font-size': '11px',
                '--ag-row-height': '24px',
                '--ag-header-height': '28px',
                '--ag-cell-horizontal-padding': '6px',
                '--ag-grid-size': '4px',
                '--ag-list-item-height': '20px',
              } as React.CSSProperties
            }
          >
            <AgGridReact
              rowData={rowData}
              columnDefs={colDefs}
              // Stable row identity → AG Grid diffs rows instead of replacing
              // them wholesale, so the user's filter/sort survives any
              // upstream rowData rebuild (e.g. when a tier renderer recomputes
              // `figure.tiers` after a Settings tweak).
              getRowId={(params) =>
                String((params.data as Record<string, unknown> | undefined)?.[ROW_ID_COLUMN] ?? '')
              }
              animateRows={false}
              rowBuffer={25}
              rowHeight={24}
              headerHeight={28}
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
      </Popover.Dropdown>
    </Popover>
  );
};
