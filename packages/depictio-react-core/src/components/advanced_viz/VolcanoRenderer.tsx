import React, { useEffect, useMemo, useState } from 'react';
import {
  Group,
  NumberInput,
  Stack,
  Switch,
  TextInput,
  Tooltip,
  useMantineColorScheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

interface VolcanoConfig {
  feature_id_col: string;
  effect_size_col: string;
  significance_col: string;
  label_col?: string;
  category_col?: string;
  significance_is_neg_log10?: boolean;
  significance_threshold?: number;
  effect_threshold?: number;
  top_n_labels?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: VolcanoConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const VolcanoRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const config = (metadata.config || {}) as VolcanoConfig;

  // Tier-2 local controls (never enter the global filter array).
  const [sigThreshold, setSigThreshold] = useState<number>(
    config.significance_threshold ?? 0.05,
  );
  const [effectThreshold, setEffectThreshold] = useState<number>(
    config.effect_threshold ?? 1.0,
  );
  const [topN, setTopN] = useState<number>(config.top_n_labels ?? 20);
  const [search, setSearch] = useState<string>('');
  const [showLabels, setShowLabels] = useState<boolean>(true);

  const requiredCols = useMemo(
    () => [
      config.feature_id_col,
      config.effect_size_col,
      config.significance_col,
      ...(config.label_col ? [config.label_col] : []),
      ...(config.category_col ? [config.category_col] : []),
    ].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Volcano: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData(
      metadata.wf_id,
      metadata.dc_id,
      requiredCols,
      filters,
    )
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
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
    const xs = (rows[config.effect_size_col] || []) as number[];
    const sigRaw = (rows[config.significance_col] || []) as number[];
    const ids = (rows[config.feature_id_col] || []) as (string | number)[];
    const labels = config.label_col
      ? ((rows[config.label_col] || []) as (string | number)[])
      : ids;
    const ys = config.significance_is_neg_log10
      ? sigRaw
      : sigRaw.map((p) => (p == null || p <= 0 ? null : -Math.log10(p)));

    const sigThresholdY = config.significance_is_neg_log10
      ? sigThreshold
      : -Math.log10(sigThreshold);

    // Classify each point: significant + above-threshold effect ⇒ "hit".
    const colors = xs.map((x, i) => {
      const y = ys[i];
      if (y == null) return 'rgba(160,160,160,0.5)';
      const passSig = y >= sigThresholdY;
      const passEffect = Math.abs(x) >= effectThreshold;
      if (passSig && passEffect) return x > 0 ? '#e64980' : '#1c7ed6';
      return 'rgba(160,160,160,0.55)';
    });

    // Top-N label selection — by combined (|x| × y) so both axes matter.
    const ranked = xs
      .map((x, i) => ({ i, score: (Math.abs(x) || 0) * (ys[i] ?? 0) }))
      .filter((d) => Number.isFinite(d.score))
      .sort((a, b) => b.score - a.score);
    const topIdx = new Set(ranked.slice(0, topN).map((d) => d.i));

    // Search filter — case-insensitive substring against feature id + label.
    const searchLower = search.trim().toLowerCase();
    const matchedIdx = searchLower
      ? new Set(
          ids
            .map((v, i) => ({ v, i }))
            .filter(({ v, i }) => {
              const a = String(v ?? '').toLowerCase();
              const b = String(labels[i] ?? '').toLowerCase();
              return a.includes(searchLower) || b.includes(searchLower);
            })
            .map(({ i }) => i),
        )
      : null;

    const annotations = showLabels
      ? xs
          .map((x, i) => {
            const y = ys[i];
            if (y == null) return null;
            const labelMe = matchedIdx ? matchedIdx.has(i) : topIdx.has(i);
            if (!labelMe) return null;
            return {
              x,
              y,
              text: String(labels[i] ?? ids[i] ?? ''),
              showarrow: false,
              font: { size: 10 },
            };
          })
          .filter(Boolean)
      : [];

    return {
      data: [
        {
          type: 'scattergl' as const,
          mode: 'markers' as const,
          x: xs,
          y: ys,
          text: ids.map((v) => String(v ?? '')),
          hovertemplate:
            `<b>%{text}</b><br>${config.effect_size_col}: %{x}<br>${config.significance_col}: %{y}<extra></extra>`,
          marker: { color: colors, size: 6, opacity: 0.85 },
        },
      ],
      layout: {
        template: colorScheme === 'dark' ? 'plotly_dark' : 'plotly_white',
        margin: { l: 50, r: 20, t: 30, b: 40 },
        xaxis: { title: { text: config.effect_size_col }, zeroline: true },
        yaxis: {
          title: {
            text: config.significance_is_neg_log10
              ? config.significance_col
              : `-log10(${config.significance_col})`,
          },
        },
        shapes: [
          {
            type: 'line' as const,
            x0: -effectThreshold,
            x1: -effectThreshold,
            yref: 'paper',
            y0: 0,
            y1: 1,
            line: { dash: 'dot', color: 'gray', width: 1 },
          },
          {
            type: 'line' as const,
            x0: effectThreshold,
            x1: effectThreshold,
            yref: 'paper',
            y0: 0,
            y1: 1,
            line: { dash: 'dot', color: 'gray', width: 1 },
          },
          {
            type: 'line' as const,
            xref: 'paper',
            x0: 0,
            x1: 1,
            y0: sigThresholdY,
            y1: sigThresholdY,
            line: { dash: 'dot', color: 'gray', width: 1 },
          },
        ],
        annotations,
        showlegend: false,
        autosize: true,
      },
    };
  }, [rows, config, sigThreshold, effectThreshold, topN, search, showLabels, colorScheme]);

  const controls = (
    <Group gap="xs" wrap="wrap">
      <Tooltip label="Significance threshold (raw p/padj)">
        <NumberInput
          size="xs"
          label="p / padj"
          value={sigThreshold}
          onChange={(v) => setSigThreshold(Number(v) || 0.05)}
          step={0.01}
          min={0}
          max={1}
          decimalScale={3}
          w={110}
        />
      </Tooltip>
      <NumberInput
        size="xs"
        label="|effect|"
        value={effectThreshold}
        onChange={(v) => setEffectThreshold(Number(v) || 0)}
        step={0.1}
        min={0}
        decimalScale={2}
        w={90}
      />
      <NumberInput
        size="xs"
        label="Top-N labels"
        value={topN}
        onChange={(v) => setTopN(Math.max(0, Number(v) || 0))}
        min={0}
        max={500}
        w={110}
      />
      <TextInput
        size="xs"
        label="Search"
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        w={140}
        placeholder="gene / taxon"
      />
      <Switch
        size="xs"
        checked={showLabels}
        onChange={(e) => setShowLabels(e.currentTarget.checked)}
        label="Labels"
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

export default VolcanoRenderer;
