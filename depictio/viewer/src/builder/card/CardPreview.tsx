/**
 * Live preview for the Card builder. Uses the same `DepictioCard` renderer
 * the dashboard grid uses, so what the user sees here is exactly what gets
 * rendered after save. Sized to a small fixed footprint mirroring a
 * one-column grid cell from the dashboard (≈ 280px × 140px).
 *
 * Multi-metric preview: when the form picks vertical / compact / box_plot,
 * we render the same `SecondaryMetrics` strip the dashboard uses, fed by
 * values pulled from the precomputed `col.specs`. Quartiles for box_plot
 * are not precomputed (specs only carries min/max/median/mean) — we
 * synthesise rough Q1/Q3 + lower/upper whiskers so the user sees the
 * box-plot shape; the actual saved card recomputes from the live data.
 *
 * The categorical layouts (top_n / concentration / composition / donut) do
 * *not* estimate: they fetch the real breakdown from
 * `/deltatables/breakdown`, which runs the same helper `bulk_compute_cards`
 * runs for the saved card. Previously this preview invented `Bucket 1/2/3`
 * split evenly at 33/33/34, so a perfectly good card looked broken in the
 * builder and then rendered completely different numbers once saved.
 */
import React, { useEffect, useState } from 'react';
import { Center, Text } from '@mantine/core';
import { DepictioCard } from 'depictio-components';
import { useBuilderStore } from '../store/useBuilderStore';
import PreviewPanel from '../shared/PreviewPanel';
import { autoCardTitle } from './cardTitle';
import {
  SecondaryMetrics,
  fetchBreakdown,
  fetchCardMetric,
  isBreakdownLayout,
  isNumericLayout,
  type BreakdownPayloadDTO,
  type SecondaryLayout,
} from 'depictio-react-core';

type Specs = Record<string, unknown> | undefined;

const pickNum = (specs: Specs, key: string): number | undefined => {
  const v = specs?.[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
};

/** Build the rows array `SecondaryMetrics` expects, from the precomputed
 *  column specs + the chosen layout. */
function buildPreviewRows(
  specs: Specs,
  aggregations: string[] | null | undefined,
  layout: SecondaryLayout,
): { name: string; value: unknown }[] {
  // Box-plot needs a compound payload — synthesise one from whatever specs
  // we have. Quartiles aren't precomputed; estimate them so the shape is
  // visible. The saved card pulls real q1/q3/outliers from the server.
  if (
    layout === 'box_plot' &&
    aggregations &&
    aggregations.includes('box_plot_stats')
  ) {
    const min = pickNum(specs, 'min');
    const max = pickNum(specs, 'max');
    const median =
      pickNum(specs, 'median') ?? pickNum(specs, 'average') ?? pickNum(specs, 'mean');
    const mean = pickNum(specs, 'average') ?? pickNum(specs, 'mean') ?? median;
    if (min === undefined || max === undefined || median === undefined || mean === undefined) {
      return [];
    }
    const range = max - min;
    // Rough estimate: pull quartiles 25% in from each side. Visually
    // honest because the user sees the median+mean positions for real,
    // and the box-plot shape only locks in once they save.
    const q1 = min + 0.25 * range;
    const q3 = max - 0.25 * range;
    return [
      {
        name: 'box_plot_stats',
        value: {
          min,
          max,
          q1,
          q3,
          median,
          mean,
          lower_whisker: min,
          upper_whisker: max,
          outliers: [] as number[],
          outlier_count: 0,
        },
      },
    ];
  }

  if (!aggregations || aggregations.length === 0) return [];

  // Vertical / compact: just pull scalar values from specs by aggregation name.
  return aggregations
    .map((agg) => ({ name: agg, value: pickNum(specs, agg) }))
    .filter((r) => r.value !== undefined);
}

/** Fetch the *real* ``__breakdown__`` payload for the categorical layouts.
 *
 *  The server runs the same helper ``bulk_compute_cards`` runs for the saved
 *  card, so the preview and the dashboard agree by construction. Nothing is
 *  fetched until the user has actually picked a breakdown column, so an
 *  incomplete form shows no strip rather than a fake one.
 *
 *  In-flight requests are aborted on dependency change: flipping through
 *  layouts and columns fires one request per change, and a slow earlier
 *  response must not overwrite a newer one. */
function useBreakdownPreview(
  dcId: string | null,
  column: string | undefined,
  breakdownCol: string | null | undefined,
  aggregation: string | undefined,
  topNCount: number,
  enabled: boolean,
): { payload: BreakdownPayloadDTO | null; loading: boolean; error: string | null } {
  const [payload, setPayload] = useState<BreakdownPayloadDTO | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !dcId || !column || !breakdownCol) {
      setPayload(null);
      setError(null);
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    fetchBreakdown(dcId, column, breakdownCol, aggregation || 'count', topNCount, ctrl.signal)
      .then((res) => {
        setPayload(res);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name === 'AbortError') return;
        setPayload(null);
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [enabled, dcId, column, breakdownCol, aggregation, topNCount]);

  return { payload, loading, error };
}

/** Fetch the server-computed payload for a numeric / QC layout.
 *
 *  Same contract as the breakdown hook above: aborts in-flight requests on
 *  dependency change, and resolves to ``null`` when the server declines
 *  (incomplete config, or data that cannot support the layout). ``configKey``
 *  is the serialised layout config, so editing a threshold refetches while an
 *  unrelated styling change does not. */
function useNumericPreview(
  dcId: string | null,
  column: string | undefined,
  layout: SecondaryLayout,
  layoutConfig: Record<string, unknown>,
  enabled: boolean,
): { payload: Record<string, unknown> | null; loading: boolean; error: string | null } {
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const configKey = JSON.stringify(layoutConfig);

  useEffect(() => {
    if (!enabled || !dcId || !column) {
      setPayload(null);
      setError(null);
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    fetchCardMetric(dcId, layout, column, JSON.parse(configKey), ctrl.signal)
      .then((res) => {
        setPayload(res);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name === 'AbortError') return;
        setPayload(null);
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [enabled, dcId, column, layout, configKey]);

  return { payload, loading, error };
}

const CardPreview: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    title?: string;
    column_name?: string;
    column_type?: string;
    aggregation?: string;
    aggregations?: string[] | null;
    secondary_layout?: SecondaryLayout;
    breakdown_col?: string | null;
    coverage_max?: number | null;
    top_n_count?: number;
    threshold_value?: number | null;
    threshold_direction?: 'min' | 'max';
    threshold_warn?: number | null;
    attrition_cols?: string[] | null;
    background_color?: string;
    title_color?: string;
    icon_name?: string;
    title_font_size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  };
  const cols = useBuilderStore((s) => s.cols);
  const dcId = useBuilderStore((s) => s.dcId);

  const layout: SecondaryLayout = config.secondary_layout ?? 'vertical';
  // Hooks must run unconditionally, so this sits above the early return for an
  // incomplete form. ``enabled`` carries the gating instead.
  const {
    payload: breakdownPayload,
    loading: breakdownLoading,
    error: breakdownError,
  } = useBreakdownPreview(
    dcId,
    config.column_name,
    config.breakdown_col,
    config.aggregation,
    config.top_n_count ?? 3,
    isBreakdownLayout(layout),
  );

  const {
    payload: numericPayload,
    loading: numericLoading,
    error: numericError,
  } = useNumericPreview(
    dcId,
    config.column_name,
    layout,
    {
      aggregation: config.aggregation,
      threshold_value: config.threshold_value ?? null,
      threshold_direction: config.threshold_direction ?? 'min',
      threshold_warn: config.threshold_warn ?? null,
      attrition_cols: config.attrition_cols ?? [],
    },
    isNumericLayout(layout),
  );

  if (!config.column_name || !config.aggregation) {
    return (
      <PreviewPanel
        empty
        emptyMessage="Pick a column and aggregation to preview..."
        minHeight={200}
      />
    );
  }

  const col = cols.find((c) => c.name === config.column_name);
  const rawValue = col?.specs?.[config.aggregation as string];
  const value = formatValue(rawValue);

  const effectiveTitle =
    (config.title && config.title.trim()) ||
    autoCardTitle(
      config.aggregation,
      config.column_name,
      config.column_type,
    );

  const secondaryRows = buildPreviewRows(
    col?.specs as Specs,
    config.aggregations,
    layout,
  );

  // Categorical layouts read the server-computed payload; coverage passes the
  // hero value + coverage_max straight to the strip. Both render no strip at
  // all until the required config (breakdown_col / coverage_max) is filled in.
  let stripRows: { name: string; value: unknown }[] = secondaryRows;
  let coverageValue: number | null = null;
  let coverageMax: number | null = null;
  if (isBreakdownLayout(layout)) {
    stripRows = breakdownPayload
      ? [{ name: '__breakdown__', value: breakdownPayload }]
      : [];
  } else if (isNumericLayout(layout)) {
    stripRows = numericPayload ? [{ name: `__${layout}__`, value: numericPayload }] : [];
  } else if (layout === 'coverage') {
    if (
      typeof config.coverage_max === 'number' &&
      config.coverage_max > 0 &&
      typeof rawValue === 'number' &&
      Number.isFinite(rawValue)
    ) {
      coverageValue = rawValue;
      coverageMax = config.coverage_max;
    }
  }

  const showStrip =
    stripRows.length > 0 ||
    (layout === 'coverage' &&
      typeof coverageMax === 'number' &&
      typeof coverageValue === 'number');
  // Only box_plot still estimates (quartiles aren't precomputed). The
  // categorical strips now show server-computed numbers, so claiming they are
  // estimates would be the inaccurate statement.
  const showApproxHint = layout === 'box_plot' && secondaryRows.length > 0;
  const breakdownHint = !isBreakdownLayout(layout)
    ? null
    : breakdownError
      ? `Breakdown unavailable: ${breakdownError}`
      : breakdownLoading
        ? 'Computing breakdown from the live data…'
        : !config.breakdown_col
          ? 'Pick a breakdown column to see the distribution.'
          : null;

  // Why a numeric layout is showing nothing. The server returns null for data
  // that genuinely cannot support the layout, and saying so beats an empty
  // panel the user reads as a bug.
  const numericHint = !isNumericLayout(layout)
    ? null
    : numericError
      ? `Preview unavailable: ${numericError}`
      : numericLoading
        ? 'Computing from the live data…'
        : layout === 'threshold' && config.threshold_value == null
          ? 'Set a threshold value to see the pass/fail split.'
          : layout === 'attrition' && (config.attrition_cols?.length ?? 0) < 1
            ? 'Add at least one further stage column to see the funnel.'
            : !numericPayload
              ? layout === 'histogram'
                ? 'No histogram: this column has no spread (every value is identical).'
                : 'No data available for this layout.'
              : null;

  return (
    <PreviewPanel minHeight={200}>
      <Center style={{ width: '100%', padding: '0.5rem' }}>
        <div style={{ width: 280, maxWidth: '100%' }}>
          <DepictioCard
            title={effectiveTitle}
            value={value}
            icon_name={config.icon_name || 'mdi:chart-line'}
            background_color={config.background_color}
            title_color={config.title_color}
            title_font_size={config.title_font_size ?? 'md'}
            value_font_size="xl"
            secondaryStrip={
              showStrip ? (
                <SecondaryMetrics
                  rows={stripRows}
                  layout={layout}
                  coverageValue={coverageValue}
                  coverageMax={coverageMax}
                />
              ) : undefined
            }
          />
          {showApproxHint ? (
            <Text size="10" c="dimmed" ta="center" mt={2} style={{ fontSize: 10 }}>
              Preview values are estimated; the saved card recomputes from the
              live data.
            </Text>
          ) : null}
          {breakdownHint || numericHint ? (
            <Text size="10" c="dimmed" ta="center" mt={2} style={{ fontSize: 10 }}>
              {breakdownHint || numericHint}
            </Text>
          ) : null}
        </div>
      </Center>
    </PreviewPanel>
  );
};

function formatValue(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return '—';
    if (Number.isInteger(v)) return v.toLocaleString('en-US');
    return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  return String(v);
}

export default CardPreview;
