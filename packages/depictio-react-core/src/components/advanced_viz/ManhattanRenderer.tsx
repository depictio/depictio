import React, { useEffect, useMemo, useState } from 'react';
import {
  Input,
  MultiSelect,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import AdvancedVizFrame, { TIER_COLORS } from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';

type Highlight = 'above' | 'below' | 'none';

interface ManhattanConfig {
  chr_col: string;
  pos_col: string;
  score_col: string;
  feature_col?: string | null;
  effect_col?: string | null;
  score_kind?: string;
  score_threshold?: number | null;
  top_n_labels?: number | null;
  marker_size_above?: number;
  marker_size_below?: number;
  marker_size_uniform?: number;
  highlight?: Highlight;
  /** Extra columns to fetch + expose in the Colour-by dropdown. */
  color_by_columns?: string[];
}

/** Sentinel values for the Colour-by Select that aren't real DC columns. */
const COLOR_BY_CHROMOSOME = '__chromosome__';
const COLOR_BY_SCORE = '__score__';

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: ManhattanConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const _palette = [
  '#1c7ed6',
  '#e64980',
  '#fab005',
  '#37b24d',
  '#7048e8',
  '#f76707',
  '#0ca678',
  '#d6336c',
];

// Natural chromosome order: chr1..chr22, chrX, chrY, chrMT, then anything else
// alphabetically. Returns Infinity for unrecognised labels so they sort last.
function chromosomeSortKey(label: string): number {
  const stripped = label.replace(/^chr/i, '').toUpperCase();
  if (stripped === 'X') return 23;
  if (stripped === 'Y') return 24;
  if (stripped === 'MT' || stripped === 'M') return 25;
  const n = Number.parseInt(stripped, 10);
  return Number.isFinite(n) ? n : 100;
}

const ManhattanRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as ManhattanConfig;

  const [scoreThreshold, setScoreThreshold] = useState<number | undefined>(
    config.score_threshold ?? undefined,
  );
  const [topNLabels, setTopNLabels] = useState<number>(
    config.top_n_labels ?? 8,
  );
  const [selectedChrs, setSelectedChrs] = useState<string[]>([]);
  const [markerSizeAbove, setMarkerSizeAbove] = useState<number>(
    config.marker_size_above ?? 6,
  );
  const [markerSizeBelow, setMarkerSizeBelow] = useState<number>(
    config.marker_size_below ?? 4,
  );
  const [markerSizeUniform, setMarkerSizeUniform] = useState<number>(
    config.marker_size_uniform ?? 5,
  );
  const [highlight, setHighlight] = useState<Highlight>(config.highlight ?? 'above');
  const [colorBy, setColorBy] = useState<string>(
    (config as { default_color_by?: string }).default_color_by ?? COLOR_BY_CHROMOSOME,
  );

  const requiredCols = useMemo(() => {
    const cols = [config.chr_col, config.pos_col, config.score_col].filter(Boolean) as string[];
    if (config.feature_col) cols.push(config.feature_col);
    // Fetch the user-declared colour-by columns alongside so swapping colour
    // mode doesn't require a re-fetch (the data endpoint caps at 100k rows
    // which is plenty for variant tracks).
    for (const c of config.color_by_columns ?? []) {
      if (!cols.includes(c)) cols.push(c);
    }
    return cols;
  }, [config]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Manhattan: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData(metadata.wf_id, metadata.dc_id, requiredCols, filters)
      .then((res) => {
        if (!cancelled) setRows(res.rows);
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
    JSON.stringify(filters),
    refreshTick,
  ]);

  const { figure, allChrs, tiers, counts } = useMemo(() => {
    if (!rows)
      return {
        figure: null,
        allChrs: [] as string[],
        tiers: null as ('ABOVE' | 'BELOW')[] | null,
        counts: undefined as Record<string, number> | undefined,
      };

    const chrs = (rows[config.chr_col] || []).map((v) => String(v ?? '')) as string[];
    const positions = (rows[config.pos_col] || []) as number[];
    const scores = (rows[config.score_col] || []) as number[];
    const feats = config.feature_col ? (rows[config.feature_col] as (string | number)[]) : [];

    // Natural-sorted chromosome list (chr1..chr22, chrX, chrY, chrMT).
    const allChrs = Array.from(new Set(chrs)).sort(
      (a, b) => chromosomeSortKey(a) - chromosomeSortKey(b),
    );
    const activeChrs = selectedChrs.length === 0 ? new Set(allChrs) : new Set(selectedChrs);

    // 1) Per-chromosome cumulative x-offset. Each chromosome's block spans
    //    [offset, offset + max_pos]; we pad between chromosomes by ~2% of the
    //    largest chromosome so they don't visually butt against each other.
    const maxPosByChr = new Map<string, number>();
    for (let i = 0; i < chrs.length; i++) {
      const c = chrs[i];
      const p = positions[i] ?? 0;
      const prev = maxPosByChr.get(c) ?? 0;
      if (p > prev) maxPosByChr.set(c, p);
    }
    const globalMax = Math.max(0, ...Array.from(maxPosByChr.values()));
    const padding = Math.max(1, Math.round(globalMax * 0.02));

    const offsetByChr = new Map<string, number>();
    const chrSpan = new Map<string, { start: number; end: number; mid: number }>();
    let cursor = 0;
    for (const c of allChrs) {
      offsetByChr.set(c, cursor);
      const span = maxPosByChr.get(c) ?? 0;
      const start = cursor;
      const end = cursor + span;
      chrSpan.set(c, { start, end, mid: start + span / 2 });
      cursor = end + padding;
    }
    const totalSpan = cursor;

    // 2) Map every row to its cumulative x and chromosome colour. When a
    //    threshold is set, points below it dim to grey so the eye is drawn to
    //    the "hits" instead of the chromosome blocks. `tiers` mirrors the
    //    Volcano/MA classification so the data popover can highlight the same
    //    rows and the counts row shows ABOVE / BELOW.
    const xs = chrs.map((c, i) => (offsetByChr.get(c) ?? 0) + (positions[i] ?? 0));
    const colorByChr = new Map<string, string>(
      allChrs.map((c, i) => [c, _palette[i % _palette.length]]),
    );
    const hasThreshold = scoreThreshold != null && Number.isFinite(scoreThreshold);
    const tiers: ('ABOVE' | 'BELOW')[] | null = hasThreshold
      ? scores.map((s) => (s != null && s >= (scoreThreshold as number) ? 'ABOVE' : 'BELOW'))
      : null;

    // Marker colouring rules — composed from two orthogonal axes:
    //  1) ``colorBy`` (Colour-by Select): chromosome / score / any extra
    //     fetched column. Categorical columns get hash→palette assignment;
    //     numeric columns (incl. ``score`` itself) use a continuous teal-
    //     orange gradient that matches the tier palette so the chip ↔ dot
    //     visual language stays consistent. Chromosome mode keeps the
    //     canonical GWAS-style chromosome palette + the tier palette as a
    //     special case when a threshold is set.
    //  2) ``highlight`` (when a threshold is set): the dimmed tier overrides
    //     whatever colour rule (1) produced and falls back to grey. This is
    //     what lets the user emphasise consensus vs subconsensus regardless
    //     of which Colour-by mode they picked.
    const dimColor = 'rgba(160,160,160,0.45)';
    const tierColorHex = (tier: 'ABOVE' | 'BELOW') => {
      const name = TIER_COLORS[tier];
      const swatch = (theme.colors as Record<string, readonly string[]>)[name];
      return swatch?.[5] ?? colorByChr.values().next().value ?? '#777';
    };

    // Detect numeric vs categorical for an arbitrary colour-by column.
    const colorByValues =
      colorBy === COLOR_BY_CHROMOSOME || colorBy === COLOR_BY_SCORE
        ? null
        : (rows[colorBy] as (string | number | null)[] | undefined) ?? null;
    const colorByIsNumeric =
      colorBy === COLOR_BY_SCORE ||
      (colorByValues != null &&
        colorByValues.find((v) => v != null) != null &&
        typeof colorByValues.find((v) => v != null) === 'number');

    // Hex helpers for the palette + gradient endpoints.
    const tealHex = tierColorHex('ABOVE');
    const orangeHex = tierColorHex('BELOW');

    /** Linear interpolate between two #rrggbb colours. */
    const lerp = (a: string, b: string, t: number) => {
      const tt = Math.max(0, Math.min(1, t));
      const pa = [
        parseInt(a.slice(1, 3), 16),
        parseInt(a.slice(3, 5), 16),
        parseInt(a.slice(5, 7), 16),
      ];
      const pb = [
        parseInt(b.slice(1, 3), 16),
        parseInt(b.slice(3, 5), 16),
        parseInt(b.slice(5, 7), 16),
      ];
      const mix = pa.map((c, j) => Math.round(c + (pb[j] - c) * tt));
      return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
    };

    // Continuous gradient for numeric colour-by: orange (low) → teal (high)
    // so it matches the tier palette semantics (low score = below threshold
    // = orange; high score = above = teal).
    const numericSrc = colorBy === COLOR_BY_SCORE ? scores : (colorByValues as number[] | null) ?? null;
    let numericMin = 0;
    let numericMax = 1;
    if (colorByIsNumeric && numericSrc) {
      let lo = Infinity;
      let hi = -Infinity;
      for (const v of numericSrc) {
        if (typeof v === 'number' && Number.isFinite(v)) {
          if (v < lo) lo = v;
          if (v > hi) hi = v;
        }
      }
      if (lo < hi) {
        numericMin = lo;
        numericMax = hi;
      }
    }
    const numericColor = (v: number) =>
      lerp(orangeHex, tealHex, (v - numericMin) / Math.max(1e-9, numericMax - numericMin));

    // Categorical palette assignment for non-numeric colour-by. The
    // ``categoricalLegendItems`` list is exposed to the figure builder so it
    // can emit one invisible legend trace per value — Plotly then draws a
    // proper colour legend the user can read.
    let categoricalColor: ((idx: number) => string) | null = null;
    let categoricalLegendItems: { name: string; color: string }[] = [];
    if (colorByValues && !colorByIsNumeric) {
      const uniqueVals: string[] = [];
      const seen = new Set<string>();
      for (const v of colorByValues) {
        const s = v == null ? '∅' : String(v);
        if (!seen.has(s)) {
          seen.add(s);
          uniqueVals.push(s);
        }
      }
      const map = new Map(uniqueVals.map((v, i) => [v, _palette[i % _palette.length]]));
      categoricalColor = (i: number) => {
        const v = colorByValues[i];
        const key = v == null ? '∅' : String(v);
        return map.get(key) ?? '#777';
      };
      categoricalLegendItems = uniqueVals.map((v) => ({
        name: v,
        color: map.get(v) ?? '#777',
      }));
    }

    const colors = chrs.map((c, i) => {
      // Inactive chromosomes (filtered out via the chromosome dropdown) always
      // dim, regardless of colour-by mode.
      if (!activeChrs.has(c)) return 'rgba(200,200,200,0.3)';

      // Highlight-driven dimming wins over colour-by for the non-highlighted
      // tier — same logic as before, just composed with arbitrary colour rules.
      if (tiers && highlight !== 'none') {
        const isAbove = tiers[i] === 'ABOVE';
        const isHighlighted = highlight === 'above' ? isAbove : !isAbove;
        if (!isHighlighted) return dimColor;
      }

      // Highlighted (or no-threshold) points: paint by the Colour-by mode.
      if (colorBy === COLOR_BY_CHROMOSOME) {
        // Chromosome mode → tier palette if a threshold is set (so chip ↔ dot
        // colours match), otherwise the canonical chromosome palette.
        if (tiers) return tierColorHex(tiers[i]);
        return colorByChr.get(c) || '#777';
      }
      if (colorByIsNumeric && numericSrc) {
        const v = numericSrc[i];
        if (typeof v !== 'number' || !Number.isFinite(v)) return dimColor;
        return numericColor(v);
      }
      if (categoricalColor) return categoricalColor(i);
      // Fallback to chromosome palette if the chosen column had no usable data.
      return colorByChr.get(c) || '#777';
    });
    const sizes = tiers
      ? tiers.map((t) => {
          const isAbove = t === 'ABOVE';
          if (highlight === 'none') return isAbove ? markerSizeAbove : markerSizeBelow;
          const isHighlighted = highlight === 'above' ? isAbove : !isAbove;
          // Highlighted tier gets the larger size, dimmed tier the smaller.
          return isHighlighted ? markerSizeAbove : markerSizeBelow;
        })
      : markerSizeUniform;

    // 3) Alternating background band shapes — one per chromosome.
    const bandFill = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)';
    const layoutShapes: any[] = [];
    allChrs.forEach((c, idx) => {
      if (idx % 2 !== 0) return;
      const span = chrSpan.get(c)!;
      layoutShapes.push({
        type: 'rect',
        xref: 'x',
        yref: 'paper',
        x0: span.start,
        x1: span.end,
        y0: 0,
        y1: 1,
        fillcolor: bandFill,
        line: { width: 0 },
        layer: 'below',
      });
    });

    // 4) Threshold horizontal line. Solid + accent colour so it actually
    //    catches the eye — the previous dotted rgba(128,128,128,0.6) was
    //    invisible against the grey theme. Paired with the per-point recolour
    //    above (hits in chromosome colour, misses dimmed), the line is now
    //    informational rather than load-bearing.
    if (hasThreshold) {
      const accent =
        colorScheme === 'dark' ? 'rgba(232,62,140,0.85)' : 'rgba(214,51,108,0.85)';
      layoutShapes.push({
        type: 'line',
        xref: 'paper',
        x0: 0,
        x1: 1,
        y0: scoreThreshold as number,
        y1: scoreThreshold as number,
        line: { dash: 'solid', color: accent, width: 1.5 },
      });
    }

    // 5) Top-N label annotations. Use the feature column when present,
    //    fall back to "chr:pos". Three filters apply:
    //    a) active chromosomes — chromosome dropdown narrows labels.
    //    b) score threshold (when set) — only label the highlighted tier so
    //       labels match the recoloured markers. ``highlight === 'above'``
    //       labels the high-score side (classic GWAS hits); ``below`` labels
    //       the sub-threshold candidates (minority-allele hunting).
    //    c) sort direction follows the highlight target — highest scores first
    //       when highlighting above, lowest first when highlighting below.
    const annotations: any[] = [];
    if (topNLabels > 0) {
      const candidates: number[] = [];
      for (let i = 0; i < scores.length; i++) {
        if (!activeChrs.has(chrs[i])) continue;
        if (hasThreshold && highlight !== 'none') {
          const isAbove = scores[i] != null && scores[i] >= (scoreThreshold as number);
          const isHighlighted = highlight === 'above' ? isAbove : !isAbove;
          if (!isHighlighted) continue;
        }
        candidates.push(i);
      }
      const direction = hasThreshold && highlight === 'below' ? 1 : -1;
      candidates.sort(
        (a, b) => direction * ((scores[a] ?? Infinity) - (scores[b] ?? Infinity)),
      );
      const top = candidates.slice(0, topNLabels);
      for (const i of top) {
        const labelRaw = feats.length > 0 ? feats[i] : null;
        const label = labelRaw != null && String(labelRaw).length > 0
          ? String(labelRaw)
          : `${chrs[i]}:${positions[i]}`;
        annotations.push({
          x: xs[i],
          y: scores[i],
          text: label,
          showarrow: true,
          arrowhead: 0,
          arrowsize: 0.7,
          arrowwidth: 1,
          ax: 0,
          ay: -20,
          font: { size: 10 },
          bgcolor: isDark ? 'rgba(20,20,20,0.6)' : 'rgba(255,255,255,0.85)',
          bordercolor: 'rgba(0,0,0,0.2)',
          borderwidth: 1,
          borderpad: 2,
        });
      }
    }

    // 6) Chromosome tick labels at midpoints.
    const tickvals = allChrs.map((c) => chrSpan.get(c)!.mid);
    const ticktext = allChrs.map((c) => c.replace(/^chr/i, ''));

    const counts: Record<string, number> | undefined = tiers
      ? tiers.reduce<Record<string, number>>(
          (acc, t) => {
            acc[t] += 1;
            return acc;
          },
          { ABOVE: 0, BELOW: 0 },
        )
      : undefined;

    // Main scatter trace (all points). For numeric colour-by we attach a
    // continuous colorscale + colorbar so the gradient reads as a legend.
    const mainTrace: Record<string, unknown> = {
      type: 'scattergl' as const,
      mode: 'markers' as const,
      x: xs,
      y: scores,
      text: feats.length > 0 ? feats.map((v) => String(v ?? '')) : chrs,
      customdata: chrs,
      hovertemplate:
        `chr %{customdata}, pos %{x}<br>score: %{y}<br>%{text}<extra></extra>`,
      marker: { color: colors, size: sizes, opacity: 0.85 },
      showlegend: false,
    };

    // Invisible legend traces — one per categorical value — so Plotly draws a
    // proper colour legend the user can decode. Same pattern as
    // OncoplotRenderer uses for mutation-type colours.
    const legendTraces = categoricalLegendItems.map((item) => ({
      type: 'scatter' as const,
      mode: 'markers' as const,
      x: [null as unknown as number],
      y: [null as unknown as number],
      name: item.name,
      marker: { color: item.color, size: 10 },
      showlegend: true,
      hoverinfo: 'skip' as const,
    }));

    // Colorbar trace for numeric colour-by — invisible scatter that just
    // hosts the colorscale + colorbar config. Plotly renders the bar to the
    // right of the plot area.
    const numericColorbarTrace =
      colorByIsNumeric && numericSrc
        ? [
            {
              type: 'scatter' as const,
              mode: 'markers' as const,
              x: [null as unknown as number],
              y: [null as unknown as number],
              showlegend: false,
              hoverinfo: 'skip' as const,
              marker: {
                color: [numericMin, numericMax],
                colorscale: [
                  [0, orangeHex],
                  [1, tealHex],
                ],
                cmin: numericMin,
                cmax: numericMax,
                showscale: true,
                colorbar: {
                  title: {
                    text:
                      colorBy === COLOR_BY_SCORE
                        ? config.score_kind || config.score_col
                        : colorBy,
                    side: 'right' as const,
                  },
                  thickness: 12,
                  len: 0.9,
                  x: 1.02,
                  xpad: 0,
                },
                size: 0.001,
              },
            },
          ]
        : [];

    const showLegend = legendTraces.length > 0;

    return {
      figure: {
        data: [mainTrace, ...legendTraces, ...numericColorbarTrace],
        layout: {
          ...plotlyThemeFragment(isDark, theme),
          // Slightly more right margin to give the colorbar / legend breathing
          // room so it doesn't crowd the plot area.
          // Bottom margin: for single-chromosome datasets (viral genomes etc.)
          // the chromosome name is shown in the tile description, so we hide
          // ticks entirely and trim margin.b to a minimum. Multi-chromosome
          // datasets still need ~22 px for the tick labels.
          margin: {
            l: 55,
            r: showLegend || numericColorbarTrace.length ? 110 : 20,
            t: 10,
            b: allChrs.length <= 1 ? 8 : 22,
          },
          xaxis: {
            ...plotlyAxisOverrides(isDark, theme),
            // No axis title — the chromosome tick labels are the axis label.
            // Removes ~22 px of dead space under the plot.
            zeroline: false,
            showgrid: false,
            tickmode: 'array',
            tickvals,
            ticktext,
            showticklabels: allChrs.length > 1,
            range: [0, totalSpan],
          },
          yaxis: {
            ...plotlyAxisOverrides(isDark, theme),
            title: { text: config.score_kind || config.score_col },
            zeroline: false,
            // Clamp range for bounded score types. Plotly's autorange
            // over-pads when annotation labels sit at the data ceiling
            // (variant labels at AF=1), which is what created the giant
            // [-1, 4] empty band under the variant dots.
            ...(/(af|allele frequency|frequency|proportion|fraction)/i.test(
              String(config.score_kind || ''),
            )
              ? { range: [0, 1.05], autorange: false, fixedrange: false }
              : {}),
          },
          shapes: layoutShapes,
          annotations,
          showlegend: showLegend,
          legend: showLegend
            ? {
                orientation: 'v' as const,
                x: 1.02,
                y: 1,
                font: { size: 10 },
                title: { text: typeof colorBy === 'string' ? colorBy : '', font: { size: 10 } },
              }
            : undefined,
          autosize: true,
        },
      },
      allChrs,
      tiers,
      counts,
    };
  }, [
    rows,
    config,
    scoreThreshold,
    selectedChrs,
    topNLabels,
    markerSizeAbove,
    markerSizeBelow,
    markerSizeUniform,
    highlight,
    colorBy,
    colorScheme,
    theme,
  ]);

  // Memoised so AdvancedVizFrame's `extras` useMemo stays stable between
  // renders — see VolcanoRenderer for the full reasoning.
  const hasThreshold = scoreThreshold != null && Number.isFinite(scoreThreshold);

  // Build Colour-by Select options from the live data — always include the two
  // sentinels (Chromosome / Score), then any extra ``color_by_columns`` that
  // actually came back in ``rows`` (so a stale config doesn't surface a column
  // the DC no longer has).
  const colorByOptions = useMemo(() => {
    const opts: { value: string; label: string }[] = [
      { value: COLOR_BY_CHROMOSOME, label: 'Chromosome' },
      { value: COLOR_BY_SCORE, label: `${config.score_kind || 'Score'} (continuous)` },
    ];
    for (const c of config.color_by_columns ?? []) {
      if (rows && c in rows) opts.push({ value: c, label: c });
    }
    return opts;
  }, [config.color_by_columns, config.score_kind, rows]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        {colorByOptions.length > 2 ? (
          <Select
            size="xs"
            label="Colour by"
            value={colorBy}
            onChange={(v) => setColorBy(v ?? COLOR_BY_CHROMOSOME)}
            data={colorByOptions}
            allowDeselect={false}
          />
        ) : null}
        <NumberInput
          size="xs"
          label="Threshold"
          value={scoreThreshold ?? ''}
          onChange={(v) => setScoreThreshold(v === '' ? undefined : Number(v))}
          decimalScale={3}
        />
        <NumberInput
          size="xs"
          label="Top-N labels"
          value={topNLabels}
          onChange={(v) => setTopNLabels(Number(v) || 0)}
          min={0}
          max={50}
        />
        {hasThreshold ? (
          <>
            <Input.Wrapper label="Highlight" size="xs">
              <Stack gap={4}>
                <Text size="xs" fw={500}>
                  Mode
                </Text>
                <SegmentedControl
                size="xs"
                fullWidth
                value={highlight}
                onChange={(v) => setHighlight(v as Highlight)}
                data={[
                  { value: 'above', label: 'Above' },
                  { value: 'below', label: 'Below' },
                  { value: 'none', label: 'Both' },
                ]}
              />
              </Stack>
            </Input.Wrapper>
            <NumberInput
              size="xs"
              label={
                highlight === 'below'
                  ? 'Marker size (below — highlighted)'
                  : highlight === 'above'
                  ? 'Marker size (above — highlighted)'
                  : 'Marker size (above)'
              }
              value={markerSizeAbove}
              onChange={(v) => setMarkerSizeAbove(Math.max(1, Number(v) || 1))}
              min={1}
              max={30}
            />
            <NumberInput
              size="xs"
              label={
                highlight === 'below'
                  ? 'Marker size (above — dimmed)'
                  : highlight === 'above'
                  ? 'Marker size (below — dimmed)'
                  : 'Marker size (below)'
              }
              value={markerSizeBelow}
              onChange={(v) => setMarkerSizeBelow(Math.max(1, Number(v) || 1))}
              min={1}
              max={30}
            />
          </>
        ) : (
          <NumberInput
            size="xs"
            label="Marker size"
            value={markerSizeUniform}
            onChange={(v) => setMarkerSizeUniform(Math.max(1, Number(v) || 1))}
            min={1}
            max={30}
          />
        )}
        <MultiSelect
          size="xs"
          label="Chromosomes"
          value={selectedChrs}
          onChange={setSelectedChrs}
          data={allChrs}
          placeholder="all"
          searchable
          clearable
        />
      </Stack>
    ),
    [
      scoreThreshold,
      hasThreshold,
      topNLabels,
      markerSizeAbove,
      markerSizeBelow,
      markerSizeUniform,
      highlight,
      colorBy,
      colorByOptions,
      selectedChrs,
      allChrs,
    ],
  );

  // ``selectedOrder`` drives which tier gets the "selected" treatment in the
  // top counts chips AND the Show-data table row highlighting. Follow the
  // user's highlight pick so the chips, table rows, and plot markers all agree
  // on which side of the threshold is the interesting one. ``none`` selects
  // both tiers so neither dims.
  const tierAnnotation = useMemo(
    () =>
      tiers
        ? {
            values: tiers,
            selectedOrder:
              highlight === 'below'
                ? ['BELOW']
                : highlight === 'none'
                ? ['ABOVE', 'BELOW']
                : ['ABOVE'],
            columnLabel: 'threshold',
          }
        : undefined,
    [tiers, highlight],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Manhattan'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
      counts={counts}
      tierAnnotation={tierAnnotation}
    >
      {figure ? (
        <Plot
          data={applyDataTheme(figure.data, isDark, theme) as any}
          layout={applyLayoutTheme(figure.layout as any, isDark, theme) as any}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default ManhattanRenderer;
