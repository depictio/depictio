import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  AdvancedVizKind,
  ContactMapResult,
  dispatchContactMap,
  fetchAdvancedVizData,
  InteractiveFilter,
  pollContactMap,
  StoredMetadata,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  VizControlGroup,
  VizSegmented,
  VizSelect,
  VizSlider,
  VizSwitch,
} from './controls/VizControls';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import {
  chooseResolution,
  coarsenBins,
  DEFAULT_BINS_PER_PIXEL,
  DEFAULT_PIXELS,
  formatResolution,
  shouldRefetchWindow,
} from './contactMapBinning';
import { displayForRegion, rotateToTriangle } from './contactMapTriangle';
import { regionXRange, useFollowedRegion } from './genomicAxis';
import { clipContactCells, inferContactWindow } from './contactMapWindow';
import { regionFilterActive } from './genomespy/defaultRegionGate';
import { applyDataTheme, applyLayoutTheme, plotlyThemeFragment } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Square puts genomic position on both axes; triangle rotates the matrix 45
 *  degrees so x alone carries position, on the same scale a `genome_view`
 *  track above it uses, and y carries the separation between the two bins. */
type ContactMapDisplay = 'square' | 'triangle';

/** Mirrors `ContactMapConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there, and `test_advanced_viz_config_alignment`
 *  enforces it. */
interface ContactMapConfig {
  chrom1_col: string;
  start1_col: string;
  chrom2_col: string;
  start2_col: string;
  count_col: string;
  end1_col?: string | null;
  end2_col?: string | null;
  sample_col?: string | null;
  resolution_col?: string | null;
  chrom?: string | null;
  log_scale?: boolean;
  colour_scale?: ColourScale;
  balance?: boolean;
  display?: ContactMapDisplay;
  max_separation_bins?: number;
  max_bins?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: ContactMapConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

// `contact_map` reads client-side as a whole grid, so the server never
// samples it (`KIND_SAMPLING_POLICY["contact_map"] == "none"`); `max_bins`
// below is this renderer's own guard on how large a matrix it draws.
const CONTACT_MAP_VIZ_KIND: AdvancedVizKind = 'contact_map';

const PLOT_STYLE = { width: '100%', height: '100%' };
const PLOT_CONFIG = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
  scrollZoom: false,
};

const DEFAULT_MAX_BINS = 500;

/** Column the `cooler/contact_matrix.py` recipe writes for the partition key.
 *  Requested even when the config does not name it: the data route drops
 *  columns a collection does not have, so asking costs nothing on a flat DC
 *  and is what lets a dashboard authored before multi-resolution zoom. */
const DEFAULT_RESOLUTION_COL = 'resolution';
/** A followed region narrower than this is widened around its centre before
 *  it is fetched: a gene window (a few kb) is one Hi-C bin, and a matrix of one
 *  cell says nothing about the neighbourhood the reader asked for. The
 *  reader's own zoom inside the tile is not widened. */
const MIN_REGION_SPAN_BP = 400_000;

/** How long a zoom has to settle before it is worth a round trip. */
const ZOOM_DEBOUNCE_MS = 300;

/** How long after new data an autorange is treated as Plotly fitting the axis
 *  rather than the reader resetting the zoom. */
const SETTLE_MS = 800;

/** Poll interval for the windowed fetch, matching the other compute kinds. */
const POLL_MS = 700;
const POLL_TIMEOUT_MS = 60_000;

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const bp = (v: number): string => Math.round(v).toLocaleString('en-US');

interface Window {
  start: number;
  end: number;
}

const ContactMapPlot = React.memo<{
  figure: { data?: unknown[]; layout?: Record<string, unknown> };
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
  onRelayout?: (event: Record<string, unknown>) => void;
}>(({ figure, isDark, theme, onRelayout }) => {
  const themedData = useMemo(() => applyDataTheme(figure.data, isDark, theme), [figure.data, isDark, theme]);
  const themedLayout = useMemo(
    () => applyLayoutTheme(figure.layout as any, isDark, theme),
    [figure.layout, isDark, theme],
  );
  return (
    <Plot
      data={themedData as any}
      layout={themedLayout as any}
      useResizeHandler
      style={PLOT_STYLE}
      config={PLOT_CONFIG as any}
      onRelayout={onRelayout as any}
    />
  );
});
ContactMapPlot.displayName = 'ContactMapPlot';

/**
 * Binned Hi-C style contact matrix: a symmetric heatmap of one chromosome's
 * intra-chromosomal contacts, coloured on a log scale by default. Only one
 * triangle of (bin1, bin2) needs to be present in the data: the figure mirrors
 * it across the diagonal.
 *
 * Two ways in, chosen by whether the tile is showing a window:
 *
 *  * **Whole chromosome** (no region filter, no zoom): the ordinary
 *    advanced-viz data route, and a matrix above `max_bins` per side is
 *    coarsened client-side by merging adjacent bins. When the collection
 *    carries several resolutions as partitions (the `resolution` column that
 *    `cooler/contact_matrix.py` writes), the coarsest one is drawn, which is
 *    the level a whole contig deserves.
 *  * **A window** (a `genome_selection` region reached the tile, or the reader
 *    zoomed the triangle): the `compute_contact_map` dispatch/poll route, which
 *    reads only the region and only from the resolution whose bins land closest
 *    to a quarter of a pixel each. Zooming in past a factor of two dispatches
 *    another window; panning inside the loaded one does not.
 *
 * Neither path needs the dashboard to declare anything: a collection with a
 * single resolution behaves exactly as it did before the column existed.
 */
const ContactMapRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const config = (metadata.config || {}) as ContactMapConfig;
  const isDark = colorScheme === 'dark';
  const maxBins = config.max_bins && config.max_bins > 0 ? config.max_bins : DEFAULT_MAX_BINS;
  const resolutionCol = config.resolution_col || DEFAULT_RESOLUTION_COL;

  const [logScale, setLogScale] = usePersistedVizControl<boolean>(metadata, 'log_scale', config.log_scale ?? true);
  const [colourScale, setColourScale] = usePersistedVizControl<ColourScale>(
    metadata,
    'colour_scale',
    config.colour_scale ?? 'Viridis',
  );
  const [balance, setBalance] = usePersistedVizControl<boolean>(metadata, 'balance', config.balance ?? false);
  const [chrom, setChrom] = usePersistedVizControl<string | null>(metadata, 'chrom', config.chrom ?? null);
  const [display, setDisplay] = usePersistedVizControl<ContactMapDisplay>(
    metadata,
    'display',
    config.display ?? 'square',
  );
  const [maxSeparationBins, setMaxSeparationBins] = usePersistedVizControl<number>(
    metadata,
    'max_separation_bins',
    config.max_separation_bins ?? 0,
  );

  // The region the dashboard is on, read through this tile's own columns.
  // `chrom1`/`start1` is the axis the triangle shares with a genome_view track
  // stacked above it.
  const region = useFollowedRegion(metadata, config as unknown as Record<string, unknown>, filters);

  // The reader's own zoom inside the tile, which only the triangle can report
  // (the square draws categorical labels, so its x range is not in base pairs).
  const [zoomWindow, setZoomWindow] = useState<Window | null>(null);
  useEffect(() => {
    // A new region supersedes whatever the reader had zoomed to.
    setZoomWindow(null);
  }, [region?.chrom, region?.start, region?.end]);

  const regionWindow: Window | null = useMemo(() => {
    if (!region || !Number.isFinite(region.start) || !Number.isFinite(region.end)) return null;
    if (region.end <= region.start) return null;
    const span = region.end - region.start;
    if (span >= MIN_REGION_SPAN_BP) return { start: region.start, end: region.end };
    const centre = (region.start + region.end) / 2;
    return {
      start: Math.max(0, Math.round(centre - MIN_REGION_SPAN_BP / 2)),
      end: Math.round(centre + MIN_REGION_SPAN_BP / 2),
    };
  }, [region?.start, region?.end]);
  const regionWidened = Boolean(
    region && regionWindow && regionWindow.end - regionWindow.start > region.end - region.start,
  );
  const wantedWindow = zoomWindow ?? regionWindow;

  // Triangle is the reading that lines up with the tracks under it, so a tile
  // that has been handed a region opens as one. An authored `display`, or the
  // reader's own pick, wins over that default.
  const displayPinned = useRef(config.display != null);
  const effectiveDisplay: ContactMapDisplay = displayForRegion(display, {
    pinned: displayPinned.current,
    hasRegion: Boolean(region),
  });
  const onDisplayChange = useCallback(
    (v: string) => {
      displayPinned.current = true;
      setDisplay(v as ContactMapDisplay);
    },
    [setDisplay],
  );

  const plotRef = useRef<HTMLDivElement | null>(null);
  // Quantised to 100 px: the width is part of the dispatch payload and therefore
  // of the server's cache key, so an unrounded width would mint a fresh job for
  // every pixel of a window drag while changing the answer for none of them.
  const pixels = Math.max(
    200,
    Math.round((plotRef.current?.clientWidth || DEFAULT_PIXELS) / 100) * 100,
  );

  const requiredCols = useMemo(() => {
    const cols = [
      config.chrom1_col,
      config.start1_col,
      config.chrom2_col,
      config.start2_col,
      config.count_col,
    ].filter(Boolean) as string[];
    for (const extra of [config.sample_col, resolutionCol]) {
      if (extra && !cols.includes(extra)) cols.push(extra);
    }
    return cols;
  }, [
    config.chrom1_col,
    config.start1_col,
    config.chrom2_col,
    config.start2_col,
    config.count_col,
    config.sample_col,
    resolutionCol,
  ]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);
  /** Set when the last frame came from the windowed route. */
  const [served, setServed] = useState<ContactMapResult['summary'] | null>(null);
  /** The window the loaded frame covers, so a pan inside it costs nothing. */
  const [loadedWindow, setLoadedWindow] = useState<Window | null>(null);
  /** Picked by the reader; `null` lets the span decide. */
  const [pinnedResolution, setPinnedResolution] = useState<number | null>(null);
  /** When the frame in hand arrived, so a fit-to-data autorange is not read as
   *  the reader resetting their zoom. */
  const loadedAt = useRef(0);

  // ---------------------------------------------------------------- fetching

  const fetchKey = useMemo(() => {
    if (!wantedWindow) return 'whole';
    return `${region?.chrom ?? ''}:${Math.round(wantedWindow.start)}-${Math.round(wantedWindow.end)}`;
  }, [wantedWindow?.start, wantedWindow?.end, region?.chrom]);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 5) {
      setError('Contact map: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    const wholeFrame = () =>
      fetchAdvancedVizData({
        wfId: metadata.wf_id!,
        dcId: metadata.dc_id!,
        columns: requiredCols,
        filters,
        vizKind: CONTACT_MAP_VIZ_KIND,
        roles: {
          chrom1: config.chrom1_col,
          start1: config.start1_col,
          chrom2: config.chrom2_col,
          start2: config.start2_col,
          count: config.count_col,
        },
      }).then((res) => {
        if (cancelled) return;
        loadedAt.current = Date.now();
        setRows(res.rows);
        setEstimated(Boolean(res.sampling?.degraded));
        setServed(null);
        setLoadedWindow(null);
      });

    const window = wantedWindow;
    if (!window || !region) {
      wholeFrame()
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
      return () => {
        cancelled = true;
      };
    }

    const windowed = async () => {
      let job = await dispatchContactMap({
        wf_id: metadata.wf_id!,
        dc_id: metadata.dc_id!,
        chrom1_col: config.chrom1_col,
        start1_col: config.start1_col,
        chrom2_col: config.chrom2_col,
        start2_col: config.start2_col,
        count_col: config.count_col,
        end1_col: config.end1_col ?? null,
        end2_col: config.end2_col ?? null,
        sample_col: config.sample_col ?? null,
        resolution_col: config.resolution_col ?? null,
        chrom: region.chrom,
        start: window.start,
        end: window.end,
        resolution: pinnedResolution,
        pixels,
        target_bins_per_pixel: DEFAULT_BINS_PER_PIXEL,
        filter_metadata: filters,
      });
      const deadline = Date.now() + POLL_TIMEOUT_MS;
      while (job.status === 'pending' && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        if (cancelled) return;
        job = await pollContactMap(job.job_id);
      }
      if (cancelled) return;
      if (job.status === 'failed') throw new Error(job.error || 'contact map window failed');
      if (job.status !== 'done' || !job.result) throw new Error('contact map window timed out');
      loadedAt.current = Date.now();
      setRows(job.result.rows);
      setServed(job.result.summary);
      setEstimated(Boolean(job.result.summary.truncated));
      setLoadedWindow(window);
    };

    windowed()
      .catch((err: unknown) => {
        if (cancelled) return;
        // An API that predates this route (or a worker that is down) must not
        // leave the tile empty: fall back to the whole frame and say so in the
        // echo line rather than failing a view that used to work.
        console.warn('contact_map: windowed fetch unavailable, reading the whole frame', err);
        return wholeFrame().catch((inner: unknown) => {
          if (!cancelled) setError(inner instanceof Error ? inner.message : String(inner));
        });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filters),
    fetchKey,
    pinnedResolution,
    refreshTick,
  ]);

  // -------------------------------------------------------------- zoom to bp

  const zoomTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (zoomTimer.current) clearTimeout(zoomTimer.current);
  }, []);

  const onRelayout = useCallback(
    (event: Record<string, unknown>) => {
      // Only the triangle carries base pairs on x; the square's axis is a list
      // of category labels and its range is an index, not a coordinate.
      if (effectiveDisplay !== 'triangle' || !region) return;
      if (zoomTimer.current) clearTimeout(zoomTimer.current);
      if (event['xaxis.autorange'] === true) {
        // A double-click resets to the region. An autorange that lands right
        // after new data arrived is Plotly fitting the axis to it, not the
        // reader asking for anything, and undoing their zoom on it would snap
        // the view back a beat after they zoomed in.
        if (Date.now() - loadedAt.current < SETTLE_MS) return;
        zoomTimer.current = setTimeout(() => setZoomWindow(null), ZOOM_DEBOUNCE_MS);
        return;
      }
      const lo = num(event['xaxis.range[0]']);
      const hi = num(event['xaxis.range[1]']);
      if (lo === null || hi === null || hi <= lo) return;
      const next = { start: lo, end: hi };
      zoomTimer.current = setTimeout(() => {
        if (shouldRefetchWindow(loadedWindow ?? wantedWindow, next)) setZoomWindow(next);
      }, ZOOM_DEBOUNCE_MS);
    },
    [effectiveDisplay, region, loadedWindow, wantedWindow?.start, wantedWindow?.end],
  );

  // ------------------------------------------------------------- resolutions

  /** Resolutions the frame in hand actually holds. On the windowed path the
   *  server reports the whole ladder; on the whole-frame path the column is
   *  read off the rows. */
  const resolutions = useMemo(() => {
    if (served?.resolutions?.length) return served.resolutions;
    if (!rows) return [] as number[];
    const column = rows[resolutionCol];
    if (!column) return [] as number[];
    const seen = new Set<number>();
    for (const v of column) {
      const n = num(v);
      if (n !== null && n > 0) seen.add(n);
    }
    return Array.from(seen).sort((a, b) => a - b);
  }, [rows, served, resolutionCol]);

  const span = wantedWindow ? wantedWindow.end - wantedWindow.start : null;
  const effectiveResolution = useMemo(() => {
    if (served?.resolution) return served.resolution;
    if (pinnedResolution && resolutions.includes(pinnedResolution)) return pinnedResolution;
    return chooseResolution(resolutions, span, pixels, DEFAULT_BINS_PER_PIXEL);
  }, [served, pinnedResolution, resolutions, span, pixels]);

  // Chromosomes present in the fetched frame, for the selector. The first one
  // seen (row order) is the default when no chrom is chosen yet.
  const chromOptions = useMemo(() => {
    if (!rows) return [] as string[];
    const c1 = (rows[config.chrom1_col] || []) as unknown[];
    const seen = new Set<string>();
    const ordered: string[] = [];
    for (const v of c1) {
      if (v === null || v === undefined) continue;
      const s = String(v);
      if (!seen.has(s)) {
        seen.add(s);
        ordered.push(s);
      }
    }
    return ordered;
  }, [rows, config.chrom1_col]);

  const effectiveChrom =
    (region?.chrom && chromOptions.includes(region.chrom) ? region.chrom : null) ??
    (chrom && chromOptions.includes(chrom) ? chrom : (chromOptions[0] ?? null));

  // Some tile's region is in force, so the rows may have come back narrowed
  // through a `region` link even when `region` above is null.
  const regionActive = regionFilterActive(filters);

  // The window the axis is pinned to when the tile is following a region.
  const xRange = useMemo(
    () => regionXRange(wantedWindow ? { chrom: '', ...wantedWindow } : null),
    [wantedWindow?.start, wantedWindow?.end],
  );

  const figure = useMemo(() => {
    if (!rows || !effectiveChrom) return null;
    const c1 = (rows[config.chrom1_col] || []) as unknown[];
    const s1 = (rows[config.start1_col] || []) as unknown[];
    const c2 = (rows[config.chrom2_col] || []) as unknown[];
    const s2 = (rows[config.start2_col] || []) as unknown[];
    const counts = (rows[config.count_col] || []) as unknown[];
    // Mixing two bin sizes on one axis draws nonsense, so exactly one
    // partition is read out of a multi-resolution frame.
    const res = (rows[resolutionCol] || null) as unknown[] | null;

    type Cell = { a: number; b: number; count: number };
    const rawCells: Cell[] = [];
    const n = Math.min(c1.length, s1.length, c2.length, s2.length, counts.length);
    for (let i = 0; i < n; i++) {
      if (String(c1[i]) !== effectiveChrom || String(c2[i]) !== effectiveChrom) continue;
      if (res && effectiveResolution !== null && num(res[i]) !== effectiveResolution) continue;
      const a = num(s1[i]);
      const b = num(s2[i]);
      const count = num(counts[i]);
      if (a === null || b === null || count === null) continue;
      rawCells.push({ a, b, count });
    }
    // Both bins of a pair on the window, by role (`contactMapWindow.ts`): the
    // window the tile fetched, or, when a region reached it only through a
    // `region` link on other column names, the first-bin extent of the
    // narrowed rows. Without that the second bin ran to the chromosome end.
    const axisWindow =
      wantedWindow ??
      (regionActive ? inferContactWindow(rawCells, effectiveResolution) : null);
    const cells = clipContactCells(rawCells, axisWindow, effectiveResolution);
    if (cells.length === 0) return null;
    const startSet = new Set<number>();
    for (const { a, b } of cells) {
      startSet.add(a);
      startSet.add(b);
    }
    const axisRange =
      xRange ?? (axisWindow ? regionXRange({ chrom: '', ...axisWindow }) : null);

    const sortedStarts = Array.from(startSet).sort((x, y) => x - y);
    const { buckets, index } = coarsenBins(sortedStarts, maxBins);
    const size = buckets.length;

    const rawSum: number[][] = Array.from({ length: size }, () => new Array(size).fill(0));
    for (const { a, b, count } of cells) {
      const ia = index.get(a)!;
      const ib = index.get(b)!;
      // Coarsened bins accumulate; the raw triangle is mirrored below.
      rawSum[ia][ib] += count;
      if (ia !== ib) rawSum[ib][ia] += count;
    }

    let matrix = rawSum;
    if (balance) {
      // Single-pass bias correction (not iterative ICE): divide each cell by
      // the geometric mean of its row and column sums, so high-coverage bins
      // stop dominating the colour scale. Good enough for a quick-look view;
      // a proper ICE balance belongs upstream of the DC.
      const rowSums = rawSum.map((r) => r.reduce((a, v) => a + v, 0));
      matrix = rawSum.map((r, i) =>
        r.map((v, j) => {
          const denom = Math.sqrt((rowSums[i] || 1) * (rowSums[j] || 1));
          return denom > 0 ? v / denom : 0;
        }),
      );
    }

    // log10 of positive values only: balanced (ICE) contacts sit far below 1, where
    // log1p flattens everything to ~0. Empty cells stay blank instead of -Infinity.
    const scaled = (v: number | null): number | null => {
      if (v === null) return null;
      if (!logScale) return v;
      return v > 0 ? Math.log10(v) : null;
    };
    const colourbarTitle = logScale ? 'log10(value)' : 'value';

    if (effectiveDisplay === 'triangle') {
      const { z: rotated, positionIndex, separations } = rotateToTriangle(matrix, maxSeparationBins);
      if (rotated.length === 0) return null;
      // A rotated column can land between two buckets (index i.5): that column
      // holds the contact between bin i and bin i+1, which belongs over their
      // midpoint.
      const positionAt = (p: number) => {
        const lo = buckets[Math.floor(p)] ?? 0;
        const hi = buckets[Math.ceil(p)] ?? lo;
        return (lo + hi) / 2;
      };
      const binWidth = size > 1 ? (buckets[size - 1] - buckets[0]) / (size - 1) : 0;
      return {
        data: [
          {
            type: 'heatmap' as const,
            x: positionIndex.map(positionAt),
            y: separations.map((sep) => sep * binWidth),
            z: rotated.map((row) => row.map((v) => scaled(v))),
            colorscale: colourScale,
            showscale: true,
            colorbar: { thickness: 10, len: 0.75, title: { text: colourbarTitle } },
            hovertemplate: `${effectiveChrom}:%{x}<br>separation: %{y}<br>value: %{z:.3g}<extra></extra>`,
          },
        ],
        layout: {
          ...plotlyThemeFragment(isDark, theme),
          margin: { l: 70, r: 20, t: 12, b: 50 },
          // Genomic position on x alone, so a genome_view track stacked in the
          // same section lines up with the matrix bin for bin. The range is
          // pinned to the region rather than fitted to the bins that came back,
          // because a bin straddling either edge would otherwise push this axis
          // wider than the tracks under it and break exactly that alignment.
          xaxis: {
            automargin: true,
            showgrid: false,
            title: { text: effectiveChrom },
            ...(axisRange ? { range: axisRange } : {}),
          },
          yaxis: { automargin: true, showgrid: false, title: { text: 'separation (bp)' } },
          autosize: true,
        },
      };
    }

    const z = matrix.map((row) => row.map((v) => scaled(v)));

    const labels = buckets.map((b) => `${effectiveChrom}:${Math.round(b / 1000)}kb`);

    return {
      data: [
        {
          type: 'heatmap' as const,
          x: labels,
          y: labels,
          z,
          colorscale: colourScale,
          showscale: true,
          colorbar: { thickness: 10, len: 0.75, title: { text: colourbarTitle } },
          hovertemplate: '%{x} × %{y}<br>value: %{z:.3g}<extra></extra>',
        },
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 70, r: 20, t: 12, b: 70 },
        xaxis: { tickangle: -45, automargin: true, showgrid: false },
        yaxis: { automargin: true, showgrid: false, autorange: 'reversed' as const },
        autosize: true,
      },
    };
  }, [
    rows,
    effectiveChrom,
    effectiveResolution,
    resolutionCol,
    config,
    maxBins,
    balance,
    logScale,
    colourScale,
    effectiveDisplay,
    maxSeparationBins,
    xRange,
    wantedWindow,
    regionActive,
    isDark,
    theme,
  ]);

  // ------------------------------------------------------------------ chrome

  /** One dim line saying what is on screen: where, at what bin size, and
   *  whether the matrix came windowed from the server or whole from the DC. */
  const echo = useMemo(() => {
    const parts: string[] = [];
    if (effectiveChrom) {
      parts.push(
        wantedWindow
          ? `${effectiveChrom}:${bp(wantedWindow.start)}-${bp(wantedWindow.end)}`
          : effectiveChrom,
      );
    }
    if (effectiveResolution) parts.push(formatResolution(effectiveResolution));
    if (regionWidened && !zoomWindow) parts.push('widened around the region');
    if (wantedWindow && !served) parts.push('whole collection, binned in the browser');
    if (served?.truncated) parts.push('truncated to the cell budget');
    return parts.length ? parts.join(' · ') : undefined;
  }, [effectiveChrom, wantedWindow?.start, wantedWindow?.end, effectiveResolution, served, regionWidened, zoomWindow]);

  const resolutionData = useMemo(
    () => [
      { value: '', label: resolutions.length ? 'Auto (fits the span)' : 'Single resolution' },
      ...resolutions.map((r) => ({ value: String(r), label: formatResolution(r) })),
    ],
    [resolutions],
  );

  const primaryControls = (
    <>
      <VizControlGroup title="View">
        {chromOptions.length > 0 ? (
          <VizSelect
            label="Chromosome"
            value={effectiveChrom}
            onChange={(v) => setChrom(v)}
            data={chromOptions}
            allowDeselect={false}
          />
        ) : null}
        <VizSegmented
          label="Display"
          value={effectiveDisplay}
          onChange={onDisplayChange}
          data={[
            { value: 'square', label: 'Square' },
            { value: 'triangle', label: 'Triangle' },
          ]}
        />
        <VizSelect
          label="Resolution"
          value={pinnedResolution === null ? '' : String(pinnedResolution)}
          onChange={(v) => setPinnedResolution(v ? Number(v) : null)}
          data={resolutionData}
          disabled={resolutions.length < 2}
          allowDeselect={false}
        />
      </VizControlGroup>
    </>
  );

  const controls = (
    <>
      <VizControlGroup title="Colour">
        <VizSelect
          label="Colour scale"
          value={colourScale}
          onChange={(v) => setColourScale((v as ColourScale) || 'Viridis')}
          data={COLOUR_SCALES as unknown as string[]}
          allowDeselect={false}
        />
      </VizControlGroup>
      <VizControlGroup title="Scaling">
        <VizSwitch
          checked={logScale}
          onChange={(e) => setLogScale(e.currentTarget.checked)}
          label="Log colour scale"
        />
        <VizSwitch
          checked={balance}
          onChange={(e) => setBalance(e.currentTarget.checked)}
          label="Row/column balance"
        />
      </VizControlGroup>
      {effectiveDisplay === 'triangle' ? (
        <VizControlGroup title="Triangle">
          <VizSlider
            label="Separation drawn (bins)"
            min={0}
            max={200}
            step={5}
            value={maxSeparationBins}
            onChangeEnd={(v) => setMaxSeparationBins(v)}
            thumbLabel={(v) => (v === 0 ? 'all' : String(v))}
            marks={[
              { value: 0, label: 'all' },
              { value: 100, label: '100' },
              { value: 200, label: '200' },
            ]}
          />
        </VizControlGroup>
      ) : null}
    </>
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Contact map'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      echo={echo}
      primaryControls={primaryControls}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={rows ? requiredCols.filter((c) => rows[c]) : requiredCols}
    >
      {figure ? (
        <div ref={plotRef} style={PLOT_STYLE}>
          <ContactMapPlot figure={figure} isDark={isDark} theme={theme} onRelayout={onRelayout} />
        </div>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default ContactMapRenderer;
