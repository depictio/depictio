import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Group,
  Pagination,
  Paper,
  SegmentedControl,
  Stack,
  Table,
  Text,
  useComputedColorScheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  GeneralStatsColumn,
  GeneralStatsColumnFormat,
  GeneralStatsModeData,
  GeneralStatsPayload,
  GeneralStatsStyle,
  InteractiveFilter,
  StoredMetadata,
  renderMultiQCGeneralStats,
} from '../../api';
import { useInView } from '../../hooks/useInView';
import { enqueueFetch, isStaleFetch } from '../../fetchQueue';
import ComponentSkeleton from '../ComponentSkeleton';
import RefetchOverlay from '../RefetchOverlay';
import { useReportLoadStatus } from '../DashboardLoadingProvider';
import { useAnnotationLayer } from '../../annotations/AnnotationLayerContext';
import { DEFAULT_ANNOTATE_OPTIONS } from '../../annotations/layer';
import { isAnnotateEscape } from '../../annotations/escape';
import { GENERAL_STATS_SAMPLE_KEY, MULTIQC_SAMPLE_COLUMN } from '../../annotations/multiqc';
import { annotationColorTint, annotationColorValue } from '../../annotations/resolveColor';
import {
  buildRowAnnotationMap,
  markedRowsFromSelection,
  rowAnnotationBadge,
} from '../../annotations/tableRows';
import type { RowAnnotationMark } from '../../annotations/tableRows';
import type { RenderableAnnotation } from '../../annotations/types';
import AnnotateToolbar from '../annotations/AnnotateToolbar';
import InlineAnnotationEditor from '../annotations/InlineAnnotationEditor';

interface MultiQCGeneralStatsProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  refreshTick?: number;
}

type ReadMode = 'mean' | 'r1' | 'r2' | 'all';
type ViewMode = 'table' | 'violin';
type SortDir = 'asc' | 'desc' | null;

const PAGE_SIZE = 50;

interface DataBar {
  min: number;
  max: number;
  backgroundImage: string;
  paddingTop?: number;
  paddingBottom?: number;
}

/** Parse the Dash filter_query "{col} >= 12 && {col} < 17" into a (min, max) pair. */
function parseFilterQuery(query: string | undefined): { min: number; max: number } | null {
  if (!query) return null;
  const matches = query.match(/-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g);
  if (!matches || matches.length === 0) return null;
  const min = Number(matches[0]);
  const max = matches.length > 1 ? Number(matches[1]) : Number.POSITIVE_INFINITY;
  return { min, max };
}

/** Pre-index `table_styles` by column id so per-cell lookup is O(bins) per cell. */
function indexDataBars(styles: GeneralStatsStyle[]): Map<string, DataBar[]> {
  const byColumn = new Map<string, DataBar[]>();
  for (const style of styles) {
    const colId = style.if?.column_id;
    if (!colId || !style.backgroundImage) continue;
    const bounds = parseFilterQuery(style.if.filter_query);
    if (!bounds) continue;
    const bar: DataBar = {
      min: bounds.min,
      max: bounds.max,
      backgroundImage: style.backgroundImage,
      paddingTop: style.paddingTop,
      paddingBottom: style.paddingBottom,
    };
    const list = byColumn.get(colId) ?? [];
    list.push(bar);
    byColumn.set(colId, list);
  }
  return byColumn;
}

function findDataBar(bars: DataBar[] | undefined, value: unknown): DataBar | null {
  if (!bars) return null;
  if (value == null || value === '') return null;
  const num = Number(value);
  if (Number.isNaN(num)) return null;
  for (const bar of bars) {
    if (num >= bar.min && num < bar.max) return bar;
  }
  // Last bin has no upper bound (Infinity); the loop above catches it. If a
  // value lies exactly on the global max it falls through — clamp to the
  // last bar so the cell still gets a colored background.
  return bars[bars.length - 1] ?? null;
}

function formatCell(value: unknown, fmt: GeneralStatsColumnFormat | null): string {
  if (value == null || value === '') return '';
  if (fmt == null) return String(value);
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  const formatted = new Intl.NumberFormat(undefined, {
    minimumFractionDigits: fmt.precision,
    maximumFractionDigits: fmt.precision,
    useGrouping: fmt.group,
  }).format(num);
  return fmt.suffix ? `${formatted}${fmt.suffix}` : formatted;
}

function compareCell(a: unknown, b: unknown): number {
  const aNull = a == null || a === '';
  const bNull = b == null || b === '';
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;
  const an = Number(a);
  const bn = Number(b);
  if (!Number.isNaN(an) && !Number.isNaN(bn)) return an - bn;
  return String(a).localeCompare(String(b));
}

const HEADER_STYLE: React.CSSProperties = {
  position: 'sticky',
  top: 0,
  zIndex: 1,
  background: 'var(--mantine-color-body)',
  color: 'var(--mantine-color-text)',
  borderBottom: '2px solid var(--mantine-color-default-border)',
  fontWeight: 700,
  fontSize: 12,
  padding: '8px',
  whiteSpace: 'nowrap',
  cursor: 'pointer',
  userSelect: 'none',
};

const CELL_STYLE: React.CSSProperties = {
  padding: '6px 8px',
  fontSize: 12,
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  backgroundColor: 'var(--mantine-color-body)',
  color: 'var(--mantine-color-text)',
  borderBottom: '1px solid var(--mantine-color-default-border)',
};

const NO_ANNOTATIONS: RenderableAnnotation[] = [];

/** Narrow first column carrying the ①② badges of annotated rows. */
const BADGE_CELL_STYLE: React.CSSProperties = {
  ...CELL_STYLE,
  width: 40,
  minWidth: 40,
  padding: '6px 2px 6px 4px',
  textAlign: 'center',
  fontWeight: 600,
  letterSpacing: '-0.05em',
};

/** The sample a General Stats row shows, as the id marked rows are stored with. */
function rowSample(row: Record<string, unknown>): string | number | null {
  const v = row[GENERAL_STATS_SAMPLE_KEY];
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  return typeof v === 'string' && v !== '' ? v : null;
}

const MultiQCGeneralStats: React.FC<MultiQCGeneralStatsProps> = ({
  dashboardId,
  metadata,
  filters,
  refreshTick,
}) => {
  const [payload, setPayload] = useState<GeneralStatsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [readMode, setReadMode] = useState<ReadMode>('mean');
  const [view, setView] = useState<ViewMode>('table');
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);
  const [page, setPage] = useState(1);
  const [containerRef, inView] = useInView<HTMLDivElement>('200px');

  // First-load skeleton vs refetch overlay (mirrors MultiQCFigure): show the big
  // table skeleton only before the first payload; a later refetch keeps the
  // current table visible under a small overlay.
  const isInitialLoad = payload === null;
  const showInitialLoader = !inView || (isInitialLoad && loading);
  const showRefetchOverlay = !isInitialLoad && loading;

  // Report to the dashboard load registry (mirrors FigureRenderer) so the header
  // progress bar counts the General-Statistics table.
  useReportLoadStatus(
    metadata.index,
    !inView ? null : payload != null ? 'ready' : error ? 'error' : 'loading',
  );

  const filtersSig = JSON.stringify(filters ?? []);

  useEffect(() => {
    if (!inView) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    // Queue the fetch (vertical position = priority) so a dense dashboard paints
    // top-down instead of firing every panel at once — mirrors FigureRenderer.
    enqueueFetch(
      () => renderMultiQCGeneralStats(dashboardId, metadata.index, filters),
      metadata.layout?.y ?? 0,
    )
      .then((res) => {
        if (cancelled) return;
        setPayload(res);
        if (!res.is_paired_end) setReadMode('mean');
        setPage(1);
      })
      .catch((err) => {
        // Superseded queue generation (filter changed) is not an error.
        if (cancelled || isStaleFetch(err)) return;
        setError(err?.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, filtersSig, inView, refreshTick]);

  const titleText = (metadata.title as string | undefined) || 'MultiQC General Statistics';

  const mode: GeneralStatsModeData | null = useMemo(() => {
    if (!payload) return null;
    return payload.modes[readMode] ?? payload.modes.mean ?? null;
  }, [payload, readMode]);

  const dataBars = useMemo(() => indexDataBars(mode?.table_styles ?? []), [mode]);

  const sortedRows = useMemo(() => {
    const rows = mode?.table_data ?? [];
    if (!sortKey || !sortDir) return rows;
    const dir = sortDir === 'asc' ? 1 : -1;
    return [...rows].sort((a, b) => dir * compareCell(a[sortKey], b[sortKey]));
  }, [mode, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sortedRows.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const visibleRows = useMemo(
    () => sortedRows.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE),
    [sortedRows, safePage],
  );

  // ── Annotation layer ──────────────────────────────────────────────────────
  // Rows are marked by sample (the same `sample` ids as the MultiQC figures):
  // a marked row gets a tint, a coloured stripe and a ①② badge, as in
  // TableRenderer. Annotate mode picks rows by click, in the table view only.
  const layer = useAnnotationLayer();
  const componentIndex = String(metadata.index);
  const colorScheme = useComputedColorScheme('light');
  const layerItems = layer ? layer.itemsFor(componentIndex) : NO_ANNOTATIONS;
  const highlightAnnotationId = layer?.highlightId ?? null;
  const rowAnnotations = useMemo(
    () => buildRowAnnotationMap(layerItems, MULTIQC_SAMPLE_COLUMN, highlightAnnotationId),
    [layerItems, highlightAnnotationId],
  );
  const hasRowAnnotations = rowAnnotations.size > 0;

  const annotatable = !!payload && !error && view === 'table';
  const reportAnnotatable = layer?.reportAnnotatable;
  useEffect(() => {
    if (!reportAnnotatable) return;
    reportAnnotatable(componentIndex, annotatable);
    return () => reportAnnotatable(componentIndex, false);
  }, [reportAnnotatable, componentIndex, annotatable]);
  const annotateHere = !!layer && layer.canAnnotate && layer.annotate?.componentIndex === componentIndex;
  const annotating = annotateHere && annotatable;
  // Switching to the violin view leaves annotate mode.
  useEffect(() => {
    if (annotateHere && !annotatable) layer?.setAnnotate(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [annotateHere, annotatable]);
  const pendingHere =
    layer?.pending && layer.pending.componentIndex === componentIndex ? layer.pending : null;

  // Rows picked for the next "Mark rows", by stringified sample (raw value kept).
  const [annotateSelected, setAnnotateSelected] = useState<Map<string, string | number>>(() => new Map());
  useEffect(() => {
    setAnnotateSelected((prev) => (prev.size ? new Map() : prev));
  }, [annotating]);
  const toggleAnnotateRow = (row: Record<string, unknown>) => {
    if (!annotating || pendingHere) return;
    const sample = rowSample(row);
    if (sample == null) return;
    setAnnotateSelected((prev) => {
      const next = new Map(prev);
      const key = String(sample);
      if (next.has(key)) next.delete(key);
      else next.set(key, sample);
      return next;
    });
  };
  const markSelectedRows = () => {
    if (!layer || pendingHere) return;
    const geometry = markedRowsFromSelection(
      Array.from(annotateSelected.values(), (v) => ({ [MULTIQC_SAMPLE_COLUMN]: v })),
      MULTIQC_SAMPLE_COLUMN,
    );
    if (!geometry) return;
    layer.onCaptured(componentIndex, geometry, 'points');
    setAnnotateSelected(new Map());
  };

  // Esc cancels the pending label first, then leaves annotate mode.
  useEffect(() => {
    if (!annotating || !layer) return;
    const onKey = (e: KeyboardEvent) => {
      if (!isAnnotateEscape(e, containerRef.current)) return;
      if (pendingHere) layer.cancelPending();
      else layer.setAnnotate(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [annotating, layer, pendingHere, containerRef]);

  // A badge opens the inline editor of the annotation styling the row (or its
  // thread), outside annotate mode where row clicks belong to the tool.
  const openAnnotation = layer?.openAnnotation ?? null;
  const onBadgeClick = useCallback(
    (mark: RowAnnotationMark | undefined, e: React.MouseEvent<HTMLElement>) => {
      if (!mark || !openAnnotation || annotating) return;
      const r = e.currentTarget.getBoundingClientRect();
      openAnnotation(mark.id, componentIndex, { x: r.left + r.width / 2, y: r.bottom });
    },
    [openAnnotation, annotating, componentIndex],
  );

  /** Cell colours of a marked or picked row; null for a plain row. */
  const rowTone = (
    mark: RowAnnotationMark | undefined,
    picked: boolean,
  ): React.CSSProperties | null => {
    if (picked) return { backgroundColor: 'var(--mantine-primary-color-light)' };
    if (!mark) return null;
    return {
      backgroundColor: annotationColorTint(mark.color, colorScheme, mark.highlighted),
      ...(mark.highlighted ? { fontWeight: 600 } : {}),
    };
  };

  const onHeaderClick = (colId: string) => {
    if (sortKey !== colId) {
      setSortKey(colId);
      setSortDir('asc');
    } else if (sortDir === 'asc') {
      setSortDir('desc');
    } else if (sortDir === 'desc') {
      setSortKey(null);
      setSortDir(null);
    } else {
      setSortDir('asc');
    }
    setPage(1);
  };

  const renderControls = () => {
    const pairedEnd = !!payload?.is_paired_end;
    // When the dataset isn't paired-end, only one set of values exists per
    // sample — there's no Mean/R1/R2 distinction to make. Surface that as the
    // "All" pill (instead of "Mean") so the active label matches the data.
    return (
      <Group justify="space-between" align="center" wrap="nowrap">
        <Text fw={600} size="sm">{titleText}</Text>
        <Group gap="xs" wrap="nowrap">
          <SegmentedControl
            size="xs"
            value={pairedEnd ? readMode : 'all'}
            onChange={(v) => {
              if (!pairedEnd) return;
              setReadMode(v as ReadMode);
              setPage(1);
            }}
            data={[
              { label: 'Mean', value: 'mean', disabled: !pairedEnd },
              { label: 'R1', value: 'r1', disabled: !pairedEnd },
              { label: 'R2', value: 'r2', disabled: !pairedEnd },
              { label: 'All', value: 'all', disabled: !pairedEnd },
            ]}
          />
          <SegmentedControl
            size="xs"
            value={view}
            onChange={(v) => setView(v as ViewMode)}
            data={[
              { label: 'Table', value: 'table' },
              { label: 'Violin', value: 'violin' },
            ]}
          />
        </Group>
      </Group>
    );
  };

  const renderTable = (m: GeneralStatsModeData) => {
    const columns: GeneralStatsColumn[] = m.table_columns;
    return (
      <Stack gap="xs" style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        <div
          style={{
            flex: 1,
            minHeight: 0,
            overflow: 'auto',
            border: '1px solid var(--mantine-color-default-border)',
            borderRadius: 4,
          }}
        >
          <Table
            withTableBorder={false}
            withColumnBorders={false}
            highlightOnHover
            verticalSpacing={0}
            horizontalSpacing={0}
            style={{ borderCollapse: 'separate', borderSpacing: 0 }}
          >
            <Table.Thead>
              <Table.Tr>
                {hasRowAnnotations && (
                  <Table.Th style={{ ...HEADER_STYLE, cursor: 'default', width: 40 }} title="Annotations" />
                )}
                {columns.map((col) => {
                  const isSort = sortKey === col.id;
                  const arrow = isSort ? (sortDir === 'asc' ? ' ↑' : sortDir === 'desc' ? ' ↓' : '') : '';
                  return (
                    <Table.Th
                      key={col.id}
                      style={HEADER_STYLE}
                      onClick={() => onHeaderClick(col.id)}
                    >
                      {col.name}{arrow}
                    </Table.Th>
                  );
                })}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {visibleRows.map((row, rowIdx) => {
                const sample = rowSample(row);
                const mark = sample == null ? undefined : rowAnnotations.get(String(sample));
                const picked = annotating && sample != null && annotateSelected.has(String(sample));
                const tone = rowTone(mark, picked);
                const stripe = mark ? annotationColorValue(mark.color, colorScheme) : undefined;
                return (
                  <Table.Tr
                    key={rowIdx}
                    onClick={annotating ? () => toggleAnnotateRow(row) : undefined}
                    style={{
                      ...(annotating ? { cursor: 'pointer' } : {}),
                      ...(picked
                        ? { outline: '2px dashed var(--mantine-primary-color-filled)', outlineOffset: -2 }
                        : {}),
                    }}
                  >
                    {hasRowAnnotations && (
                      <Table.Td
                        style={{
                          ...BADGE_CELL_STYLE,
                          ...tone,
                          ...(stripe
                            ? {
                                color: stripe,
                                boxShadow: `inset ${mark?.highlighted ? 5 : 3}px 0 0 ${stripe}`,
                                cursor: openAnnotation && !annotating ? 'pointer' : undefined,
                              }
                            : {}),
                        }}
                        onClick={mark && !annotating ? (e) => onBadgeClick(mark, e) : undefined}
                      >
                        {rowAnnotationBadge(mark)}
                      </Table.Td>
                    )}
                    {columns.map((col) => {
                      const value = row[col.id];
                      const bar = col.id === 'Sample Name' ? null : findDataBar(dataBars.get(col.id), value);
                      const cellStyle: React.CSSProperties = {
                        ...CELL_STYLE,
                        ...(col.id === 'Sample Name'
                          ? { fontWeight: 600, minWidth: 200 }
                          : {}),
                        ...(bar
                          ? {
                              backgroundImage: bar.backgroundImage,
                              paddingTop: bar.paddingTop ?? CELL_STYLE.padding,
                              paddingBottom: bar.paddingBottom ?? CELL_STYLE.padding,
                            }
                          : {}),
                        ...tone,
                      };
                      const display =
                        col.type === 'numeric' ? formatCell(value, col.format) : String(value ?? '');
                      return (
                        <Table.Td key={col.id} style={cellStyle}>
                          {display}
                        </Table.Td>
                      );
                    })}
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </div>
        {totalPages > 1 && (
          <Group justify="flex-end">
            <Pagination
              size="xs"
              total={totalPages}
              value={safePage}
              onChange={setPage}
            />
          </Group>
        )}
        {annotating && layer && (
          <AnnotateToolbar
            variant="rows"
            tool="points"
            options={DEFAULT_ANNOTATE_OPTIONS}
            onChange={() => undefined}
            onDone={() => layer.setAnnotate(null)}
            pending={pendingHere}
            onSave={layer.savePending}
            onCancel={layer.cancelPending}
            selectedCount={annotateSelected.size}
            onMarkRows={markSelectedRows}
          />
        )}
        {layer && <InlineAnnotationEditor componentIndex={componentIndex} />}
      </Stack>
    );
  };

  const renderViolin = (m: GeneralStatsModeData) => (
    <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
      <Plot
        data={(m.violin_figure?.data as any[]) || []}
        layout={{
          ...((m.violin_figure?.layout as Record<string, unknown>) || {}),
          autosize: true,
          margin: {
            l: 50,
            r: 20,
            t: 30,
            b: 50,
            ...((m.violin_figure?.layout?.margin as Record<string, unknown>) || {}),
          },
          uirevision: `tick-${refreshTick ?? 0}`,
        }}
        revision={refreshTick ?? 0}
        config={{ displaylogo: false, responsive: true }}
        style={{ width: '100%', height: '100%' }}
        useResizeHandler
      />
    </div>
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
        position: 'relative',
      }}
    >
      <Stack gap="xs" style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        {renderControls()}
        {/* Skeleton only on the empty first load; a refetch (filter / realtime
            tick) keeps the current table mounted under a RefetchOverlay instead
            of blanking it — mirrors MultiQCFigure / TableRenderer. */}
        {showInitialLoader && <ComponentSkeleton variant="table" />}
        {error && !loading && (
          <Stack style={{ flex: 1 }} justify="center" align="center">
            <Text size="sm" c="red" className="dashboard-error">General Stats failed: {error}</Text>
          </Stack>
        )}
        {mode && !isInitialLoad && !error && (
          view === 'table' ? renderTable(mode) : renderViolin(mode)
        )}
        <RefetchOverlay visible={showRefetchOverlay} />
      </Stack>
    </Paper>
  );
};

export default MultiQCGeneralStats;
