/**
 * JourneyFunnel — pin-based funnel UI.
 *
 * A journey is a declarative, tab-ordered list of pinned filter steps.
 * This component renders two surfaces:
 *
 *   1. Inline strip (filter rail) — read-only one-liner showing the
 *      current chain across the primary DC. Hidden when `controlledOpen`
 *      is set so the modal can be driven from outside.
 *   2. Modal — the canonical surface where everything funnel-related
 *      happens:
 *      - Sticky summary line (initial → final → biggest drop)
 *      - Funnel-switcher menu (switch active / create / rename / delete /
 *        toggle default) — Settings drawer keeps only the master toggle.
 *      - Chart tab: Plotly funnel + cascade table + view-mode picker
 *        (Rows / Unique / % survived / Step drop % / Abs drop). Cascade
 *        cells where the step doesn't link to a DC render `—` dimmed so
 *        the no-op semantics are explicit instead of looking like the
 *        filter matched everything.
 *      - Steps tab: per-tab list with ↑ / ↓ / × actions and an inline
 *        metric value matching the chart's view mode. Clicking a step
 *        opens a detail panel with per-DC before/after numbers.
 *
 * The caller (App.tsx) resolves each step's current value into a
 * `FunnelStepInput`, owns the journey store, and provides the action
 * handlers — this component is presentational and stateless w.r.t.
 * persistence.
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Divider,
  Drawer,
  Group,
  LoadingOverlay,
  Loader,
  Menu,
  Modal,
  Paper,
  ScrollArea,
  SegmentedControl,
  Select,
  Skeleton,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
  useMantineColorScheme,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import Plot from 'react-plotly.js';

import { AgGridReact } from 'ag-grid-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import type { ColDef, RowClassParams } from 'ag-grid-community';

import {
  computeFunnel,
  fetchJourneyPreview,
  type FunnelMetric,
  type FunnelResponse,
  type FunnelStep,
  type FunnelStepInput,
  type FunnelTargetDC,
  type Journey,
  type JourneyPreviewResponse,
} from '../../api';

// Long enough that rapid MultiSelect keystrokes (typical: 4-5 picks in
// quick succession) collapse to a single backend call, not five. The
// funnel is a derived view — staleness during the typing window is
// acceptable; back-pressuring the API is not.
const FETCH_DEBOUNCE_MS = 800;

/** View modes drive how raw funnel values are displayed. Backend metrics
 *  ('rows', 'nunique') are fetched server-side; '% survived', 'step drop %',
 *  and 'abs drop' are client-side projections of the raw vector. */
type ViewMode = 'rows' | 'unique' | 'pctInitial' | 'pctStep' | 'absDrop';

const VIEW_MODE_OPTIONS: { label: string; value: ViewMode }[] = [
  { label: 'Rows', value: 'rows' },
  { label: 'Unique', value: 'unique' },
  { label: '% survived', value: 'pctInitial' },
  { label: 'Step drop %', value: 'pctStep' },
  { label: 'Abs drop', value: 'absDrop' },
];

/** Display modes shape how the multi-DC response is rendered. All three
 *  share the same backend `FunnelResponse`; only the visual projection
 *  differs. Lets the user compare which model fits their analysis without
 *  re-fetching.
 *  - 'primary': one Plotly funnel for a user-picked DC, plus cascade table.
 *  - 'multiples': one mini-funnel per linked DC, no cascade.
 *  - 'cascade': one chart whose bars walk the journey's source DCs (each
 *    bar pulls from that step's source DC), no "All rows" anchor. */
type DisplayMode = 'primary' | 'multiples' | 'cascade';

const DISPLAY_MODE_OPTIONS: { label: string; value: DisplayMode }[] = [
  { label: 'Primary DC', value: 'primary' },
  { label: 'Per DC', value: 'multiples' },
  { label: 'Step source', value: 'cascade' },
];

function viewModeBackendMetric(mode: ViewMode): FunnelMetric {
  return mode === 'unique' ? 'nunique' : 'rows';
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function formatPercent(n: number): string {
  if (!Number.isFinite(n)) return '—';
  const sign = n < 0 ? '−' : '';
  const abs = Math.abs(n);
  return `${sign}${abs >= 10 ? abs.toFixed(0) : abs.toFixed(1)}%`;
}

/** Project a raw counts vector onto the chosen display mode.
 *  Returns `(value, label)` pairs to feed the chart / table / step rows. */
function deriveDisplay(raw: number[] | null, mode: ViewMode): {
  values: number[];
  formatted: string[];
} {
  if (!raw || raw.length === 0) return { values: [], formatted: [] };
  switch (mode) {
    case 'rows':
    case 'unique':
      return {
        values: raw.slice(),
        formatted: raw.map(formatCount),
      };
    case 'pctInitial': {
      const base = raw[0] || 0;
      const values = raw.map((v) => (base > 0 ? (v / base) * 100 : 0));
      return { values, formatted: values.map(formatPercent) };
    }
    case 'pctStep': {
      // First slot has no previous step, so we anchor it at 0%.
      const values = raw.map((v, i) => {
        if (i === 0) return 0;
        const prev = raw[i - 1];
        if (!prev) return 0;
        return ((v - prev) / prev) * 100;
      });
      return { values, formatted: values.map(formatPercent) };
    }
    case 'absDrop': {
      const values = raw.map((v, i) => (i === 0 ? 0 : (raw[i - 1] ?? 0) - v));
      return {
        values,
        formatted: values.map((v, i) => (i === 0 ? '—' : `−${formatCount(v)}`)),
      };
    }
  }
}

function unitFor(mode: ViewMode, metricColumn: string | null | undefined): string {
  switch (mode) {
    case 'rows':
      return 'rows';
    case 'unique':
      return metricColumn ? `unique ${metricColumn}` : 'unique values';
    case 'pctInitial':
      return 'of initial';
    case 'pctStep':
      return 'step Δ';
    case 'absDrop':
      return 'rows dropped';
  }
}

function dcLabel(dcId: string, dcTagsById?: Record<string, string>): string {
  return dcTagsById?.[dcId] || dcId.slice(-6);
}

/** Map a retention ratio (0..1) to an HSL color: green at 1.0 (full
 *  retention), amber at 0.5, red at 0.0. Out-of-range values clamp. Used
 *  to color each funnel bar so the user can read at a glance which steps
 *  cut deeply. */
function retentionColor(ratio: number): string {
  const r = Math.min(1, Math.max(0, ratio));
  // 0.0 → hue 0 (red); 1.0 → hue 145 (green/teal). Saturation/lightness
  // kept consistent so the gradient reads as a single ramp.
  const hue = 145 * r;
  return `hsl(${hue.toFixed(0)}, 65%, 50%)`;
}

/** Per-bar colors for a funnel — each bar shaded by its ratio to bar 0.
 *  When the first bar is 0 (empty funnel), all bars are neutral grey. */
function retentionColors(values: number[]): string[] {
  if (values.length === 0) return [];
  const base = values[0];
  if (!base || base <= 0) return values.map(() => '#adb5bd');
  return values.map((v) => retentionColor(v / base));
}

// ─────────────────────────────────────────────────────────────────────────────
// Data fetching
// ─────────────────────────────────────────────────────────────────────────────

function useFunnelCounts(
  parentDashboardId: string,
  stepInputs: FunnelStepInput[],
  targetDcs: FunnelTargetDC[],
  refreshTick: number | undefined,
  metric: FunnelMetric,
  metricColumn: string | null,
): { data: FunnelResponse | null; loading: boolean } {
  const [data, setData] = useState<FunnelResponse | null>(null);
  const [loading, setLoading] = useState(false);

  // nunique requires a column; without one we don't bother round-tripping.
  const skip = metric === 'nunique' && !metricColumn;

  useEffect(() => {
    // No targets OR no steps OR skip-flagged metric ⇒ nothing to compute.
    // Without the no-steps guard we'd fire a funnel call returning only
    // the unfiltered baseline — pointless work that still hits mongo +
    // S3 for each target DC on every filter keystroke.
    if (targetDcs.length === 0 || stepInputs.length === 0 || skip) {
      // Clear stale numbers from a prior journey/tab — without this, a
      // journey switch that ends up with zero targets leaves the previous
      // response on screen and looks like the funnel isn't updating.
      setData(null);
      return;
    }
    // Guard against stale responses overwriting a fresher one when the user
    // toggles modes / edits steps in quick succession. Without this, an
    // older in-flight request resolving after a newer one would clobber the
    // visible numbers.
    let cancelled = false;
    const handle = setTimeout(() => {
      setLoading(true);
      computeFunnel(parentDashboardId, stepInputs, targetDcs, {
        metric,
        metricColumn,
      })
        .then((res) => {
          if (cancelled) return;
          setData(res);
        })
        .catch((err) => {
          if (cancelled) return;
          console.warn('JourneyFunnel: compute failed:', err);
          setData(null);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, FETCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [
    parentDashboardId,
    JSON.stringify(stepInputs),
    JSON.stringify(targetDcs),
    refreshTick,
    metric,
    metricColumn,
    skip,
  ]);

  return { data, loading };
}

// ─────────────────────────────────────────────────────────────────────────────
// Inline strip — always visible, one line
// ─────────────────────────────────────────────────────────────────────────────

interface InlineStripProps {
  primaryDcId: string | null;
  counts: number[] | null;
  loading: boolean;
  hasSteps: boolean;
  linkedCount: number;
  dcTagsById?: Record<string, string>;
  journeyName: string | null;
  onOpen: () => void;
}

const InlineStrip: React.FC<InlineStripProps> = ({
  primaryDcId,
  counts,
  loading,
  hasSteps,
  linkedCount,
  dcTagsById,
  journeyName,
  onOpen,
}) => {
  if (!primaryDcId) return null;

  if (!hasSteps) {
    return (
      <UnstyledButton onClick={onOpen} style={{ width: '100%' }}>
        <Group gap={6} wrap="nowrap" align="center">
          <Icon icon="tabler:filter-cog" width={14} color="var(--mantine-color-dimmed)" />
          <Text size="xs" c="dimmed" fw={500} style={{ flex: 1 }}>
            {journeyName ? `${journeyName} · no steps yet` : 'Pin filters to build a funnel'}
          </Text>
          <Icon icon="tabler:chart-bar" width={12} color="var(--mantine-color-blue-6)" />
        </Group>
      </UnstyledButton>
    );
  }

  if (loading && !counts) {
    return <Skeleton height={16} radius="sm" />;
  }
  if (!counts || counts.length === 0) return null;

  const primaryTag = dcLabel(primaryDcId, dcTagsById);
  return (
    <UnstyledButton onClick={onOpen} style={{ width: '100%' }}>
      <Group gap={6} wrap="nowrap" align="center">
        {journeyName && (
          <Tooltip label={`Journey: ${journeyName}`} withArrow>
            <Icon icon="tabler:route" width={12} color="var(--mantine-color-blue-7)" />
          </Tooltip>
        )}
        <Text size="xs" fw={600} c="dimmed" style={{ whiteSpace: 'nowrap' }}>
          {primaryTag}:
        </Text>
        <Group gap={4} wrap="nowrap" align="center" style={{ flex: 1, minWidth: 0 }}>
          {counts.map((n, idx) => (
            <React.Fragment key={idx}>
              {idx > 0 && (
                <Icon
                  icon="tabler:chevron-right"
                  width={10}
                  color="var(--mantine-color-dimmed)"
                />
              )}
              <Text
                size="xs"
                fw={idx === counts.length - 1 ? 700 : 500}
                c={idx === counts.length - 1 ? 'blue.7' : 'dimmed'}
                style={{ fontVariantNumeric: 'tabular-nums' }}
              >
                {formatCount(n)}
              </Text>
            </React.Fragment>
          ))}
        </Group>
        {linkedCount > 0 && (
          <Tooltip
            label={`+${linkedCount} linked data collection${linkedCount > 1 ? 's' : ''}`}
            withArrow
          >
            <Text size="xs" c="dimmed" fw={500}>
              +{linkedCount}
            </Text>
          </Tooltip>
        )}
        {loading ? (
          <Tooltip label="Recomputing…" withArrow>
            <Loader size={12} color="blue" />
          </Tooltip>
        ) : (
          <Icon icon="tabler:chart-bar" width={12} color="var(--mantine-color-blue-6)" />
        )}
      </Group>
    </UnstyledButton>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Plotly funnel chart — one bar per step
// ─────────────────────────────────────────────────────────────────────────────

interface FunnelChartProps {
  labels: string[];
  values: number[];
  formatted: string[];
  unit: string;
  height?: number;
  /** Optional explicit per-bar colors. When omitted, FunnelChart derives
   *  them from `values` (retention ratio vs the first bar). */
  colors?: string[];
}

// Static Plot props — keep references stable so react-plotly.js doesn't
// trigger a full re-layout each parent render. Only `data` (which is
// data-derived) and `layout.height` (which is steps-derived) change.
const PLOT_CONFIG = { displayModeBar: false, responsive: true } as const;
const PLOT_STYLE = { width: '100%' } as const;

const FunnelChart: React.FC<FunnelChartProps> = React.memo(
  ({ labels, values, formatted, unit, height = 240, colors }) => {
    const barColors = useMemo(
      () => colors ?? retentionColors(values),
      [colors, values],
    );
    const data = useMemo(
      () => [
        {
          type: 'funnel',
          y: labels,
          x: values,
          text: formatted,
          textinfo: 'text' as Plotly.PlotData['textinfo'],
          textposition: 'inside',
          marker: { color: barColors },
          connector: { line: { color: 'rgba(120, 120, 120, 0.25)', width: 1 } },
          hovertemplate: `<b>%{y}</b><br>%{x:,.2f} ${unit}<extra></extra>`,
        } as Plotly.Data,
      ],
      [labels, values, formatted, unit, barColors],
    );
    const layout = useMemo(
      () => ({
        height,
        margin: { l: 200, r: 24, t: 8, b: 8 },
        font: { size: 12 },
        showlegend: false,
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
      }),
      [height],
    );
    return <Plot data={data} layout={layout} config={PLOT_CONFIG} style={PLOT_STYLE} />;
  },
);
FunnelChart.displayName = 'FunnelChart';

// ─────────────────────────────────────────────────────────────────────────────
// MultiFunnelChart — small multiples (one mini funnel per DC)
// ─────────────────────────────────────────────────────────────────────────────

interface MultiFunnelChartProps {
  dcIds: string[];
  stepLabels: string[];
  data: FunnelResponse;
  mode: ViewMode;
  unit: string;
  dcTagsById?: Record<string, string>;
}

/** Renders one ~120px-tall Plotly funnel per DC. No "primary" — each DC
 *  is rendered equally. The cascade table is redundant here so it's
 *  omitted. DCs with `counts == null` (failed to load) are shown with
 *  a dim "data unavailable" placeholder. */
const MultiFunnelChart: React.FC<MultiFunnelChartProps> = ({
  dcIds,
  stepLabels,
  data,
  mode,
  unit,
  dcTagsById,
}) => {
  const labels = useMemo(() => ['All rows', ...stepLabels], [stepLabels]);
  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">
        {unit} per data collection after each step.
      </Text>
      {dcIds.map((dcId) => {
        const counts = data.counts[dcId];
        const tag = dcLabel(dcId, dcTagsById);
        if (counts == null) {
          return (
            <Paper key={dcId} withBorder p="xs" radius="sm">
              <Group gap={8}>
                <Badge size="xs" variant="light">
                  {tag}
                </Badge>
                <Text size="xs" c="dimmed">
                  Data unavailable for this DC.
                </Text>
              </Group>
            </Paper>
          );
        }
        const display = deriveDisplay(counts, mode);
        const values = display.values.map((v) => Math.abs(v));
        return (
          <Paper key={dcId} withBorder p={6} radius="sm">
            <Group gap={6} mb={4} wrap="nowrap">
              <Icon icon="tabler:database" width={12} color="var(--mantine-color-blue-7)" />
              <Text size="xs" fw={600}>
                {tag}
              </Text>
            </Group>
            <FunnelChart
              labels={labels}
              values={values}
              formatted={display.formatted}
              unit={unit}
              height={Math.max(120, labels.length * 28)}
            />
          </Paper>
        );
      })}
    </Stack>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// CascadeFunnelChart — bars walk the journey's source DCs, no "All rows"
// ─────────────────────────────────────────────────────────────────────────────

interface CascadeFunnelChartProps {
  stepInputs: FunnelStepInput[];
  stepLabels: string[];
  data: FunnelResponse;
  mode: ViewMode;
  unit: string;
  dcTagsById?: Record<string, string>;
}

/** Each bar pulls from its step's *source* DC after steps 1..k are
 *  applied (or projected via link). The Y-axis crosses DC scales —
 *  meaningful for "journey through data collections" but not a strict
 *  subset funnel. Steps with no resolvable source DC fall back to the
 *  response's first DC. */
const CascadeFunnelChart: React.FC<CascadeFunnelChartProps> = ({
  stepInputs,
  stepLabels,
  data,
  mode,
  unit,
  dcTagsById,
}) => {
  if (stepInputs.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        Cascade mode needs at least one step.
      </Text>
    );
  }

  const rows = stepInputs.map((step, i) => {
    const stepLabel = stepLabels[i] ?? `Step ${i + 1}`;
    // Legacy steps without source_dc_id can't be placed on a DC axis in
    // this mode — fabricating a fallback DC from response insertion order
    // would mislabel the bar. Render as "unknown source" instead.
    if (!step.source_dc_id) {
      return {
        label: `${stepLabel} @ unknown source`,
        value: null as number | null,
        formatted: '—',
        applicable: false,
      };
    }
    const sourceDc = step.source_dc_id;
    const label = `${stepLabel} @ ${dcLabel(sourceDc, dcTagsById)}`;
    const counts = data.counts[sourceDc];
    if (counts == null) {
      return { label, value: null as number | null, formatted: '—', applicable: false };
    }
    const display = deriveDisplay(counts, mode);
    return {
      label,
      value: display.values[i + 1] ?? null,
      formatted: display.formatted[i + 1] ?? '—',
      applicable: data.applicable[sourceDc]?.[i + 1] !== false,
    };
  });

  // Plotly needs non-negative bars — keep magnitudes for geometry, keep
  // signed text. Carry-forward bars (not applicable) render at 0 height
  // so the no-op semantics are visible.
  const labels = rows.map((r) => r.label);
  const values = rows.map((r) => (r.value == null || !r.applicable ? 0 : Math.abs(r.value)));
  const formatted = rows.map((r) => (r.applicable ? r.formatted : '— (carry-forward)'));

  return (
    <Stack gap="xs">
      <Text size="xs" c="dimmed">
        Each bar measures the step's source DC after steps 1..k are applied.
        Counts cross DC scales — useful for tracing a journey through data
        collections, not for absolute subset comparisons.
      </Text>
      <FunnelChart
        labels={labels}
        values={values}
        formatted={formatted}
        unit={unit}
        height={Math.max(260, labels.length * 50)}
      />
    </Stack>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// JourneyTableModal — full sample of rows with per-step removal color
// ─────────────────────────────────────────────────────────────────────────────

interface JourneyTableModalProps {
  opened: boolean;
  onClose: () => void;
  parentDashboardId: string;
  stepInputs: FunnelStepInput[];
  initialStepIdx: number;
  targetDc: FunnelTargetDC | null;
  stepLabels: string[];
  dcTagsById?: Record<string, string>;
  /** Dark mode flips the ag-grid theme + slightly mutes the row tints
   *  so the colored backgrounds stay legible on dark cells. */
  isDark?: boolean;
}

const JOURNEY_PREVIEW_LIMIT = 200;

/** A row's removal-step (or `null` for survivors) drives its tint. The
 *  scale walks teal → amber → red so users can map a row to the funnel
 *  bar that dropped it without reading the legend. */
function rowTintForStep(removedAt: number | null, nSteps: number, dark: boolean): string | null {
  if (removedAt == null) return dark ? 'rgba(46, 204, 113, 0.20)' : 'rgba(46, 204, 113, 0.18)';
  if (nSteps <= 0) return null;
  // 0 → cool (early-drop = small impact), 1 → red (late-drop = surprising).
  const t = nSteps === 1 ? 1 : (nSteps - 1 - removedAt) / (nSteps - 1);
  const hue = 25 + (1 - t) * 110; // 135 (teal) → 25 (red)
  const alpha = dark ? 0.22 : 0.18;
  return `hsla(${hue.toFixed(0)}, 70%, 55%, ${alpha})`;
}

/** Modal showing up to 200 sampled rows of `targetDc` from the unfiltered
 *  baseline. Each row is annotated by which step first removed it (or
 *  `null` if it survived all). The view selector switches between:
 *   - "All rows" — every row, colored by its removal step
 *   - "Step N"   — only rows that survived through step N (i.e.
 *                  removed_at_step is null OR > N)
 *   - "Final"    — only survivors
 *  One fetch on open; switching views is purely client-side filtering. */
const JourneyTableModal: React.FC<JourneyTableModalProps> = ({
  opened,
  onClose,
  parentDashboardId,
  stepInputs,
  initialStepIdx,
  targetDc,
  stepLabels,
  dcTagsById,
  isDark = false,
}) => {
  const [data, setData] = useState<JourneyPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 'all' shows every row colored; a number N shows rows surviving
  // through step N; 'final' shows the full-chain survivors.
  type View = 'all' | number | 'final';
  const [view, setView] = useState<View>('all');

  // Reset view when the modal is re-opened so a stale state from a prior
  // step doesn't show on the next open.
  useEffect(() => {
    if (opened) {
      setView(initialStepIdx >= 0 ? initialStepIdx : 'all');
    }
  }, [opened, initialStepIdx]);

  useEffect(() => {
    if (!opened || !targetDc) {
      setData(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchJourneyPreview(parentDashboardId, stepInputs, targetDc, JOURNEY_PREVIEW_LIMIT)
      .then((res) => {
        if (cancelled) return;
        setData(res);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err?.message || String(err));
        setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [opened, parentDashboardId, JSON.stringify(stepInputs), targetDc?.dc_id, targetDc?.wf_id]);

  const nSteps = stepInputs.length;
  const viewOptions = useMemo(() => {
    const opts: { value: string; label: string }[] = [{ value: 'all', label: 'All rows' }];
    stepLabels.forEach((lbl, i) => {
      opts.push({ value: String(i), label: `Survived ${lbl || `step ${i + 1}`}` });
    });
    if (nSteps > 0) opts.push({ value: 'final', label: 'Final survivors' });
    return opts;
  }, [stepLabels, nSteps]);

  /** Augment each row with the metadata we need for ag-grid: the
   *  removal step (for the row classRule + a visible badge column) and
   *  a stable id (the original row index). */
  const augmentedRows = useMemo(() => {
    if (!data) return [];
    return data.rows.map((row, i) => ({
      ...row,
      __removed_at: data.removed_at_step[i],
      __row_id: i,
    }));
  }, [data]);

  /** Apply the view filter purely in-memory — no extra fetch. */
  const visibleRows = useMemo(() => {
    if (view === 'all') return augmentedRows;
    if (view === 'final') {
      return augmentedRows.filter((r) => r.__removed_at == null);
    }
    return augmentedRows.filter(
      (r) => r.__removed_at == null || (r.__removed_at as number) > view,
    );
  }, [augmentedRows, view]);

  const columnDefs = useMemo<ColDef[]>(() => {
    if (!data) return [];
    const statusCol: ColDef = {
      headerName: 'Status',
      field: '__removed_at',
      width: 150,
      pinned: 'left',
      cellRenderer: (params: { value: number | null }) => {
        if (params.value == null) return '✓ survived';
        const label = stepLabels[params.value] || `step ${params.value + 1}`;
        return `✗ removed at ${label}`;
      },
      sortable: true,
    };
    const dataCols: ColDef[] = data.columns.map((c) => ({
      headerName: c,
      field: c,
      sortable: true,
      filter: true,
      resizable: true,
    }));
    return [statusCol, ...dataCols];
  }, [data, stepLabels]);

  const getRowStyle = useMemo(
    () =>
      (params: RowClassParams<{ __removed_at: number | null }>) => {
        const removedAt = params.data?.__removed_at ?? null;
        const bg = rowTintForStep(removedAt, nSteps, isDark);
        return bg ? { backgroundColor: bg } : undefined;
      },
    [nSteps, isDark],
  );

  const dcTag = targetDc ? dcLabel(targetDc.dc_id, dcTagsById) : '';

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      size="100%"
      title={
        <Group gap={8} wrap="nowrap">
          <Icon icon="tabler:table" width={16} />
          <Text fw={600}>Journey rows</Text>
          <Text size="xs" c="dimmed">
            in {dcTag}
          </Text>
          {data && (
            <Badge size="xs" variant="light">
              showing {visibleRows.length} of {data.rows.length} sampled · {data.survivors}/
              {data.total} survive
            </Badge>
          )}
        </Group>
      }
    >
      <Stack gap="xs">
        {data && nSteps > 0 && (
          <Group gap="xs" wrap="wrap" align="center">
            <SegmentedControl
              size="xs"
              value={String(view)}
              onChange={(v) => setView(v === 'all' || v === 'final' ? v : Number(v))}
              data={viewOptions}
            />
            <Text size="xs" c="dimmed">
              {data.step_drops
                .map((n, i) => `${stepLabels[i] || `Step ${i + 1}`}: -${n}`)
                .join(' · ')}
            </Text>
          </Group>
        )}
        {loading ? (
          <Skeleton height={400} />
        ) : error ? (
          <Text size="sm" c="red.7">
            {error}
          </Text>
        ) : !data || data.rows.length === 0 ? (
          <Text size="sm" c="dimmed">
            No rows to display.
          </Text>
        ) : (
          <div
            className={isDark ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
            style={{ width: '100%', height: '70vh' }}
          >
            <AgGridReact
              rowData={visibleRows}
              columnDefs={columnDefs}
              getRowStyle={getRowStyle}
              defaultColDef={{
                resizable: true,
                sortable: true,
                filter: true,
                minWidth: 100,
              }}
              animateRows={false}
              suppressColumnVirtualisation={false}
            />
          </div>
        )}
      </Stack>
    </Modal>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Cascade table — one row per non-primary DC, one cell per step
// ─────────────────────────────────────────────────────────────────────────────

interface CascadeTableProps {
  primaryDcId: string;
  dcIds: string[];
  labels: string[];
  data: FunnelResponse;
  mode: ViewMode;
  dcTagsById?: Record<string, string>;
}

const CascadeTable: React.FC<CascadeTableProps> = ({
  primaryDcId,
  dcIds,
  labels,
  data,
  mode,
  dcTagsById,
}) => {
  const others = dcIds.filter((d) => d !== primaryDcId);
  if (others.length === 0) return null;
  return (
    <Box>
      <Text
        size="xs"
        fw={600}
        c="dimmed"
        tt="uppercase"
        mb={4}
        style={{ letterSpacing: 0.4 }}
      >
        Cascading effect on linked data collections
      </Text>
      <Table withTableBorder withColumnBorders striped highlightOnHover fz="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Data collection</Table.Th>
            {labels.map((l, i) => (
              <Table.Th key={i} style={{ textAlign: 'right' }}>
                {l}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {others.map((dcId) => {
            const counts = data.counts[dcId];
            const applicable = data.applicable[dcId];
            const display = deriveDisplay(counts ?? null, mode);
            const tag = dcLabel(dcId, dcTagsById);
            // A DC that's not-applicable for every step (only slot 0 = true)
            // is genuinely unreachable from the current journey — no project
            // link connects its source DCs to this target. Surface that as
            // a different message than per-step "this filter doesn't apply".
            const unreachable =
              applicable != null &&
              applicable.slice(1).every((a) => a === false);
            return (
              <Table.Tr key={dcId}>
                <Table.Td fw={600}>{tag}</Table.Td>
                {labels.map((_, i) => {
                  if (counts == null) {
                    return (
                      <Table.Td
                        key={i}
                        style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                      >
                        —
                      </Table.Td>
                    );
                  }
                  const isApplicable = applicable?.[i] !== false;
                  if (!isApplicable) {
                    const tipLabel =
                      unreachable && i > 0
                        ? `No project link reaches ${tag} from this journey's source DCs.`
                        : `This filter doesn't apply to ${tag}.`;
                    return (
                      <Table.Td
                        key={i}
                        style={{
                          textAlign: 'right',
                          fontVariantNumeric: 'tabular-nums',
                          color: 'var(--mantine-color-dimmed)',
                        }}
                      >
                        <Tooltip label={tipLabel} withArrow position="top">
                          <Text component="span" c="dimmed">
                            —
                          </Text>
                        </Tooltip>
                      </Table.Td>
                    );
                  }
                  return (
                    <Table.Td
                      key={i}
                      style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                    >
                      {display.formatted[i] ?? '—'}
                    </Table.Td>
                  );
                })}
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Box>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Steps panel — per-tab groups with ↑/↓/× actions and inline metric values
// ─────────────────────────────────────────────────────────────────────────────

interface StepsPanelProps {
  journey: Journey;
  tabs: FunnelTab[];
  primaryCounts: number[] | null;
  mode: ViewMode;
  resolveStepLabel?: (step: FunnelStep) => string | null;
  onReorderStep?: (journeyId: string, stepId: string, direction: 'up' | 'down') => void;
  onUnpinStep?: (stepId: string) => void;
  onSelectStep: (stepId: string) => void;
  selectedStepId: string | null;
  /** Open the rows-table modal for a step against its source DC.
   *  Receives the step index in journey order so the modal can apply
   *  filters 0..idx inclusive. */
  onViewRows?: (stepIdx: number, step: FunnelStep) => void;
}

const StepsPanel: React.FC<StepsPanelProps> = ({
  journey,
  tabs,
  primaryCounts,
  mode,
  resolveStepLabel,
  onReorderStep,
  onUnpinStep,
  onSelectStep,
  selectedStepId,
  onViewRows,
}) => {
  // Map step id -> its index in `journey.steps` so the View-rows handler
  // knows which filter prefix to apply.
  const stepIdToIndex = new Map<string, number>();
  journey.steps.forEach((s, i) => stepIdToIndex.set(s.id, i));
  const labelFor = (step: FunnelStep): string =>
    (resolveStepLabel ? resolveStepLabel(step) : null) || step.label || 'Filter';

  // Index by step id for the inline metric value. The chart's value array
  // (after `deriveDisplay`) is in dashboard step order, prepended with
  // "All rows" at slot 0, so step `i` lives at slot `i + 1`.
  const display = deriveDisplay(primaryCounts, mode);
  const stepIdToValue = new Map<string, string>();
  journey.steps.forEach((s, i) => {
    stepIdToValue.set(s.id, display.formatted[i + 1] ?? '');
  });

  const stepsByTab = new Map<string, FunnelStep[]>();
  for (const step of journey.steps) {
    const list = stepsByTab.get(step.tab_id) ?? [];
    list.push(step);
    stepsByTab.set(step.tab_id, list);
  }

  if (journey.steps.length === 0) {
    return (
      <Stack gap="xs">
        <Text size="sm" c="dimmed">
          This funnel has no steps yet. In edit mode, click the funnel-pin icon
          on any filter card (next to the globe icon) to add it as a step.
          Cross-tab order follows the dashboard's tab order automatically.
        </Text>
      </Stack>
    );
  }

  return (
    <Stack gap="sm">
      <Text size="xs" c="dimmed">
        Need a step to apply across tabs? Use the{' '}
        <Text component="span" fw={600}>
          globe icon
        </Text>{' '}
        on the filter card to promote it to a global filter.
      </Text>
      {tabs.map((tab) => {
        const tabSteps = stepsByTab.get(tab.id) ?? [];
        return (
          <Paper key={tab.id} withBorder p="xs" radius="sm">
            <Group gap={6} wrap="nowrap" mb={tabSteps.length ? 6 : 0}>
              <Icon icon={tab.icon ?? 'tabler:layout-bottombar-inactive'} width={14} />
              <Text size="sm" fw={600} truncate>
                {tab.name}
              </Text>
              {tabSteps.length === 0 && (
                <Text size="xs" c="dimmed">
                  no steps
                </Text>
              )}
            </Group>
            {tabSteps.length > 0 && (
              <Stack gap={2} pl={20}>
                {tabSteps.map((step, idx) => {
                  const isSelected = selectedStepId === step.id;
                  return (
                    <Group
                      key={step.id}
                      gap={4}
                      wrap="nowrap"
                      justify="space-between"
                      style={{
                        background: isSelected
                          ? 'var(--mantine-color-blue-light)'
                          : undefined,
                        borderRadius: 4,
                        padding: '2px 4px',
                        cursor: 'pointer',
                      }}
                      onClick={() => onSelectStep(step.id)}
                    >
                      <Group gap={6} wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
                        <Icon
                          icon={
                            step.scope === 'global'
                              ? 'tabler:world'
                              : 'tabler:filter'
                          }
                          width={12}
                          color={
                            step.scope === 'global'
                              ? 'var(--mantine-color-blue-6)'
                              : 'var(--mantine-color-gray-6)'
                          }
                        />
                        <Text size="xs" truncate style={{ flex: 1 }}>
                          {labelFor(step)}
                        </Text>
                        <Text
                          size="xs"
                          c="dimmed"
                          fw={500}
                          style={{
                            fontVariantNumeric: 'tabular-nums',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {stepIdToValue.get(step.id) ?? ''}
                        </Text>
                      </Group>
                      <Group gap={2} wrap="nowrap" onClick={(e) => e.stopPropagation()}>
                        {onViewRows && (
                          <Tooltip label="View surviving rows">
                            <ActionIcon
                              size="xs"
                              variant="subtle"
                              color="blue"
                              onClick={() => {
                                const i = stepIdToIndex.get(step.id);
                                if (i != null) onViewRows(i, step);
                              }}
                            >
                              <Icon icon="tabler:table" width={12} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                        {onReorderStep && (
                          <>
                            <Tooltip label="Move up">
                              <ActionIcon
                                size="xs"
                                variant="subtle"
                                color="gray"
                                disabled={idx === 0}
                                onClick={() =>
                                  void onReorderStep(journey.id, step.id, 'up')
                                }
                              >
                                <Icon icon="tabler:chevron-up" width={12} />
                              </ActionIcon>
                            </Tooltip>
                            <Tooltip label="Move down">
                              <ActionIcon
                                size="xs"
                                variant="subtle"
                                color="gray"
                                disabled={idx === tabSteps.length - 1}
                                onClick={() =>
                                  void onReorderStep(journey.id, step.id, 'down')
                                }
                              >
                                <Icon icon="tabler:chevron-down" width={12} />
                              </ActionIcon>
                            </Tooltip>
                          </>
                        )}
                        {onUnpinStep && (
                          <Tooltip label="Remove step">
                            <ActionIcon
                              size="xs"
                              variant="subtle"
                              color="gray"
                              onClick={() => void onUnpinStep(step.id)}
                            >
                              <Icon icon="tabler:x" width={12} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                      </Group>
                    </Group>
                  );
                })}
              </Stack>
            )}
          </Paper>
        );
      })}
    </Stack>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Step detail panel (Drawer) — per-DC before/after/Δ for one step
// ─────────────────────────────────────────────────────────────────────────────

interface StepDetailProps {
  opened: boolean;
  onClose: () => void;
  journey: Journey;
  stepId: string | null;
  data: FunnelResponse | null;
  dcIds: string[];
  dcTagsById?: Record<string, string>;
  resolveStepLabel?: (step: FunnelStep) => string | null;
}

const StepDetail: React.FC<StepDetailProps> = ({
  opened,
  onClose,
  journey,
  stepId,
  data,
  dcIds,
  dcTagsById,
  resolveStepLabel,
}) => {
  if (!stepId) return null;
  const stepIndex = journey.steps.findIndex((s) => s.id === stepId);
  if (stepIndex < 0) return null;
  const step = journey.steps[stepIndex];

  const stepLabel =
    (resolveStepLabel ? resolveStepLabel(step) : null) || step.label || 'Filter';
  // Vector slot `i+1` is "after step i" — slot 0 is the initial count.
  const cellIdx = stepIndex + 1;
  const beforeIdx = stepIndex; // "after previous step" or "All rows" for slot 0

  const dcRows = dcIds.map((dcId) => {
    const counts = data?.counts[dcId] ?? null;
    const applicable = data?.applicable[dcId] ?? null;
    const before = counts?.[beforeIdx] ?? null;
    const after = counts?.[cellIdx] ?? null;
    const applies = applicable?.[cellIdx] !== false;
    const delta = before != null && after != null ? after - before : null;
    const pct =
      before != null && after != null && before > 0
        ? ((after - before) / before) * 100
        : null;
    return { dcId, before, after, delta, pct, applies };
  });

  const nonApplicable = dcRows.filter((r) => !r.applies);

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="md"
      title={
        <Group gap={6}>
          <Icon
            icon={step.scope === 'global' ? 'tabler:world' : 'tabler:filter'}
            width={16}
            color={
              step.scope === 'global'
                ? 'var(--mantine-color-blue-6)'
                : 'var(--mantine-color-gray-6)'
            }
          />
          <Text fw={600}>{stepLabel}</Text>
          <Badge size="xs" variant="light" color={step.scope === 'global' ? 'blue' : 'gray'}>
            {step.scope}
          </Badge>
        </Group>
      }
    >
      <Stack gap="md">
        <Text size="xs" c="dimmed">
          Step {stepIndex + 1} of {journey.steps.length} in {journey.name}.
        </Text>
        <Table withTableBorder withColumnBorders fz="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Data collection</Table.Th>
              <Table.Th style={{ textAlign: 'right' }}>Before</Table.Th>
              <Table.Th style={{ textAlign: 'right' }}>After</Table.Th>
              <Table.Th style={{ textAlign: 'right' }}>Δ</Table.Th>
              <Table.Th style={{ textAlign: 'right' }}>Δ %</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {dcRows.map((r) => (
              <Table.Tr key={r.dcId}>
                <Table.Td fw={600}>{dcLabel(r.dcId, dcTagsById)}</Table.Td>
                <Table.Td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {r.before != null ? formatCount(r.before) : '—'}
                </Table.Td>
                <Table.Td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {r.applies && r.after != null ? (
                    formatCount(r.after)
                  ) : (
                    <Text component="span" c="dimmed">
                      —
                    </Text>
                  )}
                </Table.Td>
                <Table.Td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {r.applies && r.delta != null ? formatCount(r.delta) : '—'}
                </Table.Td>
                <Table.Td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {r.applies && r.pct != null ? formatPercent(r.pct) : '—'}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {nonApplicable.length > 0 && (
          <Box>
            <Text size="xs" c="dimmed" fw={600} tt="uppercase" mb={4}>
              Doesn't apply to
            </Text>
            <Text size="xs" c="dimmed">
              {nonApplicable.map((r) => dcLabel(r.dcId, dcTagsById)).join(', ')}
            </Text>
            <Text size="xs" c="dimmed" mt={4}>
              The filter isn't linked to these data collections, so this step is a no-op
              there and the previous count is carried forward.
            </Text>
          </Box>
        )}
      </Stack>
    </Drawer>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Funnel-switcher menu (modal header) — switch / create / rename / delete
// ─────────────────────────────────────────────────────────────────────────────

interface FunnelSwitcherProps {
  journeys: Journey[];
  activeJourneyId: string | null;
  onSwitch?: (journeyId: string) => void;
  onCreate?: (name: string) => void;
  onRename?: (journeyId: string, name: string) => void;
  onDelete?: (journeyId: string) => void;
  onToggleDefault?: (journeyId: string) => void;
}

const FunnelSwitcher: React.FC<FunnelSwitcherProps> = ({
  journeys,
  activeJourneyId,
  onSwitch,
  onCreate,
  onRename,
  onDelete,
  onToggleDefault,
}) => {
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState('');

  const active = journeys.find((j) => j.id === activeJourneyId) ?? null;
  const sorted = [...journeys].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    if ((a.is_default ?? false) !== (b.is_default ?? false))
      return a.is_default ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  const handleCreate = () => {
    const name = newName.trim();
    if (!name || !onCreate) return;
    onCreate(name);
    setCreateOpen(false);
    setNewName('');
  };

  const handleRename = () => {
    if (!active || !onRename) return;
    const name = renameValue.trim();
    if (!name || name === active.name) {
      setRenameOpen(false);
      return;
    }
    onRename(active.id, name);
    setRenameOpen(false);
  };

  return (
    <>
      <Menu shadow="md" position="bottom-end" width={280} closeOnItemClick={false}>
        <Menu.Target>
          <ActionIcon variant="subtle" size="md" aria-label="Funnel actions">
            <Icon icon="tabler:dots-vertical" width={16} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Label>Active funnel</Menu.Label>
          {sorted.length === 0 ? (
            <Menu.Item disabled>
              <Text size="xs" c="dimmed">
                No funnels yet
              </Text>
            </Menu.Item>
          ) : (
            sorted.map((j) => {
              const isActive = j.id === activeJourneyId;
              return (
                <Menu.Item
                  key={j.id}
                  onClick={() => {
                    if (!isActive && onSwitch) onSwitch(j.id);
                  }}
                  leftSection={
                    <Icon
                      icon={isActive ? 'tabler:check' : 'tabler:circle-dot'}
                      width={14}
                      color={isActive ? 'var(--mantine-color-blue-6)' : undefined}
                    />
                  }
                  rightSection={
                    <Group gap={4} wrap="nowrap">
                      {j.is_default && (
                        <Tooltip label="Default funnel">
                          <Icon
                            icon="tabler:star-filled"
                            width={12}
                            color="var(--mantine-color-yellow-6)"
                          />
                        </Tooltip>
                      )}
                      <Badge size="xs" variant="outline">
                        {j.steps.length}
                      </Badge>
                    </Group>
                  }
                >
                  <Text size="sm" fw={isActive ? 700 : 500} truncate>
                    {j.name}
                  </Text>
                </Menu.Item>
              );
            })
          )}
          <Menu.Divider />
          {onCreate && (
            <Menu.Item
              leftSection={<Icon icon="tabler:plus" width={14} />}
              onClick={() => setCreateOpen(true)}
            >
              New funnel
            </Menu.Item>
          )}
          {active && onRename && (
            <Menu.Item
              leftSection={<Icon icon="tabler:edit" width={14} />}
              onClick={() => {
                setRenameValue(active.name);
                setRenameOpen(true);
              }}
            >
              Rename
            </Menu.Item>
          )}
          {active && onToggleDefault && (
            <Menu.Item
              leftSection={
                <Icon
                  icon={active.is_default ? 'tabler:star-off' : 'tabler:star'}
                  width={14}
                />
              }
              onClick={() => onToggleDefault(active.id)}
            >
              {active.is_default ? 'Unset default' : 'Set as default'}
            </Menu.Item>
          )}
          {active && onDelete && (
            <Menu.Item
              color="red"
              leftSection={<Icon icon="tabler:trash" width={14} />}
              onClick={() => {
                if (confirm(`Delete funnel "${active.name}"?`)) onDelete(active.id);
              }}
            >
              Delete
            </Menu.Item>
          )}
        </Menu.Dropdown>
      </Menu>

      <Modal
        opened={createOpen}
        onClose={() => setCreateOpen(false)}
        title="New funnel"
        size="sm"
      >
        <Stack gap="sm">
          <TextInput
            label="Name"
            placeholder="e.g. Riverwater drill-down"
            value={newName}
            onChange={(e) => setNewName(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
            autoFocus
          />
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={!newName.trim()}>
              Create
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={renameOpen}
        onClose={() => setRenameOpen(false)}
        title="Rename funnel"
        size="sm"
      >
        <Stack gap="sm">
          <TextInput
            value={renameValue}
            onChange={(e) => setRenameValue(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleRename()}
            autoFocus
          />
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setRenameOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleRename} disabled={!renameValue.trim()}>
              Save
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// Top-level component
// ─────────────────────────────────────────────────────────────────────────────

export interface FunnelTab {
  id: string;
  name: string;
  icon?: string | null;
}

export interface JourneyFunnelProps {
  parentDashboardId: string;
  /** The active journey (funnel). Null if none active. */
  journey: Journey | null;
  /** All journeys on the dashboard — drives the switcher menu. */
  journeys?: Journey[];
  /** Pre-resolved step inputs (current values bound to each pinned step).
   *  Must be 1:1 with `journey?.steps`. */
  stepInputs: FunnelStepInput[];
  /** Display labels for each step's funnel bar — 1:1 with `journey?.steps`. */
  stepLabels: string[];
  targetDcs: FunnelTargetDC[];
  dcTagsById?: Record<string, string>;
  /** Columns the user can pick from when view mode is "Unique values".
   *  Keyed by `dc_id`. We populate from the primary DC. */
  columnsByDc?: Record<string, string[]>;
  /** Tabs (in dashboard order) for the Steps panel grouping. */
  tabs?: FunnelTab[];
  /** Resolves a human label for a step (e.g. the bound filter's label).
   *  If returning null, falls back to step.label or "Filter". */
  resolveStepLabel?: (step: FunnelStep) => string | null;
  /** Bump to force refresh (e.g. when a local filter changes elsewhere). */
  refreshTick?: number;
  /** Controlled-modal mode — when set, the rail strip is hidden and the
   *  modal is fully driven by the caller. */
  controlledOpen?: boolean;
  onCloseControlled?: () => void;
  // Funnel CRUD + step actions — wired from the App.tsx store. When a
  // handler is omitted, the corresponding UI is hidden.
  onSwitchJourney?: (journeyId: string) => void;
  onCreateJourney?: (name: string) => void;
  onRenameJourney?: (journeyId: string, name: string) => void;
  onDeleteJourney?: (journeyId: string) => void;
  onToggleDefaultJourney?: (journeyId: string) => void;
  onReorderStep?: (journeyId: string, stepId: string, direction: 'up' | 'down') => void;
  onUnpinStep?: (stepId: string) => void;
}

const JourneyFunnel: React.FC<JourneyFunnelProps> = ({
  parentDashboardId,
  journey,
  journeys,
  stepInputs,
  stepLabels,
  targetDcs,
  dcTagsById,
  columnsByDc,
  tabs,
  resolveStepLabel,
  refreshTick,
  controlledOpen,
  onCloseControlled,
  onSwitchJourney,
  onCreateJourney,
  onRenameJourney,
  onDeleteJourney,
  onToggleDefaultJourney,
  onReorderStep,
  onUnpinStep,
}) => {
  const controlled = controlledOpen !== undefined;
  const [internalOpen, setInternalOpen] = useState(false);
  const modalOpen = controlled ? controlledOpen : internalOpen;
  const closeModal = controlled
    ? onCloseControlled ?? (() => undefined)
    : () => setInternalOpen(false);
  const setModalOpen = (next: boolean) => {
    if (controlled) {
      if (!next) closeModal();
    } else {
      setInternalOpen(next);
    }
  };

  const [activeTab, setActiveTab] = useState<'chart' | 'steps'>('chart');
  const [viewMode, setViewMode] = useState<ViewMode>('rows');
  const [metricColumn, setMetricColumn] = useState<string | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [displayMode, setDisplayMode] = useState<DisplayMode>('primary');
  // User-picked primary DC overrides the default (first target). Falls
  // back when the picked DC is no longer in the target list (e.g. the
  // journey was edited and that DC dropped out).
  const [primaryDcOverride, setPrimaryDcOverride] = useState<string | null>(null);
  // Per-step "View rows" target — when set, the JourneyTableModal is
  // open with that step preselected against the chosen DC.
  const [rowsForStep, setRowsForStep] = useState<{
    stepIdx: number;
    targetDc: FunnelTargetDC;
  } | null>(null);
  // Detect dark mode so the ag-grid theme + row tints can adapt.
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  const fallbackPrimaryDcId = targetDcs[0]?.dc_id ?? null;
  const primaryDcId = useMemo(() => {
    if (primaryDcOverride && targetDcs.some((d) => d.dc_id === primaryDcOverride)) {
      return primaryDcOverride;
    }
    return fallbackPrimaryDcId;
  }, [primaryDcOverride, targetDcs, fallbackPrimaryDcId]);

  // Columns the user can pick from for "Unique" — primary DC's schema only.
  const columnChoices = useMemo(() => {
    if (!primaryDcId || !columnsByDc) return [];
    return columnsByDc[primaryDcId] ?? [];
  }, [primaryDcId, columnsByDc]);

  // Auto-pick the first column when entering Unique mode without one chosen.
  useEffect(() => {
    if (viewMode === 'unique' && !metricColumn && columnChoices.length > 0) {
      setMetricColumn(columnChoices[0]);
    }
  }, [viewMode, metricColumn, columnChoices]);

  const backendMetric = viewModeBackendMetric(viewMode);
  // When the modal is closed only the InlineStrip is visible — it shows
  // a single chevron chain for the primary DC. Fetching all linked DCs
  // every filter keystroke is wasted work. Trim to primary-only when
  // closed; full list when open so cascade/multiples views have data.
  const effectiveTargets = useMemo(() => {
    if (modalOpen) return targetDcs;
    if (!primaryDcId) return [];
    return targetDcs.filter((d) => d.dc_id === primaryDcId);
  }, [modalOpen, targetDcs, primaryDcId]);

  const { data, loading } = useFunnelCounts(
    parentDashboardId,
    stepInputs,
    effectiveTargets,
    refreshTick,
    backendMetric,
    backendMetric === 'nunique' ? metricColumn : null,
  );

  const primaryCounts = primaryDcId ? data?.counts[primaryDcId] ?? null : null;
  const dcIds = useMemo(() => targetDcs.map((d) => d.dc_id), [targetDcs]);
  const linkedCount = Math.max(0, dcIds.length - 1);
  const hasSteps = (journey?.steps.length ?? 0) > 0;

  const display = useMemo(
    () => deriveDisplay(primaryCounts, viewMode),
    [primaryCounts, viewMode],
  );

  // Plotly funnel needs non-negative bar magnitudes — pctStep produces
  // negative percentages for drops, which render as blank bars. Take the
  // absolute magnitude for the chart geometry; the sign is preserved in
  // `display.formatted` so the bar text still reads "−83%".
  // Memoized so `<FunnelChart>` (React.memo) doesn't re-render on every
  // parent render with a fresh array reference.
  const chartValues = useMemo(
    () => display.values.map((v) => Math.abs(v)),
    [display.values],
  );

  const labels = useMemo(() => {
    const prefixed = ['All rows', ...stepLabels];
    return prefixed.slice(0, display.values.length || prefixed.length);
  }, [stepLabels, display.values.length]);

  // Summary metrics for the sticky strip — driven by raw counts so they
  // stay meaningful across view modes.
  const summary = useMemo(() => {
    if (!primaryCounts || primaryCounts.length < 2) return null;
    const initial = primaryCounts[0];
    const final = primaryCounts[primaryCounts.length - 1];
    const overallDrop = initial > 0 ? ((final - initial) / initial) * 100 : 0;
    let biggestIdx = -1;
    let biggestPct = 0;
    for (let i = 1; i < primaryCounts.length; i++) {
      const prev = primaryCounts[i - 1];
      if (!prev) continue;
      const pct = ((primaryCounts[i] - prev) / prev) * 100;
      if (pct < biggestPct) {
        biggestPct = pct;
        biggestIdx = i;
      }
    }
    return {
      initial,
      final,
      overallDrop,
      biggestLabel: biggestIdx > 0 ? stepLabels[biggestIdx - 1] ?? '' : '',
      biggestPct,
    };
  }, [primaryCounts, stepLabels]);

  // Reset selected step when the journey changes.
  useEffect(() => {
    setSelectedStepId(null);
  }, [journey?.id]);

  // The inline strip (uncontrolled mode) requires a primary DC to render
  // numbers — bail there. The Modal body has its own empty-state copy that
  // covers the no-DCs case, so we don't return null at the component root.
  // (Otherwise a controlled-open modal with no global filters yet renders
  // as an empty container — that's the "funnel not showing up" bug.)
  const inlineStripRenderable = !!primaryDcId;

  const switcherEnabled =
    journeys !== undefined &&
    Boolean(
      onSwitchJourney ||
        onCreateJourney ||
        onRenameJourney ||
        onDeleteJourney ||
        onToggleDefaultJourney,
    );

  return (
    <>
      {!controlled && inlineStripRenderable && (
        <InlineStrip
          primaryDcId={primaryDcId}
          counts={primaryCounts}
          loading={loading}
          hasSteps={hasSteps}
          linkedCount={linkedCount}
          dcTagsById={dcTagsById}
          journeyName={journey?.name ?? null}
          onOpen={() => setModalOpen(true)}
        />
      )}

      <Modal
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
        size="xl"
        title={
          <Group gap={8} wrap="nowrap" align="center" style={{ flex: 1 }}>
            {journey ? (
              <>
                <Icon
                  icon={journey.icon ?? 'tabler:route'}
                  width={18}
                  color={journey.color ?? 'var(--mantine-color-blue-filled)'}
                />
                <Text fw={600}>Funnel · {journey.name}</Text>
                <Badge size="xs" variant="outline">
                  {journey.steps.length} step{journey.steps.length === 1 ? '' : 's'}
                </Badge>
              </>
            ) : (
              <>
                <Icon icon="tabler:filter-cog" width={18} />
                <Text fw={600}>Filter funnel</Text>
              </>
            )}
            {switcherEnabled && (
              <Box style={{ marginLeft: 'auto' }}>
                <FunnelSwitcher
                  journeys={journeys ?? []}
                  activeJourneyId={journey?.id ?? null}
                  onSwitch={onSwitchJourney}
                  onCreate={onCreateJourney}
                  onRename={onRenameJourney}
                  onDelete={onDeleteJourney}
                  onToggleDefault={onToggleDefaultJourney}
                />
              </Box>
            )}
          </Group>
        }
      >
        <Stack gap="md">
          {summary && hasSteps && (
            <Paper withBorder p="xs" radius="sm" style={{ background: 'var(--mantine-color-blue-light)' }}>
              <Group gap={8} wrap="nowrap" align="center">
                <Icon icon="tabler:chart-bar" width={14} color="var(--mantine-color-blue-7)" />
                <Text size="xs" fw={600} c="blue.8" style={{ whiteSpace: 'nowrap' }}>
                  All rows: {formatCount(summary.initial)}
                </Text>
                <Icon icon="tabler:arrow-right" width={12} color="var(--mantine-color-dimmed)" />
                <Text size="xs" fw={700} c="blue.8" style={{ whiteSpace: 'nowrap' }}>
                  {formatCount(summary.final)}
                </Text>
                <Text size="xs" c={summary.overallDrop < 0 ? 'red.7' : 'dimmed'}>
                  ({formatPercent(summary.overallDrop)})
                </Text>
                {summary.biggestLabel && summary.biggestPct < 0 && (
                  <Text size="xs" c="dimmed" truncate>
                    · Biggest drop:{' '}
                    <Text component="span" fw={600}>
                      {summary.biggestLabel}
                    </Text>{' '}
                    ({formatPercent(summary.biggestPct)})
                  </Text>
                )}
              </Group>
            </Paper>
          )}

          {!primaryDcId ? (
            <Stack gap="xs">
              <Text size="sm" c="dimmed">
                {journeys && journeys.length === 0
                  ? 'No funnel yet. Use the menu (⋯) in the title bar above to create one, then pin filters from any filter card to add them as steps.'
                  : 'This dashboard has no global filters yet, and the active funnel has no local steps tied to data collections on this tab. Pin a filter from a filter card, or promote a filter to global with the globe icon, to wire up a funnel.'}
              </Text>
              <Text size="xs" c="dimmed">
                Tip — promote a filter to global (globe icon on the filter card)
                to make it apply across tabs; pin filters (funnel icon) to add
                them as funnel steps.
              </Text>
            </Stack>
          ) : !hasSteps ? (
            <Stack gap="xs">
              <Text size="sm" c="dimmed">
                This funnel has no steps yet. In edit mode, click the funnel-pin
                icon on any filter card (next to the globe icon) to add it as a
                step. Cross-tab order follows the dashboard's tab order
                automatically.
              </Text>
              <Text size="xs" c="dimmed">
                Tip — to make a step apply across tabs, click the{' '}
                <Text component="span" fw={600}>
                  globe icon
                </Text>{' '}
                on its filter card to promote it to a global filter first.
              </Text>
            </Stack>
          ) : (
            <Box pos="relative">
              <LoadingOverlay
                visible={loading}
                zIndex={2}
                overlayProps={{ blur: 1, backgroundOpacity: 0.35 }}
                loaderProps={{ size: 'sm', color: 'blue' }}
              />
              <Tabs value={activeTab} onChange={(v) => v && setActiveTab(v as 'chart' | 'steps')}>
              <Tabs.List>
                <Tabs.Tab value="chart" leftSection={<Icon icon="tabler:chart-bar" width={14} />}>
                  Chart
                </Tabs.Tab>
                <Tabs.Tab value="steps" leftSection={<Icon icon="tabler:list-numbers" width={14} />}>
                  Steps
                </Tabs.Tab>
              </Tabs.List>

              <Tabs.Panel value="chart" pt="md">
                <Stack gap="md">
                  <Group gap="sm" wrap="wrap" align="flex-end">
                    <Box>
                      <Text size="xs" c="dimmed" mb={4}>
                        Display
                      </Text>
                      <SegmentedControl
                        size="xs"
                        value={displayMode}
                        onChange={(v) => setDisplayMode(v as DisplayMode)}
                        data={DISPLAY_MODE_OPTIONS}
                      />
                    </Box>
                    {displayMode === 'primary' && dcIds.length > 1 && (
                      <Box style={{ minWidth: 160 }}>
                        <Select
                          size="xs"
                          label="Primary DC"
                          value={primaryDcId}
                          onChange={(v) => setPrimaryDcOverride(v)}
                          data={dcIds.map((d) => ({
                            value: d,
                            label: dcLabel(d, dcTagsById),
                          }))}
                          allowDeselect={false}
                        />
                      </Box>
                    )}
                    <Box>
                      <Text size="xs" c="dimmed" mb={4}>
                        View
                      </Text>
                      <SegmentedControl
                        size="xs"
                        value={viewMode}
                        onChange={(v) => setViewMode(v as ViewMode)}
                        data={VIEW_MODE_OPTIONS}
                      />
                    </Box>
                    {viewMode === 'unique' && (
                      <Box style={{ minWidth: 180 }}>
                        <Select
                          size="xs"
                          label="Column"
                          placeholder={
                            columnChoices.length === 0
                              ? 'No columns available'
                              : 'Pick a column'
                          }
                          value={metricColumn}
                          onChange={(v) => setMetricColumn(v)}
                          data={columnChoices.map((c) => ({ value: c, label: c }))}
                          searchable
                          disabled={columnChoices.length === 0}
                        />
                      </Box>
                    )}
                    {/* Primary affordance for the rows table — fires the
                        StepRowsModal at the LAST step (most useful: rows
                        surviving the full filter chain). Steps tab keeps
                        the per-step icons for finer-grained access. */}
                    {hasSteps && primaryDcId && (
                      <Box style={{ marginLeft: 'auto' }}>
                        <Button
                          size="xs"
                          variant="light"
                          leftSection={<Icon icon="tabler:table" width={14} />}
                          onClick={() => {
                            const lastIdx = stepInputs.length - 1;
                            const stepInput = stepInputs[lastIdx];
                            const sourceDcId = stepInput?.source_dc_id || primaryDcId;
                            const targetDc =
                              targetDcs.find((t) => t.dc_id === sourceDcId) ?? targetDcs[0];
                            if (!targetDc) return;
                            setRowsForStep({ stepIdx: lastIdx, targetDc });
                          }}
                        >
                          View filtered rows
                        </Button>
                      </Box>
                    )}
                  </Group>

                  {(() => {
                    if (viewMode === 'unique' && !metricColumn) {
                      return (
                        <Text size="sm" c="dimmed">
                          Pick a column above to compute unique counts.
                        </Text>
                      );
                    }
                    if (!data) {
                      return <Skeleton height={240} radius="sm" />;
                    }
                    const unit = unitFor(viewMode, metricColumn);
                    if (displayMode === 'multiples') {
                      return (
                        <MultiFunnelChart
                          dcIds={dcIds}
                          stepLabels={stepLabels}
                          data={data}
                          mode={viewMode}
                          unit={unit}
                          dcTagsById={dcTagsById}
                        />
                      );
                    }
                    if (displayMode === 'cascade') {
                      return (
                        <CascadeFunnelChart
                          stepInputs={stepInputs}
                          stepLabels={stepLabels}
                          data={data}
                          mode={viewMode}
                          unit={unit}
                          dcTagsById={dcTagsById}
                        />
                      );
                    }
                    // displayMode === 'primary'
                    if (!primaryCounts) {
                      return <Skeleton height={240} radius="sm" />;
                    }
                    return (
                      <>
                        <Text size="xs" c="dimmed">
                          {unit} in{' '}
                          <Text component="span" fw={600}>
                            {dcLabel(primaryDcId, dcTagsById)}
                          </Text>{' '}
                          after each step is applied.
                        </Text>
                        <FunnelChart
                          labels={labels}
                          values={chartValues}
                          formatted={display.formatted}
                          unit={unit}
                          height={Math.max(260, labels.length * 50)}
                        />
                        {linkedCount > 0 && (
                          <CascadeTable
                            primaryDcId={primaryDcId}
                            dcIds={dcIds}
                            labels={labels}
                            data={data}
                            mode={viewMode}
                            dcTagsById={dcTagsById}
                          />
                        )}
                      </>
                    );
                  })()}

                </Stack>
              </Tabs.Panel>

              <Tabs.Panel value="steps" pt="md">
                {journey && (tabs?.length ?? 0) > 0 ? (
                  <ScrollArea.Autosize mah={520}>
                    <StepsPanel
                      journey={journey}
                      tabs={tabs ?? []}
                      primaryCounts={primaryCounts}
                      mode={viewMode}
                      resolveStepLabel={resolveStepLabel}
                      onReorderStep={onReorderStep}
                      onUnpinStep={onUnpinStep}
                      onSelectStep={(id) => setSelectedStepId(id)}
                      selectedStepId={selectedStepId}
                      onViewRows={(stepIdx, step) => {
                        // Prefer the step's pinned source DC; fall back to
                        // the modal's primary DC so a legacy step without
                        // source_dc_id still has a sensible target.
                        const stepInput = stepInputs[stepIdx];
                        const sourceDcId = stepInput?.source_dc_id || primaryDcId;
                        const targetDc = targetDcs.find((t) => t.dc_id === sourceDcId);
                        if (!targetDc) return;
                        setRowsForStep({ stepIdx, targetDc });
                        void step;
                      }}
                    />
                  </ScrollArea.Autosize>
                ) : (
                  <Text size="sm" c="dimmed">
                    Steps panel needs tab metadata — open this modal from a dashboard
                    page.
                  </Text>
                )}
              </Tabs.Panel>
            </Tabs>
            </Box>
          )}

          <Divider />
          <Text size="xs" c="dimmed">
            Tip — switch view modes to inspect rows, unique values, or % drops without
            re-pinning. Empty cells in the cascade table mean the step's filter isn't
            linked to that data collection.
          </Text>
        </Stack>
      </Modal>

      {journey && (
        <StepDetail
          opened={!!selectedStepId}
          onClose={() => setSelectedStepId(null)}
          journey={journey}
          stepId={selectedStepId}
          data={data}
          dcIds={dcIds}
          dcTagsById={dcTagsById}
          resolveStepLabel={resolveStepLabel}
        />
      )}

      <JourneyTableModal
        opened={!!rowsForStep}
        onClose={() => setRowsForStep(null)}
        parentDashboardId={parentDashboardId}
        stepInputs={stepInputs}
        initialStepIdx={rowsForStep?.stepIdx ?? -1}
        targetDc={rowsForStep?.targetDc ?? null}
        stepLabels={stepLabels}
        dcTagsById={dcTagsById}
        isDark={isDark}
      />
    </>
  );
};

export default JourneyFunnel;
