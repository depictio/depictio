import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Group, Paper, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';

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
import { sampleColorscale } from '../../utils/colorScale';
import AdvancedVizFrame from './AdvancedVizFrame';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import { demandForPx } from './contentDemand';
import {
  VizControlGroup,
  VizNumberInput,
  VizSegmented,
  VizSelect,
  VizSwitch,
} from './controls/VizControls';
import { useFollowedRegion } from './genomicAxis';
import {
  ASSEMBLY_NAMES,
  bandSummary,
  barForChrom,
  barSummary,
  chromosomeBars,
  countByChrom,
  densityBands,
  effectiveMode,
  featureSummary,
  featuresOf,
  formatBp,
  formatValue,
  idealHeight,
  layoutPanels,
  parseIdeogramRows,
  planFacets,
  pointerAlong,
  positionAt,
  regionFromGesture,
  scaleT,
  spanRect,
  valueExtent,
  type BarGeom,
  type ChromBar,
  type DensityResult,
  type IdeogramFeature,
  type IdeogramMode,
  type Orientation,
  type PanelGeom,
} from './ideogram/ideogramLayout';
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
  mode?: IdeogramMode;
  bin_size?: number | null;
  orientation?: Orientation;
  chromosomes?: string[] | null;
  colour_scale?: ColourScale;
  facet_by_sample?: boolean;
  sample?: string | null;
  max_facets?: number;
  max_chromosomes?: number;
  max_features?: number;
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
// "none"`); `max_features` below switches to density bands rather than drawing
// a subset of the marks.
const IDEOGRAM_VIZ_KIND: AdvancedVizKind = 'ideogram';

const DEFAULT_MAX_FEATURES = 20000;
const DEFAULT_MAX_CHROMOSOMES = 60;
const DEFAULT_MAX_FACETS = 6;
const ASSEMBLY_AUTO = 'auto';
const MAX_LEGEND_ENTRIES = 12;
/** Narrower than this on screen, a feature is drawn as an overhanging tick. */
const TICK_PX = 2;
const TICK_OVERHANG = 3;
/** A drag shorter than this many pixels is a click. */
const DRAG_MIN_PX = 4;
/** Title, echo and legend strip, which do not scale with the bars. */
const CHROME_PX = 72;

/** `rgb(r, g, b)` for a position on a named colour scale. */
function scaleColour(name: ColourScale, t: number): string {
  const [r, g, b] = sampleColorscale(name, t);
  return `rgb(${r}, ${g}, ${b})`;
}

interface Hover {
  text: string;
}

interface Drag {
  panel: number;
  bar: number;
  fromPx: number;
  toPx: number;
}

/**
 * A karyotype: one bar per chromosome from a common origin, scaled to its
 * length, with a glyph per feature or a heat band per bin.
 *
 * Drawn as plain SVG elements, like the genome chord ring: a karyotype is a few
 * rectangles per chromosome, which no chart library here draws as such, and
 * every number lives in `ideogram/ideogramLayout.ts` where vitest covers it.
 * The SVG is sized to the measured tile rather than scaled from a fixed box,
 * so bars use the whole tile and no band is left empty.
 *
 * A click on a chromosome, or a drag along it, emits the same
 * `genome_selection` pair a genome_view brush emits (`genomeRegionFilters`):
 * every tile bound to the same columns narrows to that chromosome or range.
 * A region another tile emitted is shaded on the matching bar.
 */
const IdeogramRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const config = (metadata.config || {}) as IdeogramConfig;
  const isDark = colorScheme === 'dark';
  const themeColors = plotlyThemeColors(isDark, theme);
  const palette = resolveCategoricalPalette(theme, mantineCategoricalPalette(theme, isDark));

  // ---- Controls. Defaults agree with IdeogramConfig's own. ---------------
  const [mode, setMode] = usePersistedVizControl<IdeogramMode>(metadata, 'mode', 'marks');
  const [orientation, setOrientation] = usePersistedVizControl<Orientation>(metadata, 'orientation', 'horizontal');
  const [assembly, setAssembly] = usePersistedVizControl<string | null>(metadata, 'assembly', null);
  const [binSize, setBinSize] = usePersistedVizControl<number | null>(metadata, 'bin_size', null);
  const [colourScale, setColourScale] = usePersistedVizControl<ColourScale>(metadata, 'colour_scale', 'Viridis');
  const [facetBySample, setFacetBySample] = usePersistedVizControl<boolean>(metadata, 'facet_by_sample', true);
  const [sample, setSample] = usePersistedVizControl<string | null>(metadata, 'sample', null);
  const pinnedColours = usePinnedCategoryColors(config.category_col);

  const regionEnabled = Boolean(onFilterChange) && config.region_filter_enabled !== false;

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

  // The tile never narrows itself by its own region, or a click on chr3 would
  // redraw the karyotype as chr3 alone and the reader could never pick another
  // chromosome. Both halves of the pair are dropped.
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
  const [hover, setHover] = useState<Hover | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);

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

  const shownFeatures = useMemo(
    () => facets.shown.flatMap((s) => featuresOf(features, s)),
    [facets, features],
  );
  const drawn = effectiveMode(
    mode,
    shownFeatures.length,
    config.max_features ?? DEFAULT_MAX_FEATURES,
  );
  const useValue = Boolean(config.value_col);

  // One karyotype per shown sample, each with its own chromosomes: two genomes
  // of a BUSCO comparison do not share contigs.
  const karyotypes = useMemo(
    () =>
      facets.shown.map((s) => {
        const own = featuresOf(features, s);
        const set = chromosomeBars(own, {
          assembly,
          order: config.chromosomes,
          maxChromosomes: config.max_chromosomes ?? DEFAULT_MAX_CHROMOSOMES,
        });
        return { sample: s, features: own, bars: set.bars, dropped: set.dropped };
      }),
    [facets, features, assembly, config.chromosomes, config.max_chromosomes],
  );

  const densities = useMemo<DensityResult[] | null>(() => {
    if (drawn.mode !== 'density') return null;
    return karyotypes.map((k) => densityBands(k.features, k.bars, { binSize, useValue }));
  }, [drawn.mode, karyotypes, binSize, useValue]);

  // One colour scale across every karyotype, so the same colour means the same
  // density in each genome.
  const densityExtent = useMemo<[number, number] | null>(() => {
    if (!densities) return null;
    let lo = Number.POSITIVE_INFINITY;
    let hi = Number.NEGATIVE_INFINITY;
    for (const d of densities) {
      if (d.bands.size === 0) continue;
      lo = Math.min(lo, d.min);
      hi = Math.max(hi, d.max);
    }
    return Number.isFinite(lo) ? [lo, hi] : null;
  }, [densities]);

  const markExtent = useMemo(() => valueExtent(features), [features]);

  // Colour universe: the whole fetched frame, so a class keeps its colour when
  // a filter removes its last feature from view.
  const colourMap = useMemo(
    () => stableColorMap(features.map((f) => f.category), palette, pinnedColours),
    [features, palette, pinnedColours],
  );
  const primary = theme.colors[theme.primaryColor]?.[isDark ? 4 : 6] ?? themeColors.textColor;
  const markColour = useCallback(
    (f: IdeogramFeature): string => {
      if (config.category_col && f.category) return colourMap.get(f.category);
      if (useValue && f.value !== null && markExtent) {
        return scaleColour(colourScale, scaleT(f.value, markExtent[0], markExtent[1]));
      }
      return primary;
    },
    [config.category_col, colourMap, useValue, markExtent, colourScale, primary],
  );

  // Measured through a callback ref: the plot box only mounts once rows have
  // arrived, so an observer attached on the first render would watch nothing.
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [view, setView] = useState({ w: 0, h: 0 });
  useEffect(() => {
    if (!container) return;
    const measure = () =>
      setView((prev) =>
        prev.w === container.clientWidth && prev.h === container.clientHeight
          ? prev
          : { w: container.clientWidth, h: container.clientHeight },
      );
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(container);
    return () => ro.disconnect();
  }, [container]);

  const panelInputs = useMemo(
    () => karyotypes.map((k) => ({ title: k.sample, bars: k.bars })),
    [karyotypes],
  );
  const panels = useMemo(
    () => layoutPanels(panelInputs, { width: view.w, height: view.h, orientation }),
    [panelInputs, view.w, view.h, orientation],
  );

  const contentDemand = useMemo(() => {
    if (!rows || panelInputs.every((p) => p.bars.length === 0)) return undefined;
    return demandForPx(idealHeight(view.w || 800, panelInputs, orientation) + CHROME_PX);
  }, [rows, panelInputs, view.w, orientation]);

  // ---- Region emission ----------------------------------------------------
  const emitRegion = useCallback(
    (region: { chroms: string[]; range: [number, number] | null } | null) => {
      if (!onFilterChange || !regionEnabled) return;
      for (const filter of genomeRegionFilters(metadata, config.chrom_col, config.start_col, region)) {
        onFilterChange(filter);
      }
    },
    [onFilterChange, regionEnabled, metadata, config.chrom_col, config.start_col],
  );

  const svgPoint = (event: React.PointerEvent<SVGElement>): { x: number; y: number } => {
    const svg = (event.currentTarget as SVGElement).ownerSVGElement ?? (event.currentTarget as SVGSVGElement);
    const box = svg.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  };

  const startDrag = (panelIdx: number, barIdx: number, event: React.PointerEvent<SVGElement>) => {
    if (!regionEnabled || event.button !== 0) return;
    event.stopPropagation();
    const p = svgPoint(event);
    const along = pointerAlong(panels[panelIdx], p.x, p.y);
    const next = { panel: panelIdx, bar: barIdx, fromPx: along, toPx: along };
    dragRef.current = next;
    setDrag(next);
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
  };

  const moveDrag = (event: React.PointerEvent<SVGElement>) => {
    const current = dragRef.current;
    if (!current) return;
    const p = svgPoint(event);
    const next = { ...current, toPx: pointerAlong(panels[current.panel], p.x, p.y) };
    dragRef.current = next;
    setDrag(next);
  };

  const endDrag = (event: React.PointerEvent<SVGElement>) => {
    const current = dragRef.current;
    dragRef.current = null;
    setDrag(null);
    if (!current) return;
    event.stopPropagation();
    const panel = panels[current.panel];
    const geom = panel?.bars[current.bar];
    if (!panel || !geom) return;
    const isClick = Math.abs(current.toPx - current.fromPx) < DRAG_MIN_PX;
    const bar = geom.bar;
    if (isClick) {
      // A second click on the chromosome already picked clears it.
      const same =
        ownRegion !== null &&
        barForChrom(panel, ownRegion.chrom)?.bar.key === bar.key &&
        !Number.isFinite(ownRegion.end);
      emitRegion(same ? null : { chroms: [bar.name], range: null });
      return;
    }
    const a = positionAt(panel, geom, current.fromPx);
    const b = positionAt(panel, geom, current.toPx);
    emitRegion(regionFromGesture(bar, a, b, 1));
  };

  // ---- Drawing --------------------------------------------------------------
  const barFill = isDark ? theme.colors.dark[4] : theme.colors.gray[2];
  const barStroke = isDark ? theme.colors.dark[2] : theme.colors.gray[5];
  const highlight = theme.colors[theme.primaryColor]?.[isDark ? 3 : 7] ?? themeColors.textColor;

  const regionRect = (
    panel: PanelGeom,
    region: { chrom: string; start: number; end: number } | null,
  ) => {
    if (!region) return null;
    const geom = barForChrom(panel, region.chrom);
    if (!geom) return null;
    const start = Number.isFinite(region.start) ? region.start : 0;
    const end = Number.isFinite(region.end) ? region.end : geom.bar.length;
    return { geom, rect: spanRect(panel, geom, start, end, { minPx: TICK_PX, overhang: 4 }) };
  };

  const featureCounts = useMemo(() => karyotypes.map((k) => countByChrom(k.features)), [karyotypes]);
  const valueLabel = config.value_col ?? 'value';

  const renderPanel = (panel: PanelGeom, pi: number) => {
    const k = karyotypes[pi];
    const horizontal = panel.orientation === 'horizontal';
    const density = densities?.[pi] ?? null;
    const own = regionRect(panel, ownRegion);
    const foreign = regionRect(panel, followed);
    const nodes: React.ReactNode[] = [];

    if (panel.title !== null) {
      nodes.push(
        <text
          key="title"
          x={panel.x + (horizontal ? 4 : panel.w / 2)}
          y={panel.y + 13}
          fontSize={12}
          fontWeight={600}
          fill={themeColors.textColor}
          textAnchor={horizontal ? 'start' : 'middle'}
        >
          {panel.title}
        </text>,
      );
    }

    // Axis.
    nodes.push(
      <g key="axis" fill={themeColors.textColor} fontSize={10}>
        {panel.ticks.map((t) =>
          horizontal ? (
            <g key={t.pos}>
              <line
                x1={t.px}
                x2={t.px}
                y1={panel.y + 4}
                y2={panel.y + panel.h - 18}
                stroke={themeColors.gridColor}
              />
              <text x={t.px} y={panel.y + panel.h - 6} textAnchor="middle" fillOpacity={0.7}>
                {t.label}
              </text>
            </g>
          ) : (
            <g key={t.pos}>
              <line
                x1={panel.x + 44}
                x2={panel.x + panel.w - 4}
                y1={t.px}
                y2={t.px}
                stroke={themeColors.gridColor}
              />
              <text
                x={panel.x + 40}
                y={t.px}
                textAnchor="end"
                dominantBaseline="middle"
                fillOpacity={0.7}
              >
                {t.label}
              </text>
            </g>
          ),
        )}
      </g>,
    );

    panel.bars.forEach((geom: BarGeom, bi: number) => {
      const bar: ChromBar = geom.bar;
      const radius = Math.min(geom.w, geom.h) / 2;
      const count = featureCounts[pi]?.get(bar.key) ?? 0;
      nodes.push(
        <g key={`bar-${bar.key}`}>
          {geom.showLabel ? (
            <text
              x={geom.labelX}
              y={geom.labelY}
              fontSize={10}
              fill={themeColors.textColor}
              textAnchor={horizontal ? 'end' : 'middle'}
              dominantBaseline={horizontal ? 'middle' : 'auto'}
            >
              {bar.name}
            </text>
          ) : null}
          <rect
            x={geom.x}
            y={geom.y}
            width={geom.w}
            height={geom.h}
            rx={radius}
            ry={radius}
            fill={barFill}
            stroke={barStroke}
            strokeWidth={0.75}
            style={{ cursor: regionEnabled ? 'pointer' : 'default' }}
            onPointerDown={(e) => startDrag(pi, bi, e)}
            onPointerEnter={() => setHover({ text: barSummary(bar, count) })}
            onPointerLeave={() => setHover(null)}
          >
            <title>{barSummary(bar, count)}</title>
          </rect>
        </g>,
      );
    });

    // Features, under pointer-events: none so a drag that starts on a glyph
    // still brushes the bar beneath; the hover reads the glyph's own title.
    if (density) {
      const extent = densityExtent ?? [0, 1];
      nodes.push(
        <g key="bands">
          {panel.bars.flatMap((geom) =>
            (density.bands.get(geom.bar.key) ?? []).map((band) => {
              const r = spanRect(panel, geom, band.start, band.end, { minPx: 1 });
              const text = bandSummary(geom.bar, band, useValue, valueLabel);
              return (
                <rect
                  key={`${geom.bar.key}-${band.start}`}
                  x={r.x}
                  y={r.y}
                  width={r.w}
                  height={r.h}
                  fill={scaleColour(colourScale, scaleT(band.value, extent[0], extent[1]))}
                  onPointerEnter={() => setHover({ text })}
                  onPointerLeave={() => setHover(null)}
                  onPointerDown={(e) => startDrag(pi, panel.bars.indexOf(geom), e)}
                >
                  <title>{text}</title>
                </rect>
              );
            }),
          )}
        </g>,
      );
    } else {
      nodes.push(
        <g key="marks">
          {k.features.map((f) => {
            const geom = barForChrom(panel, f.chrom);
            if (!geom) return null;
            const r = spanRect(panel, geom, f.start, f.end, { minPx: TICK_PX, overhang: TICK_OVERHANG });
            const text = featureSummary(f, valueLabel).join('  ·  ');
            return (
              <rect
                key={`f-${f.row}`}
                x={r.x}
                y={r.y}
                width={r.w}
                height={r.h}
                fill={markColour(f)}
                onPointerEnter={() => setHover({ text })}
                onPointerLeave={() => setHover(null)}
                onPointerDown={(e) => startDrag(pi, panel.bars.indexOf(geom), e)}
              >
                <title>{featureSummary(f, valueLabel).join('\n')}</title>
              </rect>
            );
          })}
        </g>,
      );
    }

    for (const [key, hit, dashed] of [
      ['followed', foreign, true],
      ['own', own, false],
    ] as const) {
      if (!hit) continue;
      nodes.push(
        <rect
          key={key}
          x={hit.rect.x}
          y={hit.rect.y}
          width={hit.rect.w}
          height={hit.rect.h}
          fill={highlight}
          fillOpacity={0.18}
          stroke={highlight}
          strokeWidth={1.5}
          strokeDasharray={dashed ? '4 3' : undefined}
          pointerEvents="none"
        />,
      );
    }

    if (drag && drag.panel === pi) {
      const geom = panel.bars[drag.bar];
      if (geom && Math.abs(drag.toPx - drag.fromPx) >= DRAG_MIN_PX) {
        const a = positionAt(panel, geom, drag.fromPx);
        const b = positionAt(panel, geom, drag.toPx);
        const r = spanRect(panel, geom, Math.min(a, b), Math.max(a, b), { overhang: 4 });
        nodes.push(
          <rect
            key="drag"
            x={r.x}
            y={r.y - 4}
            width={r.w}
            height={r.h + (horizontal ? 8 : 0)}
            fill={highlight}
            fillOpacity={0.25}
            pointerEvents="none"
          />,
        );
      }
    }

    return <g key={`panel-${pi}`}>{nodes}</g>;
  };

  // ---- Legend ---------------------------------------------------------------
  const categoricalLegend =
    drawn.mode === 'marks' && config.category_col
      ? colourMap.universe
          .slice(0, MAX_LEGEND_ENTRIES)
          .map((value) => ({ value, colour: colourMap.get(value) }))
      : [];
  const rampExtent: [number, number] | null =
    drawn.mode === 'density' ? densityExtent : useValue && !config.category_col ? markExtent : null;
  const rampLabel =
    drawn.mode === 'density' ? (useValue ? `mean ${valueLabel}` : 'features per bin') : valueLabel;
  const rampGradient = useMemo(() => {
    const stops = Array.from({ length: 11 }, (_, i) => `${scaleColour(colourScale, i / 10)} ${i * 10}%`);
    return `linear-gradient(to right, ${stops.join(', ')})`;
  }, [colourScale]);

  // ---- Echo and counts -----------------------------------------------------
  const totalBars = karyotypes.reduce((acc, k) => acc + k.bars.length, 0);
  const droppedBars = karyotypes.reduce((acc, k) => acc + k.dropped, 0);
  const binUsed = densities?.find((d) => d.binSize !== null)?.binSize ?? null;
  const echoParts: string[] = [];
  if (facets.all.length > 1) {
    echoParts.push(
      facets.shown.length === facets.all.length
        ? `${facets.all.length} karyotypes`
        : `${facets.shown.length} of ${facets.all.length} karyotypes`,
    );
  }
  echoParts.push(`${totalBars} chromosomes`);
  if (droppedBars > 0) echoParts.push(`${droppedBars} shorter not drawn`);
  if (drawn.mode === 'density') {
    echoParts.push(binUsed ? `${formatBp(binUsed)} bins` : 'one band per row');
  }
  if (drawn.guarded) {
    echoParts.push(
      `${shownFeatures.length.toLocaleString('en-US')} features, above ${formatValue(
        config.max_features ?? DEFAULT_MAX_FEATURES,
      )}: drawn as density`,
    );
  }
  const echo = rows && totalBars > 0 ? echoParts.join(' · ') : undefined;

  const counts = useMemo(() => {
    const out: Record<string, number> = { features: shownFeatures.length };
    if (facets.dropped > 0) out.karyotypes_hidden = facets.dropped;
    return out;
  }, [shownFeatures.length, facets.dropped]);

  // ---- Controls --------------------------------------------------------------
  // Encoding tier: what each bar carries and which way the bars run. The
  // sample picker joins it when one karyotype is shown at a time.
  const primaryControls = (
    <>
      <VizSegmented
        label="Show"
        value={mode}
        onChange={(v) => setMode((v as IdeogramMode) || 'marks')}
        data={[
          { value: 'marks', label: 'Marks' },
          { value: 'density', label: 'Density' },
        ]}
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
      {!facetBySample && facets.all.length > 1 ? (
        <VizSelect
          label="Sample"
          value={facets.shown[0] ?? null}
          onChange={(v) => setSample(v || null)}
          data={facets.all}
          allowDeselect={false}
          searchable
        />
      ) : null}
    </>
  );

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
        {config.sample_col ? (
          <VizSwitch
            checked={facetBySample}
            onChange={(e) => setFacetBySample(e.currentTarget.checked)}
            label="One karyotype per sample"
          />
        ) : null}
      </VizControlGroup>
      <VizControlGroup title="Density">
        <VizNumberInput
          label="Bin size (bp)"
          placeholder={useValue ? 'one band per row' : 'automatic'}
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

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Ideogram'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
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
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>
          <div ref={setContainer} style={{ flex: '1 1 auto', minHeight: 0, position: 'relative' }}>
            {view.w > 0 && view.h > 0 ? (
              <svg
                width={view.w}
                height={view.h}
                style={{ display: 'block', touchAction: 'none', userSelect: 'none' }}
                role="img"
                aria-label={`${totalBars} chromosomes, ${shownFeatures.length} features`}
                onPointerMove={moveDrag}
                onPointerUp={endDrag}
                onPointerDown={() => {
                  // A press that misses every bar clears the tile's region.
                  if (regionEnabled && ownRegion) emitRegion(null);
                }}
              >
                {panels.map(renderPanel)}
              </svg>
            ) : null}
            {hover ? (
              <Paper
                withBorder
                shadow="sm"
                p={6}
                radius="sm"
                style={{ position: 'absolute', right: 4, top: 4, maxWidth: '70%', pointerEvents: 'none' }}
              >
                <Text size="xs" lineClamp={2}>
                  {hover.text}
                </Text>
              </Paper>
            ) : null}
          </div>
          {categoricalLegend.length > 0 ? (
            <Group gap={10} mt={4} wrap="wrap" justify="center" style={{ flex: '0 0 auto' }}>
              {categoricalLegend.map(({ value, colour }) => (
                <Group key={value} gap={4} wrap="nowrap">
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      backgroundColor: colour,
                      display: 'inline-block',
                    }}
                  />
                  <Text size="xs" c="dimmed">
                    {value}
                  </Text>
                </Group>
              ))}
            </Group>
          ) : rampExtent ? (
            <Group gap={8} mt={4} wrap="nowrap" justify="center" style={{ flex: '0 0 auto' }}>
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
