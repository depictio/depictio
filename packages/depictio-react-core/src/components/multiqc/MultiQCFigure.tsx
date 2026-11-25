import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Group, Paper, Text, Stack, useMantineColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { renderMultiQC, InteractiveFilter, StoredMetadata } from '../../api';
import { useInView } from '../../hooks/useInView';
import { useDataVersionRequest } from '../../dataVersions';
import { useChangeMark, useNewsSplitGroups } from '../../changeMarks';
import { panelFilters, panelsFromGroups, withOverallPanel } from '../../splitPanels';
import type { PanelSpec } from '../../splitPanels';
import SplitPanels from '../advanced_viz/SplitPanels';
import { useGroupsForDc } from '../advanced_viz/groupsForDc';
import GroupStatusBadge from '../GroupStatusBadge';
import { useReportGroupReach } from '../../groupReach';
import type { GroupRenderState } from '../../selectionGroups';
import {
  MULTIQC_NOT_GROUPED_LABEL,
  allIdentical,
  figureSamples,
  figureSignature,
  multiqcDeclineReasons,
  overlayGroupsOnFigure,
  planMultiQCGroups,
} from './multiqcGroups';
import type { MultiQCGroupDecline } from './multiqcGroups';
import { useFigureDiffOverlay } from '../../hooks/useComponentDiff';
import { enqueueFetch, isStaleFetch } from '../../fetchQueue';
import { readMultiqcSelection } from '../../utils/multiqcSelection';
import ComponentSkeleton from '../ComponentSkeleton';
import RefetchOverlay from '../RefetchOverlay';
import DiffSummaryChip from '../chrome/DiffSummaryChip';
import { useReportLoadStatus } from '../DashboardLoadingProvider';
import { usePlotAnnotationLayer } from '../annotations/usePlotAnnotationLayer';
import {
  MULTIQC_SAMPLE_COLUMN,
  multiqcFigureAnnotatable,
  multiqcVariantKey,
  withSampleCustomdata,
} from '../../annotations/multiqc';
import MultiQCGeneralStats from './MultiQCGeneralStats';
import { multiqcLogoSrc } from '../Glyph';
import { rowsForHeight, useContentDemand } from '../autofit';

interface MultiQCFigureProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** One panel of a split: the figure alone, no frame, title or overlay. */
  bare?: boolean;
  /** Analysis mode's groups and how to show them. A plot is split into one
   *  panel per group; General Stats is split too, or, in the Overlay, banded. */
  groupRender?: GroupRenderState;
  /** A group status badge, drawn beside the title (set by the wrapper). */
  badge?: React.ReactNode;
  /** What this panel drew, as a fingerprint; `null` while it loads. */
  onSignature?: (signature: string | null) => void;
  /** Overlay of Analysis mode on a plot: the groups drawn on its marks. */
  overlay?: { panels: PanelSpec[]; showOther: boolean } | null;
  /** How the overlay went: `null` while unknown or when there is none. */
  onOverlayReach?: (outcome: 'ok' | 'unreachable' | 'unsupported' | null) => void;
}

const NOOP = (): void => {};

// Plotly config / style passed by reference to keep <Plot> stable across renders.
const PLOT_CONFIG = { displaylogo: false, responsive: true } as const;
const PLOT_STYLE = { width: '100%', height: '100%' } as const;

/**
 * Renders one regular MultiQC Plotly figure. Server-side route wraps the pure
 * `create_multiqc_plot(s3_locations, module, plot, dataset_id, theme)` in
 * `figure_component/multiqc_vis.py:282` — same path the Dash callback uses.
 *
 * The route reads `selected_module`, `selected_plot`, `selected_dataset` and
 * `s3_locations` from the component's stored_metadata, so we just pass the
 * component_id and let the backend resolve everything.
 *
 * Mirrors FigureRenderer; the MultiQC overlay logo is a small absolutely
 * positioned image in the top-right corner (matches the Dash viewer chrome).
 */
// Defensive routing: when a General Stats component lands here (e.g. a stale
// HMR bundle of the parent dispatcher routes it as a regular figure), calling
// renderMultiQC 500s with `Module "general_stats" is not found`. Detect at
// the wrapper layer so the heavy hooks/effects of MultiQCFigureBody never
// mount in that case. Reads both `selected_*` and the legacy `multiqc_*`
// keys so pre-rename dashboards work without a re-save.
const MultiQCFigure: React.FC<MultiQCFigureProps> = (props) => {
  const isGeneralStats = readMultiqcSelection(props.metadata as Record<string, unknown>).isGeneralStats;
  // "What's new" split (#1397): the figure once for the new samples, once for
  // the samples seen before. Each panel is the same component with that
  // side's sample filter appended, which the render route resolves like the
  // dashboard's own "Sample ID" filter.
  const meta = props.metadata as Record<string, unknown>;
  const dcId = String(meta.dc_id ?? meta.data_collection_id ?? '');
  const splitGroups = useNewsSplitGroups(props.bare ? null : dcId);
  // Two sides mean the Split: the whole report first, as for the runs.
  const panels = useMemo(() => withOverallPanel(panelsFromGroups(splitGroups)), [splitGroups]);
  const newsActive = panels.length > 0;

  // Analysis mode (#1476). The "What's new" split wins when it is on: both
  // ask for panels and the two cannot share a tile.
  const analysis = props.bare || newsActive ? undefined : props.groupRender;
  const { groupRender: linkedGroups } = useGroupsForDc(analysis, props.dashboardId, dcId || undefined);
  const plan = useMemo(
    () => planMultiQCGroups(analysis ? linkedGroups : undefined, props.filters, isGeneralStats),
    [analysis, linkedGroups, props.filters, isGeneralStats],
  );
  const groupPanels = plan.kind === 'split' || plan.kind === 'bands' ? plan.panels : null;
  // The panels' identity: a new set of groups remounts the split, a new filter
  // does not (it only refetches each panel).
  const panelsKey = useMemo(() => (groupPanels ? JSON.stringify(groupPanels) : ''), [groupPanels]);
  const splitKey = useMemo(
    () => (groupPanels ? JSON.stringify([props.filters, groupPanels]) : ''),
    [groupPanels, props.filters],
  );
  // Every panel came back holding the same samples: the groups name nothing
  // this report can be narrowed on. Retried when the filters change.
  const [ineffectiveKey, setIneffectiveKey] = useState<string | null>(null);
  const splitIneffective = plan.kind === 'split' && ineffectiveKey === splitKey;
  const [bandsReached, setBandsReached] = useState<boolean | null>(null);
  useEffect(() => {
    if (plan.kind !== 'bands') setBandsReached(null);
  }, [plan.kind]);
  const [overlayOutcome, setOverlayOutcome] = useState<'ok' | 'unreachable' | 'unsupported' | null>(null);
  useEffect(() => {
    if (plan.kind !== 'overlay') setOverlayOutcome(null);
  }, [plan.kind]);

  let decline: { reason: MultiQCGroupDecline; panelCount?: number } | null = null;
  if (plan.kind === 'declined') decline = { reason: plan.reason, panelCount: plan.panelCount };
  else if (
    splitIneffective ||
    (plan.kind === 'bands' && bandsReached === false) ||
    (plan.kind === 'overlay' && overlayOutcome === 'unreachable')
  ) {
    decline = { reason: 'unreachable' };
  } else if (plan.kind === 'overlay' && overlayOutcome === 'unsupported') {
    decline = { reason: 'overlay_plot' };
  }
  const declineReason = decline?.reason;
  const declineCount = decline?.panelCount;
  const badge = useMemo(
    () =>
      declineReason ? (
        <GroupStatusBadge
          label={MULTIQC_NOT_GROUPED_LABEL}
          colored={false}
          reasons={multiqcDeclineReasons(declineReason, declineCount)}
        />
      ) : null,
    [declineReason, declineCount],
  );
  useReportGroupReach(
    props.bare || newsActive ? undefined : String(props.metadata.index),
    plan.kind === 'none' ? null : !decline,
  );

  if (panels.length > 1) {
    return (
      <MultiQCSplit {...props} panels={panels} isGeneralStats={isGeneralStats} />
    );
  }
  if (plan.kind === 'split' && !splitIneffective) {
    return (
      <MultiQCSplit
        key={panelsKey}
        {...props}
        panels={plan.panels}
        isGeneralStats={isGeneralStats}
        onIneffective={() => setIneffectiveKey(splitKey)}
      />
    );
  }
  // A single side ("New only") or a single group: that side's filter, no panels.
  const single = panels.length === 1 ? panels[0] : plan.kind === 'filter' ? plan.panel : null;
  const filters = single ? panelFilters(props.filters, single) : props.filters;
  if (isGeneralStats) {
    const { bare: _bare, groupRender: _groupRender, ...rest } = props;
    return (
      <MultiQCGeneralStats
        {...rest}
        filters={filters}
        badge={badge}
        bands={plan.kind === 'bands' ? { panels: plan.panels, showOther: plan.showOther } : null}
        onBandsReach={plan.kind === 'bands' ? setBandsReached : undefined}
      />
    );
  }
  return (
    <MultiQCFigureBody
      {...props}
      filters={filters}
      badge={badge}
      overlay={plan.kind === 'overlay' ? { panels: plan.panels, showOther: plan.showOther } : null}
      onOverlayReach={plan.kind === 'overlay' ? setOverlayOutcome : undefined}
    />
  );
};

const MultiQCSplit: React.FC<
  MultiQCFigureProps & {
    panels: ReturnType<typeof panelsFromGroups>;
    isGeneralStats: boolean;
    /** Raised when every panel drew the same thing: the split narrowed nothing. */
    onIneffective?: () => void;
  }
> = ({ panels, isGeneralStats, onIneffective, ...props }) => {
  const { bare: _bare, groupRender: _groupRender, badge: _badge, onSignature: _sig, ...rest } = props;
  const titleText = multiqcTitle(props.metadata);
  // What each panel drew, to tell a split that narrowed from one that did not.
  const signatures = useRef<Record<string, string | null>>({});
  const latest = useRef({ panels, onIneffective });
  latest.current = { panels, onIneffective };
  const reportSignature = useCallback((name: string, signature: string | null) => {
    signatures.current[name] = signature;
    const { panels: cells, onIneffective: raise } = latest.current;
    if (raise && allIdentical(cells.map((p) => signatures.current[p.name]))) raise();
  }, []);
  if (isGeneralStats) {
    return (
      <GeneralStatsQuadrants
        {...rest}
        panels={panels}
        filters={props.filters}
        onSignature={reportSignature}
      />
    );
  }
  return (
    <Paper
      p="sm"
      withBorder
      radius="md"
      style={{ flex: 1, minHeight: 0, height: '100%', display: 'flex', flexDirection: 'column' }}
    >
      {titleText && (
        <Text fw={600} size="sm" mb="xs">
          {titleText}
        </Text>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>
        <SplitPanels
          panels={panels}
          filters={props.filters}
          onIneffective={NOOP}
          renderPanel={(filters, key) => (
            <MultiQCFigureBody
              key={key}
              {...rest}
              filters={filters}
              bare
              onSignature={(sig) => reportSignature(key, sig)}
            />
          )}
        />
      </div>
    </Paper>
  );
};

function multiqcTitle(metadata: StoredMetadata): string {
  return (
    (metadata.title as string | undefined) ||
    [metadata.selected_module, metadata.selected_plot].filter(Boolean).join(' / ')
  );
}

/** Gap between the quadrants, and the Paper's padding and border around them. */
const QUADRANT_GAP_PX = 8;
const QUADRANT_FRAME_PX = 2 * 12 + 2;
/** A quadrant whose group has no sample in view, or not loaded yet. */
const QUADRANT_EMPTY_PX = 72;

/**
 * General Stats split: one table per group, dealt into quadrants (two
 * columns). Each quadrant is headed by its group (colour, name, sample count)
 * instead of the tile's title and controls, and its rows are dense, so it
 * lists more samples in its share of the tile; past that it scrolls. The tile
 * shrinks to its tallest row of quadrants when every table fits.
 */
const GeneralStatsQuadrants: React.FC<
  Omit<MultiQCFigureProps, 'onSignature' | 'badge' | 'bare' | 'groupRender'> & {
    panels: ReturnType<typeof panelsFromGroups>;
    onSignature: (name: string, signature: string | null) => void;
  }
> = ({ panels, filters, onSignature, ...rest }) => {
  const columns = panels.length <= 1 ? 1 : 2;
  const gridRows = Math.ceil(panels.length / columns);
  // What each table needs, in px (0: no row), absent until it first loads.
  const [heights, setHeights] = useState<Record<string, number>>({});
  const setHeight = useCallback((name: string, px: number | null) => {
    if (px == null) return;
    setHeights((prev) => (prev[name] === px ? prev : { ...prev, [name]: px }));
  }, []);
  const measured = panels.every((p) => p.name in heights);
  let total = QUADRANT_FRAME_PX + QUADRANT_GAP_PX * Math.max(0, gridRows - 1);
  for (let r = 0; r < gridRows; r++) {
    const row = panels.slice(r * columns, (r + 1) * columns);
    total += Math.max(...row.map((p) => heights[p.name] || QUADRANT_EMPTY_PX));
  }
  useContentDemand(rest.metadata.index, measured ? { rows: rowsForHeight(total) } : null);
  return (
    <Paper
      p="sm"
      withBorder
      radius="md"
      style={{
        flex: 1,
        minHeight: 0,
        height: '100%',
        display: 'grid',
        gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        gridTemplateRows: `repeat(${gridRows}, minmax(0, 1fr))`,
        gap: QUADRANT_GAP_PX,
      }}
    >
      {panels.map((panel) => (
        <div key={panel.name} style={{ minWidth: 0, minHeight: 0, display: 'flex' }}>
          <MultiQCGeneralStats
            {...rest}
            filters={panelFilters(filters, panel)}
            splitLabel={{ name: panel.name, color: panel.color }}
            onSignature={(sig) => onSignature(panel.name, sig)}
            onContentHeight={(px) => setHeight(panel.name, px)}
          />
        </div>
      ))}
    </Paper>
  );
};

// Backend returns 202 when the figure cache is being prebuilt. The viewer
// polls every PREPARE_POLL_INTERVAL_MS until the figure is ready or
// PREPARE_POLL_MAX_MS elapses (then gives up with an error). 1.5s feels
// responsive without hammering the backend. 5 min covers worst-case
// rebuilds (large reports, many modules, slow workers) with margin — if
// it actually trips, something upstream is wrong and we want a clear error.
const PREPARE_POLL_INTERVAL_MS = 1500;
const PREPARE_POLL_MAX_MS = 300_000;

const MultiQCFigureBody: React.FC<MultiQCFigureProps> = ({
  dashboardId,
  metadata,
  filters,
  refreshTick,
  bare,
  badge,
  onSignature,
  overlay,
  onOverlayReach,
}) => {
  const [figure, setFigure] = useState<
    { data?: unknown[]; layout?: Record<string, unknown> } | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { colorScheme } = useMantineColorScheme();
  // Data time travel: the version's report set rides in the body, its key in the effect deps.
  const { body: versionBody, key: versionKey } = useDataVersionRequest();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';
  const [containerRef, inView] = useInView<HTMLDivElement>('200px');

  // Match FigureRenderer's loading story: a full-panel ComponentSkeleton on the
  // first paint (chunk + data fetch read as one continuous shimmer), then keep
  // the previous figure mounted under a small RefetchOverlay on filter/theme
  // refetches instead of tearing the Plotly figure down. Also report status to
  // the dashboard load registry so the header progress bar counts MultiQC.
  const isInitialLoad = figure === null;
  const showInitialLoader = !inView || (isInitialLoad && loading);
  const showRefetchOverlay = !isInitialLoad && loading;
  useReportLoadStatus(
    metadata.index,
    !inView ? null : figure != null ? 'ready' : error ? 'error' : 'loading',
  );

  useEffect(() => {
    if (!inView) return;
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const startedAt = Date.now();

    const attempt = (): void => {
      setLoading(true);
      setError(null);
      // Queue the render POST so a dense dashboard paints top-down (vertical
      // position = priority) instead of firing every MultiQC panel at once —
      // mirrors FigureRenderer. Each 202-poll retry re-enqueues.
      enqueueFetch(
        () => renderMultiQC(dashboardId, metadata.index, filters, theme, versionBody),
        metadata.layout?.y ?? 0,
      )
        .then((res) => {
          if (cancelled) return;
          if (res.status === 'preparing') {
            setPreparing(true);
            if (Date.now() - startedAt >= PREPARE_POLL_MAX_MS) {
              setError('MultiQC figures took too long to build.');
              setLoading(false);
              return;
            }
            timeoutId = setTimeout(attempt, PREPARE_POLL_INTERVAL_MS);
            return;
          }
          setPreparing(false);
          setFigure(res.figure);
          setLoading(false);
        })
        .catch((err) => {
          if (cancelled) return;
          // A superseded queue generation (filter changed mid-flight) is not an
          // error — the effect is about to re-run with the new inputs. Clear
          // `loading` either way: a generation bump that doesn't also change
          // this component's deps leaves the effect un-re-run, and a stuck
          // `loading` pins the RefetchOverlay and keeps reporting 'loading' to
          // the dashboard load registry so the header bar never completes.
          if (!isStaleFetch(err)) setError(err?.message || String(err));
          setLoading(false);
        });
    };

    attempt();
    return () => {
      cancelled = true;
      if (timeoutId !== null) clearTimeout(timeoutId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, JSON.stringify(filters), theme, inView, refreshTick, versionKey]);

  const titleText = bare ? '' : multiqcTitle(metadata);

  // What this panel drew, for a Split to compare (null while it loads).
  const reportSignature = useRef(onSignature);
  reportSignature.current = onSignature;
  const signature = useMemo(
    () => (figure && !loading ? figureSignature(figure.data) : null),
    [figure, loading],
  );
  useEffect(() => {
    reportSignature.current?.(signature);
  }, [signature]);

  // Memoize the props passed to <Plot>. Without this, every parent re-render
  // (theme change, sibling layout shift, etc.) reconstructs `data` / `layout`
  // identities and triggers a full Plotly relayout, which is the dominant
  // client-side cost on big MultiQC figures.
  // Each point carries its sample in customdata, so marked points are stored
  // as sample ids (see annotations/multiqc.ts).
  const sampleData = useMemo(
    () => withSampleCustomdata((figure?.data as unknown[]) || []),
    [figure],
  );

  // Overlay of Analysis mode: each group's samples, as this plot names them,
  // read off the plot rendered for that group alone (the render a Split panel
  // makes, so the two agree on every sample). Fetched once the plot is drawn,
  // when the report's figures are known to be built.
  const overlayKey = overlay ? JSON.stringify([overlay.panels, filters, theme, versionKey]) : '';
  const [overlayMembers, setOverlayMembers] = useState<{ key: string; members: Set<string>[] | null } | null>(
    null,
  );
  const figureReady = figure != null && !loading;
  useEffect(() => {
    if (!overlay || !inView || !figureReady) return;
    let cancelled = false;
    Promise.all(
      overlay.panels.map((panel) =>
        enqueueFetch(
          () => renderMultiQC(dashboardId, metadata.index, panelFilters(filters, panel), theme, versionBody),
          metadata.layout?.y ?? 0,
        ),
      ),
    )
      .then((results) => {
        if (cancelled) return;
        const members = results.every((r) => r.status === 'ready')
          ? results.map((r) => figureSamples((r.figure?.data as unknown[]) ?? []))
          : null;
        setOverlayMembers({ key: overlayKey, members });
      })
      .catch((err) => {
        if (cancelled || isStaleFetch(err)) return;
        setOverlayMembers({ key: overlayKey, members: null });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlayKey, inView, figureReady, refreshTick]);
  const members = overlay && overlayMembers?.key === overlayKey ? overlayMembers.members : null;
  const groupView = useMemo(
    () =>
      overlay && members && figure
        ? overlayGroupsOnFigure(
            sampleData,
            (figure.layout as Record<string, unknown>) ?? {},
            overlay.panels.map((panel, i) => ({ name: panel.name, color: panel.color, members: members[i] })),
            overlay.showOther,
          )
        : null,
    [overlay, members, figure, sampleData],
  );
  const reportOverlay = useRef(onOverlayReach);
  reportOverlay.current = onOverlayReach;
  const overlayOutcome = !overlay || !groupView ? null : 'failed' in groupView ? groupView.failed : 'ok';
  useEffect(() => {
    reportOverlay.current?.(overlayOutcome);
  }, [overlayOutcome]);
  const drawn = groupView && !('failed' in groupView) ? groupView : null;
  const plotData = drawn ? drawn.data : sampleData;
  // "Compare with last visit" (#1397): the samples new since the reader's last
  // visit stand out, the rest recede. Inert unless switched on from the dot.
  const mark = useChangeMark(String(metadata.index));
  const comparing = !bare && mark.comparing;
  const diffView = useFigureDiffOverlay({
    dashboardId,
    componentId: String(metadata.index),
    comparing,
    filters,
    figure,
    rootRef: containerRef,
    theme,
  });
  const shownData = useMemo(() => diffView.apply(plotData), [diffView.apply, plotData]);
  const plotLayout = useMemo(
    () => ({
      ...((drawn?.layout ?? (figure?.layout as Record<string, unknown>)) || {}),
      autosize: true,
      margin: {
        l: 50,
        r: 20,
        t: 30,
        b: 50,
        ...((figure?.layout?.margin as Record<string, unknown>) || {}),
      },
      // Bump uirevision per refreshTick so realtime updates produce a unique
      // value and force Plotly to repaint. The server bakes in
      // `uirevision: "persistent"`; without overwriting it, identical
      // uirevision means Plotly skips repaint even on data changes.
      uirevision: `tick-${refreshTick ?? 0}`,
    }),
    [figure, drawn, refreshTick],
  );

  // ── Annotation layer ──────────────────────────────────────────────────────
  // Annotations are drawn on the dataset they were made on (the variant), and
  // marked points are samples: a line graph re-draws a marked sample's line,
  // a bar graph rings its bar.
  const selection = readMultiqcSelection(metadata as Record<string, unknown>);
  const variant = multiqcVariantKey({
    module: selection.module,
    plot: selection.plot,
    dataset: selection.dataset,
  });
  const annotations = usePlotAnnotationLayer({
    componentIndex: String(metadata.index),
    enabled: multiqcFigureAnnotatable(plotData),
    data: shownData,
    layout: plotLayout,
    pointIdIndex: 0,
    pointIdColumn: MULTIQC_SAMPLE_COLUMN,
    variant,
  });

  return (
    <Paper
      ref={containerRef}
      p={bare ? 0 : 'sm'}
      withBorder={!bare}
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
      {(titleText || badge || annotations.badges.length > 0) && (
        <Group gap="xs" mb="xs" wrap="nowrap">
          {titleText && (
            <Text fw={600} size="sm">
              {titleText}
            </Text>
          )}
          {badge}
          {annotations.badges}
        </Group>
      )}
      {comparing && (
        <DiffSummaryChip
          diff={diffView.diff}
          loading={diffView.loading}
          error={diffView.error}
          matched={diffView.overlay.matched}
        />
      )}
      {showInitialLoader && <ComponentSkeleton variant="block" />}
      {/* Paper-level, not inside the figure block: on a cold DC the backend
          202s and `figure` stays null for the whole poll window (up to
          PREPARE_POLL_MAX_MS), so a caption scoped to the rendered figure could
          only ever appear on a refetch — i.e. never when it's actually needed.
          Here it explains the 30-75s shimmer on first open. */}
      {preparing && (
        <Text
          size="xs"
          c="dimmed"
          style={{ position: 'absolute', bottom: 6, left: 10, zIndex: 1001 }}
        >
          Preparing MultiQC figures…
        </Text>
      )}
      {error && !loading && (
        <Stack style={{ flex: 1 }} justify="center" align="center">
          <Text size="sm" c="red" className="dashboard-error">MultiQC failed: {error}</Text>
        </Stack>
      )}
      {figure && !error && (
        <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
          <Plot
            data={annotations.data as any[]}
            layout={annotations.layout}
            revision={refreshTick ?? 0}
            config={PLOT_CONFIG}
            style={PLOT_STYLE}
            useResizeHandler
            {...annotations.plotProps()}
          />
          {annotations.toolbar}
          <RefetchOverlay visible={showRefetchOverlay} />
          {/* MultiQC logo overlay — official icon set
            (https://github.com/MultiQC/logo). Dark icon on light backgrounds,
            white icon in dark mode. The served SVG on a server; a serverless
            static bundle (file://, no /dashboard/logos/ mount) hands in
            inlined copies through `setMultiqcLogoSources`. `onError` still
            retires the element should a source ever fail to load, rather
            than leave a broken-image glyph in the corner of the tile. */}
          <img
            src={multiqcLogoSrc(theme === 'dark' ? 'white' : 'dark')}
            title="Generated with MultiQC"
            alt="MultiQC"
            onError={(e) => {
              e.currentTarget.style.display = 'none';
            }}
            style={{
              position: 'absolute',
              top: 10,
              right: 10,
              width: 40,
              height: 40,
              opacity: 0.6,
              pointerEvents: 'none',
              zIndex: 1000,
            }}
          />
        </div>
      )}
    </Paper>
  );
};

// React.memo with a custom comparator: filters are array-shaped, so a
// reference check would re-render whenever the parent re-creates the array
// even when the contents are identical. Stringifying mirrors the comparison
// the useEffect dep already uses. ``refreshTick`` MUST be in the comparator —
// otherwise realtime updates from the parent are memoized away and the fetch
// effect never re-runs.
export default React.memo(MultiQCFigure, (prev, next) => {
  return (
    prev.dashboardId === next.dashboardId &&
    prev.metadata.index === next.metadata.index &&
    prev.metadata.title === next.metadata.title &&
    prev.metadata.selected_module === next.metadata.selected_module &&
    prev.metadata.selected_plot === next.metadata.selected_plot &&
    prev.refreshTick === next.refreshTick &&
    prev.bare === next.bare &&
    // By reference: the dashboard memoises it, and its value lists can be long.
    prev.groupRender === next.groupRender &&
    JSON.stringify(prev.filters) === JSON.stringify(next.filters)
  );
});
