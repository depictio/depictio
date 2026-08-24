import React from 'react';

import AttritionMetric from './metrics/Attrition';
import BoxPlotMetric from './metrics/BoxPlot';
import CompletenessMetric from './metrics/Completeness';
import CompositionMetric from './metrics/Composition';
import ConcentrationMetric from './metrics/Concentration';
import CoverageMetric from './metrics/Coverage';
import DonutMetric from './metrics/Donut';
import GaugeMetric from './metrics/Gauge';
import HistogramMetric from './metrics/Histogram';
import StatList from './metrics/StatList';
import ThresholdMetric from './metrics/Threshold';
import TopNMetric from './metrics/TopN';
import TrendMetric from './metrics/Trend';
import UniquenessMetric from './metrics/Uniqueness';
import {
  isBreakdownPayload,
  isNumericLayout,
  type AttritionPayload,
  type BreakdownPayload,
  type CompletenessPayload,
  type HistogramPayload,
  type MetricRow,
  type SecondaryLayout,
  type ThresholdPayload,
  type TrendPayload,
  type UniquenessPayload,
} from './metrics/types';

export {
  BREAKDOWN_LAYOUTS,
  NUMERIC_LAYOUTS,
  STAT_LIST_LAYOUTS,
  isBreakdownLayout,
  isNumericLayout,
} from './metrics/types';
export type {
  AttritionPayload,
  BreakdownPayload,
  CompletenessPayload,
  HistogramPayload,
  MetricRow,
  SecondaryLayout,
  ThresholdPayload,
  TrendPayload,
  UniquenessPayload,
} from './metrics/types';

interface SecondaryMetricsProps {
  rows: MetricRow[];
  layout?: SecondaryLayout;
  /** Accent colour for the strip's bars, arcs and box — the card's icon or
   *  title colour. Falls back to teal. */
  color?: string | null;
  /** Numerator for ``coverage`` / ``gauge`` — the card's hero value. */
  coverageValue?: number | null;
  /** Denominator for ``coverage`` / ``gauge`` — e.g. 44 samples / 11 ORFs. */
  coverageMax?: number | null;
}

/** Pull one server-computed payload out of the rows array. The strips dispatch
 *  on the synthetic row *name*, not on the card's aggregation order. */
function payloadFor(rows: MetricRow[], key: string): unknown {
  return rows.find((r) => r.name === key)?.value;
}

/**
 * The strip under a card's hero value.
 *
 * Every layout is one component under ``./metrics``, and they all draw with the
 * same primitives (``./metrics/tokens``) so a dashboard mixing several card
 * layouts still reads as one product. This file only decides which one runs and
 * whether its payload is there.
 *
 * A missing payload always renders nothing rather than an empty chart: the
 * server returns null when a layout's config is incomplete or the data cannot
 * support it (a constant column has no histogram), and an all-zero chart would
 * read as a real answer.
 */
const SecondaryMetrics: React.FC<SecondaryMetricsProps> = ({
  rows,
  layout = 'vertical',
  color,
  coverageValue,
  coverageMax,
}) => {
  // Categorical layouts — all four read the same ``__breakdown__`` payload and
  // differ only in how they draw it.
  const breakdown = rows.find(
    (r) => r.name === '__breakdown__' && isBreakdownPayload(r.value),
  )?.value as BreakdownPayload | undefined;
  if (layout === 'top_n' || layout === 'concentration' || layout === 'composition' || layout === 'donut') {
    if (!breakdown) return null;
    if (layout === 'top_n') return <TopNMetric payload={breakdown} color={color} />;
    if (layout === 'concentration') {
      return <ConcentrationMetric payload={breakdown} color={color} />;
    }
    if (layout === 'composition') {
      return <CompositionMetric payload={breakdown} color={color} />;
    }
    return <DonutMetric payload={breakdown} color={color} />;
  }

  // Numeric / QC layouts — each reads its own ``__<layout>__`` key.
  if (isNumericLayout(layout)) {
    const payload = payloadFor(rows, `__${layout}__`);
    if (!payload || typeof payload !== 'object') return null;
    switch (layout) {
      case 'histogram':
        return <HistogramMetric payload={payload as HistogramPayload} color={color} />;
      case 'threshold':
        return <ThresholdMetric payload={payload as ThresholdPayload} />;
      case 'completeness':
        return <CompletenessMetric payload={payload as CompletenessPayload} color={color} />;
      case 'uniqueness':
        return <UniquenessMetric payload={payload as UniquenessPayload} color={color} />;
      case 'trend':
        return <TrendMetric payload={payload as TrendPayload} color={color} />;
      default:
        return <AttritionMetric payload={payload as AttritionPayload} color={color} />;
    }
  }

  // Value-against-a-maximum layouts read the card's hero value directly, so
  // they need no secondary aggregation at all.
  if (layout === 'coverage' || layout === 'gauge') {
    const usable =
      typeof coverageValue === 'number' &&
      typeof coverageMax === 'number' &&
      coverageMax > 0;
    if (usable) {
      const Metric = layout === 'gauge' ? GaugeMetric : CoverageMetric;
      return <Metric value={coverageValue} max={coverageMax} color={color} />;
    }
    // Fall through to the stat list rather than draw an always-zero bar.
  }

  if (layout === 'box_plot') {
    if (!rows.length) return null;
    return <BoxPlotMetric rows={rows} color={color} />;
  }

  if (!rows.length) return null;
  return (
    <StatList
      rows={rows}
      variant={layout === 'compact' || layout === 'grid' ? layout : 'vertical'}
    />
  );
};

export default SecondaryMetrics;
