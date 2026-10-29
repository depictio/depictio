import React, {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  CloseButton,
  Group,
  Menu,
  Paper,
  Popover,
  SegmentedControl,
  Select,
  Slider,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  AdvancedVizKind,
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { mantineCategoricalPalette, resolveCategoricalPalette, stableColorMap } from '../../colors';
import { usePinnedCategoryColors } from '../../hooks/useCategoryColors';
import {
  filtersExcludingOwn,
  genomePosFilterIndex,
  genomeRegionFilters,
  regionFromFilters,
} from '../../selection';
import { usePublishHighlight } from '../../highlight/bus';
import { contigSpellings } from '../../highlight/genomicHover';
import { useFullscreenPortalTarget } from '../chrome/useFullscreenPortalTarget';
import { isZoomWheel } from '../zoomGate';
import { useZoomGate } from '../zoomGateDom';
import AdvancedVizFrame from './AdvancedVizFrame';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import { demandForPx } from './contentDemand';
import {
  VizControlGroup,
  VizNumberInput,
  VizSegmented,
  VizSelect,
} from './controls/VizControls';
import { useFollowedRegion } from './genomicAxis';
import {
  ASSEMBLY_NAMES,
  autoBinSize,
  barSummary,
  chromosomeBars,
  featureSummary,
  featuresOf,
  formatBp,
  formatValue,
  idealHeight,
  layoutPanels,
  normaliseChrom,
  parseIdeogramRows,
  planFacets,
  scaleT,
  spanRect,
  valueExtent,
  type ChromBar,
  type IdeogramFeature,
  type Orientation,
  type PanelGeom,
} from './ideogram/ideogramLayout';
import {
  lutColour,
  paintDetail,
  paintHover,
  paintOverview,
  prepareCanvas,
  scaleLut,
  type DensityStyle,
  type HoverMark,
  type PaintColours,
  type PanelLayer,
} from './ideogram/ideogramPaint';
import {
  binAt,
  binBreakdown,
  binFeatures,
  binSpan,
  binValue,
  bpToX,
  centreWindow,
  countOverlapping,
  detailLayout,
  DRAG_MIN_PX,
  fullWindow,
  hitBar,
  lodDecision,
  nearestFeature,
  panWindow,
  screenBinSize,
  wheelZoomFactor,
  windowLabel,
  xToBp,
  zoomLevel,
  zoomWindow,
  type BinSet,
  type ChromIndex,
  type DrawnAs,
  type RenderMode,
  type Window,
  buildChromIndex,
} from './ideogram/ideogramView';
import { plotlyThemeColors } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `IdeogramConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there, and `test_advanced_viz_config_alignment`
 *  enforces it. */
interface IdeogramConfig {
  chrom_col: string;
  start_col: string;
  end_col: string;
  value_col?: string | null;
  category_col?: string | null;
  sample_col?: string | null;
  label_col?: string | null;
  chrom_length_col?: string | null;
  assembly?: string | null;
  mode?: RenderMode;
  bin_size?: number | null;
  orientation?: Orientation;
  chromosomes?: string[] | null;
  colour_scale?: ColourScale;
  facet_by_sample?: boolean;
  sample?: string | null;
  max_facets?: number;
  max_chromosomes?: number;
  max_features?: number;
  lod_threshold?: number;
  feature_opacity?: number;
  hidden_categories?: string[] | null;
  region_filter_enabled?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: IdeogramConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

// Every row is a feature a reader may be looking for (a BUSCO gene, a variant),
// so the server sends the frame whole (`KIND_SAMPLING_POLICY["ideogram"] ==
// "none"`). The canvas draws tens of thousands of rows in milliseconds; the
// level of detail decides marks against bins, never a subset of the marks.
const IDEOGRAM_VIZ_KIND: AdvancedVizKind = 'ideogram';

const DEFAULT_MAX_FEATURES = 20000;
const DEFAULT_LOD_THRESHOLD = 2000;
const DEFAULT_MAX_CHROMOSOMES = 60;
const DEFAULT_MAX_FACETS = 6;
const DEFAULT_OPACITY = 0.85;
const ASSEMBLY_AUTO = 'auto';
const ALL_GENOMES = '__all__';
const MAX_LEGEND_ENTRIES = 12;
/** Title, echo and legend strip, which do not scale with the bars. */
const CHROME_PX = 72;
/** The interaction toolbar over the canvas. */
const TOOLBAR_PX = 34;
/** Minimum detail-view canvas height that still fits locator, body and axis. */
const DETAIL_MIN_PX = 150;
/** Hit tolerance along a bar, in px. */
const HIT_TOL_PX = 3;

type ColourKind = 'category' | 'value' | 'count';

interface DetailTarget {
  /** Index of the karyotype (shown sample) the chromosome belongs to. */
  karyotype: number;
  key: string;
}

interface Karyotype {
  sample: string | null;
  bars: ChromBar[];
  droppedBars: ChromBar[];
  index: Map<string, ChromIndex>;
  /** Features drawn (on a bar, not hidden). */
  visible: number;
}

// ---------------------------------------------------------------------------
// Hover card: owns its own state so a pointer move never re-renders the tile.
// ---------------------------------------------------------------------------

interface HoverContent {
  title: string;
  lines: string[];
  breakdown?: { colour: string; label: string; count: number }[];
  hint?: string;
}

interface HoverCardHandle {
  show: (content: HoverContent, x: number, y: number) => void;
  hide: () => void;
}

/** The genomic interval a hover points at, for the highlight bus. */
interface HoverGenomic {
  refName: string;
  start: number;
  end: number;
  color?: string;
}

const HoverCard = forwardRef<HoverCardHandle, { bounds: { w: number; h: number } }>(({ bounds }, ref) => {
  const [state, setState] = useState<{ content: HoverContent; x: number; y: number } | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useImperativeHandle(
    ref,
    () => ({
      show: (content, x, y) => setState({ content, x, y }),
      hide: () => setState(null),
    }),
    [],
  );
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    setSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
  });
  if (!state) return null;
  const { content, x, y } = state;
  let left = x + 14;
  let top = y + 14;
  if (left + size.w > bounds.w - 4) left = Math.max(4, x - size.w - 10);
  if (top + size.h > bounds.h - 4) top = Math.max(4, y - size.h - 10);
  return (
    <Paper
      ref={boxRef}
      withBorder
      shadow="sm"
      p={6}
      radius="sm"
      style={{ position: 'absolute', left, top, maxWidth: 300, pointerEvents: 'none', zIndex: 3 }}
    >
      <Text size="xs" fw={600} lineClamp={2}>
        {content.title}
      </Text>
      {content.lines.map((line) => (
        <Text key={line} size="xs" c="dimmed" lineClamp={1}>
          {line}
        </Text>
      ))}
      {content.breakdown && content.breakdown.length > 0 ? (
        <Stack gap={1} mt={3}>
          {content.breakdown.map((b) => (
            <Group key={b.label} gap={5} wrap="nowrap">
              <span
                style={{ width: 8, height: 8, borderRadius: 2, background: b.colour, display: 'inline-block' }}
              />
              <Text size="xs" style={{ flex: 1 }} lineClamp={1}>
                {b.label}
              </Text>
              <Text size="xs" c="dimmed">
                {b.count.toLocaleString('en-US')}
              </Text>
            </Group>
          ))}
        </Stack>
      ) : null}
      {content.hint ? (
        <Text size="xs" c="dimmed" fs="italic" mt={3}>
          {content.hint}
        </Text>
      ) : null}
    </Paper>
  );
});
HoverCard.displayName = 'IdeogramHoverCard';

// ---------------------------------------------------------------------------
// The renderer
// ---------------------------------------------------------------------------

/**
 * A karyotype browser drawn on one canvas.
 *
 * Overview: every chromosome of each genome as a bar scaled to its length,
 * with marks while few features are in view and density bins above the level
 * of detail threshold (each bin in its dominant category, or on the value
 * scale). Click a chromosome, or pick one in the toolbar (the short contigs the
 * overview leaves out included), to open it: a horizontal detail view with its
 * own finer bins, a bp axis and a locator, zoomed with Ctrl/Cmd + wheel, the
 * buttons or a shift-drag, panned by dragging. Esc goes back.
 *
 * Opening a chromosome is local to the tile. Narrowing the rest of the
 * dashboard to it (the `genome_selection` pair a genome_view brush emits) is an
 * explicit "Filter dashboard" action, and an active filter shows as a badge
 * that clears it.
 */
const IdeogramRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const config = (metadata.config || {}) as IdeogramConfig;
  const isDark = colorScheme === 'dark';
  const themeColors = plotlyThemeColors(isDark, theme);
  const palette = resolveCategoricalPalette(theme, mantineCategoricalPalette(theme, isDark));
  const portalTarget = useFullscreenPortalTarget();

  // ---- Controls. Defaults agree with IdeogramConfig's own. ---------------
  const [mode, setMode] = usePersistedVizControl<RenderMode>(metadata, 'mode', 'marks');
  const [orientation, setOrientation] = usePersistedVizControl<Orientation>(metadata, 'orientation', 'horizontal');
  const [assembly, setAssembly] = usePersistedVizControl<string | null>(metadata, 'assembly', null);
  const [binSize, setBinSize] = usePersistedVizControl<number | null>(metadata, 'bin_size', null);
  const [colourScale, setColourScale] = usePersistedVizControl<ColourScale>(metadata, 'colour_scale', 'Viridis');
  const [facetBySample, setFacetBySample] = usePersistedVizControl<boolean>(metadata, 'facet_by_sample', true);
  const [sample, setSample] = usePersistedVizControl<string | null>(metadata, 'sample', null);
  const [opacity, setOpacity] = usePersistedVizControl<number>(metadata, 'feature_opacity', DEFAULT_OPACITY);
  const [hiddenCats, setHiddenCats] = usePersistedVizControl<string[] | null>(metadata, 'hidden_categories', null);
  const [colourBy, setColourBy] = useState<'category' | 'value'>('category');
  const pinnedColours = usePinnedCategoryColors(config.category_col);

  const regionEnabled = Boolean(onFilterChange) && config.region_filter_enabled !== false;
  const lodThreshold = config.lod_threshold ?? DEFAULT_LOD_THRESHOLD;
  const maxFeatures = config.max_features ?? DEFAULT_MAX_FEATURES;

  const requiredCols = useMemo(() => {
    const cols = [config.chrom_col, config.start_col, config.end_col].filter(Boolean) as string[];
    for (const c of [
      config.value_col,
      config.category_col,
      config.sample_col,
      config.label_col,
      config.chrom_length_col,
    ]) {
      if (c && !cols.includes(c)) cols.push(c);
    }
    return cols;
  }, [
    config.chrom_col,
    config.start_col,
    config.end_col,
    config.value_col,
    config.category_col,
    config.sample_col,
    config.label_col,
    config.chrom_length_col,
  ]);

  // The tile never narrows itself by its own region, or filtering the
  // dashboard to chr3 would redraw the karyotype as chr3 alone and the reader
  // could never pick another chromosome. Both halves of the pair are dropped.
  const filtersForFetch = useMemo(() => {
    const withoutChrom = filtersExcludingOwn(filters, metadata.index, 'genome_selection');
    return filtersExcludingOwn(withoutChrom, genomePosFilterIndex(metadata.index), 'genome_selection');
  }, [filters, metadata.index]);

  const ownRegion = useMemo(() => {
    const posIndex = genomePosFilterIndex(metadata.index);
    const own = filters.filter(
      (f) => f.source === 'genome_selection' && (f.index === metadata.index || f.index === posIndex),
    );
    if (!own.length || !config.chrom_col || !config.start_col) return null;
    return regionFromFilters(own, config.chrom_col, config.start_col);
  }, [filters, metadata.index, config.chrom_col, config.start_col]);
  const followed = useFollowedRegion(metadata, config, filters);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || !config.chrom_col || !config.start_col) {
      setError('Ideogram: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns: requiredCols,
      filters: filtersForFetch,
      vizKind: IDEOGRAM_VIZ_KIND,
      roles: { chrom: config.chrom_col, start: config.start_col, end: config.end_col },
    })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setEstimated(Boolean(res.sampling?.degraded));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filtersForFetch),
    refreshTick,
  ]);

  const features = useMemo<IdeogramFeature[]>(() => {
    if (!rows) return [];
    return parseIdeogramRows(rows, {
      chrom: config.chrom_col,
      start: config.start_col,
      end: config.end_col,
      value: config.value_col,
      category: config.category_col,
      sample: config.sample_col,
      label: config.label_col,
      chromLength: config.chrom_length_col,
    });
  }, [
    rows,
    config.chrom_col,
    config.start_col,
    config.end_col,
    config.value_col,
    config.category_col,
    config.sample_col,
    config.label_col,
    config.chrom_length_col,
  ]);

  const facets = useMemo(
    () =>
      planFacets(features, {
        facetBySample,
        sample,
        maxFacets: config.max_facets ?? DEFAULT_MAX_FACETS,
      }),
    [features, facetBySample, sample, config.max_facets],
  );

  // ---- Colour ----------------------------------------------------------------
  const colourKind: ColourKind =
    config.category_col && (colourBy === 'category' || !config.value_col)
      ? 'category'
      : config.value_col
        ? 'value'
        : 'count';
  const useValue = colourKind === 'value';
  // A value bound and no bin width set: the rows are already bins (10 kb
  // windows, one row per sequence) and keep their own extents, merged only
  // where they are finer than the screen.
  const rowsAreBins = useValue && (binSize === null || binSize === undefined);

  // Colour universe: the whole fetched frame, so a class keeps its colour when
  // a filter removes its last feature from view.
  const colourMap = useMemo(
    () => stableColorMap(features.map((f) => f.category), palette, pinnedColours),
    [features, palette, pinnedColours],
  );
  const catIndex = useMemo(() => {
    const m = new Map<string, number>();
    colourMap.universe.forEach((v, i) => m.set(v, i));
    return m;
  }, [colourMap]);
  const catColours = useMemo(() => colourMap.universe.map((v) => colourMap.get(v)), [colourMap]);
  const catOf = useMemo(
    () => (colourKind === 'category' ? (f: IdeogramFeature) => (f.category ? (catIndex.get(f.category) ?? -1) : -1) : null),
    [colourKind, catIndex],
  );
  const hidden = useMemo(() => new Set(hiddenCats ?? []), [hiddenCats]);
  const lut = useMemo(() => scaleLut(colourScale), [colourScale]);
  const markExtent = useMemo(() => valueExtent(features), [features]);
  const primary = theme.colors[theme.primaryColor]?.[isDark ? 4 : 6] ?? themeColors.textColor;
  const markColour = useCallback(
    (f: IdeogramFeature): string => {
      if (colourKind === 'category' && f.category) return colourMap.get(f.category);
      if (colourKind === 'value' && f.value !== null && markExtent) {
        return lutColour(lut, scaleT(f.value, markExtent[0], markExtent[1]));
      }
      return primary;
    },
    [colourKind, colourMap, markExtent, lut, primary],
  );

  const paintColours = useMemo<PaintColours>(
    () => ({
      barFill: isDark ? theme.colors.dark[5] : theme.colors.gray[1],
      barStroke: isDark ? theme.colors.dark[2] : theme.colors.gray[5],
      text: themeColors.textColor,
      dimText: isDark ? theme.colors.dark[1] : theme.colors.gray[6],
      grid: themeColors.gridColor,
      highlight: theme.colors[theme.primaryColor]?.[isDark ? 3 : 7] ?? themeColors.textColor,
      fontFamily: theme.fontFamily ?? 'sans-serif',
    }),
    [isDark, theme, themeColors.textColor, themeColors.gridColor],
  );

  // ---- Karyotypes: bars and a sorted index per chromosome ------------------
  const karyotypes = useMemo<Karyotype[]>(
    () =>
      facets.shown.map((s) => {
        const own = featuresOf(features, s);
        const set = chromosomeBars(own, {
          assembly,
          order: config.chromosomes,
          maxChromosomes: config.max_chromosomes ?? DEFAULT_MAX_CHROMOSOMES,
        });
        const index = buildChromIndex(
          features,
          (f) => (s === null || f.sample === s) && !(f.category !== null && hidden.has(f.category)),
        );
        let visible = 0;
        for (const b of set.bars) visible += index.get(b.key)?.order.length ?? 0;
        return { sample: s, bars: set.bars, droppedBars: set.droppedBars, index, visible };
      }),
    [facets, features, assembly, config.chromosomes, config.max_chromosomes, hidden],
  );
  const totalBars = karyotypes.reduce((acc, k) => acc + k.bars.length, 0);
  const droppedBars = karyotypes.reduce((acc, k) => acc + k.droppedBars.length, 0);
  const visibleTotal = karyotypes.reduce((acc, k) => acc + k.visible, 0);

  // ---- Measuring -----------------------------------------------------------
  const baseRef = useRef<HTMLCanvasElement | null>(null);
  const overlayRef = useRef<HTMLCanvasElement | null>(null);
  const hoverRef = useRef<HoverCardHandle | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const hoverMarkRef = useRef<HoverMark | null>(null);
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  hostRef.current = host;
  const [view, setView] = useState({ w: 0, h: 0 });
  useEffect(() => {
    if (!host) return;
    const measure = () =>
      setView((prev) =>
        prev.w === host.clientWidth && prev.h === host.clientHeight
          ? prev
          : { w: host.clientWidth, h: host.clientHeight },
      );
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(host);
    return () => ro.disconnect();
  }, [host]);
  useZoomGate(hostRef, { block: false });

  // ---- Overview geometry and level of detail -------------------------------
  const panelInputs = useMemo(
    () => karyotypes.map((k) => ({ title: k.sample, bars: k.bars })),
    [karyotypes],
  );
  const panels = useMemo(
    () => layoutPanels(panelInputs, { width: view.w, height: view.h, orientation }),
    [panelInputs, view.w, view.h, orientation],
  );
  const overviewLod = lodDecision(mode, visibleTotal, { lodThreshold, maxFeatures });

  const overviewBinSize = useMemo(() => {
    if (binSize) return Math.max(1, Math.floor(binSize));
    const longest = panelInputs.reduce((acc, p) => p.bars.reduce((a, b) => Math.max(a, b.length), acc), 0);
    if (rowsAreBins) {
      const alongPx = panels.reduce((acc, p) => Math.min(acc, Math.max(1, p.far - p.origin)), Number.POSITIVE_INFINITY);
      return screenBinSize(longest, Number.isFinite(alongPx) ? alongPx : 800, 2);
    }
    return autoBinSize(longest, 100);
  }, [binSize, panelInputs, rowsAreBins, panels]);

  const overviewBins = useMemo<(Map<string, BinSet> | null)[]>(() => {
    if (overviewLod.drawn !== 'density') return karyotypes.map(() => null);
    return karyotypes.map((k) => {
      const out = new Map<string, BinSet>();
      for (const bar of k.bars) {
        out.set(
          bar.key,
          binFeatures(features, k.index.get(bar.key), {
            start: 0,
            end: bar.length,
            binSize: overviewBinSize,
            catOf,
            nCats: catColours.length,
            useValue,
            keepWide: rowsAreBins,
          }),
        );
      }
      return out;
    });
  }, [overviewLod.drawn, karyotypes, features, overviewBinSize, catOf, catColours.length, useValue, rowsAreBins]);

  // One scale across every karyotype, so a colour means the same in each genome.
  const overviewExtent = useMemo(() => {
    let lo = Number.POSITIVE_INFINITY;
    let hi = Number.NEGATIVE_INFINITY;
    let maxCount = 0;
    for (const m of overviewBins) {
      if (!m) continue;
      for (const b of m.values()) {
        maxCount = Math.max(maxCount, b.maxCount);
        if (b.maxCount > 0 || b.wide.length > 0) {
          lo = Math.min(lo, b.minValue);
          hi = Math.max(hi, b.maxValue);
        }
      }
    }
    return { value: Number.isFinite(lo) ? ([lo, hi] as [number, number]) : null, maxCount };
  }, [overviewBins]);

  const densityStyleFor = useCallback(
    (maxCount: number, valueExt: [number, number] | null): DensityStyle => ({
      kind: colourKind,
      catColours,
      lut,
      extent: colourKind === 'value' ? (valueExt ?? markExtent ?? [0, 1]) : [0, Math.max(1, maxCount)],
      maxCount,
    }),
    [colourKind, catColours, lut, markExtent],
  );

  // ---- Detail view state ---------------------------------------------------
  const [detail, setDetail] = useState<DetailTarget | null>(null);
  const [win, setWin] = useState<Window>({ start: 0, end: 1 });
  const [brush, setBrush] = useState<[number, number] | null>(null);
  const detailKaryotype = detail ? karyotypes[detail.karyotype] : undefined;
  const detailBar = useMemo(() => {
    if (!detail || !detailKaryotype) return null;
    return (
      detailKaryotype.bars.find((b) => b.key === detail.key) ??
      detailKaryotype.droppedBars.find((b) => b.key === detail.key) ??
      null
    );
  }, [detail, detailKaryotype]);
  const inDetail = detailBar !== null;
  const detailIdx = detail && detailKaryotype ? detailKaryotype.index.get(detail.key) : undefined;
  const L = detailBar?.length ?? 1;
  const geom = useMemo(() => detailLayout(view.w, Math.max(DETAIL_MIN_PX, view.h)), [view.w, view.h]);
  const detailVisible = inDetail ? countOverlapping(detailIdx, win.start, win.end) : 0;
  const detailLod = lodDecision(mode, detailVisible, { lodThreshold, maxFeatures });
  const span = Math.max(1, win.end - win.start);
  const detailBinSize = useMemo(() => {
    const screen = screenBinSize(span, geom.body.w, rowsAreBins ? 2 : 4);
    return binSize ? Math.max(1, Math.min(Math.floor(binSize), screen)) : screen;
  }, [span, geom.body.w, rowsAreBins, binSize]);
  // Bin the whole chromosome when that is a reasonable array (stable colours
  // while panning); far into a long chromosome, a chunk around the window.
  const chunk = detailBinSize * 512;
  const wholeChrom = L / detailBinSize <= 200_000;
  const chunkKey = wholeChrom ? -1 : Math.floor(win.start / chunk);
  const detailBins = useMemo(() => {
    if (!inDetail || detailLod.drawn !== 'density') return null;
    const start = wholeChrom ? 0 : Math.max(0, (chunkKey - 1) * chunk);
    const end = wholeChrom ? L : Math.min(L, (chunkKey + 2) * chunk + chunk);
    return binFeatures(features, detailIdx, {
      start,
      end,
      binSize: detailBinSize,
      catOf,
      nCats: catColours.length,
      useValue,
      keepWide: rowsAreBins,
    });
  }, [inDetail, detailLod.drawn, wholeChrom, chunkKey, chunk, L, features, detailIdx, detailBinSize, catOf, catColours.length, useValue, rowsAreBins]);
  const locatorBins = useMemo(() => {
    if (!inDetail) return null;
    return binFeatures(features, detailIdx, {
      start: 0,
      end: L,
      binSize: screenBinSize(L, geom.locator.w, 2),
      catOf,
      nCats: catColours.length,
      useValue,
      keepWide: rowsAreBins,
    });
  }, [inDetail, features, detailIdx, L, geom.locator.w, catOf, catColours.length, useValue, rowsAreBins]);

  const openDetail = useCallback(
    (karyotype: number, key: string, window?: Window) => {
      const k = karyotypes[karyotype];
      const bar = k?.bars.find((b) => b.key === key) ?? k?.droppedBars.find((b) => b.key === key);
      if (!bar) return;
      setDetail({ karyotype, key });
      setWin(window ?? fullWindow(bar.length));
      setBrush(null);
      hoverRef.current?.hide();
      wrapRef.current?.focus({ preventScroll: true });
    },
    [karyotypes],
  );
  const closeDetail = useCallback(() => {
    setDetail(null);
    setBrush(null);
    hoverRef.current?.hide();
  }, []);
  // A data change that drops the open chromosome returns to the overview.
  useEffect(() => {
    if (detail && !detailBar) setDetail(null);
  }, [detail, detailBar]);

  const zoomBy = useCallback(
    (factor: number, anchor?: number) => {
      if (!detailBar) return;
      setWin((w) => zoomWindow(w, factor, anchor ?? (w.start + w.end) / 2, detailBar.length));
    },
    [detailBar],
  );
  const resetZoom = useCallback(() => {
    if (detailBar) setWin(fullWindow(detailBar.length));
  }, [detailBar]);

  // ---- Region emission (explicit) ------------------------------------------
  const emitRegion = useCallback(
    (region: { chroms: string[]; range: [number, number] | null } | null) => {
      if (!onFilterChange || !regionEnabled) return;
      for (const filter of genomeRegionFilters(metadata, config.chrom_col, config.start_col, region)) {
        onFilterChange(filter);
      }
    },
    [onFilterChange, regionEnabled, metadata, config.chrom_col, config.start_col],
  );

  // ---- Painting -------------------------------------------------------------

  const canvasH = inDetail ? Math.max(DETAIL_MIN_PX, view.h) : view.h;

  useEffect(() => {
    const canvas = baseRef.current;
    if (!canvas || view.w <= 0 || canvasH <= 0) return;
    const frame = requestAnimationFrame(() => {
      const ctx = prepareCanvas(canvas, view.w, canvasH);
      if (!ctx) return;
      if (inDetail && detailBar && detailKaryotype) {
        const valueExt = overviewExtent.value ?? markExtent;
        paintDetail(
          ctx,
          {
            geom,
            bar: detailBar,
            title: `${detailKaryotype.sample ? `${detailKaryotype.sample} · ` : ''}${windowLabel(
              detailBar.name,
              win,
              L,
            )}  ·  ${detailVisible.toLocaleString('en-US')} of ${(detailIdx?.order.length ?? 0).toLocaleString(
              'en-US',
            )} features in view`,
            window: win,
            drawn: detailLod.drawn,
            index: detailIdx,
            features,
            bins: detailBins,
            locatorBins,
            markColour,
            density: densityStyleFor(detailBins?.maxCount ?? 1, valueExt),
            locatorDensity: densityStyleFor(locatorBins?.maxCount ?? 1, valueExt),
            opacity,
            own: ownRegion,
            followed,
            brush,
            colours: paintColours,
          },
          normaliseChrom,
        );
      } else {
        const layers: PanelLayer[] = karyotypes.map((k, i) => ({
          drawn: overviewLod.drawn,
          index: k.index,
          bins: overviewBins[i],
        }));
        paintOverview(ctx, {
          panels,
          layers,
          features,
          markColour,
          density: densityStyleFor(overviewExtent.maxCount, overviewExtent.value),
          opacity,
          own: ownRegion,
          followed,
          colours: paintColours,
        });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [
    view.w,
    canvasH,
    inDetail,
    detailBar,
    detailKaryotype,
    geom,
    win,
    L,
    detailVisible,
    detailLod.drawn,
    detailIdx,
    features,
    detailBins,
    locatorBins,
    markColour,
    densityStyleFor,
    opacity,
    ownRegion,
    followed,
    brush,
    paintColours,
    karyotypes,
    overviewLod.drawn,
    overviewBins,
    overviewExtent,
    markExtent,
    panels,
  ]);

  const paintOverlay = useCallback(() => {
    const canvas = overlayRef.current;
    if (!canvas || view.w <= 0 || canvasH <= 0) return;
    const ctx = prepareCanvas(canvas, view.w, canvasH);
    if (ctx) paintHover(ctx, hoverMarkRef.current, paintColours);
  }, [view.w, canvasH, paintColours]);
  useEffect(() => {
    hoverMarkRef.current = null;
    paintOverlay();
  }, [paintOverlay, inDetail, win]);

  // ---- Hover ----------------------------------------------------------------
  const valueLabel = config.value_col ?? 'value';

  const featureContent = (f: IdeogramFeature): HoverContent => {
    const parts = featureSummary(f, valueLabel);
    return { title: parts[0] ?? f.chrom, lines: parts.slice(1) };
  };
  const binContent = (bar: ChromBar, bins: BinSet, b: number): HoverContent => {
    const [s, e] = binSpan(bins, b);
    const count = bins.count[b];
    const lines = [`${count.toLocaleString('en-US')} feature${count === 1 ? '' : 's'} in this bin`];
    if (useValue) lines.push(`mean ${valueLabel} ${formatValue(binValue(bins, b, true))}`);
    const breakdown = binBreakdown(bins, b, 6).map((x) => ({
      colour: catColours[x.cat],
      label: colourMap.universe[x.cat],
      count: x.count,
    }));
    return {
      title: `${bar.name}:${formatBp(s)}–${formatBp(Math.min(bar.length, e))}`,
      lines,
      breakdown,
    };
  };
  const chromContent = (k: Karyotype, bar: ChromBar, hint: string): HoverContent => {
    const n = k.index.get(bar.key)?.order.length ?? 0;
    const lines = barSummary(bar, n).split('  ·  ').slice(1);
    if (k.sample) lines.push(k.sample);
    return { title: bar.name, lines, hint };
  };

  const pointerXY = (e: { clientX: number; clientY: number }) => {
    const box = overlayRef.current?.getBoundingClientRect();
    return box ? { x: e.clientX - box.left, y: e.clientY - box.top } : { x: 0, y: 0 };
  };

  // What the pointer is on, as a genomic interval, goes out on the highlight
  // bus: a genome browser draws a band there, wearing the mark's colour. Never
  // a filter. The bus coalesces and drops repeats, so every move may publish.
  const publishHighlight = usePublishHighlight(String(metadata.index));
  useEffect(() => () => publishHighlight(null), [publishHighlight]);
  const publishGenomic = (g: HoverGenomic | null) => {
    if (!g || !g.refName || !Number.isFinite(g.start) || !Number.isFinite(g.end)) {
      publishHighlight(null);
      return;
    }
    const aliases = contigSpellings(g.refName);
    publishHighlight({
      entity: g.refName,
      start: Math.min(g.start, g.end),
      end: Math.max(g.start, g.end),
      ...(aliases ? { entityAliases: aliases } : {}),
      positionColumn: config.start_col,
      ...(g.color ? { color: g.color } : {}),
      genomic: {
        refName: g.refName,
        start: Math.min(g.start, g.end),
        end: Math.max(g.start, g.end),
        ...(aliases ? { aliases } : {}),
      },
    });
  };
  const featureGenomic = (f: IdeogramFeature): HoverGenomic => ({
    refName: f.chrom,
    start: f.start,
    end: Math.max(f.start, f.end),
    color: markColour(f),
  });

  const showHover = (
    content: HoverContent | null,
    mark: HoverMark | null,
    x: number,
    y: number,
    cursor: string,
    genomic: HoverGenomic | null = null,
  ) => {
    publishGenomic(genomic);
    if (content) hoverRef.current?.show(content, x, y);
    else hoverRef.current?.hide();
    hoverMarkRef.current = mark;
    paintOverlay();
    if (overlayRef.current) overlayRef.current.style.cursor = cursor;
  };

  const hoverOverview = (x: number, y: number) => {
    const hit = hitBar(panels, x, y);
    if (!hit) return showHover(null, null, x, y, 'default');
    const panel: PanelGeom = panels[hit.panel];
    const g = panel.bars[hit.bar];
    const k = karyotypes[hit.panel];
    const bpPerPx = panel.scaleLength / Math.max(1, panel.far - panel.origin);
    const tol = HIT_TOL_PX * bpPerPx;
    const chromHint = 'Click to open this chromosome';
    const barRect = { x: g.x, y: g.y, w: g.w, h: g.h };
    if (!hit.onLabel) {
      if (overviewLod.drawn === 'marks') {
        const fi = nearestFeature(features, k.index.get(g.bar.key), hit.pos, tol);
        if (fi >= 0) {
          const f = features[fi];
          const r = spanRect(panel, g, f.start, f.end, { minPx: 2, overhang: 3 });
          return showHover({ ...featureContent(f), hint: chromHint }, { rect: r, guideX: null, guideTop: 0, guideBottom: 0 }, x, y, 'pointer', featureGenomic(f));
        }
      } else {
        const bins = overviewBins[hit.panel]?.get(g.bar.key);
        const at = bins ? binAt(bins, features, hit.pos, tol) : null;
        if (bins && at) {
          if (at.kind === 'wide') {
            const f = features[at.feature];
            const r = spanRect(panel, g, f.start, f.end, { minPx: 1 });
            return showHover({ ...featureContent(f), hint: chromHint }, { rect: r, guideX: null, guideTop: 0, guideBottom: 0 }, x, y, 'pointer', featureGenomic(f));
          }
          const [s, e] = binSpan(bins, at.bin);
          const r = spanRect(panel, g, s, Math.min(g.bar.length, e), { minPx: 2 });
          return showHover({ ...binContent(g.bar, bins, at.bin), hint: chromHint }, { rect: r, guideX: null, guideTop: 0, guideBottom: 0 }, x, y, 'pointer', {
            refName: g.bar.name,
            start: s,
            end: Math.min(g.bar.length, e),
            color: primary,
          });
        }
      }
    }
    return showHover(chromContent(k, g.bar, chromHint), { rect: barRect, guideX: null, guideTop: 0, guideBottom: 0 }, x, y, 'pointer');
  };

  const inBody = (x: number, y: number) =>
    x >= geom.body.x && x <= geom.body.x + geom.body.w && y >= geom.body.y - 10 && y <= geom.axisY + 20;
  const inLocator = (x: number, y: number) =>
    x >= geom.locator.x - 4 &&
    x <= geom.locator.x + geom.locator.w + 4 &&
    y >= geom.locator.y - 6 &&
    y <= geom.locator.y + geom.locator.h + 6;

  const hoverDetail = (x: number, y: number) => {
    if (!detailBar || !detailKaryotype) return;
    if (inLocator(x, y)) {
      const pos = xToBp(x, fullWindow(L), geom.locator.x, geom.locator.w);
      return showHover(
        { title: `${detailBar.name}:${formatBp(Math.max(0, Math.min(L, pos)))}`, lines: [], hint: 'Click or drag to move the view' },
        null,
        x,
        y,
        'pointer',
      );
    }
    if (!inBody(x, y)) return showHover(null, null, x, y, 'default');
    const pos = xToBp(x, win, geom.body.x, geom.body.w);
    const tol = (HIT_TOL_PX * span) / Math.max(1, geom.body.w);
    const guide = { guideX: x, guideTop: geom.body.y - 8, guideBottom: geom.axisY };
    const toRect = (s: number, e: number) => {
      const x0 = bpToX(s, win, geom.body.x, geom.body.w);
      const x1 = bpToX(e, win, geom.body.x, geom.body.w);
      return { x: Math.max(geom.body.x, Math.min(x0, x1 - 1)), y: geom.body.y, w: Math.max(2, Math.min(x1, geom.body.x + geom.body.w) - Math.max(x0, geom.body.x)), h: geom.body.h };
    };
    if (detailLod.drawn === 'marks') {
      const fi = nearestFeature(features, detailIdx, pos, tol);
      if (fi >= 0) {
        const f = features[fi];
        return showHover(featureContent(f), { ...guide, rect: toRect(f.start, Math.max(f.end, f.start)) }, x, y, 'grab', featureGenomic(f));
      }
    } else if (detailBins) {
      const at = binAt(detailBins, features, pos, tol);
      if (at?.kind === 'wide') {
        const f = features[at.feature];
        return showHover(featureContent(f), { ...guide, rect: toRect(f.start, f.end) }, x, y, 'grab', featureGenomic(f));
      }
      if (at) {
        const [s, e] = binSpan(detailBins, at.bin);
        return showHover(binContent(detailBar, detailBins, at.bin), { ...guide, rect: toRect(s, e) }, x, y, 'grab', {
          refName: detailBar.name,
          start: s,
          end: Math.min(L, e),
          color: primary,
        });
      }
    }
    return showHover(
      { title: `${detailBar.name}:${Math.round(Math.max(0, Math.min(L, pos))).toLocaleString('en-US')}`, lines: [] },
      { ...guide, rect: null },
      x,
      y,
      'grab',
      // The base under the pointer: a cursor on the genome browser.
      { refName: detailBar.name, start: Math.round(pos), end: Math.round(pos), color: primary },
    );
  };

  // ---- Pointer gestures -----------------------------------------------------
  const dragRef = useRef<{
    x: number;
    y: number;
    kind: 'click' | 'pan' | 'brush' | 'locator';
    startWin: Window;
    moved: boolean;
  } | null>(null);

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) return;
    const { x, y } = pointerXY(e);
    wrapRef.current?.focus({ preventScroll: true });
    let kind: 'click' | 'pan' | 'brush' | 'locator' = 'click';
    if (inDetail) {
      if (inLocator(x, y)) kind = 'locator';
      else if (e.shiftKey) kind = 'brush';
      else kind = 'pan';
    }
    dragRef.current = { x, y, kind, startWin: win, moved: false };
    e.currentTarget.setPointerCapture?.(e.pointerId);
    if (kind === 'locator') setWin((w) => centreWindow(w, xToBp(x, fullWindow(L), geom.locator.x, geom.locator.w), L));
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const { x, y } = pointerXY(e);
    const drag = dragRef.current;
    if (!drag) {
      if (inDetail) hoverDetail(x, y);
      else hoverOverview(x, y);
      return;
    }
    if (Math.abs(x - drag.x) >= DRAG_MIN_PX || Math.abs(y - drag.y) >= DRAG_MIN_PX) drag.moved = true;
    if (!drag.moved || !detailBar) return;
    hoverRef.current?.hide();
    if (drag.kind === 'pan') {
      const s = drag.startWin.end - drag.startWin.start;
      setWin(panWindow(drag.startWin, (-(x - drag.x) * s) / Math.max(1, geom.body.w), L));
      if (overlayRef.current) overlayRef.current.style.cursor = 'grabbing';
    } else if (drag.kind === 'locator') {
      setWin((w) => centreWindow(w, xToBp(x, fullWindow(L), geom.locator.x, geom.locator.w), L));
    } else if (drag.kind === 'brush') {
      const a = xToBp(drag.x, drag.startWin, geom.body.x, geom.body.w);
      const b = xToBp(x, drag.startWin, geom.body.x, geom.body.w);
      setBrush([Math.max(0, Math.min(a, b)), Math.min(L, Math.max(a, b))]);
    }
  };

  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag) return;
    const { x, y } = pointerXY(e);
    if (drag.kind === 'brush' && brush && detailBar) {
      if (brush[1] - brush[0] > 0) setWin(zoomWindow({ start: brush[0], end: brush[1] }, 1, brush[0], L));
      setBrush(null);
      return;
    }
    setBrush(null);
    if (drag.moved) return;
    if (!inDetail) {
      const hit = hitBar(panels, x, y);
      if (hit) openDetail(hit.panel, panels[hit.panel].bars[hit.bar].bar.key);
    }
  };

  const onDoubleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!inDetail) return;
    const { x, y } = pointerXY(e);
    if (!inBody(x, y)) return;
    zoomBy(e.shiftKey ? 0.5 : 2, xToBp(x, win, geom.body.x, geom.body.w));
  };

  const onPointerLeave = () => {
    if (dragRef.current) return;
    showHover(null, null, 0, 0, 'default');
  };

  // Wheel: Ctrl / Cmd + wheel (or a trackpad pinch) zooms, as on every figure;
  // in fullscreen, where there is no page to scroll, a plain wheel zooms too. A
  // sideways wheel pans the detail view.
  const wheelRef = useRef<(e: WheelEvent) => void>(() => {});
  wheelRef.current = (e: WheelEvent) => {
    const { x, y } = pointerXY(e);
    const fullscreen = typeof document !== 'undefined' && document.fullscreenElement === wrapRef.current;
    const zoom = isZoomWheel(e) || fullscreen;
    if (!inDetail) {
      if (!zoom) return;
      const hit = hitBar(panels, x, y);
      if (!hit || e.deltaY >= 0) return;
      e.preventDefault();
      const bar = panels[hit.panel].bars[hit.bar].bar;
      openDetail(hit.panel, bar.key, zoomWindow(fullWindow(bar.length), 2, hit.pos, bar.length));
      return;
    }
    if (!detailBar) return;
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && !zoom) {
      e.preventDefault();
      setWin((w) => panWindow(w, (e.deltaX * (w.end - w.start)) / Math.max(1, geom.body.w), L));
      return;
    }
    if (!zoom) return;
    e.preventDefault();
    const anchor = xToBp(x, win, geom.body.x, geom.body.w);
    setWin((w) => zoomWindow(w, wheelZoomFactor(e.deltaY, e.deltaMode), anchor, L));
  };
  const overlayEl = overlayRef.current;
  useEffect(() => {
    const el = overlayRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => wheelRef.current(e);
    el.addEventListener('wheel', handler, { passive: false });
    return () => el.removeEventListener('wheel', handler);
  }, [overlayEl, view.w > 0]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!inDetail || !detailBar) return;
    const target = e.target as HTMLElement;
    // Esc from anywhere in the tile but a text field (a search box keeps its
    // own Esc); the other keys only when the canvas itself has the focus.
    if (e.key === 'Escape' && !target.closest('input, textarea')) {
      e.preventDefault();
      closeDetail();
      wrapRef.current?.focus({ preventScroll: true });
      return;
    }
    if (target !== wrapRef.current) return;
    const step = (win.end - win.start) * 0.25;
    if (e.key === 'ArrowLeft') setWin((w) => panWindow(w, -step, L));
    else if (e.key === 'ArrowRight') setWin((w) => panWindow(w, step, L));
    else if (e.key === '+' || e.key === '=') zoomBy(2);
    else if (e.key === '-' || e.key === '_') zoomBy(0.5);
    else if (e.key === '0') resetZoom();
    else return;
    e.preventDefault();
  };

  // ---- Fullscreen ------------------------------------------------------------
  const [isFullscreen, setIsFullscreen] = useState(false);
  useEffect(() => {
    const sync = () => setIsFullscreen(document.fullscreenElement === wrapRef.current && wrapRef.current !== null);
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);
  const toggleFullscreen = () => {
    const el = wrapRef.current;
    if (!el) return;
    if (document.fullscreenElement === el) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  };

  // ---- Toolbar data ----------------------------------------------------------
  const chromOptions = useMemo(
    () =>
      karyotypes.flatMap((k, ki) => {
        const groupName = k.sample ?? 'Chromosomes';
        const drawn = k.bars.map((b) => ({ value: `${ki}|${b.key}`, label: `${b.name}  ·  ${formatBp(b.length)}` }));
        const shorter = k.droppedBars.map((b) => ({
          value: `${ki}|${b.key}`,
          label: `${b.name}  ·  ${formatBp(b.length)}`,
        }));
        const out: { group: string; items: { value: string; label: string }[] }[] = [];
        if (drawn.length) out.push({ group: groupName, items: drawn });
        if (shorter.length) out.push({ group: `${groupName}: shorter, not drawn`, items: shorter });
        return out;
      }),
    [karyotypes],
  );

  const comboboxProps = { portalProps: { target: portalTarget }, withinPortal: true };
  const zoomed = inDetail && zoomLevel(win, L) > 1.0001;
  const ownLabel = ownRegion
    ? Number.isFinite(ownRegion.end)
      ? `${ownRegion.chrom}:${formatBp(ownRegion.start)}–${formatBp(ownRegion.end)}`
      : ownRegion.chrom
    : null;

  // Narrow tiles trade button labels for icons so the row never scrolls.
  const compact = view.w > 0 && view.w < 820;
  const toolbar = (
    <Group
      gap={6}
      wrap="nowrap"
      px={4}
      style={{ flex: '0 0 auto', minHeight: TOOLBAR_PX, overflowX: 'auto', overflowY: 'hidden', scrollbarWidth: 'none' }}
    >
      {inDetail ? (
        <Tooltip label="Back to the overview (Esc)" portalProps={{ target: portalTarget }} withArrow>
          {compact ? (
            <ActionIcon variant="light" size="md" onClick={closeDetail} aria-label="Back to the overview">
              <Icon icon="mdi:arrow-left" width={15} />
            </ActionIcon>
          ) : (
            <Button
              size="compact-xs"
              variant="light"
              leftSection={<Icon icon="mdi:arrow-left" width={14} />}
              onClick={closeDetail}
            >
              Overview
            </Button>
          )}
        </Tooltip>
      ) : facets.all.length > 1 ? (
        <Select
          size="xs"
          w={compact ? 128 : 150}
          aria-label="Genome"
          value={facetBySample ? ALL_GENOMES : (facets.shown[0] ?? null)}
          onChange={(v) => {
            if (!v || v === ALL_GENOMES) {
              setFacetBySample(true);
            } else {
              setFacetBySample(false);
              setSample(v);
            }
          }}
          data={[{ value: ALL_GENOMES, label: `All genomes (${facets.all.length})` }, ...facets.all]}
          allowDeselect={false}
          comboboxProps={comboboxProps}
        />
      ) : null}
      <Select
        size="xs"
        w={compact ? 128 : 170}
        aria-label="Go to chromosome"
        placeholder="Go to chromosome…"
        leftSection={<Icon icon="mdi:magnify" width={14} />}
        searchable
        limit={150}
        value={detail && inDetail ? `${detail.karyotype}|${detail.key}` : null}
        onChange={(v) => {
          if (!v) return;
          const [ki, key] = [Number(v.slice(0, v.indexOf('|'))), v.slice(v.indexOf('|') + 1)];
          openDetail(ki, key);
        }}
        data={chromOptions}
        nothingFoundMessage="No chromosome by that name"
        comboboxProps={comboboxProps}
      />
      <SegmentedControl
        size="xs"
        aria-label="Draw features as"
        value={mode}
        onChange={(v) => setMode((v as RenderMode) || 'marks')}
        data={[
          { value: 'auto', label: 'Auto' },
          { value: 'marks', label: 'Marks' },
          { value: 'density', label: 'Density' },
        ]}
      />
      <ActionIcon.Group>
        <Tooltip label={inDetail ? 'Zoom out (−)' : 'Open a chromosome to zoom'} portalProps={{ target: portalTarget }} withArrow>
          <ActionIcon variant="default" size="md" disabled={!zoomed} onClick={() => zoomBy(0.5)} aria-label="Zoom out">
            <Icon icon="mdi:magnify-minus-outline" width={15} />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={inDetail ? 'Zoom in (+)' : 'Open a chromosome to zoom'} portalProps={{ target: portalTarget }} withArrow>
          <ActionIcon variant="default" size="md" disabled={!inDetail} onClick={() => zoomBy(2)} aria-label="Zoom in">
            <Icon icon="mdi:magnify-plus-outline" width={15} />
          </ActionIcon>
        </Tooltip>
        <Tooltip label="Whole chromosome (0)" portalProps={{ target: portalTarget }} withArrow>
          <ActionIcon variant="default" size="md" disabled={!zoomed} onClick={resetZoom} aria-label="Reset zoom">
            <Icon icon="mdi:fit-to-screen-outline" width={15} />
          </ActionIcon>
        </Tooltip>
      </ActionIcon.Group>
      <Popover position="bottom" withArrow shadow="sm" portalProps={{ target: portalTarget }}>
        <Popover.Target>
          <Tooltip label="Feature opacity" portalProps={{ target: portalTarget }} withArrow>
            <ActionIcon variant="default" size="md" aria-label="Feature opacity">
              <Icon icon="mdi:circle-opacity" width={15} />
            </ActionIcon>
          </Tooltip>
        </Popover.Target>
        <Popover.Dropdown>
          <Text size="xs" mb={4}>
            Feature opacity {Math.round(opacity * 100)}%
          </Text>
          <Slider
            w={160}
            size="sm"
            min={0.1}
            max={1}
            step={0.05}
            value={opacity}
            onChange={(v) => setOpacity(v)}
            label={(v) => `${Math.round(v * 100)}%`}
          />
        </Popover.Dropdown>
      </Popover>
      <Box style={{ flex: 1 }} />
      {regionEnabled && inDetail && detailBar ? (
        <Menu position="bottom-end" withArrow shadow="sm" portalProps={{ target: portalTarget }}>
          <Menu.Target>
            {compact ? (
              <Tooltip label="Filter dashboard" portalProps={{ target: portalTarget }} withArrow>
                <ActionIcon variant="default" size="md" aria-label="Filter dashboard">
                  <Icon icon="mdi:filter-variant" width={15} />
                </ActionIcon>
              </Tooltip>
            ) : (
              <Button size="compact-xs" variant="default" leftSection={<Icon icon="mdi:filter-variant" width={14} />}>
                Filter dashboard
              </Button>
            )}
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Label>Narrow the other tiles to</Menu.Label>
            <Menu.Item onClick={() => emitRegion({ chroms: [detailBar.name], range: null })}>
              {detailBar.name} (whole chromosome)
            </Menu.Item>
            {zoomed ? (
              <Menu.Item
                onClick={() =>
                  emitRegion({ chroms: [detailBar.name], range: [Math.round(win.start), Math.round(win.end)] })
                }
              >
                The visible range ({windowLabel(detailBar.name, win, L)})
              </Menu.Item>
            ) : null}
          </Menu.Dropdown>
        </Menu>
      ) : null}
      {regionEnabled && ownLabel ? (
        <Tooltip
          label="This tile is filtering the dashboard: tiles bound to the same columns show this region only."
          multiline
          w={240}
          portalProps={{ target: portalTarget }}
          withArrow
        >
          <Badge
            size="sm"
            variant="light"
            style={{ flex: '0 0 auto', textTransform: 'none' }}
            leftSection={<Icon icon="mdi:filter" width={12} />}
            rightSection={
              <CloseButton
                size="xs"
                variant="transparent"
                aria-label="Clear the dashboard filter"
                onClick={() => emitRegion(null)}
              />
            }
          >
            {ownLabel}
          </Badge>
        </Tooltip>
      ) : null}
      {droppedBars > 0 && !inDetail ? (
        <Tooltip
          label={`${droppedBars.toLocaleString('en-US')} shorter sequence${
            droppedBars === 1 ? ' is' : 's are'
          } not drawn (max_chromosomes). Open any of them with "Go to chromosome".`}
          multiline
          w={240}
          portalProps={{ target: portalTarget }}
          withArrow
        >
          <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap', cursor: 'help' }}>
            +{droppedBars.toLocaleString('en-US')} short
          </Text>
        </Tooltip>
      ) : null}
      <Tooltip label={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'} portalProps={{ target: portalTarget }} withArrow>
        <ActionIcon variant="subtle" size="md" onClick={toggleFullscreen} aria-label="Fullscreen">
          <Icon icon={isFullscreen ? 'mdi:fullscreen-exit' : 'mdi:fullscreen'} width={17} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );

  // ---- Legend: category toggles, or the scale ------------------------------
  const toggleCategory = (value: string) => {
    const next = new Set(hidden);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    setHiddenCats(next.size ? [...next].sort() : null);
  };
  const drawnNow: DrawnAs = inDetail ? detailLod.drawn : overviewLod.drawn;
  const categoricalLegend =
    colourKind === 'category'
      ? colourMap.universe.slice(0, MAX_LEGEND_ENTRIES).map((value) => ({ value, colour: colourMap.get(value) }))
      : [];
  const rampExtent: [number, number] | null =
    colourKind === 'category'
      ? null
      : drawnNow === 'density'
        ? colourKind === 'value'
          ? (overviewExtent.value ?? markExtent)
          : [0, Math.max(1, (inDetail ? detailBins?.maxCount : overviewExtent.maxCount) ?? 1)]
        : colourKind === 'value'
          ? markExtent
          : null;
  const rampLabel =
    drawnNow === 'density'
      ? useValue
        ? `mean ${valueLabel}`
        : 'features per bin'
      : valueLabel;
  const rampGradient = useMemo(() => {
    const stops = Array.from({ length: 11 }, (_, i) => `${lutColour(lut, i / 10)} ${i * 10}%`);
    return `linear-gradient(to right, ${stops.join(', ')})`;
  }, [lut]);

  // ---- Echo and counts -----------------------------------------------------
  const echoParts: string[] = [];
  if (facets.all.length > 1) {
    echoParts.push(
      facets.shown.length === facets.all.length
        ? `${facets.all.length} karyotypes`
        : `${facets.shown.length} of ${facets.all.length} karyotypes`,
    );
  }
  echoParts.push(`${totalBars} chromosomes`);
  if (overviewLod.drawn === 'density') {
    echoParts.push(rowsAreBins ? `rows merged to ${formatBp(overviewBinSize)}` : `${formatBp(overviewBinSize)} bins`);
  }
  if (overviewLod.guarded) {
    echoParts.push(
      `${visibleTotal.toLocaleString('en-US')} features, above ${formatValue(maxFeatures)}: drawn as density`,
    );
  }
  const echo = rows && totalBars > 0 ? echoParts.join(' · ') : undefined;

  const counts = useMemo(() => {
    const out: Record<string, number> = { features: visibleTotal };
    if (facets.dropped > 0) out.karyotypes_hidden = facets.dropped;
    return out;
  }, [visibleTotal, facets.dropped]);

  const contentDemand = useMemo(() => {
    if (!rows || panelInputs.every((p) => p.bars.length === 0)) return undefined;
    return demandForPx(idealHeight(view.w || 800, panelInputs, orientation) + CHROME_PX + TOOLBAR_PX);
  }, [rows, panelInputs, view.w, orientation]);

  // ---- Settings popover (the encoding, not the interaction) ---------------
  const controls = (
    <>
      <VizControlGroup title="Chromosomes">
        <VizSelect
          label="Assembly"
          value={assembly ?? ASSEMBLY_AUTO}
          onChange={(v) => setAssembly(v && v !== ASSEMBLY_AUTO ? v : null)}
          data={[
            {
              value: ASSEMBLY_AUTO,
              label: config.chrom_length_col ? 'From the length column' : 'From the data',
            },
            ...ASSEMBLY_NAMES.map((name) => ({ value: name, label: name })),
          ]}
          allowDeselect={false}
        />
        <VizSegmented
          label="Bars"
          value={orientation}
          onChange={(v) => setOrientation((v as Orientation) || 'horizontal')}
          data={[
            { value: 'horizontal', label: 'Rows' },
            { value: 'vertical', label: 'Columns' },
          ]}
        />
        {config.category_col && config.value_col ? (
          <VizSegmented
            label="Colour"
            value={colourBy}
            onChange={(v) => setColourBy(v === 'value' ? 'value' : 'category')}
            data={[
              { value: 'category', label: 'Category' },
              { value: 'value', label: 'Value' },
            ]}
          />
        ) : null}
      </VizControlGroup>
      <VizControlGroup title="Density">
        <VizNumberInput
          label="Bin size (bp)"
          placeholder={useValue ? 'the rows' : 'automatic'}
          min={1}
          step={100000}
          value={binSize ?? ''}
          onChange={(v) => setBinSize(v === '' || v === null ? null : Math.max(1, Number(v)))}
        />
        <VizSelect
          label="Colour scale"
          value={colourScale}
          onChange={(v) => setColourScale((v as ColourScale) || 'Viridis')}
          data={COLOUR_SCALES.map((name) => ({ value: name, label: name }))}
          allowDeselect={false}
        />
      </VizControlGroup>
    </>
  );

  let emptyMessage: string | undefined;
  if (rows && totalBars === 0) {
    emptyMessage = features.length === 0 ? 'No features' : 'No chromosome left to draw';
  }

  const ariaLabel = inDetail && detailBar
    ? `Ideogram detail of ${detailBar.name}, ${windowLabel(detailBar.name, win, L)}, ${detailVisible} features in view`
    : `${totalBars} chromosomes, ${visibleTotal} features`;

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Ideogram'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      counts={totalBars > 0 ? counts : undefined}
      emptyMessage={emptyMessage}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
      contentDemand={contentDemand}
      echo={echo}
    >
      {rows && totalBars > 0 ? (
        <div
          ref={wrapRef}
          className="depictio-ideogram"
          tabIndex={0}
          onKeyDown={onKeyDown}
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            outline: 'none',
            background: isFullscreen ? 'var(--mantine-color-body)' : undefined,
            padding: isFullscreen ? 12 : undefined,
          }}
        >
          {toolbar}
          <div
            ref={setHost}
            style={{
              flex: '1 1 auto',
              minHeight: 0,
              position: 'relative',
              overflowY: inDetail && view.h < DETAIL_MIN_PX ? 'auto' : 'hidden',
            }}
          >
            {view.w > 0 && view.h > 0 ? (
              <>
                <canvas
                  ref={baseRef}
                  role="img"
                  aria-label={ariaLabel}
                  style={{ position: 'absolute', left: 0, top: 0, display: 'block' }}
                />
                <canvas
                  ref={overlayRef}
                  aria-hidden
                  style={{ position: 'absolute', left: 0, top: 0, display: 'block', touchAction: 'none', userSelect: 'none' }}
                  onPointerDown={onPointerDown}
                  onPointerMove={onPointerMove}
                  onPointerUp={onPointerUp}
                  onPointerCancel={() => {
                    dragRef.current = null;
                    setBrush(null);
                  }}
                  onPointerLeave={onPointerLeave}
                  onDoubleClick={onDoubleClick}
                />
              </>
            ) : null}
            <HoverCard ref={hoverRef} bounds={{ w: view.w, h: canvasH }} />
          </div>
          {categoricalLegend.length > 0 ? (
            <Group gap={8} mt={2} wrap="wrap" justify="center" style={{ flex: '0 0 auto' }}>
              {categoricalLegend.map(({ value, colour }) => {
                const off = hidden.has(value);
                return (
                  <UnstyledButton
                    key={value}
                    onClick={() => toggleCategory(value)}
                    aria-pressed={!off}
                    title={off ? `Show ${value}` : `Hide ${value}`}
                    style={{ opacity: off ? 0.45 : 1 }}
                  >
                    <Group gap={4} wrap="nowrap">
                      <span
                        style={{
                          width: 10,
                          height: 10,
                          borderRadius: 2,
                          backgroundColor: off ? 'transparent' : colour,
                          border: `1.5px solid ${colour}`,
                          display: 'inline-block',
                        }}
                      />
                      <Text size="xs" c="dimmed" td={off ? 'line-through' : undefined}>
                        {value}
                      </Text>
                    </Group>
                  </UnstyledButton>
                );
              })}
              {colourMap.universe.length > MAX_LEGEND_ENTRIES ? (
                <Text size="xs" c="dimmed">
                  +{colourMap.universe.length - MAX_LEGEND_ENTRIES} more
                </Text>
              ) : null}
              {hidden.size > 0 ? (
                <UnstyledButton onClick={() => setHiddenCats(null)}>
                  <Text size="xs" c="var(--mantine-primary-color-filled)">
                    Show all
                  </Text>
                </UnstyledButton>
              ) : null}
            </Group>
          ) : rampExtent ? (
            <Group gap={8} mt={2} wrap="nowrap" justify="center" style={{ flex: '0 0 auto' }}>
              <Text size="xs" c="dimmed">
                {formatValue(rampExtent[0])}
              </Text>
              <span
                aria-hidden
                style={{
                  width: 140,
                  height: 10,
                  borderRadius: 2,
                  background: rampGradient,
                  display: 'inline-block',
                }}
              />
              <Text size="xs" c="dimmed">
                {formatValue(rampExtent[1])}
              </Text>
              <Text size="xs" c="dimmed">
                {rampLabel}
              </Text>
            </Group>
          ) : null}
        </div>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default IdeogramRenderer;
