import React, { useEffect, useMemo, useState } from 'react';
import {
  NumberInput,
  Select,
  Stack,
  Switch,
  Tabs,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  fetchPolarsSchema,
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

interface RarefactionConfig {
  sample_id_col: string;
  depth_col: string;
  metric_col: string;
  // Optional allowlist of additional metric columns the user can switch to
  // in the renderer (e.g. ["observed_features", "shannon", "chao1"]).
  // When unset, the renderer auto-discovers numeric metric columns from
  // the fetched rows.
  metric_options?: string[] | null;
  iter_col?: string | null;
  group_col?: string | null;
  show_ci?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: RarefactionConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

// Shared tab10 palette via colors.ts so cross-viz colour assignments stay
// in sync. The local alias keeps the index-based fallback ergonomic.
const PALETTE = TAB10_PALETTE;

const RarefactionRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const config = (metadata.config || {}) as RarefactionConfig;
  const isDark = colorScheme === 'dark';

  const [showCI, setShowCI] = useState<boolean>(config.show_ci ?? true);
  const [topN, setTopN] = useState<number>(60);
  const [groupBy, setGroupBy] = useState<string | null>(config.group_col ?? null);
  const [activeMetric, setActiveMetric] = useState<string>(config.metric_col);

  // DC schema for auto-discovering additional numeric metric columns when the
  // dashboard JSON's metric_options is stale or under-specified. Declared
  // before requiredCols because that useMemo depends on schemaMetricCols.
  const [dcSchema, setDcSchema] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    if (!metadata.dc_id) return;
    let cancelled = false;
    fetchPolarsSchema(metadata.dc_id)
      .then((s) => {
        if (!cancelled) setDcSchema(s);
      })
      .catch(() => {
        /* schema is best-effort — falls back to row-scan inside metricOptions */
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id]);

  // Full distinct set of group values so colours stay stable when the user
  // filters down to a subset (e.g. selecting only "treatment" keeps it on the
  // 3rd palette colour instead of shifting to the 1st).
  const [groupUniverse, setGroupUniverse] = useState<string[] | null>(null);
  useEffect(() => {
    if (!metadata.dc_id || !groupBy) {
      setGroupUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, groupBy)
      .then((values) => {
        if (!cancelled) setGroupUniverse(values);
      })
      .catch(() => {
        /* fall back to filtered-set ordering if the endpoint errors */
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, groupBy]);

  const schemaMetricCols = useMemo(() => {
    if (!dcSchema) return [] as string[];
    const NUMERIC_DTYPE_PREFIXES = ['Int', 'UInt', 'Float', 'Decimal'];
    const skip = new Set<string>(
      [
        config.sample_id_col,
        config.depth_col,
        config.iter_col,
        config.group_col,
      ].filter(Boolean) as string[],
    );
    const out: string[] = [];
    for (const [col, dtype] of Object.entries(dcSchema)) {
      if (skip.has(col)) continue;
      if (NUMERIC_DTYPE_PREFIXES.some((p) => dtype.startsWith(p))) out.push(col);
    }
    return out;
  }, [dcSchema, config]);

  const requiredCols = useMemo(() => {
    const cols = [config.sample_id_col, config.depth_col, config.metric_col].filter(Boolean) as string[];
    if (config.iter_col) cols.push(config.iter_col);
    if (config.group_col && !cols.includes(config.group_col)) cols.push(config.group_col);
    // Pull additional metric columns so the user can switch without a refetch.
    for (const m of config.metric_options ?? []) {
      if (m && !cols.includes(m)) cols.push(m);
    }
    // Also fetch numeric columns discovered from the DC schema — keeps the
    // metric tabs alive even when the dashboard JSON in MongoDB is stale.
    for (const m of schemaMetricCols) {
      if (m && !cols.includes(m)) cols.push(m);
    }
    return cols;
  }, [config, schemaMetricCols]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Rarefaction: missing data binding');
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

    const sampleIds = (rows[config.sample_id_col] || []) as (string | number)[];
    const depths = (rows[config.depth_col] || []) as number[];
    const metrics = (rows[activeMetric] || rows[config.metric_col] || []) as number[];
    const groups = groupBy ? (rows[groupBy] as (string | number)[]) : null;

    // Aggregate (sample, depth) → mean + standard error across the iterations
    // (Welford-style running sums). The QIIME2 rarefaction viewer reports
    // mean ± SE; we match that so the plot reads correctly to anyone used to
    // the standard alpha-rarefaction output.
    type Acc = { sum: number; sumSq: number; n: number };
    const perSample = new Map<string, Map<number, Acc>>();
    const sampleGroup = new Map<string, string>();
    for (let i = 0; i < sampleIds.length; i++) {
      const sid = String(sampleIds[i] ?? '');
      const d = Number(depths[i]);
      const v = Number(metrics[i]);
      if (!Number.isFinite(d) || !Number.isFinite(v)) continue;
      let byDepth = perSample.get(sid);
      if (!byDepth) {
        byDepth = new Map();
        perSample.set(sid, byDepth);
      }
      const acc = byDepth.get(d) ?? { sum: 0, sumSq: 0, n: 0 };
      acc.sum += v;
      acc.sumSq += v * v;
      acc.n += 1;
      byDepth.set(d, acc);
      if (groups) sampleGroup.set(sid, String(groups[i] ?? ''));
    }

    // Limit to top-N samples (in display order) so the legend stays usable.
    const samples = Array.from(perSample.keys()).slice(0, topN);

    // Build group→colour mapping for legend consistency.
    const uniqGroups: string[] = [];
    if (groups) {
      for (const s of samples) {
        const g = sampleGroup.get(s) ?? '—';
        if (!uniqGroups.includes(g)) uniqGroups.push(g);
      }
      uniqGroups.sort();
    }
    // Use the full distinct-value universe when available so the colour for
    // each group is invariant under filtering. Falls back to the filtered
    // ordering when the unique-values endpoint hasn't responded yet.
    const colourSource = stableColorMap(groupUniverse ?? uniqGroups, PALETTE);
    const colourForGroup = new Map<string, string>(
      uniqGroups.map((g) => [g, colourSource.get(g)]),
    );
    const seenGroupInLegend = new Set<string>();

    const traces: any[] = [];
    for (let i = 0; i < samples.length; i++) {
      const sid = samples[i];
      const byDepth = perSample.get(sid)!;
      const ds = Array.from(byDepth.keys()).sort((a, b) => a - b);
      const means: number[] = [];
      const ses: number[] = [];
      for (const d of ds) {
        const a = byDepth.get(d)!;
        const m = a.sum / a.n;
        const variance = Math.max(0, a.sumSq / a.n - m * m);
        const se = a.n > 1 ? Math.sqrt(variance / a.n) : 0;
        means.push(m);
        ses.push(se);
      }
      const group = groups ? sampleGroup.get(sid) ?? '—' : sid;
      const colour = groups
        ? colourForGroup.get(group)!
        : PALETTE[i % PALETTE.length];
      const legendName = groups ? group : String(sid);
      const showInLegend = !groups || !seenGroupInLegend.has(group);
      if (showInLegend && groups) seenGroupInLegend.add(group);

      // Single trace = lines connecting the markers + scatter markers + per-
      // point SE whiskers. Matches the QIIME2 alpha-rarefaction default look:
      // mean as the dot, error bar = ±SE, segments joining adjacent depths.
      traces.push({
        type: 'scatter' as const,
        mode: 'lines+markers' as const,
        x: ds,
        y: means,
        name: legendName,
        legendgroup: legendName,
        showlegend: showInLegend,
        line: { color: colour, width: 1.6 },
        marker: { size: 6, color: colour, line: { width: 0 } },
        error_y: showCI
          ? {
              type: 'data' as const,
              array: ses,
              visible: true,
              thickness: 1,
              width: 3,
              color: colour,
            }
          : { visible: false },
        hovertemplate:
          `<b>${String(sid)}</b><br>${config.depth_col}: %{x}` +
          `<br>${activeMetric}: %{y:.3f} ± %{error_y.array:.3f}<extra></extra>`,
      });
    }

    const { textColor } = plotlyThemeColors(isDark, theme);
    return {
      data: traces,
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 56, r: 16, t: 16, b: 48 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: config.depth_col },
          zeroline: false,
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: activeMetric },
          zeroline: false,
        },
        showlegend: true,
        legend: {
          orientation: 'v',
          x: 1.02,
          y: 1,
          font: { size: 10, color: textColor },
          bgcolor: 'rgba(0,0,0,0)',
        },
        autosize: true,
      },
    };
  }, [rows, config, isDark, theme, showCI, topN, groupBy, activeMetric]);

  // Available metric columns. Prefer the config allowlist; merge in schema-
  // discovered numeric columns so a stale dashboard JSON (config.metric_options
  // missing or under-populated) still surfaces the metric tabs. Final fallback:
  // scan loaded rows for numeric columns (works even without a schema endpoint).
  const metricOptions = useMemo(() => {
    const cfgList = (config.metric_options ?? []).filter(Boolean) as string[];
    const seed = new Set<string>([config.metric_col, ...cfgList]);
    // Schema-driven discovery first (cheap, runs once after schema fetch).
    for (const c of schemaMetricCols) seed.add(c);
    // Row-scan fallback if neither config nor schema produced ≥2 metrics.
    if (seed.size <= 1 && rows) {
      const skip = new Set<string>(
        [config.sample_id_col, config.depth_col, config.iter_col, config.group_col].filter(
          Boolean,
        ) as string[],
      );
      for (const c of Object.keys(rows)) {
        if (skip.has(c)) continue;
        const v = (rows[c] || []) as unknown[];
        const firstNum = v.find((x) => x != null);
        if (typeof firstNum === 'number') seed.add(c);
      }
    }
    return Array.from(seed);
  }, [rows, config, schemaMetricCols]);

  // Discover group/metric options from the rows once they arrive.
  const groupOptions = useMemo(() => {
    if (!rows) return [] as { value: string; label: string }[];
    const out: { value: string; label: string }[] = [];
    for (const c of Object.keys(rows)) {
      if (c === config.sample_id_col || c === config.depth_col || c === config.metric_col)
        continue;
      out.push({ value: c, label: c });
    }
    return out;
  }, [rows, config]);

  const controls = (
    <Stack gap="xs">
      {groupOptions.length > 0 ? (
        <Select
          size="xs"
          label="Group by"
          value={groupBy}
          onChange={setGroupBy}
          data={groupOptions}
          clearable
          description="Colour curves by metadata column"
        />
      ) : null}
      <NumberInput
        size="xs"
        label="Top-N samples"
        value={topN}
        onChange={(v) => setTopN(Math.max(1, Number(v) || 60))}
        min={1}
        max={200}
      />
      <Switch
        size="xs"
        checked={showCI}
        onChange={(e) => setShowCI(e.currentTarget.checked)}
        label="Show error bars (±SE)"
      />
    </Stack>
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Rarefaction curves'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {metricOptions.length > 1 ? (
        // Tabs switcher (same pattern as DaBarplotRenderer's contrast switcher) —
        // the metric is the dominant axis of comparison, so it's surfaced as the
        // primary control above the chart instead of being buried in the popover.
        <Tabs
          value={activeMetric}
          onChange={(v) => v && setActiveMetric(v)}
          variant="outline"
          radius="sm"
          styles={{ root: { display: 'flex', flexDirection: 'column', height: '100%' } }}
          keepMounted={false}
        >
          <Tabs.List>
            {metricOptions.map((m) => (
              <Tabs.Tab key={m} value={m}>
                {m}
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
      ) : figure ? (
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

export default RarefactionRenderer;
