import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Group, Paper, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import {
  AdvancedVizKind,
  fetchAdvancedVizData,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { MANTINE_COLORWAY_HUES } from '../../colors';
import { usePinnedCategoryColors } from '../../hooks/useCategoryColors';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  filtersExcludingOwn,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  assignAlleleShades,
  buildAlleleGrid,
  cellKey,
  cellSummary,
  colourUniverse,
  fitAlleleLabel,
  gridGeometry,
  inkFor,
  parseAllele,
  parseAlleleRows,
  rawValuesForLabel,
  type AlleleCall,
  type AlleleResolution,
  type GenotypeCell,
} from './allele_grid/alleleGridLayout';
import { demandForPx } from './contentDemand';
import { VizControlGroup, VizSegmented, VizSelect, VizSwitch } from './controls/VizControls';
import { plotlyThemeColors } from './plotlyTheme';
import { useViewSize } from './protein/canvasHooks';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `AlleleGridConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there, and `test_advanced_viz_config_alignment`
 *  enforces it. */
interface AlleleGridConfig {
  sample_id_col: string;
  locus_col: string;
  allele_col: string;
  haplotype_col?: string | null;
  category_col?: string | null;
  value_col?: string | null;
  reads_col?: string | null;
  resolution?: AlleleResolution;
  locus_order?: string[] | null;
  sample_order?: SampleOrder;
  order_locus?: string | null;
  show_labels?: boolean;
  side_bars?: SideBar[];
  reads_as_opacity?: boolean;
  value_label?: string | null;
  reads_label?: string | null;
  max_samples?: number;
  max_loci?: number;
  selection_enabled?: boolean;
  selection_column?: string | null;
}

type SampleOrder = 'alphabetical' | 'value' | 'allele';
type SideBar = 'value' | 'reads';

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: AlleleGridConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

// A genotype is a pair of rows, so the server never samples this kind
// (`KIND_SAMPLING_POLICY["allele_grid"] == "none"`): a sampled frame would
// drop one haplotype and draw the locus as a single call.
const ALLELE_GRID_VIZ_KIND: AdvancedVizKind = 'allele_grid';

/** Hue families, one per allele group within a locus: the theme's own scales,
 *  the categorical colorway first, then the two hues it leaves out. Gray is
 *  kept for no-calls and the bars. */
const HUES: readonly string[] = [...MANTINE_COLORWAY_HUES, 'green', 'orange'];

const ROW_PX = 22;
const LOCUS_HEADER_PX = 22;
const CATEGORY_HEADER_PX = 18;
const LABEL_FONT_PX = 10;
const AXIS_FONT_PX = 11;
const LEGEND_LINE_PX = 24;
const LEGEND_PER_LOCUS = 8;
const DIM_OPACITY = 0.28;
const DEFAULT_MAX_SAMPLES = 200;
const DEFAULT_MAX_LOCI = 24;
const DEFAULT_SIDE_BARS: SideBar[] = ['value', 'reads'];

const RESOLUTIONS: { value: string; label: string }[] = [
  { value: '1', label: '1 field' },
  { value: '2', label: '2 fields' },
  { value: '3', label: '3 fields' },
  { value: '4', label: '4 fields' },
];

interface Hover {
  cell: GenotypeCell;
  x: number;
  y: number;
}

/**
 * Sample x locus grid of diploid genotypes.
 *
 * Plain SVG: a cell is two rectangles side by side, one per haplotype, and a
 * homozygous locus is one merged rectangle with a marker. Plotly's heatmap
 * holds one value per cell, which is exactly what an oncoplot of the same
 * table shows (the second allele of every heterozygous locus overwrites the
 * first), so the two halves are drawn directly. Every number comes from
 * `allele_grid/alleleGridLayout.ts`; this component resolves colours against
 * the theme and wires the hover and the picks.
 */
const AlleleGridRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as AlleleGridConfig;
  const themeColors = plotlyThemeColors(isDark, theme);

  const [resolution, setResolution] = usePersistedVizControl<AlleleResolution>(metadata, 'resolution', 2);
  const [sampleOrder, setSampleOrder] = usePersistedVizControl<SampleOrder>(metadata, 'sample_order', 'alphabetical');
  const [orderLocus, setOrderLocus] = usePersistedVizControl<string | null>(metadata, 'order_locus', null);
  const [showLabels, setShowLabels] = usePersistedVizControl<boolean>(metadata, 'show_labels', true);
  const [sideBars, setSideBars] = usePersistedVizControl<SideBar[]>(metadata, 'side_bars', DEFAULT_SIDE_BARS);
  const [readsAsOpacity, setReadsAsOpacity] = usePersistedVizControl<boolean>(metadata, 'reads_as_opacity', false);

  // An allele pick filters on the allele column (or the named one); a pick on
  // a sample label filters on the sample column. Same filter key either way.
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);
  const sampleColumn = config.sample_id_col;

  const requiredCols = useMemo(() => {
    const cols = [config.sample_id_col, config.locus_col, config.allele_col].filter(
      Boolean,
    ) as string[];
    for (const c of [
      config.haplotype_col,
      config.category_col,
      config.value_col,
      config.reads_col,
      selectionColumn,
    ]) {
      if (c && !cols.includes(c)) cols.push(c);
    }
    return cols;
  }, [
    config.sample_id_col,
    config.locus_col,
    config.allele_col,
    config.haplotype_col,
    config.category_col,
    config.value_col,
    config.reads_col,
    selectionColumn,
  ]);

  // The grid never narrows itself by its own pick: picking A*02:01 would leave
  // only its carriers' rows, and their other alleles, on screen.
  const filtersForFetch = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'scatter_selection'),
    [filters, metadata.index],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);
  const [universe, setUniverse] = useState<string[] | null>(null);
  const [hover, setHover] = useState<Hover | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Allele grid: missing data binding');
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
      vizKind: ALLELE_GRID_VIZ_KIND,
      roles: {
        sample_id: config.sample_id_col,
        locus: config.locus_col,
        allele: config.allele_col,
      },
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

  // Every allele the collection holds, so a filter that removes one does not
  // shift the shades of the rest.
  useEffect(() => {
    if (!metadata.dc_id || !config.allele_col) return;
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.allele_col)
      .then((v) => !cancelled && setUniverse(v))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.allele_col]);
  // An allele wears the dashboard's colour for it, by raw value or as shown.
  const pinned = usePinnedCategoryColors(config.allele_col);

  const parsedRows = useMemo(
    () =>
      rows
        ? parseAlleleRows(rows, {
            sample: config.sample_id_col,
            locus: config.locus_col,
            allele: config.allele_col,
            haplotype: config.haplotype_col,
            category: config.category_col,
            value: config.value_col,
            reads: config.reads_col,
          })
        : [],
    [
      rows,
      config.sample_id_col,
      config.locus_col,
      config.allele_col,
      config.haplotype_col,
      config.category_col,
      config.value_col,
      config.reads_col,
    ],
  );

  const grid = useMemo(
    () =>
      buildAlleleGrid(parsedRows, {
        resolution,
        locusOrder: config.locus_order,
        sampleOrder: sampleOrder === 'value' && !config.value_col ? 'alphabetical' : sampleOrder,
        orderLocus,
        maxSamples: config.max_samples ?? DEFAULT_MAX_SAMPLES,
        maxLoci: config.max_loci ?? DEFAULT_MAX_LOCI,
      }),
    [
      parsedRows,
      resolution,
      config.locus_order,
      sampleOrder,
      config.value_col,
      orderLocus,
      config.max_samples,
      config.max_loci,
    ],
  );

  const shades = useMemo(() => {
    const calls: AlleleCall[] = [];
    for (const cell of grid.cells.values()) {
      for (const c of cell.haplotypes) if (c) calls.push(c);
    }
    return assignAlleleShades(colourUniverse(universe, calls, resolution), HUES.length, isDark);
  }, [grid, universe, resolution, isDark]);

  const neutral = isDark ? theme.colors.dark[4] : theme.colors.gray[3];
  const colourOf = useCallback(
    (call: AlleleCall): string => {
      const own = pinned?.[call.allele.raw] ?? pinned?.[call.label];
      if (own) return own;
      const shade = shades.get(call.label);
      if (!shade) return neutral;
      return theme.colors[HUES[shade.hue]]?.[shade.shade] ?? neutral;
    },
    [pinned, shades, theme, neutral],
  );

  // ---- What is picked, read back out of the filter list ------------------
  const own = useMemo(
    () =>
      filters.find(
        (f) =>
          f.index === metadata.index &&
          f.source === 'scatter_selection' &&
          Array.isArray(f.value) &&
          f.value.length > 0,
      ),
    [filters, metadata.index],
  );
  const pickedSamples = useMemo(
    () =>
      own && own.column_name === sampleColumn && sampleColumn !== selectionColumn
        ? new Set((own.value as unknown[]).map(String))
        : new Set<string>(),
    [own, sampleColumn, selectionColumn],
  );
  const pickedLabels = useMemo(() => {
    const out = new Set<string>();
    if (!own || own.column_name !== selectionColumn) return out;
    for (const v of own.value as unknown[]) {
      const parsed = parseAllele(v);
      if (!parsed) continue;
      // Re-derive the label the way the cells do, so a pick made at 3 fields
      // still lights its 2-field cells after the resolution changes.
      for (const cell of grid.cells.values()) {
        for (const c of cell.haplotypes) if (c && c.allele.raw === parsed.raw) out.add(c.label);
      }
    }
    return out;
  }, [own, selectionColumn, grid]);

  const emit = useCallback(
    (column: string, values: string[]) => {
      if (!onFilterChange) return;
      onFilterChange(advancedVizSelectionFilter(metadata, column, values));
    },
    [onFilterChange, metadata],
  );

  const pickAllele = useCallback(
    (label: string) => {
      if (!selectionEnabled || !selectionColumn) return;
      const next = new Set(pickedLabels);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      const values = [...next].flatMap((l) => rawValuesForLabel(grid.cells.values(), l));
      emit(selectionColumn, values);
    },
    [selectionEnabled, selectionColumn, pickedLabels, grid, emit],
  );

  const pickSample = useCallback(
    (sample: string) => {
      if (!selectionEnabled || !sampleColumn) return;
      const next = new Set(pickedSamples);
      if (next.has(sample)) next.delete(sample);
      else next.add(sample);
      emit(sampleColumn, [...next]);
    },
    [selectionEnabled, sampleColumn, pickedSamples, emit],
  );

  // ---- Geometry ----------------------------------------------------------
  const viewRef = useRef<HTMLDivElement | null>(null);
  const view = useViewSize(viewRef);
  const bars = useMemo(
    () =>
      (sideBars ?? []).filter((b) => (b === 'value' ? config.value_col : config.reads_col)),
    [sideBars, config.value_col, config.reads_col],
  );
  const geometry = useMemo(
    () =>
      gridGeometry({
        width: view.w || 600,
        nLoci: grid.loci.length,
        sampleLabelChars: grid.samples.reduce((m, s) => Math.max(m, s.sample.length), 0),
        sideBars: bars.length,
        fontPx: AXIS_FONT_PX,
      }),
    [view.w, grid.loci.length, grid.samples, bars.length],
  );
  const headerPx = LOCUS_HEADER_PX + (grid.groups.length > 0 ? CATEGORY_HEADER_PX : 0);
  const svgHeight = headerPx + grid.samples.length * ROW_PX + 4;
  const barMax = useMemo(() => {
    const max = (pick: (s: { value: number | null; reads: number | null }) => number | null) =>
      grid.samples.reduce((m, s) => Math.max(m, pick(s) ?? 0), 0);
    return { value: max((s) => s.value), reads: max((s) => s.reads) };
  }, [grid.samples]);

  // One legend line per locus, and the grid's rows: what the tile asks the
  // autofit for. The legend is part of the demand so it never scrolls.
  const legendByLocus = useMemo(() => {
    const out = new Map<string, typeof grid.legend>();
    for (const e of grid.legend) {
      if (!grid.loci.some((l) => l.locus === e.locus)) continue;
      out.set(e.locus, [...(out.get(e.locus) ?? []), e]);
    }
    return out;
  }, [grid]);
  const contentDemand = useMemo(
    () =>
      grid.samples.length > 0
        ? demandForPx(svgHeight + legendByLocus.size * LEGEND_LINE_PX + 16)
        : undefined,
    [grid.samples.length, svgHeight, legendByLocus.size],
  );

  // ---- Controls ------------------------------------------------------------
  const lociOptions = useMemo(
    () => grid.loci.map((l) => ({ value: l.locus, label: l.locus })),
    [grid.loci],
  );
  const primaryControls = (
    <>
      <VizSelect
        label="Resolution"
        value={String(resolution)}
        onChange={(v) => setResolution((Number(v) || 2) as AlleleResolution)}
        data={RESOLUTIONS}
        allowDeselect={false}
      />
      <VizSelect
        label="Order samples"
        value={sampleOrder}
        onChange={(v) => setSampleOrder((v as SampleOrder) || 'alphabetical')}
        data={[
          { value: 'alphabetical', label: 'By name' },
          ...(config.value_col
            ? [{ value: 'value', label: config.value_label || `By ${config.value_col}` }]
            : []),
          { value: 'allele', label: 'By allele at a locus' },
        ]}
        allowDeselect={false}
      />
      {sampleOrder === 'allele' ? (
        <VizSelect
          label="Locus"
          value={orderLocus ?? grid.loci[0]?.locus ?? null}
          onChange={(v) => setOrderLocus(v || null)}
          data={lociOptions}
          allowDeselect={false}
        />
      ) : null}
    </>
  );
  const barOptions = [
    ...(config.value_col ? [{ value: 'value', label: config.value_label || config.value_col }] : []),
    ...(config.reads_col ? [{ value: 'reads', label: config.reads_label || config.reads_col }] : []),
  ];
  const controls = (
    <>
      <VizControlGroup title="Cells">
        <VizSwitch
          checked={showLabels}
          onChange={(e) => setShowLabels(e.currentTarget.checked)}
          label="Allele labels"
        />
        {config.reads_col ? (
          <VizSwitch
            checked={readsAsOpacity}
            onChange={(e) => setReadsAsOpacity(e.currentTarget.checked)}
            label="Fade cells by read support"
          />
        ) : null}
      </VizControlGroup>
      {barOptions.length > 0 ? (
        <VizControlGroup title="Side bars">
          <VizSegmented
            value={bars.length === barOptions.length ? 'all' : bars.length === 0 ? 'none' : bars[0]}
            onChange={(v) =>
              setSideBars(
                v === 'all'
                  ? (barOptions.map((o) => o.value) as SideBar[])
                  : v === 'none'
                    ? []
                    : [v as SideBar],
              )
            }
            data={[
              ...(barOptions.length > 1 ? [{ value: 'all', label: 'Both' }] : []),
              ...barOptions,
              { value: 'none', label: 'None' },
            ]}
          />
        </VizControlGroup>
      ) : null}
    </>
  );

  // ---- Echo and counts ---------------------------------------------------
  const homozygous = useMemo(() => {
    let n = 0;
    for (const s of grid.samples) {
      for (const l of grid.loci) if (grid.cells.get(cellKey(s.sample, l.locus))?.homozygous) n += 1;
    }
    return n;
  }, [grid]);
  const counts = useMemo(() => {
    const out: Record<string, number> = {
      samples: grid.samples.length,
      loci: grid.loci.length,
      homozygous,
    };
    if (grid.droppedSamples > 0) out['samples hidden'] = grid.droppedSamples;
    if (grid.droppedLoci > 0) out['loci hidden'] = grid.droppedLoci;
    return out;
  }, [grid, homozygous]);
  const picked = pickedLabels.size > 0 ? [...pickedLabels] : [...pickedSamples];
  const echo =
    grid.samples.length > 0
      ? [
          `${resolution}-field typing`,
          picked.length > 0 ? `picked ${picked.slice(0, 3).join(', ')}${picked.length > 3 ? ` +${picked.length - 3}` : ''}` : null,
        ]
          .filter(Boolean)
          .join(' · ')
      : undefined;

  // ---- Drawing -----------------------------------------------------------
  const ink = (bg: string) => (inkFor(bg) === 'light' ? theme.white : theme.black);
  const noCallFill = isDark ? theme.colors.dark[6] : theme.colors.gray[1];
  const gridLine = isDark ? theme.colors.dark[4] : theme.colors.gray[3];
  const barFill = isDark ? theme.colors.gray[6] : theme.colors.gray[5];
  const textColour = themeColors.textColor;
  const anyPick = pickedLabels.size > 0 || pickedSamples.size > 0;
  const x0 = geometry.labelWidth;
  const cw = geometry.cellWidth;

  const opacityFor = (sample: { reads: number | null }) =>
    readsAsOpacity && config.reads_col && barMax.reads > 0
      ? 0.35 + 0.65 * Math.max(0, Math.min(1, (sample.reads ?? 0) / barMax.reads))
      : 1;

  const half = (
    call: AlleleCall | null,
    x: number,
    y: number,
    w: number,
    key: string,
    sampleOpacity: number,
    samplePicked: boolean,
  ) => {
    const h = ROW_PX - 2;
    if (!call) {
      return (
        <rect
          key={key}
          x={x}
          y={y}
          width={w}
          height={h}
          fill={noCallFill}
          stroke={gridLine}
          strokeDasharray="2 2"
        >
          <title>no call</title>
        </rect>
      );
    }
    const fill = colourOf(call);
    const isPicked = pickedLabels.has(call.label);
    const dim = anyPick && !isPicked && !samplePicked;
    const label = showLabels ? fitAlleleLabel(call, w, LABEL_FONT_PX, resolution) : null;
    return (
      <g
        key={key}
        opacity={dim ? DIM_OPACITY : sampleOpacity}
        style={{ cursor: selectionEnabled ? 'pointer' : 'default' }}
        onClick={(e) => {
          e.stopPropagation();
          pickAllele(call.label);
        }}
      >
        <rect
          x={x}
          y={y}
          width={w}
          height={h}
          fill={fill}
          stroke={isPicked ? textColour : 'none'}
          strokeWidth={isPicked ? 2 : 0}
        />
        {label ? (
          <text
            x={x + w / 2}
            y={y + h / 2}
            fontSize={LABEL_FONT_PX}
            fill={ink(fill)}
            textAnchor="middle"
            dominantBaseline="central"
            pointerEvents="none"
          >
            {label}
          </text>
        ) : null}
      </g>
    );
  };

  const svg =
    grid.samples.length > 0 ? (
      <svg
        width={geometry.totalWidth}
        height={svgHeight}
        role="img"
        aria-label={`Genotypes of ${grid.samples.length} samples at ${grid.loci.length} loci`}
        style={{ display: 'block' }}
        onClick={() => {
          if (selectionEnabled && anyPick && selectionColumn) emit(selectionColumn, []);
        }}
        onMouseLeave={() => setHover(null)}
      >
        {grid.groups.map((g) => (
          <g key={`cat-${g.start}`}>
            <text
              x={x0 + ((g.start + g.end) / 2) * cw}
              y={CATEGORY_HEADER_PX / 2}
              fontSize={AXIS_FONT_PX}
              fill={textColour}
              fillOpacity={0.7}
              textAnchor="middle"
              dominantBaseline="central"
            >
              {g.category ?? ''}
            </text>
            <line
              x1={x0 + g.start * cw + 4}
              x2={x0 + g.end * cw - 4}
              y1={CATEGORY_HEADER_PX - 2}
              y2={CATEGORY_HEADER_PX - 2}
              stroke={gridLine}
            />
          </g>
        ))}
        {grid.loci.map((l, i) => (
          <text
            key={`locus-${l.locus}`}
            x={x0 + i * cw + cw / 2}
            y={headerPx - LOCUS_HEADER_PX / 2}
            fontSize={AXIS_FONT_PX}
            fontWeight={600}
            fill={textColour}
            textAnchor="middle"
            dominantBaseline="central"
          >
            {`HLA-${l.locus}`.length * AXIS_FONT_PX * 0.6 <= cw ? `HLA-${l.locus}` : l.locus}
          </text>
        ))}
        {bars.map((b, bi) => (
          <text
            key={`bar-head-${b}`}
            x={x0 + grid.loci.length * cw + 6 + bi * (geometry.barWidth + 6)}
            y={headerPx - LOCUS_HEADER_PX / 2}
            fontSize={AXIS_FONT_PX}
            fill={textColour}
            fillOpacity={0.7}
            dominantBaseline="central"
          >
            {b === 'value'
              ? config.value_label || config.value_col
              : config.reads_label || config.reads_col}
          </text>
        ))}
        {grid.samples.map((s, ri) => {
          const y = headerPx + ri * ROW_PX;
          const samplePicked = pickedSamples.has(s.sample);
          const rowDim = pickedSamples.size > 0 && !samplePicked && pickedLabels.size === 0;
          const sampleOpacity = opacityFor(s);
          return (
            <g key={`row-${s.sample}`} opacity={rowDim ? DIM_OPACITY : 1}>
              <text
                x={x0 - 6}
                y={y + ROW_PX / 2}
                fontSize={AXIS_FONT_PX}
                fontWeight={samplePicked ? 700 : 400}
                fill={textColour}
                textAnchor="end"
                dominantBaseline="central"
                style={{ cursor: selectionEnabled ? 'pointer' : 'default' }}
                onClick={(e) => {
                  e.stopPropagation();
                  pickSample(s.sample);
                }}
              >
                {s.sample}
              </text>
              {grid.loci.map((l, ci) => {
                const cell = grid.cells.get(cellKey(s.sample, l.locus));
                const x = x0 + ci * cw + 1;
                const w = cw - 2;
                const onEnter = (e: React.MouseEvent) => {
                  if (!cell) return;
                  const box = viewRef.current?.getBoundingClientRect();
                  setHover({
                    cell,
                    x: e.clientX - (box?.left ?? 0),
                    y: e.clientY - (box?.top ?? 0),
                  });
                };
                if (!cell) {
                  return (
                    <rect
                      key={`cell-${l.locus}`}
                      x={x}
                      y={y + 1}
                      width={w}
                      height={ROW_PX - 2}
                      fill="none"
                      stroke={gridLine}
                      strokeOpacity={0.5}
                    />
                  );
                }
                const [h1, h2] = cell.haplotypes;
                return (
                  <g key={`cell-${l.locus}`} onMouseEnter={onEnter} onMouseMove={onEnter}>
                    {cell.homozygous ? (
                      <>
                        {half(h1, x, y + 1, w, 'hom', sampleOpacity, samplePicked)}
                        <circle
                          cx={x + w - 4}
                          cy={y + 5}
                          r={2.2}
                          fill={ink(colourOf(h1!))}
                          fillOpacity={0.75}
                          pointerEvents="none"
                        />
                      </>
                    ) : (
                      <>
                        {half(h1, x, y + 1, w / 2 - 0.5, 'h1', sampleOpacity, samplePicked)}
                        {half(h2, x + w / 2 + 0.5, y + 1, w / 2 - 0.5, 'h2', sampleOpacity, samplePicked)}
                      </>
                    )}
                    {cell.extra > 0 ? (
                      <text
                        x={x + w - 2}
                        y={y + ROW_PX - 4}
                        fontSize={8}
                        fill={textColour}
                        textAnchor="end"
                        pointerEvents="none"
                      >
                        {`+${cell.extra}`}
                      </text>
                    ) : null}
                  </g>
                );
              })}
              {bars.map((b, bi) => {
                const v = b === 'value' ? s.value : s.reads;
                const max = b === 'value' ? barMax.value : barMax.reads;
                const bx = x0 + grid.loci.length * cw + 6 + bi * (geometry.barWidth + 6);
                const bw = v !== null && max > 0 ? (geometry.barWidth * v) / max : 0;
                return (
                  <rect
                    key={`bar-${b}`}
                    x={bx}
                    y={y + 5}
                    width={Math.max(0, bw)}
                    height={ROW_PX - 10}
                    fill={barFill}
                  >
                    <title>{`${s.sample}: ${v === null ? 'n/a' : v.toLocaleString()}`}</title>
                  </rect>
                );
              })}
            </g>
          );
        })}
      </svg>
    ) : null;

  const hoverText = hover
    ? [
        cellSummary(hover.cell),
        (() => {
          const s = grid.samples.find((x) => x.sample === hover.cell.sample);
          const parts: string[] = [];
          if (s?.reads !== null && s?.reads !== undefined && config.reads_col)
            parts.push(`${config.reads_label || config.reads_col} ${s.reads.toLocaleString()}`);
          if (s?.value !== null && s?.value !== undefined && config.value_col)
            parts.push(`${config.value_label || config.value_col} ${s.value.toLocaleString()}`);
          return parts.join(' · ');
        })(),
      ].filter(Boolean)
    : [];

  let emptyMessage: string | undefined;
  if (rows && grid.samples.length === 0) emptyMessage = 'No genotypes';

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Allele grid'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      echo={echo}
      counts={grid.samples.length > 0 ? counts : undefined}
      loading={loading}
      error={error}
      emptyMessage={emptyMessage}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>
        <div
          ref={viewRef}
          style={{ flex: '1 1 auto', minHeight: 0, overflow: 'auto', position: 'relative' }}
        >
          {svg}
          {hover && hoverText.length > 0 ? (
            <Paper
              withBorder
              shadow="sm"
              p={6}
              radius="sm"
              style={{
                position: 'absolute',
                left: Math.min(hover.x + 12, Math.max(0, (view.w || 0) - 260)),
                top: hover.y + 14,
                maxWidth: 260,
                pointerEvents: 'none',
                zIndex: 2,
              }}
            >
              {hoverText.map((line) => (
                <Text key={line} size="xs">
                  {line}
                </Text>
              ))}
            </Paper>
          ) : null}
        </div>
        {legendByLocus.size > 0 ? (
          <div style={{ flex: '0 0 auto', paddingTop: 4 }}>
            {[...legendByLocus.entries()].map(([locus, entries]) => (
              <Group key={locus} gap={8} wrap="nowrap" style={{ overflow: 'hidden' }} h={LEGEND_LINE_PX}>
                <Text size="xs" fw={600} w={44} style={{ flex: '0 0 auto' }}>
                  {locus}
                </Text>
                {entries.slice(0, LEGEND_PER_LOCUS).map((e) => {
                  const sample = [...grid.cells.values()].find(
                    (c) => c.locus === e.locus && c.haplotypes.some((h) => h?.label === e.label),
                  );
                  const call = sample?.haplotypes.find((h) => h?.label === e.label) ?? null;
                  const colour = call ? colourOf(call) : neutral;
                  const active = pickedLabels.has(e.label);
                  return (
                    <Group
                      key={e.label}
                      gap={4}
                      wrap="nowrap"
                      style={{
                        flex: '0 0 auto',
                        cursor: selectionEnabled ? 'pointer' : 'default',
                        opacity: pickedLabels.size > 0 && !active ? 0.5 : 1,
                      }}
                      onClick={() => pickAllele(e.label)}
                      title={`${e.label}: ${e.copies} of ${Math.round(e.copies / e.frequency)} haplotypes, ${e.carriers} carriers`}
                    >
                      <span
                        style={{
                          width: 10,
                          height: 10,
                          borderRadius: 2,
                          backgroundColor: colour,
                          display: 'inline-block',
                        }}
                      />
                      <Text size="xs" fw={active ? 700 : 400}>
                        {e.label}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {`${Math.round(e.frequency * 100)}%`}
                      </Text>
                    </Group>
                  );
                })}
                {entries.length > LEGEND_PER_LOCUS ? (
                  <Text size="xs" c="dimmed" style={{ flex: '0 0 auto' }}>
                    {`+${entries.length - LEGEND_PER_LOCUS} more`}
                  </Text>
                ) : null}
              </Group>
            ))}
          </div>
        ) : null}
      </div>
    </AdvancedVizFrame>
  );
};

export default AlleleGridRenderer;
