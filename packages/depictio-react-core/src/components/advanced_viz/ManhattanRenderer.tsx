import React, { useEffect, useMemo, useState } from 'react';
import {
  MultiSelect,
  NumberInput,
  Stack,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';

interface ManhattanConfig {
  chr_col: string;
  pos_col: string;
  score_col: string;
  feature_col?: string | null;
  effect_col?: string | null;
  score_kind?: string;
  score_threshold?: number | null;
  top_n_labels?: number | null;
}

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

  const requiredCols = useMemo(() => {
    const cols = [config.chr_col, config.pos_col, config.score_col].filter(Boolean) as string[];
    if (config.feature_col) cols.push(config.feature_col);
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
    const colors = chrs.map((c, i) => {
      if (!activeChrs.has(c)) return 'rgba(200,200,200,0.3)';
      if (tiers && tiers[i] === 'BELOW') return 'rgba(160,160,160,0.45)';
      return colorByChr.get(c) || '#777';
    });
    const sizes = tiers ? tiers.map((t) => (t === 'ABOVE' ? 6 : 4)) : 5;

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
    //    fall back to "chr:pos". Two filters apply:
    //    a) active chromosomes — chromosome dropdown narrows labels.
    //    b) score threshold (when set) — only label "hits" (score >= threshold)
    //       so labels match the recolored markers. Without (b) the top-N list
    //       was just the highest-scoring points overall, which often disagrees
    //       with what the user set the threshold for.
    const annotations: any[] = [];
    if (topNLabels > 0) {
      const candidates: number[] = [];
      for (let i = 0; i < scores.length; i++) {
        if (!activeChrs.has(chrs[i])) continue;
        if (hasThreshold && (scores[i] == null || scores[i] < (scoreThreshold as number))) continue;
        candidates.push(i);
      }
      candidates.sort((a, b) => (scores[b] ?? -Infinity) - (scores[a] ?? -Infinity));
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

    return {
      figure: {
        data: [
          {
            type: 'scattergl' as const,
            mode: 'markers' as const,
            x: xs,
            y: scores,
            text: feats.length > 0 ? feats.map((v) => String(v ?? '')) : chrs,
            customdata: chrs,
            hovertemplate:
              `chr %{customdata}, pos %{x}<br>score: %{y}<br>%{text}<extra></extra>`,
            marker: { color: colors, size: sizes, opacity: 0.85 },
          },
        ],
        layout: {
          ...plotlyThemeFragment(isDark, theme),
          margin: { l: 55, r: 20, t: 20, b: 50 },
          xaxis: {
            ...plotlyAxisOverrides(isDark, theme),
            title: { text: 'Chromosome' },
            zeroline: false,
            showgrid: false,
            tickmode: 'array',
            tickvals,
            ticktext,
            range: [0, totalSpan],
          },
          yaxis: {
            ...plotlyAxisOverrides(isDark, theme),
            title: { text: config.score_kind || config.score_col },
            zeroline: false,
          },
          shapes: layoutShapes,
          annotations,
          showlegend: false,
          autosize: true,
        },
      },
      allChrs,
      tiers,
      counts,
    };
  }, [rows, config, scoreThreshold, selectedChrs, topNLabels, colorScheme, theme]);

  // Memoised so AdvancedVizFrame's `extras` useMemo stays stable between
  // renders — see VolcanoRenderer for the full reasoning.
  const controls = useMemo(
    () => (
      <Stack gap="xs">
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
    [scoreThreshold, topNLabels, selectedChrs, allChrs],
  );

  const tierAnnotation = useMemo(
    () =>
      tiers
        ? {
            values: tiers,
            selectedOrder: ['ABOVE'],
            columnLabel: 'threshold',
          }
        : undefined,
    [tiers],
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
