import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Group,
  Modal,
  Popover,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  useMantineColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type { ColDef, GridApi, GridReadyEvent, IDatasource, IGetRowsParams } from 'ag-grid-community';

import { fetchJBrowseCalls, type InteractiveFilter, type JBrowseCall } from '../../api';
import { useUiScale } from '../../uiScale';
import type { NamedLocusSource } from './locusSources';
import {
  PICKER_PAGE_SIZE,
  cellValue,
  pickerColumns,
  pickerRequest,
  withNumericExtras,
  sourceColorVar,
  sourcesBody,
  formatCount,
  type PickerColumn,
} from './navigatorSteps';

/** Below this tile width the picker is a dialog: a popover would not fit. */
export const PICKER_MODAL_BELOW = 520;

const SEARCH_DEBOUNCE_MS = 250;
const POPOVER_WIDTH = 640;
const PICKER_HEIGHT = 420;
const MAX_BLOCKS_IN_CACHE = 20;

interface RegionPickerProps {
  opened: boolean;
  onClose: () => void;
  /** Width of the tile; narrower than `PICKER_MODAL_BELOW` opens a dialog. */
  width: number;
  sources: NamedLocusSource[];
  enabledSources: string[];
  /** Header of the score column (the primary `sort_by`). */
  scoreLabel?: string | null;
  dashboardId: string;
  index: string;
  filters: InteractiveFilter[];
  versionBody: Record<string, unknown>;
  /** A row was clicked: navigate the view (the filters are never touched). */
  onSelect: (call: JBrowseCall) => void;
  /** The element the popover hangs from. */
  children: React.ReactElement;
}

/** The picker's grid alone, for a surface that holds it (the tile's data
 *  table); `height` overrides the grid's own. */
export type RegionGridProps = Omit<RegionPickerProps, 'opened' | 'onClose' | 'children'> & {
  height?: number | string;
};

/**
 * Every region of the tile, paged from the server: click a header to sort,
 * type to search, switch between one row per merged region and one per source
 * row. A click on a row moves the view there.
 */
const RegionPicker: React.FC<RegionPickerProps> = (props) => {
  const { opened, onClose, width, children } = props;
  const body = <PickerBody {...props} />;
  if (width < PICKER_MODAL_BELOW) {
    return (
      <>
        {children}
        <Modal opened={opened} onClose={onClose} title="Regions" size="lg" centered>
          {body}
        </Modal>
      </>
    );
  }
  return (
    <Popover
      opened={opened}
      onChange={(next) => {
        if (!next) onClose();
      }}
      position="bottom-start"
      withinPortal
      shadow="md"
      width={POPOVER_WIDTH}
    >
      <Popover.Target>{children}</Popover.Target>
      <Popover.Dropdown p="xs">{body}</Popover.Dropdown>
    </Popover>
  );
};

const PickerBody: React.FC<RegionGridProps> = ({
  sources,
  enabledSources,
  scoreLabel,
  dashboardId,
  index,
  filters,
  versionBody,
  onSelect,
  width,
  height,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const uiScale = useUiScale();
  const [merged, setMerged] = useState(true);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const gridApiRef = useRef<GridApi | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  const names = useMemo(() => sources.map((s) => s.name), [sources]);
  const sourcesParam = sourcesBody(enabledSources, names);
  // The extra columns filter as numbers once the first rows show they hold
  // numbers (the manifest does not say).
  const [sampleRows, setSampleRows] = useState<JBrowseCall[]>([]);
  const columns = useMemo(
    () => withNumericExtras(pickerColumns({ sources, merged, scoreLabel }), sampleRows),
    [sources, merged, scoreLabel, sampleRows],
  );

  // The long-lived datasource reads the latest of these at request time.
  const live = useRef({ filters, versionBody, sourcesParam, merged, search, columns });
  live.current = { filters, versionBody, sourcesParam, merged, search, columns };
  const generation = useRef(0);

  const datasource = useMemo<IDatasource>(
    () => ({
      getRows: (params: IGetRowsParams) => {
        const gen = generation.current;
        const l = live.current;
        fetchJBrowseCalls(
          dashboardId,
          index,
          pickerRequest({
            filters: l.filters,
            versionBody: l.versionBody,
            startRow: params.startRow,
            endRow: params.endRow,
            sortModel: params.sortModel,
            columns: l.columns,
            search: l.search,
            sources: l.sourcesParam,
            merged: l.merged,
            filterModel: params.filterModel,
          }),
        )
          .then((res) => {
            // Asked before a filter, a pin, a source, the mode or the search
            // changed: the grid is already re-requesting for the new ones.
            if (gen !== generation.current) {
              params.failCallback();
              return;
            }
            setError(null);
            setTotal(res.total);
            if (params.startRow === 0 && res.rows.length) {
              setSampleRows((prev) => (prev.length ? prev : res.rows.slice(0, 50)));
            }
            params.successCallback(res.rows, res.total);
          })
          .catch((err) => {
            params.failCallback();
            if (gen === generation.current) setError((err as Error)?.message || String(err));
          });
      },
    }),
    [dashboardId, index],
  );

  // Everything that changes which regions the grid lists purges its cache. The
  // mode is not here: it remounts the grid (its columns change).
  const purgeKey = JSON.stringify([filters, versionBody, sourcesParam, search]);
  const firstPurge = useRef(true);
  useEffect(() => {
    if (firstPurge.current) {
      firstPurge.current = false;
      return;
    }
    generation.current += 1;
    const api = gridApiRef.current;
    if (api && !api.isDestroyed()) api.purgeInfiniteCache();
  }, [purgeKey]);

  const colDefs = useMemo<ColDef[]>(
    () => columns.map((c) => columnDef(c, sources)),
    [columns, sources],
  );
  const onGridReady = (event: GridReadyEvent) => {
    gridApiRef.current = event.api;
    event.api.setGridOption('datasource', datasource);
  };

  const gridHeight = height ?? (width < PICKER_MODAL_BELOW ? 340 : PICKER_HEIGHT - 84);
  const isDark = colorScheme === 'dark';
  return (
    <Stack gap="xs" data-testid="jbrowse-region-picker">
      <Group gap="xs" wrap="nowrap">
        <TextInput
          size="xs"
          style={{ flex: 1 }}
          placeholder="Search regions"
          leftSection={<Icon icon="tabler:search" width={14} height={14} />}
          value={searchInput}
          onChange={(e) => setSearchInput(e.currentTarget.value)}
          aria-label="Search regions"
        />
        <SegmentedControl
          size="xs"
          value={merged ? 'merged' : 'rows'}
          onChange={(v) => {
            generation.current += 1;
            setTotal(null);
            setMerged(v === 'merged');
          }}
          data={[
            { value: 'merged', label: 'Merged' },
            { value: 'rows', label: 'Rows' },
          ]}
        />
      </Group>
      <div
        className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
        style={
          {
            width: '100%',
            height: gridHeight,
            ...(uiScale !== 1
              ? {
                  '--ag-font-size': `${Math.round(13 * uiScale)}px`,
                }
              : {}),
          } as React.CSSProperties
        }
      >
        <AgGridReact
          key={merged ? 'merged' : 'rows'}
          columnDefs={colDefs}
          defaultColDef={{ resizable: true, suppressMovable: true }}
          rowModelType="infinite"
          cacheBlockSize={PICKER_PAGE_SIZE}
          maxBlocksInCache={MAX_BLOCKS_IN_CACHE}
          rowHeight={Math.round(28 * uiScale)}
          headerHeight={Math.round(32 * uiScale)}
          floatingFiltersHeight={Math.round(30 * uiScale)}
          suppressFieldDotNotation
          suppressCellFocus
          onGridReady={onGridReady}
          onRowClicked={(e) => {
            const call = e.data as JBrowseCall | undefined;
            if (call?.locus) onSelect(call);
          }}
        />
      </div>
      {error ? (
        <Text size="xs" c="red">
          {error}
        </Text>
      ) : (
        <Text size="xs" c="dimmed">
          {total === null
            ? 'Loading'
            : `${formatCount(total)} ${merged ? 'merged regions' : 'rows'}${
                search.trim() ? ' match' : ''
              }`}
        </Text>
      )}
    </Stack>
  );
};

function columnDef(c: PickerColumn, sources: readonly NamedLocusSource[]): ColDef {
  const def: ColDef = {
    colId: c.id,
    headerName: c.header,
    width: c.width,
    sortable: c.sortColumn !== null,
    valueGetter: (p) => cellValue(p.data as JBrowseCall | undefined, c.id),
  };
  if (c.filter) {
    // Server-side: AG Grid only hands its model to the datasource. One
    // condition per column, the ops the calls endpoint takes.
    def.filter = c.filter.kind === 'number' ? 'agNumberColumnFilter' : 'agTextColumnFilter';
    def.floatingFilter = true;
    def.filterParams =
      c.filter.kind === 'number'
        ? {
            maxNumConditions: 1,
            filterOptions: ['greaterThanOrEqual', 'lessThanOrEqual', 'equals', 'inRange'],
            debounceMs: 300,
          }
        : {
            maxNumConditions: 1,
            filterOptions: ['contains', 'equals', 'startsWith', 'notContains'],
            debounceMs: 300,
          };
  }
  if (c.id === 'source') {
    const colors = new Map(sources.map((s) => [s.name, sourceColorVar(s.color)]));
    def.cellRenderer = (p: { value?: string }) => {
      const color = p.value ? colors.get(p.value) : null;
      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {color && (
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: color,
                display: 'inline-block',
              }}
            />
          )}
          {p.value}
        </span>
      );
    };
  }
  return def;
}

export { PickerBody as RegionGrid };
export default RegionPicker;
