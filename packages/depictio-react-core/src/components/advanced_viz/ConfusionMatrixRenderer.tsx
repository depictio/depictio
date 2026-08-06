import React, { useEffect, useMemo, useState } from 'react';
import { Select, Slider, Stack, Switch, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyThemeFragment } from './plotlyTheme';
import { COLORSCALE_NAMES, contrastingText, plotlyColorscale, sampleColorscale } from '../../utils/colorScale';

type NormalizeMode = 'per_caller' | 'per_truth' | 'none';

interface ConfusionMatrixConfig {
  label_col: string;
  tp_col: string;
  fp_col: string;
  fn_col: string;
  tn_col?: string | null;
  normalize?: boolean;
  normalize_mode?: NormalizeMode;
  colorscale?: string;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: ConfusionMatrixConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const ConfusionMatrixRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as ConfusionMatrixConfig;

  const [showFractions, setShowFractions] = useState<boolean>(config.normalize ?? false);
  const [mode, setMode] = useState<NormalizeMode>(config.normalize_mode ?? 'per_caller');
  const [colorscale, setColorscale] = useState<string>(config.colorscale ?? 'Blues');
  const [showColorbar, setShowColorbar] = useState<boolean>(true);
  const [fontSize, setFontSize] = useState<number>(15);

  const requiredCols = useMemo(
    () =>
      [config.label_col, config.tp_col, config.fp_col, config.fn_col, ...(config.tn_col ? [config.tn_col] : [])].filter(
        Boolean,
      ) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 4) {
      setError('Confusion matrix: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns: requiredCols,
      filters,
      // Counts are summed client-side, so any subset changes the numbers
      // reported rather than their resolution.
      vizKind: 'confusion_matrix',
    })
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
    const callers = (rows[config.label_col] || []).map((v) => String(v ?? ''));
    const tp = (rows[config.tp_col] || []) as number[];
    const fp = (rows[config.fp_col] || []) as number[];
    const fn = (rows[config.fn_col] || []) as number[];
    const tn = config.tn_col ? ((rows[config.tn_col] || []) as number[]) : null;
    if (callers.length === 0) return null;

    const rowNames = tn ? ['TP', 'FP', 'FN', 'TN'] : ['TP', 'FP', 'FN'];
    const rawRows = (tn ? [tp, fp, fn, tn] : [tp, fp, fn]).map((r) => r.map((v) => v ?? 0));
    const fmt = (v: number) => (Math.abs(v) >= 1000 ? v.toLocaleString('en-US') : String(v));

    // Colour value in [0,1]: normalised so cells are comparable despite TP ≫ FP/FN.
    const zColor = rawRows.map((r) => r.map(() => 0));
    if (mode === 'per_caller') {
      for (let c = 0; c < callers.length; c++) {
        const s = rawRows.reduce((a, r) => a + r[c], 0) || 1;
        rawRows.forEach((r, ri) => (zColor[ri][c] = r[c] / s));
      }
    } else if (mode === 'per_truth') {
      rawRows.forEach((r, ri) => {
        const s = r.reduce((a, v) => a + v, 0) || 1;
        r.forEach((v, c) => (zColor[ri][c] = v / s));
      });
    } else {
      const gmax = Math.max(...rawRows.flat(), 1);
      rawRows.forEach((r, ri) => r.forEach((v, c) => (zColor[ri][c] = v / gmax)));
    }

    // Heatmap y is bottom→top, so reverse the row order to keep TP on top.
    const yOrder = [...rowNames].reverse();
    const z = yOrder.map((name) => zColor[rowNames.indexOf(name)]);
    const counts = yOrder.map((name) => rawRows[rowNames.indexOf(name)]);

    const annotations: any[] = [];
    for (let ri = 0; ri < yOrder.length; ri++) {
      for (let ci = 0; ci < callers.length; ci++) {
        annotations.push({
          x: callers[ci],
          y: yOrder[ri],
          text: showFractions ? z[ri][ci].toFixed(2) : fmt(counts[ri][ci]),
          showarrow: false,
          font: { size: fontSize, color: contrastingText(sampleColorscale(colorscale, z[ri][ci])) },
        });
      }
    }

    return {
      data: [
        {
          type: 'heatmap',
          x: callers,
          y: yOrder,
          z,
          customdata: counts,
          colorscale: plotlyColorscale(colorscale),
          zmin: 0,
          zmax: 1,
          showscale: showColorbar,
          colorbar: { thickness: 10, len: 0.7, title: { text: 'fraction' } },
          hovertemplate: '%{y} · %{x}: %{customdata} (%{z:.2f})<extra></extra>',
          xgap: 3,
          ygap: 3,
        },
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 48, r: showColorbar ? 20 : 8, t: 18, b: 64 },
        xaxis: { tickangle: -30, automargin: true },
        yaxis: { automargin: true },
        annotations,
        autosize: true,
      },
    };
  }, [rows, config, showFractions, mode, colorscale, showColorbar, fontSize, isDark, theme]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Switch size="xs" checked={showFractions} onChange={(e) => setShowFractions(e.currentTarget.checked)} label="Show fractions" />
        <Select
          size="xs"
          label="Normalise"
          value={mode}
          onChange={(v) => setMode((v as NormalizeMode) || 'per_caller')}
          data={[
            { value: 'per_caller', label: 'Per caller (column)' },
            { value: 'per_truth', label: 'Per row (TP/FP/FN)' },
            { value: 'none', label: 'None (raw scale)' },
          ]}
          comboboxProps={{ withinPortal: true }}
        />
        <Select
          size="xs"
          label="Colour scale"
          value={colorscale}
          onChange={(v) => setColorscale(v || 'Blues')}
          data={COLORSCALE_NAMES}
          comboboxProps={{ withinPortal: true }}
        />
        <Switch size="xs" checked={showColorbar} onChange={(e) => setShowColorbar(e.currentTarget.checked)} label="Colour bar" />
        <Stack gap={2}>
          <Text size="xs" fw={500}>Font size</Text>
          <Slider size="xs" min={8} max={26} value={fontSize} onChange={setFontSize} />
        </Stack>
      </Stack>
    ),
    [showFractions, mode, colorscale, showColorbar, fontSize],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Confusion matrix'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
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

export default ConfusionMatrixRenderer;
