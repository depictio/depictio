import React, { useEffect, useMemo, useState } from 'react';
import { NumberInput, Stack, Tabs, useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';

interface DaBarplotConfig {
  feature_id_col: string;
  contrast_col: string;
  lfc_col: string;
  significance_col?: string | null;
  label_col?: string | null;
  significance_threshold?: number;
  top_n?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: DaBarplotConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const POSITIVE = '#1f77b4';
const NEGATIVE = '#d62728';
const FADED = 'rgba(127,127,127,0.45)';

const DaBarplotRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const config = (metadata.config || {}) as DaBarplotConfig;
  const isDark = colorScheme === 'dark';

  const [topN, setTopN] = useState<number>(config.top_n ?? 15);
  const [sigThreshold, setSigThreshold] = useState<number>(config.significance_threshold ?? 0.05);
  const [activeContrast, setActiveContrast] = useState<string | null>(null);

  const requiredCols = useMemo(() => {
    const cols = [config.feature_id_col, config.contrast_col, config.lfc_col].filter(Boolean) as string[];
    if (config.significance_col && !cols.includes(config.significance_col))
      cols.push(config.significance_col);
    if (config.label_col && !cols.includes(config.label_col)) cols.push(config.label_col);
    return cols;
  }, [config]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('DA barplot: missing data binding');
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

  // Group rows by contrast once — both the Tabs.List and the active panel
  // read from the same Map so contrast switching never re-traverses raw rows.
  type FeatureRow = { feat: string; label: string; lfc: number; sig: number };
  const { byContrast, contrastNames } = useMemo(() => {
    const map = new Map<string, FeatureRow[]>();
    if (!rows) return { byContrast: map, contrastNames: [] as string[] };
    const feats = (rows[config.feature_id_col] || []) as (string | number)[];
    const contrasts = (rows[config.contrast_col] || []) as (string | number)[];
    const lfcs = (rows[config.lfc_col] || []) as number[];
    const sigs = config.significance_col
      ? ((rows[config.significance_col] || []) as number[])
      : null;
    const labels = config.label_col ? (rows[config.label_col] as (string | number)[]) : null;

    for (let i = 0; i < feats.length; i++) {
      const c = String(contrasts[i] ?? '');
      const lfc = Number(lfcs[i]);
      if (!Number.isFinite(lfc)) continue;
      const sig = sigs ? Number(sigs[i]) : 1;
      const r: FeatureRow = {
        feat: String(feats[i] ?? ''),
        label: labels ? String(labels[i] ?? '') : String(feats[i] ?? ''),
        lfc,
        sig: Number.isFinite(sig) ? sig : 1,
      };
      const arr = map.get(c) ?? [];
      arr.push(r);
      map.set(c, arr);
    }
    return { byContrast: map, contrastNames: Array.from(map.keys()).sort() };
  }, [rows, config]);

  // Initialise / heal the active tab when contrasts become available or change.
  useEffect(() => {
    if (contrastNames.length === 0) return;
    if (!activeContrast || !contrastNames.includes(activeContrast)) {
      setActiveContrast(contrastNames[0]);
    }
  }, [contrastNames, activeContrast]);

  const figure = useMemo(() => {
    if (!activeContrast) return null;
    const all = byContrast.get(activeContrast);
    if (!all || all.length === 0) return null;

    // Sort by |LFC|, take top-N, then re-sort by signed LFC so positives sit
    // at the top of the y-axis (plotly draws first item at the bottom).
    const ranked = [...all].sort((a, b) => Math.abs(b.lfc) - Math.abs(a.lfc)).slice(0, topN);
    ranked.sort((a, b) => a.lfc - b.lfc);
    const colour = ranked.map((r) =>
      r.sig <= sigThreshold ? (r.lfc >= 0 ? POSITIVE : NEGATIVE) : FADED,
    );

    return {
      data: [
        {
          type: 'bar' as const,
          orientation: 'h' as const,
          x: ranked.map((r) => r.lfc),
          y: ranked.map((r) => r.label),
          text: ranked.map((r) => r.label),
          customdata: ranked.map((r) => [r.feat, r.sig]),
          textposition: 'outside' as const,
          marker: { color: colour, line: { width: 0 } },
          hovertemplate:
            `<b>%{text}</b><br>${config.lfc_col}: %{x:.3f}` +
            (config.significance_col
              ? `<br>${config.significance_col}: %{customdata[1]:.2e}`
              : '') +
            `<extra></extra>`,
          showlegend: false,
        },
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 8, r: 80, t: 12, b: 36 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: config.lfc_col },
          zeroline: true,
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          automargin: true,
          showticklabels: false,
          ticks: '',
        },
        autosize: true,
      },
    };
  }, [activeContrast, byContrast, topN, sigThreshold, config, isDark, theme]);

  const controls = (
    <Stack gap="xs">
      <NumberInput
        size="xs"
        label="Top-N per contrast"
        value={topN}
        onChange={(v) => setTopN(Math.max(1, Number(v) || 15))}
        min={1}
        max={50}
      />
      <NumberInput
        size="xs"
        label="Significance threshold"
        value={sigThreshold}
        onChange={(v) => setSigThreshold(Math.max(0, Math.min(1, Number(v) || 0.05)))}
        min={0}
        max={1}
        step={0.01}
        decimalScale={3}
      />
    </Stack>
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'DA barplot (per contrast)'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {contrastNames.length > 0 ? (
        <Tabs
          value={activeContrast}
          onChange={setActiveContrast}
          variant="outline"
          radius="sm"
          styles={{ root: { display: 'flex', flexDirection: 'column', height: '100%' } }}
          keepMounted={false}
        >
          <Tabs.List>
            {contrastNames.map((c) => (
              <Tabs.Tab key={c} value={c}>
                {c}
              </Tabs.Tab>
            ))}
          </Tabs.List>
          <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
            {figure ? (
              <Plot
                data={applyDataTheme(figure.data, isDark, theme) as any}
                layout={applyLayoutTheme(figure.layout as any, isDark, theme) as any}
                useResizeHandler
                style={{ width: '100%', height: '100%' }}
                config={{ displaylogo: false, responsive: true } as any}
              />
            ) : null}
          </div>
        </Tabs>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default DaBarplotRenderer;
