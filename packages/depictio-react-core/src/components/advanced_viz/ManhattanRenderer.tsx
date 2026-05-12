import React, { useEffect, useMemo, useState } from 'react';
import {
  Group,
  MultiSelect,
  NumberInput,
  useMantineColorScheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

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

  const { figure, allChrs } = useMemo(() => {
    if (!rows) return { figure: null, allChrs: [] as string[] };

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

    // 2) Map every row to its cumulative x and chromosome colour.
    const xs = chrs.map((c, i) => (offsetByChr.get(c) ?? 0) + (positions[i] ?? 0));
    const colorByChr = new Map<string, string>(
      allChrs.map((c, i) => [c, _palette[i % _palette.length]]),
    );
    const colors = chrs.map((c) =>
      activeChrs.has(c) ? colorByChr.get(c) || '#777' : 'rgba(200,200,200,0.3)',
    );

    // 3) Alternating background band shapes — one per chromosome.
    const isDark = colorScheme === 'dark';
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

    // 4) Threshold horizontal line.
    if (scoreThreshold != null) {
      layoutShapes.push({
        type: 'line',
        xref: 'paper',
        x0: 0,
        x1: 1,
        y0: scoreThreshold,
        y1: scoreThreshold,
        line: { dash: 'dot', color: 'gray', width: 1 },
      });
    }

    // 5) Top-N label annotations. Use the feature column when present,
    //    fall back to "chr:pos". Only label points in active chromosomes
    //    (so the chromosome-filter dropdown also narrows labels).
    const annotations: any[] = [];
    if (topNLabels > 0) {
      const candidates: number[] = [];
      for (let i = 0; i < scores.length; i++) {
        if (activeChrs.has(chrs[i])) candidates.push(i);
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
            marker: { color: colors, size: 5, opacity: 0.85 },
          },
        ],
        layout: {
          template: colorScheme === 'dark' ? 'plotly_dark' : 'plotly_white',
          margin: { l: 55, r: 20, t: 20, b: 50 },
          xaxis: {
            title: { text: 'Chromosome' },
            zeroline: false,
            showgrid: false,
            tickmode: 'array',
            tickvals,
            ticktext,
            range: [0, totalSpan],
          },
          yaxis: {
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
    };
  }, [rows, config, scoreThreshold, selectedChrs, topNLabels, colorScheme]);

  const controls = (
    <Group gap="xs" wrap="wrap">
      <NumberInput
        size="xs"
        label="Threshold"
        value={scoreThreshold ?? ''}
        onChange={(v) => setScoreThreshold(v === '' ? undefined : Number(v))}
        decimalScale={3}
        w={110}
      />
      <NumberInput
        size="xs"
        label="Top-N labels"
        value={topNLabels}
        onChange={(v) => setTopNLabels(Number(v) || 0)}
        min={0}
        max={50}
        w={110}
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
        w={220}
      />
    </Group>
  );

  return (
    <AdvancedVizFrame
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? (
        <Plot
          data={figure.data as any}
          layout={figure.layout as any}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default ManhattanRenderer;
