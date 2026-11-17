import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Icon } from '@iconify/react';
import { ActionIcon, Badge, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { AdvancedVizKind, fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { mantineCategoricalPalette } from '../../colors';
import { isStaleFetch } from '../../fetchQueue';
import { useCategoryColorSource, useCategoryPalette } from '../../hooks/useCategoryColors';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  filtersForSelector,
  selectionValuesFor,
  valuesOnColumn,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import { demandForPx } from './contentDemand';
import {
  VizControlGroup,
  VizMultiSelect,
  VizNumberInput,
  VizSegmented,
  VizSelect,
  VizSwitch,
} from './controls/VizControls';
import FamilySection, {
  familyRowColumns,
  hasFamily,
  type FamilyConfig,
  type PinnedRowValues,
} from './ranked_table/FamilySection';
import RankedPopover, { type PopoverContent } from './ranked_table/RankedPopover';
import {
  badgeColourOf,
  barFraction,
  barLabel,
  barRange,
  boundFromColumn,
  categoricalColumns,
  clampTopN,
  columnLabel,
  columnsToFetch,
  distinctValues,
  EMPTY_CELL,
  formatCell,
  isFiltering,
  isNumericColumn,
  missingColumns,
  pickDefaultRow,
  rankedEcho,
  rankRows,
  rowsKept,
  sortableColumns,
  toNumber,
  type BarRange,
  type RankedRow,
  type RankedTableColumnSpec,
} from './ranked_table/rankedTable';
import { usePersistedVizControl } from './usePersistedVizControl';
import './ranked_table/rankedTable.css';

/** Mirrors `RankedTableConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there, and `test_advanced_viz_config_alignment`
 *  enforces it. */
interface RankedTableConfig extends FamilyConfig {
  title_col: string;
  score_col: string;
  subtitle_col?: string | null;
  rank_col?: string | null;
  descending?: boolean;
  columns?: RankedTableColumnSpec[];
  labels?: Record<string, string> | null;
  popover_columns?: string[];
  popover_grid_columns?: string[];
  top_n?: number;
  medals?: boolean;
  selection_enabled?: boolean;
  selection_column?: string | null;
  family_open?: boolean;
  sort_col?: string | null;
  min_score?: number | null;
  filter_col?: string | null;
  filter_values?: string[];
  hidden_columns?: string[];
  compact?: boolean;
  default_select_by?: string | null;
  default_select_order?: 'desc' | 'asc';
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: RankedTableConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

// A leaderboard is the top of an ordering: the server never samples this kind
// (`KIND_SAMPLING_POLICY["ranked_table"] == "none"`), because a sampled frame
// drops candidates and every rank under them shifts.
const RANKED_TABLE_VIZ_KIND: AdvancedVizKind = 'ranked_table';

const DEFAULT_TOP_N = 50;
const ROW_PX = 40;
const COMPACT_ROW_PX = 30;
const HEADER_PX = 34;
const FOOT_PX = 22;
const DEMAND_ROWS = 12;

type Pointer = { x: number; y: number };

/** The popover's anchor for a row: beside its right edge, level with its top,
 *  so the pointer reaches the popover without crossing another row. */
function rowAnchor(el: Element): Pointer {
  const box = el.getBoundingClientRect();
  // `placePopover` adds its 14px offset to both axes.
  return { x: box.right - 10, y: box.top - 14 };
}

/** Anything the tile shows as a cell: a string, never a raw object. */
function cellOf(rows: Record<string, unknown[]>, column: string | null | undefined, i: number): unknown {
  return column ? rows[column]?.[i] : undefined;
}

/**
 * A leaderboard of candidates ordered by a score.
 *
 * Ordering, dense ranks, bar scales and badge colours come from
 * `ranked_table/rankedTable.ts` (tested without a DOM); this component fetches
 * the frame, resolves the theme, draws the table and wires the hover, the pin
 * and the pick. A click on a row emits the dashboard's selection filter on
 * `selection_column` (else the title column) and pins its popover when a family
 * is bound; the picked rows are read back from the filter list, so a Reset
 * from the tile chrome clears the outline.
 */
const RankedTableRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as RankedTableConfig;

  const [topN, setTopN] = usePersistedVizControl<number>(metadata, 'top_n', DEFAULT_TOP_N);
  const [descending, setDescending] = usePersistedVizControl<boolean>(metadata, 'descending', true);
  const [familyOpen, setFamilyOpen] = usePersistedVizControl<boolean>(metadata, 'family_open', false);
  const [sortColStored, setSortCol] = usePersistedVizControl<string | null>(metadata, 'sort_col', null);
  const [minScore, setMinScore] = usePersistedVizControl<number | null>(metadata, 'min_score', null);
  const [filterColStored, setFilterCol] = usePersistedVizControl<string | null>(metadata, 'filter_col', null);
  const [filterValues, setFilterValues] = usePersistedVizControl<string[]>(metadata, 'filter_values', []);
  const [hiddenColumns, setHiddenColumns] = usePersistedVizControl<string[]>(metadata, 'hidden_columns', []);
  const [compact, setCompact] = usePersistedVizControl<boolean>(metadata, 'compact', false);
  const [medals, setMedals] = usePersistedVizControl<boolean>(metadata, 'medals', true);

  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);
  const familyBound = hasFamily(config);
  const keyColumn = selectionColumn || config.title_col;

  const columnSpecs = useMemo<RankedTableColumnSpec[]>(
    () =>
      config.columns && config.columns.length > 0
        ? config.columns
        : [{ column: config.score_col, display: 'bar' }],
    [config.columns, config.score_col],
  );
  const popoverColumns = useMemo(() => config.popover_columns ?? [], [config.popover_columns]);
  const gridColumns = useMemo(() => config.popover_grid_columns ?? [], [config.popover_grid_columns]);

  const requiredCols = useMemo(
    () => [
      ...columnsToFetch(
        {
          title: config.title_col,
          score: config.score_col,
          subtitle: config.subtitle_col,
          rank: config.rank_col,
        },
        columnSpecs,
        popoverColumns,
        gridColumns,
        selectionColumn,
      ),
      ...familyRowColumns(config, keyColumn),
      ...(config.default_select_by ? [config.default_select_by] : []),
    ],
    // `config` is read through its parts: the family keys change with the config object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      config.title_col,
      config.score_col,
      config.subtitle_col,
      config.rank_col,
      columnSpecs,
      popoverColumns,
      gridColumns,
      selectionColumn,
      keyColumn,
      config.family_dc_tag,
      config.family_dc_id,
      config.family_row_col,
      config.genotypes_dc_tag,
      config.genotypes_dc_id,
      config.genotypes_row_col,
      config.genotype_columns,
      config.default_select_by,
    ],
  );
  const fetchColumns = useMemo(
    () => requiredCols.filter((c, i) => requiredCols.indexOf(c) === i),
    [requiredCols],
  );

  // Never narrowed by its own pick, nor by a pick on the column it selects on:
  // a candidate picked here or in a table beside it is marked, every other
  // candidate stays, so the reader can pick another.
  const filtersForFetch = useMemo(
    () => filtersForSelector(filters, metadata.index, 'scatter_selection', selectionColumn),
    [filters, metadata.index, selectionColumn],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || !config.title_col || !config.score_col) {
      setError('Ranked table: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    fetchAdvancedVizData(
      {
        wfId: metadata.wf_id,
        dcId: metadata.dc_id,
        columns: fetchColumns,
        filters: filtersForFetch,
        vizKind: RANKED_TABLE_VIZ_KIND,
        roles: { title: config.title_col, score: config.score_col },
      },
      ctrl.signal,
    )
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setEstimated(Boolean(res.sampling?.degraded));
      })
      .catch((err: unknown) => {
        if (cancelled || isStaleFetch(err)) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [
    metadata.wf_id,
    metadata.dc_id,
    config.title_col,
    config.score_col,
    JSON.stringify(fetchColumns),
    JSON.stringify(filtersForFetch),
    refreshTick,
  ]);

  // ---- Ranking -----------------------------------------------------------
  // A stored column that the config no longer lists falls back to the default
  // rather than ordering or filtering by nothing.
  const sortable = useMemo(
    () =>
      sortableColumns(
        config.score_col,
        columnSpecs,
        popoverColumns.filter((c) => isNumericColumn(rows?.[c])),
      ),
    [config.score_col, columnSpecs, popoverColumns, rows],
  );
  const sortCol = sortColStored && sortable.includes(sortColStored) ? sortColStored : config.score_col;
  const categorical = useMemo(() => categoricalColumns(columnSpecs), [columnSpecs]);
  const filterCol = filterColStored && categorical.includes(filterColStored) ? filterColStored : null;

  const shownN = clampTopN(topN, DEFAULT_TOP_N);
  // The Data controls take rows out before the ranking, so ranks, the "of N"
  // and the unscored count all describe the rows left.
  const rowFilter = useMemo(
    () => ({ scoreColumn: config.score_col, minScore, filterColumn: filterCol, filterValues }),
    [config.score_col, minScore, filterCol, filterValues],
  );
  const filtering = isFiltering(rowFilter);
  const list = useMemo(
    () =>
      rows
        ? rankRows(
            rows,
            // A precomputed rank describes the order by the score column only.
            { score: sortCol, rank: sortCol === config.score_col ? config.rank_col : null },
            { descending, topN: shownN, include: rowsKept(rows, rowFilter) },
          )
        : null,
    [rows, sortCol, config.score_col, config.rank_col, descending, shownN, rowFilter],
  );
  const categoryOptions = useMemo(
    () => (rows && filterCol ? distinctValues(rows[filterCol]) : []),
    [rows, filterCol],
  );

  // ---- Colours -----------------------------------------------------------
  // A badge wears the dashboard's colour for its value (`category_colors`, own
  // or inherited from the main tab), else the colorway's hue for the value's
  // place in the sorted universe, the rule every other tile follows.
  const colourSource = useCategoryColorSource();
  const dashboardPalette = useCategoryPalette();
  const palette = useMemo(
    () => dashboardPalette ?? mantineCategoricalPalette(theme, isDark),
    [dashboardPalette, theme, isDark],
  );
  const badgeColours = useMemo(() => {
    const out = new Map<string, (value: unknown) => string>();
    if (!rows) return out;
    for (const spec of columnSpecs) {
      if (spec.display === 'badge') {
        out.set(spec.column, badgeColourOf(colourSource, spec.column, rows[spec.column] ?? [], palette));
      }
    }
    return out;
  }, [rows, columnSpecs, colourSource, palette]);

  // A bar scaled to a column (`max_from` / `min_from`) is full at that column's
  // largest value over the whole frame, so "14" of a possible 18 fills 14/18
  // instead of the best row shown being a full bar; `top` is that bound, for
  // the "14 / 18" label.
  const barRanges = useMemo(() => {
    const out = new Map<string, BarRange & { top: number | null }>();
    if (!rows || !list) return out;
    for (const spec of columnSpecs) {
      if (spec.display === 'bar') {
        const values = list.rows.map((r) => toNumber(rows[spec.column]?.[r.source]));
        const top = spec.max_from ? boundFromColumn(rows[spec.max_from], 'max') : null;
        const bottom = spec.min_from ? boundFromColumn(rows[spec.min_from], 'min') : null;
        out.set(spec.column, { ...barRange(values, spec, { lo: bottom, hi: top }), top });
      }
    }
    return out;
  }, [rows, list, columnSpecs]);

  // ---- Selection ---------------------------------------------------------
  const pickedValues = useMemo(
    () => valuesOnColumn(filters, selectionColumn),
    [filters, selectionColumn],
  );
  const keyOf = useCallback(
    (row: RankedRow): string | null => {
      if (!rows || !selectionColumn) return null;
      const raw = cellOf(rows, selectionColumn, row.source);
      return raw === null || raw === undefined || raw === '' ? null : String(raw);
    },
    [rows, selectionColumn],
  );

  const pick = useCallback(
    (row: RankedRow, additive: boolean) => {
      if (!selectionEnabled || !selectionColumn || !onFilterChange) return;
      const value = keyOf(row);
      if (value === null) return;
      const own = selectionValuesFor(filters, metadata.index, 'scatter_selection') ?? [];
      let next: string[];
      if (additive) next = own.includes(value) ? own.filter((v) => v !== value) : [...own, value];
      else next = own.length === 1 && own[0] === value ? [] : [value];
      onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, next));
    },
    [selectionEnabled, selectionColumn, onFilterChange, keyOf, filters, metadata],
  );

  // `default_select_by`: with nothing picked, on this tile or elsewhere on the
  // column, select the best row once the frame is in, as a click on it would,
  // so a linked record card opens filled. Once per mount: a Reset must stay a
  // reset, and the filter this publishes comes back through `filters`, where
  // `pickedValues` is no longer empty.
  const defaultAppliedRef = useRef(false);
  useEffect(() => {
    if (defaultAppliedRef.current || loading) return;
    if (!config.default_select_by || !selectionEnabled || !selectionColumn || !onFilterChange) return;
    if (!rows || !list || list.rows.length === 0) return;
    // Decided on the first frame: a selection already there (a shared link, a
    // pick in a table beside) is left alone, and a later Reset is not undone.
    defaultAppliedRef.current = true;
    if (pickedValues.size > 0) return;
    const best = pickDefaultRow(
      list.rows,
      rows[config.default_select_by],
      config.default_select_order === 'asc' ? 'asc' : 'desc',
      keyOf,
    );
    const value = best ? keyOf(best) : null;
    if (value === null) return;
    onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, [value]));
  }, [
    loading,
    rows,
    list,
    pickedValues,
    selectionEnabled,
    selectionColumn,
    onFilterChange,
    keyOf,
    metadata,
    config.default_select_by,
    config.default_select_order,
  ]);

  // ---- Popover -----------------------------------------------------------
  const [hover, setHover] = useState<{ source: number; at: Pointer } | null>(null);
  const [pinned, setPinned] = useState<{ source: number; at: Pointer } | null>(null);
  const closePin = useCallback(() => setPinned(null), []);
  // The hover popover stays a beat after the pointer leaves its row, and a row
  // crossed on the way into it does not take it over, so it can be reached and
  // clicked.
  const hoverRef = useRef(hover);
  hoverRef.current = hover;
  const hideTimer = useRef<number | undefined>(undefined);
  const showTimer = useRef<number | undefined>(undefined);
  const clearHoverTimers = useCallback(() => {
    window.clearTimeout(hideTimer.current);
    window.clearTimeout(showTimer.current);
  }, []);
  const keepHover = clearHoverTimers;
  const leaveHover = useCallback(() => {
    clearHoverTimers();
    hideTimer.current = window.setTimeout(() => setHover(null), 300);
  }, [clearHoverTimers]);
  const enterRow = useCallback(
    (source: number, el: Element) => {
      const next = { source, at: rowAnchor(el) };
      clearHoverTimers();
      if (hoverRef.current && hoverRef.current.source !== source) {
        showTimer.current = window.setTimeout(() => setHover(next), 150);
      } else if (hoverRef.current?.source !== source) {
        setHover(next);
      }
    },
    [clearHoverTimers],
  );
  useEffect(() => clearHoverTimers, [clearHoverTimers]);
  // A new frame renumbers the rows: a pin on the old one would point at another.
  useEffect(() => {
    setPinned(null);
    setHover(null);
  }, [list]);

  const labels = config.labels ?? null;
  const labelOf = (column: string) =>
    columnLabel(column, columnSpecs.find((c) => c.column === column)?.label, labels);
  const scoreLabel = labelOf(config.score_col);
  const sortLabel = labelOf(sortCol);
  const rowByPinned = (state: { source: number } | null): RankedRow | null =>
    state && list ? (list.rows.find((r) => r.source === state.source) ?? null) : null;

  const contentOf = useCallback(
    (row: RankedRow): PopoverContent => {
      const r = rows ?? {};
      const metricColumns = [
        config.score_col,
        ...popoverColumns.filter((c) => c !== config.score_col),
      ];
      return {
        rank: String(row.rank),
        title: formatCell(cellOf(r, config.title_col, row.source)),
        subtitle: config.subtitle_col ? formatCell(cellOf(r, config.subtitle_col, row.source)) : undefined,
        metrics: metricColumns.map((c): [string, string] => [
          columnLabel(c, null, labels),
          formatCell(cellOf(r, c, row.source)),
        ]),
        grid: gridColumns.map((c): [string, string] => [
          columnLabel(c, null, labels),
          formatCell(cellOf(r, c, row.source)),
        ]),
      };
    },
    [rows, config.score_col, config.title_col, config.subtitle_col, popoverColumns, gridColumns, labels],
  );

  const rowValues = useCallback(
    (row: RankedRow): PinnedRowValues => {
      const r = rows ?? {};
      const familyRaw = cellOf(r, config.family_row_col, row.source);
      const keyRaw = cellOf(r, config.genotypes_row_col || keyColumn, row.source);
      return {
        family: familyRaw === null || familyRaw === undefined || familyRaw === '' ? null : String(familyRaw),
        key: keyRaw === null || keyRaw === undefined || keyRaw === '' ? null : String(keyRaw),
        cell: (column: string) => cellOf(r, column, row.source),
      };
    },
    [rows, config.family_row_col, config.genotypes_row_col, keyColumn],
  );

  // ---- Cells -------------------------------------------------------------
  const renderCell = (spec: RankedTableColumnSpec, row: RankedRow) => {
    const raw = cellOf(rows ?? {}, spec.column, row.source);
    const text = formatCell(raw, spec.display === 'bar' || spec.display === 'number' ? spec.decimals : undefined);
    switch (spec.display) {
      case 'badge': {
        if (text === EMPTY_CELL) return <span className="dpx-rt__empty">{EMPTY_CELL}</span>;
        const colour = badgeColours.get(spec.column)?.(raw);
        return (
          <Badge variant="light" size="sm" radius="xl" tt="none" fw={500} color={colour}>
            {text}
          </Badge>
        );
      }
      case 'bar': {
        const range = barRanges.get(spec.column) ?? { lo: 0, hi: 1, top: null };
        const value = toNumber(raw);
        return (
          <div className="dpx-rt__score">
            <div className="dpx-rt__track" aria-hidden="true">
              <div className="dpx-rt__fill" style={{ width: `${barFraction(value, range) * 100}%` }} />
            </div>
            <span className="dpx-rt__value">{barLabel(text, spec, range.top)}</span>
          </div>
        );
      }
      case 'mono':
        return <span className="dpx-rt__mono">{text}</span>;
      case 'number':
        return <span className="dpx-rt__number">{text}</span>;
      default:
        return text === EMPTY_CELL ? <span className="dpx-rt__empty">{text}</span> : <>{text}</>;
    }
  };

  const useMedals = medals;
  const hiddenSet = useMemo(() => new Set(hiddenColumns), [hiddenColumns]);
  const hasSubtitle = Boolean(config.subtitle_col) && !hiddenSet.has(config.subtitle_col as string);
  const shownSpecs = useMemo(
    () => columnSpecs.filter((spec) => !hiddenSet.has(spec.column)),
    [columnSpecs, hiddenSet],
  );
  const hideableColumns = useMemo(() => {
    const out: string[] = [];
    if (config.subtitle_col) out.push(config.subtitle_col);
    for (const spec of columnSpecs) if (!out.includes(spec.column)) out.push(spec.column);
    return out;
  }, [config.subtitle_col, columnSpecs]);
  const pinnedRow = rowByPinned(pinned);
  const hoverRow = pinned ? null : rowByPinned(hover);

  const missing = useMemo(
    () => (rows ? missingColumns(rows, fetchColumns) : []),
    [rows, fetchColumns],
  );
  const bindingError =
    rows && (missing.includes(config.title_col) || missing.includes(config.score_col))
      ? `Ranked table: ${missing
          .filter((c) => c === config.title_col || c === config.score_col)
          .join(', ')} not in the collection`
      : null;
  const otherMissing = missing.filter((c) => c !== config.title_col && c !== config.score_col);

  const echo =
    pickedValues.size > 0
      ? `picked ${[...pickedValues].slice(0, 3).join(', ')}${pickedValues.size > 3 ? ` +${pickedValues.size - 3}` : ''}`
      : list && list.rows.length > 0
        ? rankedEcho({
            shown: list.rows.length,
            ranked: list.ranked,
            scoreLabel: sortLabel,
            descending,
            filtered: filtering,
          })
        : undefined;

  // The rows shown (capped: a long list scrolls), the header, and a line for
  // each footnote under the table. The family pedigree is not counted: it opens
  // in a popover over the page, not in the tile.
  const footnotes = (list && list.unscored > 0 ? 1 : 0) + (otherMissing.length > 0 ? 1 : 0);
  const contentDemand = useMemo(
    () =>
      list && list.rows.length > 0
        ? demandForPx(
            Math.min(list.rows.length, DEMAND_ROWS) * (compact ? COMPACT_ROW_PX : ROW_PX) +
              HEADER_PX +
              12 +
              footnotes * FOOT_PX,
          )
        : undefined,
    [list, footnotes, compact],
  );

  // Encoding tier: which rows are ranked and in which order.
  const primaryControls = (
    <>
      <VizControlGroup title="Data">
        <VizNumberInput
          label="Top N"
          value={shownN}
          onChange={(v) => setTopN(clampTopN(Number(v), DEFAULT_TOP_N))}
          min={1}
          max={1000}
        />
        <VizNumberInput
          label={`Min ${scoreLabel}`}
          placeholder="None"
          value={minScore ?? ''}
          onChange={(v) => setMinScore(toNumber(v))}
        />
        {categorical.length > 0 ? (
          <VizSelect
            label="Filter by"
            data={categorical.map((c) => ({ value: c, label: labelOf(c) }))}
            value={filterCol}
            onChange={(v) => {
              setFilterCol(v);
              setFilterValues([]);
            }}
            placeholder="None"
            clearable
          />
        ) : null}
        {filterCol ? (
          <VizMultiSelect
            label={`Keep ${labelOf(filterCol)}`}
            data={categoryOptions}
            value={filterValues}
            onChange={setFilterValues}
            placeholder="All"
            clearable
            searchable={categoryOptions.length > 8}
          />
        ) : null}
      </VizControlGroup>
      <VizControlGroup title="Order">
        {sortable.length > 1 ? (
          <VizSelect
            label="Sort by"
            data={sortable.map((c) => ({ value: c, label: labelOf(c) }))}
            value={sortCol}
            onChange={(v) => setSortCol(v && v !== config.score_col ? v : null)}
            allowDeselect={false}
          />
        ) : null}
        <VizSegmented
          label="First"
          value={descending ? 'high' : 'low'}
          onChange={(v) => setDescending(v !== 'low')}
          data={[
            { value: 'high', label: 'Highest' },
            { value: 'low', label: 'Lowest' },
          ]}
        />
      </VizControlGroup>
    </>
  );

  // Cosmetic tier: what the table shows and how tightly.
  const controls = (
    <VizControlGroup title="Display">
      {hideableColumns.length > 1 ? (
        <VizMultiSelect
          label="Hide columns"
          data={hideableColumns.map((c) => ({ value: c, label: labelOf(c) }))}
          value={hiddenColumns}
          onChange={setHiddenColumns}
          placeholder="None"
          clearable
        />
      ) : null}
      <VizSwitch checked={medals} onChange={(e) => setMedals(e.currentTarget.checked)} label="Medals" />
      <VizSwitch
        checked={compact}
        onChange={(e) => setCompact(e.currentTarget.checked)}
        label="Compact rows"
      />
      {familyBound ? (
        <VizSwitch
          checked={familyOpen}
          onChange={(e) => setFamilyOpen(e.currentTarget.checked)}
          label="Open family details"
        />
      ) : null}
    </VizControlGroup>
  );

  let emptyMessage: string | undefined;
  if (rows && list && list.rows.length === 0 && !bindingError) {
    emptyMessage =
      list.unscored > 0
        ? `No candidate has a ${sortLabel} to rank by`
        : filtering || filtersForFetch.length > 0
          ? 'No candidates match the current filters'
          : 'No candidates to rank';
  }

  const pinRow = (row: RankedRow, at: Pointer) => {
    if (!familyBound) return;
    clearHoverTimers();
    setPinned((current) => (current?.source === row.source ? null : { source: row.source, at }));
    setHover(null);
  };

  const headerEnd = (cls?: string) => (cls === 'number' ? 'is-end' : undefined);

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Ranked table'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      echo={echo}
      loading={loading}
      error={error || bindingError}
      estimated={estimated}
      emptyMessage={emptyMessage}
      dataRows={rows ?? undefined}
      dataColumns={fetchColumns}
    >
      <div className={`dpx-rt${compact ? ' dpx-rt--compact' : ''}`}>
        <div className="dpx-rt__scroll" onScroll={closePin}>
          {list && list.rows.length > 0 ? (
            <table className="dpx-rt__table" role="grid" aria-label={metadata.title || 'Ranked table'}>
              <thead>
                <tr>
                  <th scope="col" aria-label="Rank">
                    #
                  </th>
                  <th scope="col">{columnLabel(config.title_col, null, labels)}</th>
                  {hasSubtitle ? (
                    <th scope="col">{columnLabel(config.subtitle_col as string, null, labels)}</th>
                  ) : null}
                  {shownSpecs.map((spec) => (
                    <th key={spec.column} scope="col" className={headerEnd(spec.display)}>
                      {columnLabel(spec.column, spec.label, labels)}
                    </th>
                  ))}
                  {familyBound ? <th scope="col" aria-label="Details" /> : null}
                </tr>
              </thead>
              <tbody>
                {list.rows.map((row) => {
                  const key = keyOf(row);
                  const selected = key !== null && pickedValues.has(key);
                  const classes = [
                    'dpx-rt__row',
                    selectionEnabled || familyBound ? 'dpx-rt__row--selectable' : '',
                    useMedals && row.tier ? `dpx-rt__row--tier-${row.tier}` : '',
                    selected ? 'is-selected' : '',
                  ]
                    .filter(Boolean)
                    .join(' ');
                  return (
                    <tr
                      key={row.source}
                      data-rt-row=""
                      className={classes}
                      tabIndex={0}
                      aria-selected={selectionEnabled ? selected : undefined}
                      onPointerEnter={(e) => enterRow(row.source, e.currentTarget)}
                      onPointerLeave={leaveHover}
                      onFocus={(e) => {
                        const box = e.currentTarget.getBoundingClientRect();
                        setHover({ source: row.source, at: { x: box.left + 40, y: box.bottom - 8 } });
                      }}
                      onBlur={leaveHover}
                      onClick={(e) => {
                        pick(row, e.ctrlKey || e.metaKey || e.shiftKey);
                        pinRow(row, rowAnchor(e.currentTarget));
                      }}
                      onKeyDown={(e) => {
                        if (e.key !== 'Enter' && e.key !== ' ') return;
                        e.preventDefault();
                        const box = e.currentTarget.getBoundingClientRect();
                        pick(row, e.ctrlKey || e.metaKey || e.shiftKey);
                        pinRow(row, { x: box.left + 40, y: box.bottom - 8 });
                      }}
                    >
                      <td>
                        <span
                          className={`dpx-rt__medal${
                            useMedals && row.tier ? ` dpx-rt__medal--${row.tier}` : ''
                          }${useMedals ? '' : ' dpx-rt__medal--plain'}`}
                          aria-label={`rank ${row.rank}`}
                        >
                          {row.rank}
                        </span>
                      </td>
                      <td className="dpx-rt__title">
                        {formatCell(cellOf(rows ?? {}, config.title_col, row.source))}
                      </td>
                      {hasSubtitle ? (
                        <td>
                          <span className="dpx-rt__mono">
                            {formatCell(cellOf(rows ?? {}, config.subtitle_col, row.source))}
                          </span>
                        </td>
                      ) : null}
                      {shownSpecs.map((spec) => (
                        <td key={spec.column} className={headerEnd(spec.display)}>
                          {renderCell(spec, row)}
                        </td>
                      ))}
                      {familyBound ? (
                        <td className="is-end">
                          <ActionIcon
                            variant="subtle"
                            color="gray"
                            size="sm"
                            aria-label={`Show details of ${formatCell(cellOf(rows ?? {}, config.title_col, row.source))}`}
                            aria-expanded={pinned?.source === row.source}
                            tabIndex={-1}
                            onClick={(e) => {
                              e.stopPropagation();
                              const tr = e.currentTarget.closest('tr');
                              if (tr) pinRow(row, rowAnchor(tr));
                            }}
                          >
                            <Icon icon="mdi:chevron-down" width={16} />
                          </ActionIcon>
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : null}
        </div>
        {list && list.unscored > 0 && list.rows.length > 0 ? (
          <Text size="xs" c="dimmed" className="dpx-rt__foot">
            {list.unscored.toLocaleString('en-US')} without a {sortLabel} are not ranked
          </Text>
        ) : null}
        {otherMissing.length > 0 ? (
          <Text size="xs" c="orange" className="dpx-rt__foot">
            Not in the collection: {otherMissing.join(', ')}
          </Text>
        ) : null}
      </div>
      {hoverRow ? (
        <RankedPopover
          content={contentOf(hoverRow)}
          at={hover!.at}
          pinned={false}
          hint={familyBound ? 'Click to open the family' : undefined}
          onPointerEnter={keepHover}
          onPointerLeave={leaveHover}
          onActivate={
            familyBound
              ? () => {
                  setFamilyOpen(true);
                  pinRow(hoverRow, hover!.at);
                }
              : undefined
          }
        />
      ) : null}
      {pinnedRow && pinned ? (
        <RankedPopover content={contentOf(pinnedRow)} at={pinned.at} pinned onClose={closePin}>
          <FamilySection
            open={familyOpen}
            onToggle={() => setFamilyOpen(!familyOpen)}
            config={config}
            metadata={metadata}
            row={rowValues(pinnedRow)}
          />
        </RankedPopover>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default RankedTableRenderer;
