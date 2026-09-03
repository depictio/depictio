import React, { useEffect, useMemo, useState } from 'react';
import {
  SegmentedControl,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import { COLORSCALE_NAMES, plotlyColorscale } from '../../utils/colorScale';

interface PrBenchmarkConfig {
  label_col: string;
  recall_col: string;
  precision_col: string;
  f1_col?: string | null;
  support_col?: string | null;
  category_col?: string | null;
  show_iso_f1?: boolean;
  show_diagonal?: boolean;
  show_labels?: boolean;
  colorscale?: string;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: PrBenchmarkConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

// F1 iso-contour: for fixed F1 = c, precision = c*r / (2r - c), valid where 2r > c.
function isoF1Line(c: number): { x: number[]; y: number[] } {
  const x: number[] = [];
  const y: number[] = [];
  for (let r = c / 2 + 0.001; r <= 1.0001; r += 0.01) {
    const p = (c * r) / (2 * r - c);
    if (p >= 0 && p <= 1) {
      x.push(Math.min(r, 1));
      y.push(p);
    }
  }
  return { x, y };
}

const PrBenchmarkRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as PrBenchmarkConfig;

  const [showIso, setShowIso] = useState<boolean>(config.show_iso_f1 ?? true);
  const [showDiag, setShowDiag] = useState<boolean>(config.show_diagonal ?? true);
  const [showLabels, setShowLabels] = useState<boolean>(config.show_labels ?? true);
  const [colorscale, setColorscale] = useState<string>(config.colorscale ?? 'Tealgrn');
  const [sizeMode, setSizeMode] = useState<'support' | 'uniform'>(config.support_col ? 'support' : 'uniform');
  const [baseSize, setBaseSize] = useState<number>(14);
  const [labelFont, setLabelFont] = useState<number>(12);
  const [unitRange, setUnitRange] = useState<boolean>(true);
  const [showColorbar, setShowColorbar] = useState<boolean>(true);

  const requiredCols = useMemo(
    () =>
      [
        config.label_col,
        config.recall_col,
        config.precision_col,
        ...(config.f1_col ? [config.f1_col] : []),
        ...(config.support_col ? [config.support_col] : []),
        ...(config.category_col ? [config.category_col] : []),
      ].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Precision-recall benchmark: missing data binding');
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
      vizKind: 'pr_benchmark',
      roles: { label: config.label_col, recall: config.recall_col, precision: config.precision_col },
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
    const recall = (rows[config.recall_col] || []) as number[];
    const precision = (rows[config.precision_col] || []) as number[];
    const labels = (rows[config.label_col] || []) as (string | number)[];
    const f1 = config.f1_col ? ((rows[config.f1_col] || []) as number[]) : null;
    const support = config.support_col ? ((rows[config.support_col] || []) as number[]) : null;
    const category = config.category_col
      ? ((rows[config.category_col] || []) as (string | number)[])
      : null;

    // Point size from support (sqrt scale so area ~ count), else uniform.
    const sizes =
      support && sizeMode === 'support'
        ? (() => {
            const max = Math.max(...support.map((v) => v || 0), 1);
            return support.map((v) => baseSize * 0.6 + baseSize * 1.4 * Math.sqrt((v || 0) / max));
          })()
        : recall.map(() => baseSize);

    const traces: any[] = [];

    // F1 iso-contours (drawn first, behind the points).
    if (showIso) {
      for (const c of [0.2, 0.4, 0.6, 0.8]) {
        const { x, y } = isoF1Line(c);
        traces.push({
          type: 'scatter',
          mode: 'lines',
          x,
          y,
          line: { dash: 'dot', width: 1, color: 'rgba(140,140,140,0.5)' },
          hoverinfo: 'skip',
          showlegend: false,
          name: `F1=${c}`,
        });
        // Label the contour near its right end.
        if (x.length) {
          traces.push({
            type: 'scatter',
            mode: 'text',
            x: [x[x.length - 1]],
            y: [y[y.length - 1]],
            text: [`F1 ${c}`],
            textposition: 'top left',
            textfont: { size: 9, color: 'rgba(140,140,140,0.8)' },
            hoverinfo: 'skip',
            showlegend: false,
          });
        }
      }
    }

    const customdata = recall.map((_, i) => [
      String(labels[i] ?? ''),
      f1 ? f1[i] ?? null : null,
      support ? support[i] ?? null : null,
    ]);

    // Colour: discrete palette per category if bound, else continuous F1 scale.
    const PALETTE = ['#4C72B0', '#DD8452', '#55A467', '#C44E52', '#8172B3', '#937860', '#DA8BC3'];
    let markerColorArr: (string | number)[] | string;
    let useColorscale = false;
    if (category) {
      const uniq = Array.from(new Set(category.map((v) => String(v ?? ''))));
      markerColorArr = category.map((v) => PALETTE[uniq.indexOf(String(v ?? '')) % PALETTE.length]);
    } else if (f1) {
      markerColorArr = f1;
      useColorscale = true;
    } else {
      markerColorArr = '#3b82c4';
    }
    traces.push({
      type: 'scatter',
      mode: showLabels ? 'markers+text' : 'markers',
      x: recall,
      y: precision,
      text: labels.map((v) => String(v ?? '')),
      textposition: 'top center',
      textfont: { size: labelFont, color: isDark ? '#e6e6e6' : '#222', family: 'Inter, sans-serif' },
      cliponaxis: false,
      customdata,
      hovertemplate:
        `<b>%{customdata[0]}</b>` +
        `<br>${config.recall_col}: %{x:.3f}` +
        `<br>${config.precision_col}: %{y:.3f}` +
        (f1 ? `<br>F1: %{customdata[1]:.3f}` : '') +
        (support ? `<br>${config.support_col}: %{customdata[2]}` : '') +
        `<extra></extra>`,
      marker: {
        size: sizes,
        color: markerColorArr,
        ...(useColorscale
          ? {
              colorscale: plotlyColorscale(colorscale),
              cmin: 0,
              cmax: 1,
              showscale: showColorbar,
              colorbar: { title: { text: 'F1' }, thickness: 12, len: 0.8 },
            }
          : {}),
        opacity: 0.9,
        line: { width: 1, color: '#fff' },
      },
    });

    const shapes = showDiag
      ? [
          {
            type: 'line' as const,
            x0: 0,
            y0: 0,
            x1: 1,
            y1: 1,
            line: { dash: 'dash', width: 1, color: 'rgba(128,128,128,0.5)' },
          },
        ]
      : [];

    return {
      data: traces,
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 55, r: 20, t: 20, b: 45 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: 'Recall' },
          range: unitRange ? [-0.02, 1.06] : undefined,
          zeroline: false,
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: 'Precision' },
          range: unitRange ? [0, 1.14] : undefined,
          zeroline: false,
        },
        shapes,
        annotations: [
          {
            xref: 'paper',
            yref: 'paper',
            x: 0.99,
            y: 0.99,
            xanchor: 'right',
            yanchor: 'top',
            text: 'best ↗',
            showarrow: false,
            font: { size: 12, color: 'rgba(110,110,110,0.95)' },
          },
        ],
        showlegend: false,
        autosize: true,
      },
    };
  }, [rows, config, showIso, showDiag, showLabels, colorscale, sizeMode, baseSize, labelFont, unitRange, showColorbar, isDark, theme]);

  const hasSupport = Boolean(config.support_col);
  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Switch size="xs" checked={showIso} onChange={(e) => setShowIso(e.currentTarget.checked)} label="F1 iso-contours" />
        <Switch size="xs" checked={showDiag} onChange={(e) => setShowDiag(e.currentTarget.checked)} label="y = x diagonal" />
        <Switch size="xs" checked={showLabels} onChange={(e) => setShowLabels(e.currentTarget.checked)} label="Point labels" />
        <Switch size="xs" checked={showColorbar} onChange={(e) => setShowColorbar(e.currentTarget.checked)} label="Colour bar" />
        <Switch size="xs" checked={unitRange} onChange={(e) => setUnitRange(e.currentTarget.checked)} label="Fixed 0–1 axes" />
        <Select
          size="xs"
          label="Colour scale"
          value={colorscale}
          onChange={(v) => setColorscale(v || 'Tealgrn')}
          data={COLORSCALE_NAMES}
          comboboxProps={{ withinPortal: true }}
        />
        {hasSupport ? (
          <Stack gap={2}>
            <Text size="xs" fw={500}>Point size</Text>
            <SegmentedControl
              size="xs"
              value={sizeMode}
              onChange={(v) => setSizeMode(v as 'support' | 'uniform')}
              data={[
                { label: 'By support', value: 'support' },
                { label: 'Uniform', value: 'uniform' },
              ]}
            />
          </Stack>
        ) : null}
        <Stack gap={2}>
          <Text size="xs" fw={500}>Base marker size</Text>
          <Slider size="xs" min={6} max={30} value={baseSize} onChange={setBaseSize} />
        </Stack>
        <Stack gap={2}>
          <Text size="xs" fw={500}>Label font</Text>
          <Slider size="xs" min={8} max={18} value={labelFont} onChange={setLabelFont} />
        </Stack>
      </Stack>
    ),
    [showIso, showDiag, showLabels, showColorbar, unitRange, colorscale, sizeMode, baseSize, labelFont, hasSupport],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Precision-recall benchmark'}
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

export default PrBenchmarkRenderer;
