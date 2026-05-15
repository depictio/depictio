import React, { useEffect, useMemo, useState } from 'react';
import {
  NumberInput,
  Stack,
  Switch,
  TextInput,
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

interface MAConfig {
  feature_id_col: string;
  avg_log_intensity_col: string;
  log2_fold_change_col: string;
  significance_col?: string | null;
  label_col?: string | null;
  significance_threshold?: number;
  fold_change_threshold?: number;
  top_n_labels?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: MAConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const MARenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as MAConfig;

  const [sigThreshold, setSigThreshold] = useState<number>(config.significance_threshold ?? 0.05);
  const [fcThreshold, setFcThreshold] = useState<number>(config.fold_change_threshold ?? 1.0);
  const [topN, setTopN] = useState<number>(config.top_n_labels ?? 15);
  const [search, setSearch] = useState<string>('');
  const [showLabels, setShowLabels] = useState<boolean>(true);

  const requiredCols = useMemo(
    () => [
      config.feature_id_col,
      config.avg_log_intensity_col,
      config.log2_fold_change_col,
      ...(config.significance_col ? [config.significance_col] : []),
      ...(config.label_col ? [config.label_col] : []),
    ].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('MA plot: missing data binding');
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
    const xs = (rows[config.avg_log_intensity_col] || []) as number[];
    const ys = (rows[config.log2_fold_change_col] || []) as number[];
    const ids = (rows[config.feature_id_col] || []) as (string | number)[];
    const labels = config.label_col
      ? ((rows[config.label_col] || []) as (string | number)[])
      : ids;
    const sigRaw = config.significance_col
      ? ((rows[config.significance_col] || []) as number[])
      : null;

    // Tier mapping mirrors Volcano: significant + |fold change| above
    // threshold → UP / DN, else NS. Without a significance column we
    // colour only by |fold change|.
    const tiers: ('UP' | 'DN' | 'NS')[] = xs.map((_, i) => {
      const fc = ys[i];
      if (fc == null) return 'NS';
      const passSig = sigRaw == null ? true : sigRaw[i] != null && sigRaw[i] < sigThreshold;
      const passFC = Math.abs(fc) >= fcThreshold;
      if (passSig && passFC) return fc > 0 ? 'UP' : 'DN';
      return 'NS';
    });
    const colors = tiers.map((t) =>
      t === 'UP' ? '#e64980' : t === 'DN' ? '#1c7ed6' : 'rgba(160,160,160,0.55)',
    );
    const sizes = tiers.map((t) => (t === 'NS' ? 5 : 7));

    // Top-N by |fold change| × -log10(sig) when available, else by |FC| alone.
    const ranked = ys
      .map((fc, i) => {
        const sig = sigRaw && sigRaw[i] > 0 ? -Math.log10(sigRaw[i]) : 1;
        return { i, score: Math.abs(fc || 0) * sig };
      })
      .filter((d) => Number.isFinite(d.score))
      .sort((a, b) => b.score - a.score);
    const topIdx = new Set(ranked.slice(0, topN).map((d) => d.i));

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
            const labelMe = matchedIdx ? matchedIdx.has(i) : topIdx.has(i);
            if (!labelMe) return null;
            return {
              x,
              y: ys[i],
              text: String(labels[i] ?? ids[i] ?? ''),
              showarrow: false,
              font: { size: 10 },
            };
          })
          .filter(Boolean)
      : [];

    const customdata = xs.map((_, i) => [
      String(labels[i] ?? ids[i] ?? ''),
      sigRaw ? sigRaw[i] ?? null : null,
      tiers[i],
    ]);

    const counts: Record<string, number> = { UP: 0, DN: 0, NS: 0 };
    for (const t of tiers) counts[t] += 1;

    return {
      tiers,
      counts,
      data: [
        {
          type: 'scattergl' as const,
          mode: 'markers' as const,
          x: xs,
          y: ys,
          text: ids.map((v) => String(v ?? '')),
          customdata,
          hovertemplate:
            `<b>%{customdata[0]}</b>  <span style="opacity:0.7">[%{customdata[2]}]</span>` +
            `<br>${config.avg_log_intensity_col}: %{x:.3f}` +
            `<br>${config.log2_fold_change_col}: %{y:.3f}` +
            (sigRaw ? `<br>${config.significance_col}: %{customdata[1]:.2e}` : '') +
            `<extra></extra>`,
          marker: { color: colors, size: sizes, opacity: 0.85 },
        },
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 50, r: 20, t: 30, b: 40 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: config.avg_log_intensity_col },
          zeroline: false,
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: config.log2_fold_change_col },
          zeroline: true,
        },
        shapes: [
          {
            type: 'line' as const,
            xref: 'paper',
            x0: 0,
            x1: 1,
            y0: fcThreshold,
            y1: fcThreshold,
            line: { dash: 'dot', color: 'rgba(128,128,128,0.6)', width: 1 },
          },
          {
            type: 'line' as const,
            xref: 'paper',
            x0: 0,
            x1: 1,
            y0: -fcThreshold,
            y1: -fcThreshold,
            line: { dash: 'dot', color: 'rgba(128,128,128,0.6)', width: 1 },
          },
        ],
        annotations,
        showlegend: false,
        autosize: true,
      },
    };
  }, [rows, config, sigThreshold, fcThreshold, topN, search, showLabels, isDark, theme]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        {config.significance_col ? (
          <NumberInput
            size="xs"
            label="p / padj"
            value={sigThreshold}
            onChange={(v) => setSigThreshold(Number(v) || 0.05)}
            step={0.01}
            min={0}
            max={1}
            decimalScale={3}
          />
        ) : null}
        <NumberInput
          size="xs"
          label="|log2 FC|"
          value={fcThreshold}
          onChange={(v) => setFcThreshold(Number(v) || 0)}
          step={0.1}
          min={0}
          decimalScale={2}
        />
        <NumberInput
          size="xs"
          label="Top-N labels"
          value={topN}
          onChange={(v) => setTopN(Math.max(0, Number(v) || 0))}
          min={0}
          max={500}
        />
        <TextInput
          size="xs"
          label="Search"
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          placeholder="gene"
        />
        <Switch
          size="xs"
          checked={showLabels}
          onChange={(e) => setShowLabels(e.currentTarget.checked)}
          label="Labels"
        />
      </Stack>
    ),
    [config.significance_col, sigThreshold, fcThreshold, topN, search, showLabels],
  );

  // Memoised so the prop reference is stable until tiers themselves change —
  // otherwise a fresh literal each render invalidates AdvancedVizFrame's
  // `extras` useMemo and the Show-data popover keeps republishing.
  const tierAnnotation = useMemo(
    () =>
      figure?.tiers
        ? {
            values: figure.tiers,
            selectedOrder: ['UP', 'DN'],
            columnLabel: 'tier',
          }
        : undefined,
    [figure?.tiers],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'MA plot'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
      counts={figure?.counts}
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

export default MARenderer;
