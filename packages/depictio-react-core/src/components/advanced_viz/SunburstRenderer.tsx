import React, { useEffect, useMemo, useState } from 'react';
import {
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
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
import { brandColorway, stableColorMap, TAB10_PALETTE } from '../../colors';
import { useCategoryColorSource } from '../../hooks/useCategoryColors';
import AdvancedVizFrame from './AdvancedVizFrame';
import { isUnassigned, lineageShade, surfaceColour, unassignedGrey } from './hierarchyColors';
import { pinnedPalette } from './phylo/palette';
import { applyDataTheme, applyLayoutTheme, plotlyThemeFragment } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

interface SunburstConfig {
  rank_cols: string[];
  abundance_col: string;
  /** Per-value colour overrides for whichever rank is selected as the colour
   *  key. Wins over palette-index cycling so domain colours (e.g. Habitat
   *  → Set1) stay consistent across tiles. */
  category_palette?: Record<string, string> | null;
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
  // `startRankIdx` picks which rank is the innermost ring. Choosing a deeper
  // start (e.g. Kingdom instead of Habitat) collapses the outer split — useful
  // for "all habitats mixed" taxonomy views.
  // The two rank pickers are stored as rank *names*, not indices. rank_cols can
  // be re-bound in the builder, and a stored index would then quietly point at a
  // different rank than the author chose. Names also make the index a derived
  // value, and deriving it is what clamps it: the two effects that used to reset
  // these on a rank change are gone, which matters because an effect that
  // corrects persisted state would write to the store on every data change.
  const [startRank, setStartRank] = usePersistedVizControl<string | null>(metadata, 'start_rank', null);
  const [colourByRank, setColourByRank] = usePersistedVizControl<string | null>(metadata, 'colour_by_rank', null);
  const [maxDepth, setMaxDepth] = usePersistedVizControl<number>(metadata, 'max_depth', DEFAULT_DEPTH);
  // The instance (or dashboard) brand colorway, when there is one. It
  // becomes an option here and the default, so a branded deployment's
  // figures match its chrome without the viewer having to pick.
  const brandPalette = brandColorway(theme);
  const [palette, setPalette] = usePersistedVizControl<'brand' | 'tab10' | 'tab20'>(
    metadata,
    'palette',
    brandPalette ? 'brand' : 'tab20',
  );
  const [showCounts, setShowCounts] = usePersistedVizControl<boolean>(metadata, 'show_counts', true);
  const [minPercent, setMinPercent] = usePersistedVizControl<number>(metadata, 'min_percent', 0.5);

  // An unset or no-longer-present name falls back to the outermost rank.
  const startRankIdx = Math.max(0, ranks.indexOf(startRank ?? ''));
  // Colour-by has to stay inside the visible window; anything outside it reads
  // as the innermost visible ring.
  const colourByIdx = (() => {
    const idx = ranks.indexOf(colourByRank ?? '');
    const end = Math.min(ranks.length, startRankIdx + maxDepth);
    return idx < startRankIdx || idx >= end ? startRankIdx : idx;
  })();

  const requiredCols = useMemo(
    () => [...ranks, config.abundance_col].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // The server serves this kind whole because the renderer aggregates its rows;
  // past `advanced_viz_no_sample_max_rows` it samples anyway and says so here.
  const [estimated, setEstimated] = useState(false);
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
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns: requiredCols,
      filters,
      vizKind: 'sunburst',
    })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setEstimated(Boolean(res.sampling?.degraded));
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

  // The colour-by rank's values wear the dashboard's colours for that column
  // (a Kingdom pinned in its category colours keeps that colour here too),
  // then the component's own `category_palette`, then the palette.
  const categorySource = useCategoryColorSource();
  const colourCol = ranks[colourByIdx] ?? null;
  const pinned = useMemo(() => {
    const dashboard = pinnedPalette(categorySource, null, colourCol);
    const own = config.category_palette ?? null;
    return dashboard || own ? { ...(dashboard ?? {}), ...(own ?? {}) } : null;
  }, [categorySource, colourCol, config.category_palette]);

  const figure = useMemo(() => {
    if (!rows) return null;
    const start = Math.max(0, Math.min(ranks.length - 1, startRankIdx));
    const depth = Math.max(1, Math.min(ranks.length - start, maxDepth));
    const visibleRanks = ranks.slice(start, start + depth);
    // Re-base the colour-by index into the visible-rank slice.
    const localColourIdx = Math.max(0, Math.min(visibleRanks.length - 1, colourByIdx - start));
    const abundance = (rows[config.abundance_col] || []) as number[];
    const rankValues = visibleRanks.map((r) => (rows[r] || []) as (string | number | null)[]);

    // Build node map by walking each row's (rank_1..rank_depth) path and
    // accumulating its leaf abundance into every prefix. ids encode the path
    // so siblings with the same local label don't collide.
    interface NodeRec {
      label: string;
      parent: string;
      value: number;
      depth: number;
      /** The colour-by rank's value on this path; null above that rank. */
      colourKey: string | null;
      /** Names no group, or sits under one that does. */
      unassigned: boolean;
      children: string[];
    }
    const ROOT = '__all__';
    const nodes = new Map<string, NodeRec>();
    const tops: string[] = [];
    for (let i = 0; i < abundance.length; i++) {
      const v = Number(abundance[i]) || 0;
      let pathId = '';
      let parentId = '';
      let colourKey: string | null = null;
      let unassigned = false;
      for (let r = 0; r < depth; r++) {
        const raw = rankValues[r][i];
        if (raw == null || raw === '') break;
        const label = String(raw);
        pathId = pathId ? `${pathId} | ${label}` : label;
        if (r === localColourIdx) colourKey = label;
        unassigned = unassigned || isUnassigned(label);
        const existing = nodes.get(pathId);
        if (existing) {
          existing.value += v;
        } else {
          nodes.set(pathId, {
            label,
            parent: parentId || ROOT,
            value: v,
            depth: r,
            colourKey: r >= localColourIdx ? colourKey : null,
            unassigned,
            children: [],
          });
          if (parentId) nodes.get(parentId)!.children.push(pathId);
          else tops.push(pathId);
        }
        parentId = pathId;
      }
    }

    const total = tops.reduce((s, id) => s + nodes.get(id)!.value, 0);
    const floor = total > 0 ? total * (minPercent / 100) : 0;

    // Siblings under the floor are folded into one grey "Other" per parent
    // rather than dropped: dropped, they left gaps in their parent's ring and
    // a fringe of slivers too thin to read or hover.
    const kept: Array<NodeRec & { id: string }> = [];
    const keep = (ids: string[], parentId: string) => {
      const byValue = ids.map((id) => ({ id, n: nodes.get(id)! })).sort((a, b) => b.n.value - a.n.value);
      const small = byValue.filter((c) => c.n.value < floor);
      const folded = small.length >= 2 ? new Set(small.map((c) => c.id)) : new Set<string>();
      for (const { id, n } of byValue) {
        if (folded.has(id)) continue;
        kept.push({ ...n, id });
        // Below the floor itself: its own children are smaller still.
        if (n.value >= floor) keep(n.children, id);
      }
      if (folded.size) {
        const first = nodes.get(small[0].id)!;
        kept.push({
          id: `${parentId} | __other__`,
          label: `Other (${folded.size})`,
          parent: parentId,
          value: small.reduce((s, c) => s + c.n.value, 0),
          depth: first.depth,
          colourKey: first.colourKey,
          unassigned: true,
          children: [],
        });
      }
    };
    keep(tops, ROOT);

    const paletteArr =
      palette === 'brand' ? (brandPalette ?? TAB20_PALETTE)
      : palette === 'tab10' ? TAB10_PALETTE
      : TAB20_PALETTE;
    const colourMap = stableColorMap(
      colourRankUniverse ?? kept.map((n) => n.colourKey).filter((k): k is string => Boolean(k)),
      paletteArr as readonly string[],
      pinned,
    );
    const grey = unassignedGrey(isDark);
    // Rings above the colour-by rank carry no hue of their own: a neutral
    // tone, so the colour starts where the grouping the viewer chose does.
    const context = isDark ? '#4a4d52' : '#9aa1a8';
    const siblingIndex = new Map<string, number>();
    const seen = new Map<string, number>();
    for (const n of kept) {
      const i = seen.get(n.parent) ?? 0;
      siblingIndex.set(n.id, i);
      seen.set(n.parent, i + 1);
    }
    const colourOf = (n: NodeRec & { id: string }): string => {
      if (n.unassigned) return grey;
      if (n.colourKey == null) return context;
      return lineageShade(colourMap.get(n.colourKey), n.depth - localColourIdx, siblingIndex.get(n.id) ?? 0, isDark);
    };

    const surface = surfaceColour(isDark);
    const ids = [ROOT, ...kept.map((n) => n.id)];
    const labels = ['All', ...kept.map((n) => n.label)];
    const parents = ['', ...kept.map((n) => n.parent)];
    const values = [total, ...kept.map((n) => n.value)];
    const colors = [surface, ...kept.map(colourOf)];
    const parentLabel = (id: string) => (id === ROOT ? 'all' : nodes.get(id)?.label ?? 'all');
    const customdata = ['', ...kept.map((n) => parentLabel(n.parent))];
    const leafText = showCounts ? '%{label}<br>%{percentRoot:.1%}' : '%{label}';

    return {
      data: [
        {
          type: 'sunburst' as const,
          ids,
          labels,
          parents,
          values,
          customdata,
          branchvalues: 'total' as const,
          // The centre: the whole, and the way back up after a click zooms in.
          texttemplate: ['<b>%{label}</b>', ...kept.map(() => leafText)],
          marker: { colors, line: { color: surface, width: 1.5 } },
          // Plotly fades leaves to 0.7 by default, which turned every outer
          // ring into a washed-out copy of its parent's colour.
          leaf: { opacity: 1 },
          hovertemplate:
            '<b>%{label}</b><br>%{percentRoot:.1%} of all<br>' +
            '%{percentParent:.1%} of %{customdata}<extra></extra>',
          // Each label turned whichever way fits it largest: radial text
          // could not fit a wide, shallow outer slice such as a phylum's.
          insidetextorientation: 'auto' as const,
          maxdepth: depth + 1,
        },
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 4, r: 4, t: 4, b: 4 },
        // Labels that would not fit their slice at a legible size are hidden
        // rather than shrunk to a smudge.
        uniformtext: { minsize: 10, mode: 'hide' as const },
        autosize: true,
      },
    };
  }, [rows, config, ranks, startRankIdx, maxDepth, colourByIdx, palette, showCounts, minPercent, colorScheme, theme, colourRankUniverse, isDark, pinned]);

  const controls = useMemo(
    () => {
      const visibleEnd = Math.min(ranks.length, startRankIdx + maxDepth);
      const colourOptions = ranks.filter((_, i) => i >= startRankIdx && i < visibleEnd);
      const maxDepthAllowed = Math.max(1, ranks.length - startRankIdx);
      // Most used first: a docked panel shows the first few (DockedControls).
      return (
      <Stack gap="xs">
        <Select
          size="xs"
          label="Start from rank"
          description="Innermost ring — pick a deeper rank to collapse outer splits"
          value={ranks[startRankIdx] ?? null}
          onChange={(v) => v != null && setStartRank(v)}
          data={ranks}
          allowDeselect={false}
        />
        <NumberInput
          size="xs"
          label="Max depth"
          description={`1–${maxDepthAllowed}; 3 keeps rings readable`}
          value={maxDepth}
          onChange={(v) => setMaxDepth(Math.max(1, Math.min(maxDepthAllowed, Number(v) || 1)))}
          min={1}
          max={maxDepthAllowed}
        />
        <Select
          size="xs"
          label="Colour by rank"
          value={ranks[colourByIdx] ?? null}
          onChange={(v) => v != null && setColourByRank(v)}
          data={colourOptions}
          allowDeselect={false}
        />
        <Select
          size="xs"
          label="Palette"
          value={palette}
          onChange={(v) => v && setPalette(v as 'brand' | 'tab10' | 'tab20')}
          data={[
            ...(brandPalette ? [{ value: 'brand', label: 'Brand colours' }] : []),
            { value: 'tab20', label: 'tab20 (20 colours)' },
            { value: 'tab10', label: 'tab10 (10 colours)' },
          ]}
          allowDeselect={false}
        />
        <NumberInput
          size="xs"
          label="Min arc (% of root)"
          description="Fold slices below this share into Other"
          value={minPercent}
          onChange={(v) => setMinPercent(Math.max(0, Math.min(50, Number(v) || 0)))}
          min={0}
          max={50}
          step={0.5}
          decimalScale={1}
        />
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Show
          </Text>
          <Switch
          size="xs"
          checked={showCounts}
          onChange={(e) => setShowCounts(e.currentTarget.checked)}
          label="Show % on arcs"
        />
        </Stack>
      </Stack>
      );
    },
    [colourByIdx, ranks, startRankIdx, maxDepth, palette, minPercent, showCounts],
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
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
