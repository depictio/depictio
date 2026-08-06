import React, { Suspense, lazy, useMemo, useRef, useState } from 'react';
import { ActionIcon, Badge, Center, Loader, Popover, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  fetchMapData,
  type InteractiveFilter,
  type MapDataResponse,
  type StoredMetadata,
} from '../../api';
import {
  filtersExcludingOwn,
  isMapSelectionEnabled,
  mapSelectionFilter,
  mapSelectionValues,
} from '../../selection';

// AG Grid is ~250kB of CSS plus its own chunk, and the map branch of
// ComponentRenderer is imported eagerly — a static import here would put the
// grid on every dashboard's boot path. Mantine unmounts a closed dropdown, so
// this resolves on first open and never otherwise.
const DataGridBody = lazy(() => import('../data/DataGridBody'));

export interface MapDataButtonProps {
  /** The map's OWNING dashboard (tab), which is not always the one on screen:
   *  a floating map is authored on one tab and shown on all of them. */
  dashboardId: string;
  metadata: StoredMetadata;
  /** Every dashboard filter. The button splits them itself: the map's own
   *  selection is what pre-ticks rows, everything else is what narrows them. */
  filters: InteractiveFilter[];
  /** Omit to make the table read-only. Given one, ticking rows selects on the
   *  map — the same filter, by another gesture. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

type LoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; data: MapDataResponse }
  | { status: 'error'; message: string };

/**
 * "Show underlying data" for a map, mirroring the advanced-viz affordance.
 *
 * The rows are fetched when the popover opens rather than with the map: a
 * dashboard can carry several maps, and none of their tables are worth a
 * request until someone asks to see one.
 */
const MapDataButton: React.FC<MapDataButtonProps> = ({
  dashboardId,
  metadata,
  filters,
  onFilterChange,
}) => {
  const componentId = metadata.index;
  // The table shows every point the map shows, so it is fetched against the
  // same list the map fetches with: everything *except* this map's own
  // selection. Ticking rows must be able to widen the selection, not just
  // narrow it to what is already ticked.
  const filtersForFetch = useMemo(
    () => filtersExcludingOwn(filters, componentId, 'map_selection'),
    [filters, componentId],
  );
  const selected = useMemo(
    () => mapSelectionValues(filters, componentId),
    [filters, componentId],
  );
  const selectionColumn =
    typeof metadata.selection_column === 'string'
      ? (metadata.selection_column as string)
      : undefined;
  const selectable =
    isMapSelectionEnabled(metadata, Boolean(onFilterChange)) && Boolean(selectionColumn);

  const [opened, setOpened] = useState(false);
  const [state, setState] = useState<LoadState>({ status: 'idle' });
  const abortRef = useRef<AbortController | null>(null);
  // What the currently-held data was fetched for; only ever set on success.
  // Re-opening after nothing changed is instant, re-opening after a filter
  // moved refetches. Computed inside `load` rather than at render time: both
  // call sites hand us a fresh array on every dashboard interaction, and
  // stringifying it per map per keystroke to decide the staleness of a popover
  // that is almost always closed is pure waste.
  const loadedKeyRef = useRef<string | null>(null);

  const load = () => {
    const filterKey = JSON.stringify(filtersForFetch);
    if (loadedKeyRef.current === filterKey) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ status: 'loading' });
    fetchMapData(dashboardId, componentId, filtersForFetch, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        loadedKeyRef.current = filterKey;
        setState({ status: 'ready', data });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        loadedKeyRef.current = null;
        setState({ status: 'error', message: err instanceof Error ? err.message : String(err) });
      });
  };

  const close = () => abortRef.current?.abort();

  return (
    // closeOnClickOutside disabled for the same reason as the advanced-viz
    // popover: AG Grid renders its column and filter-operator menus in their
    // own portal at document.body level, and the outside-click detector reads
    // clicks on those as "outside" and shuts the table. Dismiss via the close
    // button in the table's header, the icon (toggle), or Escape.
    //
    // Controlled `opened` so that close button can reach it. Mantine only
    // attaches its own toggle to the target while UNcontrolled
    // (`PopoverTarget`: `...!ctx.controlled ? { onClick: ctx.onToggle }`), so
    // the trigger carries its own onClick below. `onOpen`/`onClose` fire either
    // way — they come off a `useDidUpdate` on the resolved open state.
    <Popover
      position="bottom-end"
      shadow="md"
      withArrow
      closeOnClickOutside={false}
      closeOnEscape
      opened={opened}
      onChange={setOpened}
      onOpen={load}
      onClose={close}
    >
      <Popover.Target>
        <ActionIcon
          variant="light"
          color="violet"
          size="sm"
          aria-label="Show underlying data"
          title="Show data"
          data-no-drag
          onClick={() => setOpened((v) => !v)}
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
        {state.status === 'error' ? (
          <Text size="xs" c="red">
            Could not load the map's data: {state.message}
          </Text>
        ) : state.status === 'ready' ? (
          <Suspense
            fallback={
              <Center h={120}>
                <Loader size="sm" />
              </Center>
            }
          >
            <DataGridBody
              dataRows={state.data.rows}
              dataColumns={state.data.columns}
              onClose={() => setOpened(false)}
              selection={
                selectable && selectionColumn
                  ? {
                      column: selectionColumn,
                      selected,
                      onChange: (values) =>
                        onFilterChange?.(mapSelectionFilter(metadata, values)),
                    }
                  : undefined
              }
              extraBadge={
                state.data.truncated ? (
                  <Badge size="xs" color="orange" variant="light">
                    first {state.data.row_count.toLocaleString()} of{' '}
                    {state.data.total_rows.toLocaleString()}
                  </Badge>
                ) : undefined
              }
            />
          </Suspense>
        ) : (
          <Center h={120}>
            <Loader size="sm" />
          </Center>
        )}
      </Popover.Dropdown>
    </Popover>
  );
};

export default MapDataButton;
