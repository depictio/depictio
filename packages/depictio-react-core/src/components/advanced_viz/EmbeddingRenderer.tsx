import React, { useEffect, useMemo, useState } from 'react';
import {
  Group,
  NumberInput,
  Select,
  Switch,
  useMantineColorScheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

interface EmbeddingConfig {
  sample_id_col: string;
  dim_1_col: string;
  dim_2_col: string;
  dim_3_col?: string | null;
  cluster_col?: string | null;
  color_col?: string | null;
  point_size?: number;
  show_density?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: EmbeddingConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const EmbeddingRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const config = (metadata.config || {}) as EmbeddingConfig;
  const [pointSize, setPointSize] = useState<number>(config.point_size ?? 6);
  const [colorBy, setColorBy] = useState<string | null>(
    config.color_col || config.cluster_col || null,
  );

  const requiredCols = useMemo(() => {
    const cols = [config.sample_id_col, config.dim_1_col, config.dim_2_col].filter(Boolean) as string[];
    if (config.dim_3_col) cols.push(config.dim_3_col);
    if (config.cluster_col) cols.push(config.cluster_col);
    if (config.color_col && !cols.includes(config.color_col)) cols.push(config.color_col);
    return cols;
  }, [config]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Embedding: missing data binding');
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

  const figure = useMemo(() => {
    if (!rows) return null;
    const x = (rows[config.dim_1_col] || []) as number[];
    const y = (rows[config.dim_2_col] || []) as number[];
    const ids = (rows[config.sample_id_col] || []) as (string | number)[];
    const colorValues = colorBy ? (rows[colorBy] as unknown[]) : null;

    return {
      data: [
        {
          type: 'scattergl' as const,
          mode: 'markers' as const,
          x,
          y,
          text: ids.map((v) => String(v ?? '')),
          hovertemplate: `<b>%{text}</b><br>${config.dim_1_col}: %{x}<br>${config.dim_2_col}: %{y}<extra></extra>`,
          marker: {
            size: pointSize,
            color: colorValues || '#1c7ed6',
            colorscale: colorValues && typeof colorValues[0] === 'number' ? 'Viridis' : undefined,
            showscale: Boolean(colorValues && typeof colorValues[0] === 'number'),
            opacity: 0.85,
          },
        },
      ],
      layout: {
        template: colorScheme === 'dark' ? 'plotly_dark' : 'plotly_white',
        margin: { l: 50, r: 20, t: 30, b: 40 },
        xaxis: { title: { text: config.dim_1_col }, zeroline: true },
        yaxis: { title: { text: config.dim_2_col }, zeroline: true },
        showlegend: false,
        autosize: true,
      },
    };
  }, [rows, config, pointSize, colorBy, colorScheme]);

  const colorOptions: { value: string; label: string }[] = useMemo(() => {
    const opts: { value: string; label: string }[] = [];
    if (config.cluster_col) opts.push({ value: config.cluster_col, label: `${config.cluster_col} (cluster)` });
    if (config.color_col && config.color_col !== config.cluster_col) {
      opts.push({ value: config.color_col, label: config.color_col });
    }
    return opts;
  }, [config]);

  const controls = (
    <Group gap="xs" wrap="wrap">
      <NumberInput
        size="xs"
        label="Point size"
        value={pointSize}
        onChange={(v) => setPointSize(Math.max(1, Number(v) || 6))}
        min={1}
        max={30}
        w={100}
      />
      {colorOptions.length > 0 ? (
        <Select
          size="xs"
          label="Colour by"
          value={colorBy}
          onChange={setColorBy}
          data={colorOptions}
          clearable
          w={170}
        />
      ) : null}
      <Switch
        size="xs"
        checked={Boolean(config.show_density)}
        label="Density"
        disabled
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

export default EmbeddingRenderer;
