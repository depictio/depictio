import React, { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Group,
  NumberInput,
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
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';

interface QQConfig {
  p_value_col: string;
  feature_id_col?: string | null;
  category_col?: string | null;
  show_ci?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: QQConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const QQRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as QQConfig;

  const [showCi, setShowCi] = useState<boolean>(config.show_ci ?? true);
  const [showIdentity, setShowIdentity] = useState<boolean>(true);
  const [pointSize, setPointSize] = useState<number>(5);
  const [topNLabels, setTopNLabels] = useState<number>(0);

  const requiredCols = useMemo(
    () =>
      [
        config.p_value_col,
        ...(config.feature_id_col ? [config.feature_id_col] : []),
        ...(config.category_col ? [config.category_col] : []),
      ].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryUniverse, setCategoryUniverse] = useState<string[] | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || !config.p_value_col) {
      setError('QQ plot: missing data binding');
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
    if (!metadata.dc_id || !config.category_col) {
      setCategoryUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.category_col)
      .then((v) => !cancelled && setCategoryUniverse(v))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.category_col]);

  // chi-square inverse CDF approximation (Wilson–Hilferty) for 1 df. Used to
  // turn observed/expected p-values into chi² statistics so we can compute the
  // genomic inflation factor λ = median(χ²_obs) / median(χ²_exp).
  const chi2InvCdf1df = (p: number): number => {
    if (p <= 0) return Infinity;
    if (p >= 1) return 0;
    // Approximation: chi² ~ (1 - 2/9 + z * sqrt(2/9))^3 * df, for df=1.
    // We invert via normal-quantile of (1 - p) — z = Φ⁻¹(1 - p/2) works well
    // for one-sided two-tailed p. Beasley-Springer-Moro approximation.
    const a = 1 - p;
    const t = Math.sqrt(-2 * Math.log(Math.min(a, 1 - a)));
    const num = 2.515517 + 0.802853 * t + 0.010328 * t * t;
    const den = 1 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t;
    const z = (a > 0.5 ? 1 : -1) * (t - num / den);
    return z * z;
  };

  const figure = useMemo(() => {
    if (!rows) return null;
    const ps = (rows[config.p_value_col] || []) as number[];
    const ids = config.feature_id_col
      ? ((rows[config.feature_id_col] || []) as (string | number)[])
      : null;
    const cats = config.category_col
      ? ((rows[config.category_col] || []) as (string | number)[])
      : null;

    const buildSeries = (idxs: number[]) => {
      const valid = idxs.filter((i) => {
        const p = ps[i];
        return p != null && p > 0 && p <= 1;
      });
      const sorted = valid
        .map((i) => ({ i, p: ps[i] }))
        .sort((a, b) => a.p - b.p);
      const n = sorted.length;
      const observed = sorted.map((d) => -Math.log10(d.p));
      const expected = sorted.map((_, k) => -Math.log10((k + 1) / (n + 1)));
      const idsSorted = ids ? sorted.map((d) => String(ids[d.i] ?? '')) : sorted.map(() => '');
      const psSorted = sorted.map((d) => d.p);
      return { expected, observed, ids: idsSorted, ps: psSorted, n };
    };

    const traces: any[] = [];
    let allExpectedMax = 0;
    let allObservedMax = 0;
    let ciLines: { x: number[]; lower: number[]; upper: number[] } | null = null;

    // Genomic inflation factor λ — median chi² obs / median chi² expected (= 0.4549 for 1 df).
    const lambdaFor = (psSorted: number[]): number => {
      if (psSorted.length === 0) return NaN;
      const mid = psSorted[Math.floor(psSorted.length / 2)];
      const chi2Obs = chi2InvCdf1df(mid);
      return chi2Obs / 0.4549;
    };

    let lambdaOverall = NaN;
    const lambdaByCat: { cat: string; lambda: number }[] = [];

    if (cats) {
      const allCats = Array.from(new Set(cats.map(String)));
      allCats.sort();
      const colourSource = stableColorMap(categoryUniverse ?? allCats, TAB10_PALETTE);
      const allPs: number[] = [];
      for (const c of allCats) {
        const idxs: number[] = [];
        for (let i = 0; i < cats.length; i++) {
          if (String(cats[i]) === c) idxs.push(i);
        }
        const s = buildSeries(idxs);
        if (s.n === 0) continue;
        allExpectedMax = Math.max(allExpectedMax, s.expected[s.n - 1]);
        allObservedMax = Math.max(allObservedMax, ...s.observed);
        allPs.push(...s.ps);
        lambdaByCat.push({ cat: c, lambda: lambdaFor(s.ps) });
        traces.push({
          type: 'scattergl' as const,
          mode: 'markers' as const,
          name: c,
          x: s.expected,
          y: s.observed,
          text: s.ids,
          hovertemplate:
            (s.ids[0] ? `<b>%{text}</b><br>` : '') +
            `expected: %{x:.3f}<br>observed: %{y:.3f}<extra></extra>`,
          marker: { color: colourSource.get(c), size: pointSize, opacity: 0.85 },
        });
      }
      lambdaOverall = lambdaFor(allPs.sort((a, b) => a - b));
    } else {
      const s = buildSeries(ps.map((_, i) => i));
      allExpectedMax = s.expected[s.n - 1] ?? 0;
      allObservedMax = Math.max(0, ...s.observed);
      lambdaOverall = lambdaFor(s.ps);
      traces.push({
        type: 'scattergl' as const,
        mode: 'markers' as const,
        x: s.expected,
        y: s.observed,
        text: s.ids,
        hovertemplate:
          (s.ids[0] ? `<b>%{text}</b><br>` : '') +
          `expected: %{x:.3f}<br>observed: %{y:.3f}<extra></extra>`,
        marker: { color: '#4C72B0', size: pointSize, opacity: 0.85 },
      });

      // Top-N hit labels — overlay text trace on the strongest observations.
      if (topNLabels > 0 && s.ids[0]) {
        const ranked = s.observed
          .map((o, i) => ({ o, i }))
          .sort((a, b) => b.o - a.o)
          .slice(0, topNLabels);
        traces.push({
          type: 'scatter' as const,
          mode: 'text' as const,
          x: ranked.map((r) => s.expected[r.i]),
          y: ranked.map((r) => s.observed[r.i] + (allObservedMax * 0.03)),
          text: ranked.map((r) => s.ids[r.i]),
          textposition: 'top center' as const,
          textfont: {
            size: 10,
            color: isDark ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.85)',
          },
          hoverinfo: 'skip',
          showlegend: false,
        });
      }

      if (showCi) {
        const n = s.n;
        const lower: number[] = [];
        const upper: number[] = [];
        const xs: number[] = [];
        for (let k = 1; k <= n; k++) {
          const p = k / (n + 1);
          const variance = (p * (1 - p)) / (n + 2);
          const se = Math.sqrt(variance) / (Math.log(10) * Math.max(p, 1e-12));
          const eExp = -Math.log10(p);
          xs.push(eExp);
          lower.push(Math.max(0, eExp - 1.96 * se));
          upper.push(eExp + 1.96 * se);
        }
        ciLines = { x: xs, lower, upper };
      }
    }

    if (ciLines) {
      traces.unshift(
        {
          type: 'scatter' as const,
          mode: 'lines' as const,
          x: ciLines.x,
          y: ciLines.upper,
          line: { width: 0 },
          showlegend: false,
          hoverinfo: 'skip',
        },
        {
          type: 'scatter' as const,
          mode: 'lines' as const,
          x: ciLines.x,
          y: ciLines.lower,
          fill: 'tonexty',
          fillcolor: isDark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.08)',
          line: { width: 0 },
          showlegend: false,
          hoverinfo: 'skip',
        },
      );
    }

    const upper = Math.max(allExpectedMax, allObservedMax) * 1.05;
    const annotations: any[] = [];
    if (!Number.isNaN(lambdaOverall)) {
      annotations.push({
        xref: 'paper' as const,
        yref: 'paper' as const,
        x: 0.02,
        y: 0.98,
        xanchor: 'left' as const,
        yanchor: 'top' as const,
        text: `λ = ${lambdaOverall.toFixed(3)}`,
        showarrow: false,
        font: { size: 12, color: isDark ? '#fff' : '#222' },
        bgcolor: isDark ? 'rgba(20,20,20,0.6)' : 'rgba(255,255,255,0.7)',
        bordercolor: isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.2)',
        borderwidth: 1,
        borderpad: 4,
      });
    }

    return {
      data: traces,
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 60, r: 20, t: 20, b: 50 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: '-log10(expected)' },
          range: [0, upper],
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: '-log10(observed)' },
          range: [0, upper],
        },
        shapes: showIdentity
          ? [
              {
                type: 'line' as const,
                x0: 0,
                y0: 0,
                x1: upper,
                y1: upper,
                line: { dash: 'dash', color: isDark ? '#ddd' : '#444', width: 1 },
              },
            ]
          : [],
        annotations,
        showlegend: Boolean(cats),
        autosize: true,
      },
      lambdaOverall,
      lambdaByCat,
    };
  }, [rows, config, showCi, showIdentity, pointSize, topNLabels, colorScheme, theme, categoryUniverse]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        {figure && !Number.isNaN(figure.lambdaOverall) ? (
          <Badge size="sm" color="grape" variant="light" radius="sm" fullWidth>
            λ = {figure.lambdaOverall.toFixed(3)}
          </Badge>
        ) : null}
        {figure?.lambdaByCat && figure.lambdaByCat.length > 0 ? (
          <Stack gap={2}>
            {figure.lambdaByCat.map((d) => (
              <Badge key={d.cat} size="xs" variant="light" radius="sm" fullWidth>
                {d.cat}: λ = {d.lambda.toFixed(3)}
              </Badge>
            ))}
          </Stack>
        ) : null}
        <Switch
          size="xs"
          checked={showIdentity}
          onChange={(e) => setShowIdentity(e.currentTarget.checked)}
          label="Identity line"
        />
        <Switch
          size="xs"
          checked={showCi}
          onChange={(e) => setShowCi(e.currentTarget.checked)}
          label="95% null CI band"
          disabled={Boolean(config.category_col)}
        />
        <Group gap="xs" grow>
          <NumberInput
            size="xs"
            label="Point size"
            value={pointSize}
            onChange={(v) => setPointSize(Math.max(2, Math.min(14, Number(v) || 5)))}
            min={2}
            max={14}
          />
          <NumberInput
            size="xs"
            label="Label top-N"
            description="0 = off"
            value={topNLabels}
            onChange={(v) => setTopNLabels(Math.max(0, Math.min(50, Number(v) || 0)))}
            min={0}
            max={50}
            disabled={Boolean(config.category_col) || !config.feature_id_col}
          />
        </Group>
      </Stack>
    ),
    [figure, showCi, showIdentity, pointSize, topNLabels, config.category_col, config.feature_id_col],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'QQ plot'}
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

export default QQRenderer;
