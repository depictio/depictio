import React, { useEffect, useMemo, useState } from 'react';
import { Select, Stack, Switch, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { AdvancedVizKind, fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import { coarsenBins } from './contactMapBinning';
import { applyDataTheme, applyLayoutTheme, plotlyThemeFragment } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `ContactMapConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there, and `test_advanced_viz_config_alignment`
 *  enforces it. */
interface ContactMapConfig {
  chrom1_col: string;
  start1_col: string;
  chrom2_col: string;
  start2_col: string;
  count_col: string;
  end1_col?: string | null;
  end2_col?: string | null;
  sample_col?: string | null;
  chrom?: string | null;
  log_scale?: boolean;
  colour_scale?: ColourScale;
  balance?: boolean;
  max_bins?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: ContactMapConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

// `contact_map` reads client-side as a whole grid, so the server never
// samples it (`KIND_SAMPLING_POLICY["contact_map"] == "none"`); `max_bins`
// below is this renderer's own guard on how large a matrix it draws.
const CONTACT_MAP_VIZ_KIND: AdvancedVizKind = 'contact_map';

const PLOT_STYLE = { width: '100%', height: '100%' };
const PLOT_CONFIG = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
  scrollZoom: false,
};

const DEFAULT_MAX_BINS = 500;

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const ContactMapPlot = React.memo<{
  figure: { data?: unknown[]; layout?: Record<string, unknown> };
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
}>(({ figure, isDark, theme }) => {
  const themedData = useMemo(() => applyDataTheme(figure.data, isDark, theme), [figure.data, isDark, theme]);
  const themedLayout = useMemo(
    () => applyLayoutTheme(figure.layout as any, isDark, theme),
    [figure.layout, isDark, theme],
  );
  return (
    <Plot
      data={themedData as any}
      layout={themedLayout as any}
      useResizeHandler
      style={PLOT_STYLE}
      config={PLOT_CONFIG as any}
    />
  );
});
ContactMapPlot.displayName = 'ContactMapPlot';

/**
 * Binned Hi-C style contact matrix: a symmetric heatmap of one chromosome's
 * intra-chromosomal contacts, coloured on a log scale by default. Only one
 * triangle of (bin1, bin2) needs to be present in the data: the figure
 * mirrors it across the diagonal, and a matrix above `max_bins` per side is
 * coarsened by merging adjacent bins rather than drawn at full resolution.
 */
const ContactMapRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const config = (metadata.config || {}) as ContactMapConfig;
  const isDark = colorScheme === 'dark';
  const maxBins = config.max_bins && config.max_bins > 0 ? config.max_bins : DEFAULT_MAX_BINS;

  const [logScale, setLogScale] = usePersistedVizControl<boolean>(metadata, 'log_scale', config.log_scale ?? true);
  const [colourScale, setColourScale] = usePersistedVizControl<ColourScale>(
    metadata,
    'colour_scale',
    config.colour_scale ?? 'Viridis',
  );
  const [balance, setBalance] = usePersistedVizControl<boolean>(metadata, 'balance', config.balance ?? false);
  const [chrom, setChrom] = usePersistedVizControl<string | null>(metadata, 'chrom', config.chrom ?? null);

  const requiredCols = useMemo(() => {
    const cols = [
      config.chrom1_col,
      config.start1_col,
      config.chrom2_col,
      config.start2_col,
      config.count_col,
    ].filter(Boolean) as string[];
    if (config.sample_col && !cols.includes(config.sample_col)) cols.push(config.sample_col);
    return cols;
  }, [config.chrom1_col, config.start1_col, config.chrom2_col, config.start2_col, config.count_col, config.sample_col]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 5) {
      setError('Contact map: missing data binding');
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
      vizKind: CONTACT_MAP_VIZ_KIND,
      roles: {
        chrom1: config.chrom1_col,
        start1: config.start1_col,
        chrom2: config.chrom2_col,
        start2: config.start2_col,
        count: config.count_col,
      },
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

  // Chromosomes present in the fetched frame, for the selector. The first one
  // seen (row order) is the default when no chrom is chosen yet.
  const chromOptions = useMemo(() => {
    if (!rows) return [] as string[];
    const c1 = (rows[config.chrom1_col] || []) as unknown[];
    const seen = new Set<string>();
    const ordered: string[] = [];
    for (const v of c1) {
      if (v === null || v === undefined) continue;
      const s = String(v);
      if (!seen.has(s)) {
        seen.add(s);
        ordered.push(s);
      }
    }
    return ordered;
  }, [rows, config.chrom1_col]);

  const effectiveChrom = chrom && chromOptions.includes(chrom) ? chrom : (chromOptions[0] ?? null);

  const figure = useMemo(() => {
    if (!rows || !effectiveChrom) return null;
    const c1 = (rows[config.chrom1_col] || []) as unknown[];
    const s1 = (rows[config.start1_col] || []) as unknown[];
    const c2 = (rows[config.chrom2_col] || []) as unknown[];
    const s2 = (rows[config.start2_col] || []) as unknown[];
    const counts = (rows[config.count_col] || []) as unknown[];

    const startSet = new Set<number>();
    type Cell = { a: number; b: number; count: number };
    const cells: Cell[] = [];
    const n = Math.min(c1.length, s1.length, c2.length, s2.length, counts.length);
    for (let i = 0; i < n; i++) {
      if (String(c1[i]) !== effectiveChrom || String(c2[i]) !== effectiveChrom) continue;
      const a = num(s1[i]);
      const b = num(s2[i]);
      const count = num(counts[i]);
      if (a === null || b === null || count === null) continue;
      startSet.add(a);
      startSet.add(b);
      cells.push({ a, b, count });
    }
    if (cells.length === 0) return null;

    const sortedStarts = Array.from(startSet).sort((x, y) => x - y);
    const { buckets, index } = coarsenBins(sortedStarts, maxBins);
    const size = buckets.length;

    const z: (number | null)[][] = Array.from({ length: size }, () => new Array(size).fill(0));
    const rawSum: number[][] = Array.from({ length: size }, () => new Array(size).fill(0));
    for (const { a, b, count } of cells) {
      const ia = index.get(a)!;
      const ib = index.get(b)!;
      // Coarsened bins accumulate; the raw triangle is mirrored below.
      rawSum[ia][ib] += count;
      if (ia !== ib) rawSum[ib][ia] += count;
    }

    let matrix = rawSum;
    if (balance) {
      // Single-pass bias correction (not iterative ICE): divide each cell by
      // the geometric mean of its row and column sums, so high-coverage bins
      // stop dominating the colour scale. Good enough for a quick-look view;
      // a proper ICE balance belongs upstream of the DC.
      const rowSums = rawSum.map((r) => r.reduce((a, v) => a + v, 0));
      matrix = rawSum.map((r, i) =>
        r.map((v, j) => {
          const denom = Math.sqrt((rowSums[i] || 1) * (rowSums[j] || 1));
          return denom > 0 ? v / denom : 0;
        }),
      );
    }

    for (let i = 0; i < size; i++) {
      for (let j = 0; j < size; j++) {
        // log10 of positive values only: balanced (ICE) contacts sit far below 1, where
        // log1p flattens everything to ~0. Empty cells stay blank instead of -Infinity.
        const v = matrix[i][j];
        z[i][j] = logScale ? (v > 0 ? Math.log10(v) : null) : v;
      }
    }

    const labels = buckets.map((b) => `${effectiveChrom}:${Math.round(b / 1000)}kb`);

    return {
      data: [
        {
          type: 'heatmap' as const,
          x: labels,
          y: labels,
          z,
          colorscale: colourScale,
          showscale: true,
          colorbar: { thickness: 10, len: 0.75, title: { text: logScale ? 'log10(value)' : 'value' } },
          hovertemplate: '%{x} × %{y}<br>value: %{z:.3g}<extra></extra>',
        },
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 70, r: 20, t: 12, b: 70 },
        xaxis: { tickangle: -45, automargin: true, showgrid: false },
        yaxis: { automargin: true, showgrid: false, autorange: 'reversed' as const },
        autosize: true,
      },
    };
  }, [rows, effectiveChrom, config, maxBins, balance, logScale, colourScale, isDark, theme]);

  const controls = (
    <Stack gap="xs">
      {chromOptions.length > 0 ? (
        <Select
          size="xs"
          label="Chromosome"
          value={effectiveChrom}
          onChange={(v) => setChrom(v)}
          data={chromOptions}
          allowDeselect={false}
        />
      ) : null}
      <Select
        size="xs"
        label="Colour scale"
        value={colourScale}
        onChange={(v) => setColourScale((v as ColourScale) || 'Viridis')}
        data={COLOUR_SCALES as unknown as string[]}
        allowDeselect={false}
      />
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Display
        </Text>
        <Switch size="xs" checked={logScale} onChange={(e) => setLogScale(e.currentTarget.checked)} label="Log colour scale" />
        <Switch
          size="xs"
          checked={balance}
          onChange={(e) => setBalance(e.currentTarget.checked)}
          label="Row/column balance"
        />
      </Stack>
    </Stack>
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Contact map'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? <ContactMapPlot figure={figure} isDark={isDark} theme={theme} /> : null}
    </AdvancedVizFrame>
  );
};

export default ContactMapRenderer;
