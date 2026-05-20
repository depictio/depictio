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
 */
import React from 'react';
import { Center, Text } from '@mantine/core';
import { DepictioCard } from 'depictio-components';
import { useBuilderStore } from '../store/useBuilderStore';
import PreviewPanel from '../shared/PreviewPanel';
import { autoCardTitle } from './cardTitle';
import { SecondaryMetrics, type SecondaryLayout } from 'depictio-react-core';

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
  if (!aggregations || aggregations.length === 0) return [];

  // Box-plot needs a compound payload — synthesise one from whatever specs
  // we have. Quartiles aren't precomputed; estimate them so the shape is
  // visible. The saved card pulls real q1/q3/outliers from the server.
  if (layout === 'box_plot' && aggregations.includes('box_plot_stats')) {
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

  // Vertical / compact: just pull scalar values from specs by aggregation name.
  return aggregations
    .map((agg) => ({ name: agg, value: pickNum(specs, agg) }))
    .filter((r) => r.value !== undefined);
}

const CardPreview: React.FC = () => {
  const config = useBuilderStore((s) => s.config) as {
    title?: string;
    column_name?: string;
    column_type?: string;
    aggregation?: string;
    aggregations?: string[] | null;
    secondary_layout?: SecondaryLayout;
    background_color?: string;
    title_color?: string;
    icon_name?: string;
    title_font_size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  };
  const cols = useBuilderStore((s) => s.cols);

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

  const layout: SecondaryLayout = config.secondary_layout ?? 'vertical';
  const secondaryRows = buildPreviewRows(
    col?.specs as Specs,
    config.aggregations,
    layout,
  );
  const showApproxHint =
    layout === 'box_plot' && secondaryRows.length > 0;

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
              secondaryRows.length > 0 ? (
                <SecondaryMetrics rows={secondaryRows} layout={layout} />
              ) : undefined
            }
          />
          {showApproxHint ? (
            <Text size="10" c="dimmed" ta="center" mt={2} style={{ fontSize: 10 }}>
              Preview Q1 / Q3 / outliers are estimated; the saved card recomputes
              from the live data.
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
