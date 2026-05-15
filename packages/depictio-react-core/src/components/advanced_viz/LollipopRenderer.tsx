import React, { useEffect, useMemo, useState } from 'react';
import {
  Group,
  NumberInput,
  Select,
  Stack,
  Switch,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { stableColorMap, TAB10_PALETTE } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeColors,
  plotlyThemeFragment,
} from './plotlyTheme';

interface LollipopConfig {
  feature_id_col: string;
  position_col: string;
  category_col: string;
  effect_col?: string | null;
  max_subplot_genes?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: LollipopConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

type GeneSort = 'name' | 'count' | 'effect';

// Extended palette so >10 mutation consequences stay distinguishable.
const TAB20_PALETTE = [
  '#1f77b4', '#aec7e8', '#ff7f0e', '#ffbb78', '#2ca02c', '#98df8a',
  '#d62728', '#ff9896', '#9467bd', '#c5b0d5', '#8c564b', '#c49c94',
  '#e377c2', '#f7b6d2', '#7f7f7f', '#c7c7c7', '#bcbd22', '#dbdb8d',
  '#17becf', '#9edae5',
] as const;

const LollipopRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as LollipopConfig;
  const maxSubplotGenes = config.max_subplot_genes ?? 6;

  const [pointSize, setPointSize] = useState<number>(8);
  const [stemWidth, setStemWidth] = useState<number>(1.2);
  const [scalePointsByEffect, setScalePointsByEffect] = useState<boolean>(true);
  const [showStems, setShowStems] = useState<boolean>(true);
  const [markerOutline, setMarkerOutline] = useState<boolean>(false);
  const [palette, setPalette] = useState<'tab10' | 'tab20'>('tab10');
  const [geneSort, setGeneSort] = useState<GeneSort>('count');
  const [topNLabels, setTopNLabels] = useState<number>(0);

  const requiredCols = useMemo(
    () =>
      [
        config.feature_id_col,
        config.position_col,
        config.category_col,
        ...(config.effect_col ? [config.effect_col] : []),
      ].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryUniverse, setCategoryUniverse] = useState<string[] | null>(null);
  const [selectedGene, setSelectedGene] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Lollipop: missing data binding');
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

  useEffect(() => {
    if (!metadata.dc_id || !config.category_col) return;
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.category_col)
      .then((v) => !cancelled && setCategoryUniverse(v))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.category_col]);

  const { genesInData, useSinglePicker } = useMemo(() => {
    if (!rows) return { genesInData: [] as string[], useSinglePicker: false };
    const gv = (rows[config.feature_id_col] || []) as (string | number)[];
    const pv = (rows[config.position_col] || []) as number[];
    const ev = config.effect_col ? ((rows[config.effect_col] || []) as number[]) : null;

    // Variant counts + mean abs effect per gene, used for the sort selector.
    const count = new Map<string, number>();
    const effSum = new Map<string, number>();
    for (let i = 0; i < gv.length; i++) {
      const g = String(gv[i]);
      count.set(g, (count.get(g) ?? 0) + 1);
      if (ev) effSum.set(g, (effSum.get(g) ?? 0) + Math.abs(Number(ev[i]) || 0));
    }
    let uniq = Array.from(count.keys());
    if (geneSort === 'name') {
      uniq.sort();
    } else if (geneSort === 'count') {
      uniq.sort((a, b) => (count.get(b) ?? 0) - (count.get(a) ?? 0));
    } else if (geneSort === 'effect' && ev) {
      uniq.sort((a, b) => {
        const ea = (effSum.get(a) ?? 0) / Math.max(1, count.get(a) ?? 1);
        const eb = (effSum.get(b) ?? 0) / Math.max(1, count.get(b) ?? 1);
        return eb - ea;
      });
    }
    return { genesInData: uniq, useSinglePicker: uniq.length > maxSubplotGenes };
  }, [rows, config.feature_id_col, config.position_col, config.effect_col, maxSubplotGenes, geneSort]);

  useEffect(() => {
    if (useSinglePicker && !selectedGene && genesInData.length > 0) {
      setSelectedGene(genesInData[0]);
    }
  }, [useSinglePicker, genesInData, selectedGene]);

  const figure = useMemo(() => {
    if (!rows) return null;
    const gv = (rows[config.feature_id_col] || []) as (string | number)[];
    const pv = (rows[config.position_col] || []) as number[];
    const cv = (rows[config.category_col] || []) as (string | number)[];
    const ev = config.effect_col ? ((rows[config.effect_col] || []) as number[]) : null;

    const genesToShow = useSinglePicker
      ? selectedGene
        ? [selectedGene]
        : []
      : genesInData;
    if (genesToShow.length === 0) return null;

    const categories = Array.from(new Set(cv.map(String))).sort();
    const paletteArr = palette === 'tab10' ? TAB10_PALETTE : TAB20_PALETTE;
    const colourSource = stableColorMap(
      categoryUniverse ?? categories,
      paletteArr as readonly string[],
    );

    // Marker sizes from raw effect values when scaling is enabled. Range 5..14 px.
    // (Previously this took already-clamped "heights" which double-clamped
    // negative effects to 0 — fixed by deriving from raw ev directly.)
    const sizesFromEffect = (indices: number[]) => {
      if (!ev || !scalePointsByEffect) return indices.map(() => pointSize);
      const effs = indices.map((i) => Math.abs(Number(ev[i]) || 0));
      const minE = Math.min(...effs);
      const maxE = Math.max(...effs);
      if (!(maxE > minE)) return indices.map(() => pointSize);
      return effs.map((e) => 5 + ((e - minE) / (maxE - minE)) * (pointSize + 6 - 5));
    };

    const nGenes = genesToShow.length;
    const data: any[] = [];
    const annotations: any[] = [];
    const shapes: any[] = [];
    const yaxes: Record<string, any> = {};
    const baselineColour = isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.6)';

    for (let g = 0; g < nGenes; g++) {
      const gene = genesToShow[g];
      const yref = g === 0 ? 'y' : `y${g + 1}`;
      const yaxisName = g === 0 ? 'yaxis' : `yaxis${g + 1}`;
      const domainTop = 1 - g / nGenes;
      const domainBot = 1 - (g + 1) / nGenes + 0.04;

      const xsForGene = pv.filter((_, i) => String(gv[i]) === gene);
      shapes.push({
        type: 'line' as const,
        xref: 'x',
        yref,
        x0: Math.min(...xsForGene, 0),
        x1: Math.max(...xsForGene, 1),
        y0: 0,
        y1: 0,
        line: { color: baselineColour, width: 1 },
      });

      annotations.push({
        xref: 'paper' as const,
        yref: 'paper' as const,
        x: 0,
        xanchor: 'left' as const,
        y: (domainTop + domainBot) / 2,
        yanchor: 'middle' as const,
        text: `<b>${gene}</b>`,
        showarrow: false,
        font: { size: 11, color: plotlyThemeColors(isDark, theme).textColor },
      });

      yaxes[yaxisName] = {
        ...plotlyAxisOverrides(isDark, theme),
        domain: [domainBot, domainTop],
        title: { text: '' },
        showgrid: false,
        zeroline: false,
        showticklabels: false,
      };

      for (const cat of categories) {
        const idx: number[] = [];
        for (let i = 0; i < gv.length; i++) {
          if (String(gv[i]) === gene && String(cv[i]) === cat) idx.push(i);
        }
        if (idx.length === 0) continue;

        const xs = idx.map((i) => pv[i]);
        const heights = ev ? idx.map((i) => Math.max(0, ev[i] ?? 1)) : idx.map(() => 1);

        if (showStems) {
          for (let k = 0; k < idx.length; k++) {
            shapes.push({
              type: 'line' as const,
              xref: 'x',
              yref,
              x0: xs[k],
              x1: xs[k],
              y0: 0,
              y1: heights[k],
              line: { color: colourSource.get(cat), width: stemWidth },
            });
          }
        }
        data.push({
          type: 'scattergl' as const,
          mode: 'markers' as const,
          name: cat,
          legendgroup: cat,
          showlegend: g === 0,
          x: xs,
          y: heights,
          xaxis: 'x',
          yaxis: yref,
          customdata: idx.map((i) => [
            String(gv[i] ?? ''),
            String(cv[i] ?? ''),
            ev ? ev[i] ?? null : null,
          ]),
          hovertemplate:
            `<b>%{customdata[0]}</b>:%{x}<br>${config.category_col}: %{customdata[1]}` +
            (ev ? `<br>${config.effect_col}: %{customdata[2]}` : '') +
            `<extra></extra>`,
          marker: {
            size: sizesFromEffect(idx),
            color: colourSource.get(cat),
            line: markerOutline
              ? {
                  width: 0.6,
                  color: isDark ? 'rgba(0,0,0,0.7)' : 'rgba(255,255,255,0.85)',
                }
              : { width: 0 },
          },
        });
      }

      // Top-N highest-effect labels per gene.
      if (topNLabels > 0 && ev) {
        const localIdx: number[] = [];
        for (let i = 0; i < gv.length; i++) if (String(gv[i]) === gene) localIdx.push(i);
        const ranked = localIdx
          .map((i) => ({ i, e: Math.abs(Number(ev[i]) || 0) }))
          .sort((a, b) => b.e - a.e)
          .slice(0, topNLabels);
        if (ranked.length > 0) {
          data.push({
            type: 'scatter' as const,
            mode: 'text' as const,
            x: ranked.map((r) => pv[r.i]),
            y: ranked.map((r) => Math.max(0, Number(ev[r.i]) || 0)),
            text: ranked.map((r) => String(pv[r.i])),
            textposition: 'top center' as const,
            textfont: { size: 9, color: isDark ? '#fff' : '#222' },
            xaxis: 'x',
            yaxis: yref,
            hoverinfo: 'skip',
            showlegend: false,
          });
        }
      }
    }

    const { textColor } = plotlyThemeColors(isDark, theme);
    return {
      data,
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 80, r: 20, t: 20, b: 50 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: config.position_col },
          showgrid: false,
          zeroline: false,
        },
        ...yaxes,
        shapes,
        annotations,
        showlegend: true,
        legend: {
          orientation: 'h' as const,
          x: 0,
          y: -0.15,
          font: { color: textColor },
          bgcolor: 'rgba(0,0,0,0)',
        },
        autosize: true,
      },
    };
  }, [
    rows,
    config,
    selectedGene,
    genesInData,
    useSinglePicker,
    categoryUniverse,
    colorScheme,
    theme,
    pointSize,
    stemWidth,
    scalePointsByEffect,
    showStems,
    markerOutline,
    palette,
    topNLabels,
  ]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        {useSinglePicker ? (
          <Select
            size="xs"
            label="Gene"
            value={selectedGene}
            onChange={setSelectedGene}
            data={genesInData}
            searchable
          />
        ) : null}
        <Select
          size="xs"
          label="Sort genes"
          value={geneSort}
          onChange={(v) => v && setGeneSort(v as GeneSort)}
          data={[
            { value: 'count', label: 'Variant count' },
            { value: 'effect', label: 'Mean |effect|' },
            { value: 'name', label: 'Name' },
          ]}
          allowDeselect={false}
        />
        <Group gap="xs" grow>
          <NumberInput
            size="xs"
            label="Point size"
            value={pointSize}
            onChange={(v) => setPointSize(Math.max(2, Math.min(20, Number(v) || 8)))}
            min={2}
            max={20}
          />
          <NumberInput
            size="xs"
            label="Stem width"
            value={stemWidth}
            onChange={(v) => setStemWidth(Math.max(0.5, Math.min(6, Number(v) || 1.2)))}
            min={0.5}
            max={6}
            step={0.2}
            decimalScale={1}
          />
        </Group>
        <Select
          size="xs"
          label="Palette"
          value={palette}
          onChange={(v) => v && setPalette(v as 'tab10' | 'tab20')}
          data={[
            { value: 'tab10', label: 'tab10 (10 colours)' },
            { value: 'tab20', label: 'tab20 (20 colours)' },
          ]}
          allowDeselect={false}
        />
        <NumberInput
          size="xs"
          label="Label top-N positions"
          description="Per gene, 0 = off"
          value={topNLabels}
          onChange={(v) => setTopNLabels(Math.max(0, Math.min(20, Number(v) || 0)))}
          min={0}
          max={20}
          disabled={!config.effect_col}
        />
        <Switch
          size="xs"
          checked={scalePointsByEffect}
          onChange={(e) => setScalePointsByEffect(e.currentTarget.checked)}
          label="Scale points by |effect|"
          disabled={!config.effect_col}
        />
        <Switch
          size="xs"
          checked={showStems}
          onChange={(e) => setShowStems(e.currentTarget.checked)}
          label="Show stems"
        />
        <Switch
          size="xs"
          checked={markerOutline}
          onChange={(e) => setMarkerOutline(e.currentTarget.checked)}
          label="Marker outline"
        />
      </Stack>
    ),
    [
      useSinglePicker,
      selectedGene,
      genesInData,
      geneSort,
      pointSize,
      stemWidth,
      palette,
      topNLabels,
      scalePointsByEffect,
      showStems,
      markerOutline,
      config.effect_col,
    ],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Lollipop plot'}
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

export default LollipopRenderer;
