import React, { useEffect, useMemo, useState } from 'react';
import {
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
import { applyDataTheme, applyLayoutTheme, plotlyThemeFragment } from './plotlyTheme';

interface SunburstConfig {
  rank_cols: string[];
  abundance_col: string;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: SunburstConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

// Extended categorical palette (matplotlib tab20 colours) for sunbursts with
// >10 root categories — keeps siblings visually distinct.
const TAB20_PALETTE = [
  '#1f77b4', '#aec7e8', '#ff7f0e', '#ffbb78', '#2ca02c', '#98df8a',
  '#d62728', '#ff9896', '#9467bd', '#c5b0d5', '#8c564b', '#c49c94',
  '#e377c2', '#f7b6d2', '#7f7f7f', '#c7c7c7', '#bcbd22', '#dbdb8d',
  '#17becf', '#9edae5',
] as const;

const SunburstRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as SunburstConfig;

  const ranks = config.rank_cols ?? [];
  // Default to 3 rings: shows hierarchy at a glance without thin outer slivers
  // that make the chart read as a sankey.
  const DEFAULT_DEPTH = Math.min(3, ranks.length);
  const [colourByIdx, setColourByIdx] = useState<number>(0);
  const [maxDepth, setMaxDepth] = useState<number>(DEFAULT_DEPTH);
  const [palette, setPalette] = useState<'tab10' | 'tab20'>('tab20');
  const [showCounts, setShowCounts] = useState<boolean>(true);
  const [minPercent, setMinPercent] = useState<number>(0.5);

  useEffect(() => {
    setMaxDepth(Math.min(3, ranks.length));
    setColourByIdx((prev) => (prev >= ranks.length ? 0 : prev));
  }, [ranks.length]);

  const requiredCols = useMemo(
    () => [...ranks, config.abundance_col].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [colourRankUniverse, setColourRankUniverse] = useState<string[] | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Sunburst: missing data binding (need at least 2 rank columns + abundance)');
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

  // Refetch the universe whenever the user picks a different colour rank — that
  // way the palette tracks the *rank they care about*, not just the top rank.
  useEffect(() => {
    const col = ranks[colourByIdx];
    if (!metadata.dc_id || !col) {
      setColourRankUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, col)
      .then((v) => !cancelled && setColourRankUniverse(v))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, ranks[colourByIdx]]);

  const figure = useMemo(() => {
    if (!rows) return null;
    const depth = Math.max(1, Math.min(ranks.length, maxDepth));
    const visibleRanks = ranks.slice(0, depth);
    const abundance = (rows[config.abundance_col] || []) as number[];
    const rankValues = visibleRanks.map((r) => (rows[r] || []) as (string | number | null)[]);

    // Build node map by walking each row's (rank_1..rank_depth) path and
    // accumulating its leaf abundance into every prefix. ids encode the path
    // so siblings with the same local label don't collide.
    interface NodeRec {
      label: string;
      parent: string;
      value: number;
      colourKey: string;
      depth: number;
    }
    const nodes = new Map<string, NodeRec>();
    for (let i = 0; i < abundance.length; i++) {
      const v = Number(abundance[i]) || 0;
      let pathId = '';
      let parentId = '';
      let colourKey = '';
      for (let r = 0; r < depth; r++) {
        const raw = rankValues[r][i];
        if (raw == null || raw === '') break;
        const label = String(raw);
        pathId = pathId ? `${pathId} | ${label}` : label;
        // Remember the value of the selected "colour by" rank seen on this path.
        if (r === colourByIdx) colourKey = label;
        const existing = nodes.get(pathId);
        if (existing) {
          existing.value += v;
        } else {
          nodes.set(pathId, {
            label,
            parent: parentId,
            value: v,
            colourKey: colourKey || label,
            depth: r,
          });
        }
        parentId = pathId;
      }
    }

    // Drop any node whose value is below the user-set minimum-visibility floor.
    // We compute the floor against the root total so the unit is "% of total".
    const total = Array.from(nodes.values())
      .filter((n) => n.parent === '')
      .reduce((s, n) => s + n.value, 0);
    const floor = total > 0 ? total * (minPercent / 100) : 0;

    const ids: string[] = [];
    const labels: string[] = [];
    const parents: string[] = [];
    const values: number[] = [];
    const colourKeys: string[] = [];
    nodes.forEach((n, k) => {
      if (n.value < floor) return;
      ids.push(k);
      labels.push(n.label);
      parents.push(n.parent);
      values.push(n.value);
      colourKeys.push(n.colourKey);
    });

    const paletteArr = palette === 'tab10' ? TAB10_PALETTE : TAB20_PALETTE;
    const colourSource = stableColorMap(
      colourRankUniverse ?? Array.from(new Set(colourKeys)),
      paletteArr as readonly string[],
    );
    const colors = colourKeys.map((k) => colourSource.get(k) ?? (isDark ? '#888' : '#aaa'));

    const labelText = showCounts && values.length > 0
      ? labels.map((l, i) => {
          const pct = total > 0 ? (values[i] / total) * 100 : 0;
          return pct >= 1 ? `${l}\n${pct.toFixed(1)}%` : l;
        })
      : labels;

    return {
      data: [
        {
          type: 'sunburst' as const,
          ids,
          labels: labelText,
          parents,
          values,
          branchvalues: 'total' as const,
          marker: { colors, line: { color: isDark ? '#222' : '#fff', width: 0.5 } },
          hovertemplate:
            `<b>%{label}</b><br>${config.abundance_col}: %{value}<br>` +
            `share: %{percentRoot:.2%}<extra></extra>`,
          insidetextorientation: 'auto' as const,
          maxdepth: depth + 1,
        },
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 0, r: 0, t: 20, b: 0 },
        autosize: true,
      },
    };
  }, [rows, config, ranks, maxDepth, colourByIdx, palette, showCounts, minPercent, colorScheme, theme, colourRankUniverse]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Select
          size="xs"
          label="Colour by rank"
          value={String(colourByIdx)}
          onChange={(v) => v != null && setColourByIdx(Number(v))}
          data={ranks.map((r, i) => ({ value: String(i), label: r }))}
          allowDeselect={false}
        />
        <NumberInput
          size="xs"
          label="Max depth"
          description={`1–${ranks.length}; 3 keeps rings readable`}
          value={maxDepth}
          onChange={(v) => setMaxDepth(Math.max(1, Math.min(ranks.length, Number(v) || 1)))}
          min={1}
          max={ranks.length}
        />
        <Select
          size="xs"
          label="Palette"
          value={palette}
          onChange={(v) => v && setPalette(v as 'tab10' | 'tab20')}
          data={[
            { value: 'tab20', label: 'tab20 (20 colours)' },
            { value: 'tab10', label: 'tab10 (10 colours)' },
          ]}
          allowDeselect={false}
        />
        <NumberInput
          size="xs"
          label="Min arc (% of root)"
          description="Hide slices below this share"
          value={minPercent}
          onChange={(v) => setMinPercent(Math.max(0, Math.min(50, Number(v) || 0)))}
          min={0}
          max={50}
          step={0.5}
          decimalScale={1}
        />
        <Switch
          size="xs"
          checked={showCounts}
          onChange={(e) => setShowCounts(e.currentTarget.checked)}
          label="Show % on arcs"
        />
      </Stack>
    ),
    [colourByIdx, ranks, maxDepth, palette, minPercent, showCounts],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Sunburst'}
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

export default SunburstRenderer;
