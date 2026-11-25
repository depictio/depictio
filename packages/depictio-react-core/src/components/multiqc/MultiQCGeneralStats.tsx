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
import { useDataVersionRequest } from '../../dataVersions';
import { enqueueFetch, isStaleFetch } from '../../fetchQueue';
import ComponentSkeleton from '../ComponentSkeleton';
import RefetchOverlay from '../RefetchOverlay';
import { useReportLoadStatus } from '../DashboardLoadingProvider';
import { rowsForHeight, useContentDemand } from '../autofit';
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
import DiffSummaryChip from '../chrome/DiffSummaryChip';
import { useChangeMark } from '../../changeMarks';
import { useComponentDiff } from '../../hooks/useComponentDiff';
import { panelFilters } from '../../splitPanels';
import type { PanelSpec } from '../../splitPanels';
import { bandRows, bandsReach } from './multiqcGroups';

/** Rows banded by analysis group: the Overlay of Analysis mode on this table. */
export interface GeneralStatsBands {
  /** One per group, in the groups' order. */
  panels: PanelSpec[];
  /** Whether the samples in none of the groups are listed, last, as "Other". */
  showOther: boolean;
}

interface MultiQCGeneralStatsProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Band the rows by group (Overlay). Each group is read from the same
   *  per-group render a Split panel uses, so the two agree on every sample. */
  bands?: GeneralStatsBands | null;
  /** A group status badge, drawn beside the title. */
  badge?: React.ReactNode;
  /** Whether the bands reached the rows (`null`: no bands, or not known yet). */
  onBandsReach?: (reached: boolean | null) => void;
  /** What this table holds, as a fingerprint; `null` while it loads. A Split
   *  compares its panels' to find out whether the groups narrowed anything. */
  onSignature?: (signature: string | null) => void;
  /** One table of a Split: the height it needs, in px, goes to the split
   *  (which sizes the tile to all of its tables) instead of the grid. 0 is a
   *  table with no row, `null` one still loading. */
  onContentHeight?: (px: number | null) => void;
  /** A quadrant of a split: the group heads the table in place of its title
   *  and controls, and the rows are denser, so a quadrant lists more samples. */
  splitLabel?: { name: string; color?: string } | null;
}

/** Tint of a group's rows: its colour, light, over the page background. */
function bandTint(color: string | undefined): string | undefined {
  return color ? `color-mix(in srgb, ${color} 14%, var(--mantine-color-body))` : undefined;
}

type ReadMode = 'mean' | 'r1' | 'r2' | 'all';
type ViewMode = 'table' | 'violin';
type SortDir = 'asc' | 'desc' | null;

const PAGE_SIZE = 50;

// The table's height, in the pixels its own markup takes: paper padding and
// the controls row, the header, one line per visible row, the pager when there
// is more than one page. The grid only ever shrinks the tile to this (see
// `FIT_POLICIES`), so an over-estimate costs a little white space and an
// under-estimate a scrollbar.
const TABLE_CHROME_PX = 24 + 44;
const TABLE_HEADER_PX = 34;
const TABLE_ROW_PX = 31;
/** A quadrant of a split: its header is the group, its rows are denser. */
const COMPACT_HEADER_PX = 26;
const COMPACT_ROW_PX = 23;
const TABLE_PAGER_PX = 38;
/** The violin view in one panel of a split: a plot, no content height. */
const VIOLIN_SPLIT_PX = 320;

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

/** A row of a sample the reader had already seen, under "Compare with last visit":
 *  faded but legible, the new rows stay as they are. */
const SEEN_ROW_OPACITY = 0.35;

/** A quadrant of a split lists more samples in the same room. */
const COMPACT_HEADER_STYLE: React.CSSProperties = { ...HEADER_STYLE, fontSize: 11, padding: '4px 6px' };
const COMPACT_CELL_STYLE: React.CSSProperties = { ...CELL_STYLE, fontSize: 11, padding: '3px 6px' };

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
  bands,
  badge,
  onBandsReach,
  onSignature,
  onContentHeight,
  splitLabel,
}) => {
  const headerStyle = splitLabel ? COMPACT_HEADER_STYLE : HEADER_STYLE;
  const cellBaseStyle = splitLabel ? COMPACT_CELL_STYLE : CELL_STYLE;
  const badgeCellStyle = splitLabel ? { ...BADGE_CELL_STYLE, ...COMPACT_CELL_STYLE, width: 40, minWidth: 40 } : BADGE_CELL_STYLE;
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
  // Data time travel: the version's report set rides in the body, its key in the effect deps.
  const { body: versionBody, key: versionKey } = useDataVersionRequest();

  useEffect(() => {
    if (!inView) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    // Queue the fetch (vertical position = priority) so a dense dashboard paints
    // top-down instead of firing every panel at once — mirrors FigureRenderer.
    enqueueFetch(
      () => renderMultiQCGeneralStats(dashboardId, metadata.index, filters, versionBody),
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
  }, [dashboardId, metadata.index, filtersSig, inView, refreshTick, versionKey]);

  // ── Bands (Overlay) ───────────────────────────────────────────────────────
  // One render per group, with that group's constraint appended to the
  // dashboard's filters: the samples that come back are the group's members.
  // The table itself stays the unfiltered render above, so its data bars and
  // columns are the whole report's.
  const bandsKey = bands ? JSON.stringify([bands.panels, filtersSig]) : '';
  const [bandPayloads, setBandPayloads] = useState<{
    key: string;
    payloads: GeneralStatsPayload[] | null;
  } | null>(null);
  useEffect(() => {
    if (!bands || !inView) return;
    let cancelled = false;
    Promise.all(
      bands.panels.map((panel) =>
        enqueueFetch(
          () =>
            renderMultiQCGeneralStats(dashboardId, metadata.index, panelFilters(filters ?? [], panel), versionBody),
          metadata.layout?.y ?? 0,
        ),
      ),
    )
      .then((payloads) => {
        if (!cancelled) setBandPayloads({ key: bandsKey, payloads });
      })
      .catch((err) => {
        if (cancelled || isStaleFetch(err)) return;
        // No banding without the groups' samples: the table stays as it is.
        setBandPayloads({ key: bandsKey, payloads: null });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, bandsKey, inView, refreshTick, versionKey]);

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

  // Members of each group in the read mode on screen, then the table's rows
  // ordered by group (the sort applies inside each group).
  const members = useMemo(() => {
    if (!bands || bandPayloads?.key !== bandsKey || !bandPayloads.payloads) return null;
    if (bandPayloads.payloads.length !== bands.panels.length) return null;
    return bandPayloads.payloads.map((p) => {
      const m = p.modes[readMode] ?? p.modes.mean;
      const set = new Set<string>();
      for (const row of m?.table_data ?? []) {
        const sample = rowSample(row);
        if (sample != null) set.add(String(sample));
      }
      return set as ReadonlySet<string>;
    });
  }, [bands, bandPayloads, bandsKey, readMode]);
  const bandsReached = useMemo(() => {
    if (!bands || !members) return null;
    const samples: string[] = [];
    for (const row of mode?.table_data ?? []) {
      const sample = rowSample(row);
      if (sample != null) samples.push(String(sample));
    }
    return bandsReach(samples, members);
  }, [bands, members, mode]);
  // Failed (payloads null) or not yet answered: not known, the table stays plain.
  const bandsFailed = Boolean(bands && bandPayloads?.key === bandsKey && !bandPayloads.payloads);
  const reportBandsReach = React.useRef(onBandsReach);
  reportBandsReach.current = onBandsReach;
  const bandsOutcome = !bands ? null : bandsFailed ? false : bandsReached;
  useEffect(() => {
    reportBandsReach.current?.(bandsOutcome);
  }, [bandsOutcome]);

  const bandMeta = useMemo(
    () => (bands ? [...bands.panels.map((p) => ({ name: p.name, color: p.color })), { name: 'Other', color: undefined as string | undefined }] : []),
    [bands],
  );
  const banded = useMemo(
    () =>
      bands && members && bandsReached
        ? bandRows(
            sortedRows,
            (r) => {
              const sample = rowSample(r);
              return sample == null ? null : String(sample);
            },
            members,
            bands.showOther,
          )
        : null,
    [bands, members, bandsReached, sortedRows],
  );
  const displayed = useMemo(
    () => banded ?? sortedRows.map((row) => ({ row, band: null as number | null })),
    [banded, sortedRows],
  );
  const bandCounts = useMemo(() => {
    const counts = new Map<number, number>();
    for (const d of banded ?? []) counts.set(d.band, (counts.get(d.band) ?? 0) + 1);
    return counts;
  }, [banded]);

  const totalPages = Math.max(1, Math.ceil(displayed.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const visibleRows = useMemo(
    () => displayed.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE),
    [displayed, safePage],
  );
  // A header row where a page, or a group, starts.
  const bandHeaderRows = banded
    ? visibleRows.filter((d, i) => d.band !== visibleRows[i - 1]?.band).length
    : 0;

  // What this table holds, for a Split to compare its panels by.
  const reportSignature = React.useRef(onSignature);
  reportSignature.current = onSignature;
  const signature = useMemo(
    () =>
      payload && !loading
        ? `${(payload.modes.mean?.table_data ?? []).length}:${(payload.modes.mean?.table_data ?? [])
            .map((r) => String(rowSample(r) ?? ''))
            .join('|')}`
        : null,
    [payload, loading],
  );
  useEffect(() => {
    reportSignature.current?.(signature);
  }, [signature]);

  // Height the table asks the grid for. Nothing in the violin view: a plot
  // keeps the height its author gave it.
  const contentPx =
    mode && view === 'table' && visibleRows.length > 0
      ? TABLE_CHROME_PX +
        (splitLabel ? COMPACT_HEADER_PX : TABLE_HEADER_PX) +
        (visibleRows.length + bandHeaderRows) * (splitLabel ? COMPACT_ROW_PX : TABLE_ROW_PX) +
        (totalPages > 1 ? TABLE_PAGER_PX : 0)
      : null;
  const contentDemand = useMemo(
    () => (contentPx != null ? { rows: rowsForHeight(contentPx) } : null),
    [contentPx],
  );
  // A table of a Split tells the split, which publishes for the whole tile:
  // each table publishing under the tile's index would size it to one of them.
  useContentDemand(onContentHeight ? undefined : metadata.index, contentDemand);
  const reportContentHeight = React.useRef(onContentHeight);
  reportContentHeight.current = onContentHeight;
  // To a split: 0 for a table loaded with no row, the violin plot's own
  // height, else the table's; `null` while it loads.
  const reportedPx =
    payload == null || loading
      ? null
      : view !== 'table'
        ? VIOLIN_SPLIT_PX
        : visibleRows.length === 0
          ? 0
          : contentPx;
  useEffect(() => {
    reportContentHeight.current?.(reportedPx);
  }, [reportedPx]);

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

  // "Compare with last visit" (#1397): the rows of samples new since the
  // reader's last visit keep their look, the rows already seen fade.
  const changeMark = useChangeMark(componentIndex);
  const diffState = useComponentDiff({
    dashboardId,
    componentId: componentIndex,
    comparing: changeMark.comparing,
    filters: filters ?? [],
  });
  const newSamples = useMemo(() => {
    const d = diffState.diff;
    // A truncated list would fade new rows it left out: then fade nothing.
    return d && d.supported && d.shape === 'samples' && !d.truncated ? new Set(d.added.map(String)) : null;
  }, [diffState.diff]);
  const matchedNew = useMemo(() => {
    if (!newSamples) return 0;
    return (mode?.table_data ?? []).filter((r) => {
      const s = rowSample(r);
      return s != null && newSamples.has(String(s));
    }).length;
  }, [newSamples, mode]);

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
    if (splitLabel) {
      // The group, where a reader looks first: a bar of its colour, its name
      // and how many of its samples this table lists.
      return (
        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
          <div
            style={{
              width: 4,
              height: 16,
              borderRadius: 2,
              flexShrink: 0,
              background: splitLabel.color ?? 'var(--mantine-color-gray-5)',
            }}
          />
          <Text fw={700} size="sm" truncate style={{ color: splitLabel.color ?? 'inherit' }}>
            {splitLabel.name}
          </Text>
          {payload && (
            <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
              {displayed.length} {displayed.length === 1 ? 'sample' : 'samples'}
            </Text>
          )}
        </Group>
      );
    }
    const pairedEnd = !!payload?.is_paired_end;
    // When the dataset isn't paired-end, only one set of values exists per
    // sample — there's no Mean/R1/R2 distinction to make. Surface that as the
    // "All" pill (instead of "Mean") so the active label matches the data.
    return (
      <Group justify="space-between" align="center" wrap="nowrap">
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
          <Text fw={600} size="sm">{titleText}</Text>
          {badge}
          {changeMark.comparing && (
            <DiffSummaryChip
              diff={diffState.diff}
              loading={diffState.loading}
              error={diffState.error}
              matched={matchedNew}
            />
          )}
        </Group>
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
                  <Table.Th style={{ ...headerStyle, cursor: 'default', width: 40 }} title="Annotations" />
                )}
                {columns.map((col) => {
                  const isSort = sortKey === col.id;
                  const arrow = isSort ? (sortDir === 'asc' ? ' ↑' : sortDir === 'desc' ? ' ↓' : '') : '';
                  return (
                    <Table.Th
                      key={col.id}
                      style={headerStyle}
                      onClick={() => onHeaderClick(col.id)}
                    >
                      {col.name}{arrow}
                    </Table.Th>
                  );
                })}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {visibleRows.flatMap(({ row, band }, rowIdx) => {
                const sample = rowSample(row);
                const mark = sample == null ? undefined : rowAnnotations.get(String(sample));
                const picked = annotating && sample != null && annotateSelected.has(String(sample));
                const tone = rowTone(mark, picked);
                const stripe = mark ? annotationColorValue(mark.color, colorScheme) : undefined;
                // Faded only when some row is known new: a name mismatch must not
                // dim the whole table, nor a row whose sample cannot be read.
                const seenBefore =
                  newSamples !== null &&
                  matchedNew > 0 &&
                  sample != null &&
                  !newSamples.has(String(sample));
                const meta = band != null ? bandMeta[band] : undefined;
                const tint = bandTint(meta?.color);
                // A header where a group starts, and again at the top of a page
                // so a page never opens on rows of an unnamed group.
                const header =
                  meta && band !== visibleRows[rowIdx - 1]?.band ? (
                    <Table.Tr key={`band-${rowIdx}`} data-group-band={meta.name}>
                      <Table.Td
                        colSpan={columns.length + (hasRowAnnotations ? 1 : 0)}
                        style={{
                          ...cellBaseStyle,
                          fontWeight: 700,
                          backgroundColor: bandTint(meta.color) ?? 'var(--mantine-color-default-hover)',
                          borderLeft: `4px solid ${meta.color ?? 'var(--mantine-color-gray-5)'}`,
                          color: meta.color ?? 'var(--mantine-color-dimmed)',
                        }}
                      >
                        {meta.name}
                        <span style={{ fontWeight: 400, marginLeft: 8, color: 'var(--mantine-color-dimmed)' }}>
                          {bandCounts.get(band as number) ?? 0}
                        </span>
                      </Table.Td>
                    </Table.Tr>
                  ) : null;
                const rowEl = (
                  <Table.Tr
                    key={rowIdx}
                    onClick={annotating ? () => toggleAnnotateRow(row) : undefined}
                    data-diff-row={newSamples ? (seenBefore ? 'seen' : 'new') : undefined}
                    style={{
                      ...(seenBefore ? { opacity: SEEN_ROW_OPACITY } : {}),
                      ...(annotating ? { cursor: 'pointer' } : {}),
                      ...(picked
                        ? { outline: '2px dashed var(--mantine-primary-color-filled)', outlineOffset: -2 }
                        : {}),
                    }}
                  >
                    {hasRowAnnotations && (
                      <Table.Td
                        style={{
                          ...badgeCellStyle,
                          ...(tint ? { backgroundColor: tint } : {}),
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
                        ...cellBaseStyle,
                        ...(col.id === 'Sample Name'
                          ? { fontWeight: 600, minWidth: 200 }
                          : {}),
                        ...(tint ? { backgroundColor: tint } : {}),
                        ...(bar
                          ? {
                              backgroundImage: bar.backgroundImage,
                              paddingTop: bar.paddingTop ?? cellBaseStyle.padding,
                              paddingBottom: bar.paddingBottom ?? cellBaseStyle.padding,
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
                return header ? [header, rowEl] : [rowEl];
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
      p={splitLabel ? 6 : 'sm'}
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
