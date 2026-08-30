import React, { useEffect, useMemo, useState } from 'react';
import {
  NumberInput,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { isStaleFetch } from '../../fetchQueue';
import { adaptGlTrace, SVG_MAX_POINTS, useWebglSlot } from '../../webglBudget';
import AdvancedVizFrame from './AdvancedVizFrame';
import { usePersistedVizControl } from './usePersistedVizControl';
import { splitFigureByGroups } from './groupSplit';
import type { GroupRenderState } from '../../selectionGroups';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';

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
  /** Dashboard-wide analysis grouping, recoloured into the built figure.
   *  Colour only: this plot is keyed per feature, so panels would repeat the
   *  same marks. See `splitFigureByGroups`. */
  groupRender?: GroupRenderState;
}

const VolcanoRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, groupRender }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as VolcanoConfig;

  // Tier-2 controls (never enter the global filter array). The thresholds and
  // the label budget say what the chart is, so they persist; the search box is
  // a way of looking at it and stays local.
  const [sigThreshold, setSigThreshold] = usePersistedVizControl<number>(
    metadata,
    'significance_threshold',
    0.05,
  );
  const [effectThreshold, setEffectThreshold] = usePersistedVizControl<number>(
    metadata,
    'effect_threshold',
    1.0,
  );
  const [topN, setTopN] = usePersistedVizControl<number>(metadata, 'top_n_labels', 20);
  const [search, setSearch] = useState<string>('');
  const [showLabels, setShowLabels] = usePersistedVizControl(metadata, 'show_labels', true);

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
  // Server-side downsampling state (mirrors the scatter-figure Load-All UX).
  const [fullLoad, setFullLoad] = useState(false);
  const [reduction, setReduction] = useState<{
    displayed: number;
    total: number;
    sampled: boolean;
  } | null>(null);

  // A new filter slice may have a different row count — drop back to the
  // sampled view so the user re-opts into a full load for the new data.
  const filterSig = JSON.stringify(filters);
  useEffect(() => {
    setFullLoad(false);
  }, [filterSig]);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Volcano: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    fetchAdvancedVizData(
      {
        wfId: metadata.wf_id,
        dcId: metadata.dc_id,
        columns: requiredCols,
        filters,
        fullLoad,
        vizKind: 'volcano',
        roles: {
          feature_id: config.feature_id_col,
          effect_size: config.effect_size_col,
          significance: config.significance_col,
        },
        // The server reduces a large frame to ~10k rows, and a uniform sample
        // of a genome-wide table keeps essentially none of the hits — the plot
        // that exists to show them would show a cloud. Sending the cutoff this
        // volcano draws its own line at keeps precisely those rows whole.
        //
        // Deliberately the *saved* threshold, not the live `sigThreshold`
        // control: that one is a client-side slider, and refetching a 17M-row
        // table on every drag to widen the tail is a worse trade than leaving
        // the newly-significant rows to the uniform sample of the middle.
        tail: {
          column: config.significance_col,
          direction: config.significance_is_neg_log10 ? 'high' : 'low',
          threshold: config.significance_is_neg_log10
            ? -Math.log10(config.significance_threshold ?? 0.05)
            : (config.significance_threshold ?? 0.05),
        },
      },
      ctrl.signal,
    )
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setReduction({
          displayed: res.row_count,
          total: res.total_rows ?? res.row_count,
          sampled: Boolean(res.sampled),
        });
      })
      .catch((err: unknown) => {
        if (cancelled || isStaleFetch(err)) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(requiredCols), filterSig, refreshTick, fullLoad]);

  // A volcano always draws a marker cloud, so it always competes for one of
  // the bounded WebGL slots. Without one it renders as SVG — see webglBudget.
  const glGranted = useWebglSlot(true);

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
    // The `tiers` array carries UP / DN / NS for the hover badge so the user
    // doesn't have to mentally re-derive it from x/y.
    const tiers: ('UP' | 'DN' | 'NS')[] = xs.map((x, i) => {
      const y = ys[i];
      if (y == null) return 'NS';
      const passSig = y >= sigThresholdY;
      const passEffect = Math.abs(x) >= effectThreshold;
      if (passSig && passEffect) return x > 0 ? 'UP' : 'DN';
      return 'NS';
    });
    const colors = tiers.map((t) =>
      t === 'UP' ? '#e64980' : t === 'DN' ? '#1c7ed6' : 'rgba(160,160,160,0.55)',
    );

    // Binary size scheme so significant hits visually pop out from the
    // grey NS cloud without distracting magnitude variation.
    const sizes = tiers.map((t) => (t === 'NS' ? 5 : 7));

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
            // Place each label slightly above its point with a thin connector
            // arrow. This keeps the (x, y) anchor on the point while moving
            // text-bounding-box up by 16px — far cleaner when several
            // top-N labels cluster near the same effect/significance corner.
            return {
              x,
              y,
              text: String(labels[i] ?? ids[i] ?? ''),
              showarrow: true,
              arrowhead: 0,
              arrowwidth: 0.6,
              arrowcolor: 'rgba(120,120,120,0.6)',
              ax: 0,
              ay: -16,
              font: { size: 10 },
            };
          })
          .filter(Boolean)
      : [];

    // customdata threads label, raw significance, and tier badge into the
    // hover so the tooltip reads UP / DN / NS + values without needing
    // separate per-tier traces. Index [0] is the feature id used by the
    // %{text} fallback already.
    const customdata = xs.map((_, i) => [
      String(labels[i] ?? ids[i] ?? ''),
      sigRaw[i] ?? null,
      tiers[i],
    ]);

    const counts: Record<string, number> = { UP: 0, DN: 0, NS: 0 };
    for (const t of tiers) counts[t] += 1;

    return {
      tiers,
      counts,
      data: [
        adaptGlTrace(
          {
          type: 'scattergl' as const,
          mode: 'markers' as const,
          x: xs,
          y: ys,
          text: ids.map((v) => String(v ?? '')),
          customdata,
          hovertemplate:
            `<b>%{customdata[0]}</b>  <span style="opacity:0.7">[%{customdata[2]}]</span>` +
            `<br>${config.effect_size_col}: %{x:.3f}` +
            `<br>${config.significance_col}: %{customdata[1]:.2e}` +
            `<br>-log10(sig): %{y:.2f}` +
            `<extra></extra>`,
          marker: { color: colors, size: sizes, opacity: 0.85 },
          },
          glGranted,
        ),
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 50, r: 20, t: 30, b: 40 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: config.effect_size_col },
          zeroline: true,
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
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
            line: { dash: 'dot', color: 'rgba(128,128,128,0.6)', width: 1 },
          },
          {
            type: 'line' as const,
            x0: effectThreshold,
            x1: effectThreshold,
            yref: 'paper',
            y0: 0,
            y1: 1,
            line: { dash: 'dot', color: 'rgba(128,128,128,0.6)', width: 1 },
          },
          {
            type: 'line' as const,
            xref: 'paper',
            x0: 0,
            x1: 1,
            y0: sigThresholdY,
            y1: sigThresholdY,
            line: { dash: 'dot', color: 'rgba(128,128,128,0.6)', width: 1 },
          },
        ],
        annotations,
        showlegend: false,
        autosize: true,
      },
    };
  }, [rows, config, sigThreshold, effectThreshold, topN, search, showLabels, isDark, theme, glGranted]);

  // Memoised so AdvancedVizFrame's `extras` useMemo doesn't invalidate on
  // every render — otherwise the published popover JSX is republished on
  // each tick and AG Grid receives a fresh tierAnnotation reference, which
  // (combined with controlled `sort`) was clobbering user filter/sort.
  const controls = useMemo(
    () => (
      <Stack gap="xs">
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
          placeholder="gene / taxon"
        />
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Top-n
          </Text>
          <Switch
            size="xs"
            checked={showLabels}
            onChange={(e) => setShowLabels(e.currentTarget.checked)}
            label="Top-N labels"
          />
        </Stack>
      </Stack>
    ),
    [sigThreshold, effectThreshold, topN, search, showLabels],
  );

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

  // Recolour by the dashboard's analysis groups. The join is on values, and
  // `splitFigureByGroups` returns the figure untouched when no point matches,
  // so a group built from sample ids leaves a per-feature plot alone. Slot 0 of
  // `customdata` is the feature id.
  const groupedFigure = useMemo(
    () =>
      figure
        ? splitFigureByGroups(figure, {
            groupRender,
            identitySlot: 0,
            facetable: false,
            showLegend: true,
          })
        : figure,
    [figure, groupRender],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Volcano plot'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
      counts={figure?.counts}
      tierAnnotation={tierAnnotation}
      reduction={
        reduction && (reduction.sampled || fullLoad)
          ? {
              // Without a WebGL slot the trace is drawn as downsampled SVG, so
              // the badge must report what is on screen, not what arrived.
              displayed: glGranted
                ? reduction.displayed
                : Math.min(reduction.displayed, SVG_MAX_POINTS),
              total: reduction.total,
              sampled: reduction.sampled,
              full: fullLoad,
              loading,
              onToggle: () => setFullLoad((v) => !v),
            }
          : undefined
      }
    >
      {groupedFigure ? (
        <Plot
          data={applyDataTheme(groupedFigure.data, isDark, theme) as any}
          layout={applyLayoutTheme(groupedFigure.layout as any, isDark, theme) as any}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default VolcanoRenderer;
