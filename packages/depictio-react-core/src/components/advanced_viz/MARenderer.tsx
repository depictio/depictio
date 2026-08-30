import React, { useEffect, useMemo, useState } from 'react';
import {
  NumberInput,
  Stack,
  Switch,
  Text,
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
import { isStaleFetch } from '../../fetchQueue';
import { adaptGlTrace, SVG_MAX_POINTS, useWebglSlot } from '../../webglBudget';
import AdvancedVizFrame from './AdvancedVizFrame';
import { splitFigureByGroups } from './groupSplit';
import type { GroupRenderState } from '../../selectionGroups';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

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
  /** Dashboard-wide analysis grouping, recoloured into the built figure.
   *  Colour only: this plot is keyed per feature, so panels would repeat the
   *  same marks. See `splitFigureByGroups`. */
  groupRender?: GroupRenderState;
}

const MARenderer: React.FC<Props> = ({ metadata, filters, refreshTick, groupRender }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as MAConfig;

  const [sigThreshold, setSigThreshold] = usePersistedVizControl(metadata, 'significance_threshold', 0.05);
  const [fcThreshold, setFcThreshold] = usePersistedVizControl(metadata, 'fold_change_threshold', 1.0);
  const [topN, setTopN] = usePersistedVizControl(metadata, 'top_n_labels', 15);
  // Search is where the reader is looking right now, not what the chart is.
  const [search, setSearch] = useState<string>('');
  const [showLabels, setShowLabels] = usePersistedVizControl(metadata, 'show_labels', true);

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
  // Server-side downsampling state (mirrors the scatter-figure Load-All UX).
  const [fullLoad, setFullLoad] = useState(false);
  const [reduction, setReduction] = useState<{
    displayed: number;
    total: number;
    sampled: boolean;
  } | null>(null);

  const filterSig = JSON.stringify(filters);
  useEffect(() => {
    setFullLoad(false);
  }, [filterSig]);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('MA plot: missing data binding');
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
        vizKind: 'ma',
        roles: {
          feature_id: config.feature_id_col,
          avg_log_intensity: config.avg_log_intensity_col,
          log2_fold_change: config.log2_fold_change_col,
        },
        // Same reasoning as the volcano: keep the hits whole, sample the blob.
        // An MA plot defines its hits by p-value when one is bound and by fold
        // change otherwise, and the saved threshold is used rather than the live
        // slider so dragging it doesn't refetch the table.
        tail: config.significance_col
          ? {
              column: config.significance_col,
              direction: 'low',
              threshold: config.significance_threshold ?? 0.05,
            }
          : {
              column: config.log2_fold_change_col,
              direction: 'both',
              threshold: config.fold_change_threshold ?? 1.0,
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

  // Always a marker cloud, so always in the running for a WebGL slot; without
  // one the trace renders as downsampled SVG — see webglBudget.
  const glGranted = useWebglSlot(true);

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
              `<br>${config.avg_log_intensity_col}: %{x:.3f}` +
              `<br>${config.log2_fold_change_col}: %{y:.3f}` +
              (sigRaw ? `<br>${config.significance_col}: %{customdata[1]:.2e}` : '') +
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
  }, [rows, config, sigThreshold, fcThreshold, topN, search, showLabels, isDark, theme, glGranted]);

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
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Labels
          </Text>
          <Switch
          size="xs"
          checked={showLabels}
          onChange={(e) => setShowLabels(e.currentTarget.checked)}
          label="Labels"
        />
        </Stack>
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

export default MARenderer;
