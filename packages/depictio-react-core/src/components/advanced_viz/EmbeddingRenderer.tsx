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
  const [pointSize, setPointSize] = useState<number>(config.point_size ?? 10);
  // Default to the discrete cluster column (clearer cluster separation),
  // falling back to the continuous color column. Either can be toggled in
  // the controls — picking the cluster column triggers a categorical legend
  // with one trace per cluster; picking the color column uses a Viridis
  // gradient with a colourbar.
  const [colorBy, setColorBy] = useState<string | null>(
    config.cluster_col || config.color_col || null,
  );
  const [showDensity, setShowDensity] = useState<boolean>(Boolean(config.show_density));

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
    const isDark = colorScheme === 'dark';
    const isCategorical =
      colorValues != null &&
      colorValues.length > 0 &&
      typeof colorValues[0] !== 'number';

    const traces: any[] = [];

    // Optional 2D KDE under the scatter (does NOT contribute to the legend).
    if (showDensity && x.length > 1) {
      traces.push({
        type: 'histogram2dcontour' as const,
        x,
        y,
        colorscale: isDark ? 'Greys' : 'Blues',
        reversescale: false,
        showscale: false,
        opacity: 0.45,
        contours: { coloring: 'fill', showlines: false },
        hoverinfo: 'skip',
        ncontours: 14,
        showlegend: false,
      });
    }

    // Paper-figure-friendly marker style.
    const markerOutline = isDark ? 'rgba(20,20,20,0.85)' : 'rgba(255,255,255,0.95)';
    const baseMarker = {
      size: pointSize,
      opacity: 0.95,
      line: { color: markerOutline, width: 1.2 },
    };

    if (isCategorical && colorValues) {
      // Categorical: one trace per cluster so plotly renders a clean legend
      // and discrete colours instead of one rainbow blob.
      const palette = [
        '#4C72B0', // muted blue
        '#DD8452', // muted orange
        '#55A868', // muted green
        '#C44E52', // muted red
        '#8172B3', // muted purple
        '#937860', // muted brown
        '#DA8BC3', // muted pink
        '#8C8C8C', // grey
      ];
      const categories = Array.from(new Set(colorValues.map((v) => String(v))));
      categories.sort();
      for (let ci = 0; ci < categories.length; ci++) {
        const cat = categories[ci];
        const idx: number[] = [];
        for (let i = 0; i < colorValues.length; i++) {
          if (String(colorValues[i]) === cat) idx.push(i);
        }
        traces.push({
          type: 'scattergl' as const,
          mode: 'markers' as const,
          name: cat,
          x: idx.map((i) => x[i]),
          y: idx.map((i) => y[i]),
          text: idx.map((i) => String(ids[i] ?? '')),
          hovertemplate:
            `<b>%{text}</b><br>${cat}<br>${config.dim_1_col}: %{x:.3f}` +
            `<br>${config.dim_2_col}: %{y:.3f}<extra></extra>`,
          marker: { ...baseMarker, color: palette[ci % palette.length] },
        });
      }
    } else {
      // Continuous gradient OR no colour binding.
      traces.push({
        type: 'scattergl' as const,
        mode: 'markers' as const,
        x,
        y,
        text: ids.map((v) => String(v ?? '')),
        hovertemplate:
          `<b>%{text}</b><br>${config.dim_1_col}: %{x:.3f}` +
          `<br>${config.dim_2_col}: %{y:.3f}<extra></extra>`,
        marker: {
          ...baseMarker,
          color: (colorValues as number[] | undefined) ?? '#4C72B0',
          colorscale: colorValues ? 'Viridis' : undefined,
          showscale: Boolean(colorValues),
          colorbar: colorValues
            ? { title: { text: colorBy ?? '', side: 'right' }, thickness: 12, len: 0.85 }
            : undefined,
        },
        showlegend: false,
      });
    }

    // Paper-figure layout: clean white/dark background, no zero lines, light
    // grid, square aspect (UMAP/t-SNE/PCoA have no preferred aspect; PCA
    // technically does but a square plot reads more cleanly in a grid item).
    const axisCommon = {
      zeroline: false,
      showgrid: true,
      gridcolor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
      showline: true,
      linecolor: isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.25)',
      ticks: 'outside',
      ticklen: 4,
      mirror: true,
    };

    return {
      data: traces,
      layout: {
        template: isDark ? 'plotly_dark' : 'plotly_white',
        margin: { l: 56, r: 16, t: 16, b: 48 },
        xaxis: { ...axisCommon, title: { text: config.dim_1_col } },
        yaxis: {
          ...axisCommon,
          title: { text: config.dim_2_col },
          // Lock aspect ratio to 1:1 so cluster shapes look identical
          // regardless of the underlying method (PCA can have very different
          // scales between dims otherwise).
          scaleanchor: 'x',
          scaleratio: 1,
        },
        showlegend: isCategorical,
        legend: isCategorical
          ? {
              orientation: 'v',
              x: 1.02,
              y: 1,
              bgcolor: 'rgba(0,0,0,0)',
              borderwidth: 0,
              font: { size: 11 },
            }
          : undefined,
        autosize: true,
        plot_bgcolor: isDark ? 'rgba(0,0,0,0)' : 'rgba(255,255,255,0)',
        paper_bgcolor: isDark ? 'rgba(0,0,0,0)' : 'rgba(255,255,255,0)',
      },
    };
  }, [rows, config, pointSize, colorBy, showDensity, colorScheme]);

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
        checked={showDensity}
        onChange={(e) => setShowDensity(e.currentTarget.checked)}
        label="Density"
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

export default EmbeddingRenderer;
