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
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: ManhattanConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const _palette = ['#1c7ed6', '#e64980', '#fab005', '#37b24d', '#7048e8', '#f76707', '#0ca678', '#d6336c'];

const ManhattanRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const config = (metadata.config || {}) as ManhattanConfig;

  const [scoreThreshold, setScoreThreshold] = useState<number | undefined>(
    config.score_threshold ?? undefined,
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
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(requiredCols), JSON.stringify(filters), refreshTick]);

  const { figure, allChrs } = useMemo(() => {
    if (!rows) return { figure: null, allChrs: [] as string[] };
    const chrs = (rows[config.chr_col] || []).map((v) => String(v ?? '')) as string[];
    const xs = (rows[config.pos_col] || []) as number[];
    const ys = (rows[config.score_col] || []) as number[];
    const feats = config.feature_col ? (rows[config.feature_col] as (string | number)[]) : [];
    const allChrs = Array.from(new Set(chrs));

    const activeChrs = selectedChrs.length === 0 ? new Set(allChrs) : new Set(selectedChrs);
    const colorByChr = new Map<string, string>(
      allChrs.map((c, i) => [c, _palette[i % _palette.length]]),
    );

    const colors = chrs.map((c) => (activeChrs.has(c) ? colorByChr.get(c) || '#777' : 'rgba(200,200,200,0.3)'));

    const layoutShapes: any[] = [];
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

    return {
      figure: {
        data: [
          {
            type: 'scattergl' as const,
            mode: 'markers' as const,
            x: xs,
            y: ys,
            text: feats.length > 0 ? feats.map((v) => String(v ?? '')) : chrs,
            customdata: chrs,
            hovertemplate: `chr %{customdata}, pos %{x}<br>score: %{y}<br>%{text}<extra></extra>`,
            marker: { color: colors, size: 5, opacity: 0.85 },
          },
        ],
        layout: {
          template: colorScheme === 'dark' ? 'plotly_dark' : 'plotly_white',
          margin: { l: 50, r: 20, t: 30, b: 40 },
          xaxis: { title: { text: config.pos_col }, zeroline: false },
          yaxis: {
            title: { text: config.score_kind || config.score_col },
          },
          shapes: layoutShapes,
          showlegend: false,
          autosize: true,
        },
      },
      allChrs,
    };
  }, [rows, config, scoreThreshold, selectedChrs, colorScheme]);

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
      <MultiSelect
        size="xs"
        label="Chromosomes"
        value={selectedChrs}
        onChange={setSelectedChrs}
        data={allChrs}
        placeholder="all"
        searchable
        clearable
        w={200}
      />
    </Group>
  );

  return (
    <AdvancedVizFrame
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
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
