import React, { useEffect, useMemo, useState } from 'react';
import { NumberInput, ScrollArea, Stack, Tabs, useMantineColorScheme, useMantineTheme } from '@mantine/core';
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
  contrast_view?: string;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: DaBarplotConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const POSITIVE = '#1f77b4';
const NEGATIVE = '#d62728';
const FADED = 'rgba(127,127,127,0.45)';
const ALL_TAB = 'all';

type FeatureRow = { feat: string; label: string; lfc: number; sig: number };

const DaBarplotRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const config = (metadata.config || {}) as DaBarplotConfig;
  const isDark = colorScheme === 'dark';

  const [topN, setTopN] = useState<number>(config.top_n ?? 15);
  const [sigThreshold, setSigThreshold] = useState<number>(config.significance_threshold ?? 0.05);
  const [activeTab, setActiveTab] = useState<string | null>(null);

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

  // Group rows by contrast once — both the tabs list and the active panel
  // read from the same Map so contrast switching never re-traverses raw rows.
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

  // The "All" tab shows up only when there's more than one contrast — otherwise
  // it would just duplicate the only contrast tab.
  const showAllTab = contrastNames.length > 1;
  const tabValues = useMemo(
    () => (showAllTab ? [ALL_TAB, ...contrastNames] : contrastNames),
    [contrastNames, showAllTab],
  );

  // Initialise / heal the active tab when contrasts arrive.
  // Default comes from config.contrast_view: "all" → All tab; a specific
  // contrast string → that tab; anything else → first available tab.
  useEffect(() => {
    if (tabValues.length === 0) return;
    if (activeTab && tabValues.includes(activeTab)) return;
    const preferred = config.contrast_view;
    if (preferred && tabValues.includes(preferred)) {
      setActiveTab(preferred);
    } else if (showAllTab) {
      setActiveTab(ALL_TAB);
    } else {
      setActiveTab(tabValues[0]);
    }
  }, [tabValues, activeTab, config.contrast_view, showAllTab]);

  // Build the bar trace + layout for a single contrast. Returned shape is
  // ready to pass directly to react-plotly.js.
  const buildPanel = (contrastName: string) => {
    const all = byContrast.get(contrastName);
    if (!all || all.length === 0) return null;
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
  };

  const controls = (
    <Stack gap="xs">
      <NumberInput
        size="xs"
        label="Top-N per panel"
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

  // Per-panel height for the faceted "All" view. Tight enough to fit several
  // contrasts in view without forcing scroll for 2–3 panels.
  const FACETED_PANEL_HEIGHT = 240;

  const renderAllFaceted = () => (
    <ScrollArea style={{ width: '100%', height: '100%' }}>
      <Stack gap="md" p="xs">
        {contrastNames.map((c) => {
          const panel = buildPanel(c);
          if (!panel) return null;
          const layout = {
            ...panel.layout,
            title: { text: c, font: { size: 12 } },
            margin: { ...panel.layout.margin, t: 32 },
          };
          return (
            <div key={c} style={{ height: FACETED_PANEL_HEIGHT, position: 'relative' }}>
              <Plot
                data={applyDataTheme(panel.data, isDark, theme) as any}
                layout={applyLayoutTheme(layout as any, isDark, theme) as any}
                useResizeHandler
                style={{ width: '100%', height: '100%' }}
                config={{ displaylogo: false, responsive: true } as any}
              />
            </div>
          );
        })}
      </Stack>
    </ScrollArea>
  );

  const renderSinglePanel = () => {
    if (!activeTab || activeTab === ALL_TAB) return null;
    const panel = buildPanel(activeTab);
    if (!panel) return null;
    return (
      <Plot
        data={applyDataTheme(panel.data, isDark, theme) as any}
        layout={applyLayoutTheme(panel.layout as any, isDark, theme) as any}
        useResizeHandler
        style={{ width: '100%', height: '100%' }}
        config={{ displaylogo: false, responsive: true } as any}
      />
    );
  };

  return (
    <AdvancedVizFrame
      title={metadata.title || 'DA barplot'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {tabValues.length > 0 ? (
        <Tabs
          value={activeTab}
          onChange={setActiveTab}
          variant="outline"
          radius="sm"
          styles={{ root: { display: 'flex', flexDirection: 'column', height: '100%' } }}
          keepMounted={false}
        >
          <Tabs.List>
            {tabValues.map((v) => (
              <Tabs.Tab key={v} value={v}>
                {v === ALL_TAB ? 'All' : v}
              </Tabs.Tab>
            ))}
          </Tabs.List>
          <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
            {activeTab === ALL_TAB ? renderAllFaceted() : renderSinglePanel()}
          </div>
        </Tabs>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default DaBarplotRenderer;
