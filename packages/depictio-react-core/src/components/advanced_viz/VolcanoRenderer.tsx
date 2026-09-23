import React, { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Group,
  NumberInput,
  SegmentedControl,
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
import { resolveCategoricalPalette, stableColorMap, TAB10_PALETTE } from '../../colors';
import { isStaleFetch } from '../../fetchQueue';
import { adaptGlTrace, SVG_MAX_POINTS, useWebglSlot } from '../../webglBudget';
import AdvancedVizFrame from './AdvancedVizFrame';
import { usePersistedVizControl } from './usePersistedVizControl';
import { splitFigureByGroups } from './groupSplit';
import type { GroupRenderState } from '../../selectionGroups';
import { useReportGroupColouring } from '../../groupReach';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import {
  classifyTiers,
  genomicInflation,
  matchSearch,
  offeredDeViews,
  qqConfidenceBand,
  qqSeries,
  rankTopN,
  resolveDeView,
  tierCounts,
  type DeTier,
  type DeView,
} from './deViews';

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
  /** MA and QQ view bindings. See deViews.ts for why they live on this config. */
  avg_log_intensity_col?: string | null;
  log2_fold_change_col?: string | null;
  fold_change_threshold?: number;
  p_value_col?: string | null;
  show_ci?: boolean;
  show_identity?: boolean;
  point_size?: number;
  view?: DeView;
  views?: DeView[] | null;
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

/** Tier colours, kept out of the builders so all three views share one scheme. */
const TIER_COLOURS: Record<DeTier, string> = {
  UP: '#e64980',
  DN: '#1c7ed6',
  NS: 'rgba(160,160,160,0.55)',
};

const DOTTED_GUIDE = { dash: 'dot' as const, color: 'rgba(128,128,128,0.6)', width: 1 };

const VIEW_LABELS: Record<DeView, string> = { volcano: 'Volcano', ma: 'MA', qq: 'QQ' };

/**
 * The differential-expression tile: one table, three readings.
 *
 * Volcano (effect against significance), MA (effect against abundance) and QQ
 * (observed significance against the uniform null) answer three questions about
 * the same rows, and a reader moves between them constantly. Splitting them
 * across three tiles meant three fetches of the same table and three places to
 * set the same cutoff, and left the reader comparing plots whose thresholds had
 * quietly drifted apart. One fetch, one set of thresholds, one selection, and a
 * switch in the tile header. `ma` and `qq` stay live as kind names: their
 * renderers are thin wrappers that open this tile on their view.
 */
const VolcanoRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, groupRender }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as VolcanoConfig;

  // Tier-2 controls (never enter the global filter array). The thresholds and
  // the label budget say what the chart is, so they persist; the search box is
  // a way of looking at it and stays local.
  const [view, setView] = usePersistedVizControl<DeView>(metadata, 'view', 'volcano');
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
  const [fcThreshold, setFcThreshold] = usePersistedVizControl<number>(metadata, 'fold_change_threshold', 1.0);
  const [topN, setTopN] = usePersistedVizControl<number>(metadata, 'top_n_labels', 20);
  const [search, setSearch] = useState<string>('');
  const [showLabels, setShowLabels] = usePersistedVizControl(metadata, 'show_labels', true);
  const [showCi, setShowCi] = usePersistedVizControl(metadata, 'show_ci', true);
  const [showIdentity, setShowIdentity] = usePersistedVizControl(metadata, 'show_identity', true);
  const [pointSize, setPointSize] = usePersistedVizControl(metadata, 'point_size', 5);

  const offered = useMemo(() => offeredDeViews(config), [config]);
  // The author's pick, unless the bindings stopped supporting it (a column was
  // renamed, or `views` narrowed). Resolved at build time rather than corrected
  // through the setter, so a stale stored value is never written back on load.
  const activeView = resolveDeView(view, offered);

  // The QQ view wants raw p-values. `p_value_col` names them explicitly;
  // otherwise `significance_col` already holds them, unless it was declared as
  // -log10, in which case `offeredDeViews` never offers the view at all.
  const pValueCol = config.p_value_col || config.significance_col;
  // The MA view's y is a log fold change, which for most tables is the same
  // column the volcano puts on x.
  const maYCol = config.log2_fold_change_col || config.effect_size_col;

  // One fetch for the tile: the union over every view it can show, so the
  // switch is instant and never re-queries a 17M-row table.
  const requiredCols = useMemo(
    () =>
      Array.from(
        new Set(
          [
            config.feature_id_col,
            config.effect_size_col,
            config.significance_col,
            config.label_col,
            config.category_col,
            config.avg_log_intensity_col,
            config.log2_fold_change_col,
            config.p_value_col,
          ].filter(Boolean) as string[],
        ),
      ),
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

  // At least one of the three views has to have somewhere to draw. Phrased over
  // the config rather than over the fetched column count because a QQ-only
  // binding names two columns, not three, and because it must not change when
  // the reader switches view: that would refetch the table on every switch.
  const hasBinding = Boolean(
    (config.effect_size_col && config.significance_col) ||
      (config.avg_log_intensity_col && maYCol) ||
      config.p_value_col,
  );

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || !hasBinding) {
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
        // volcano draws its own line at keeps precisely those rows whole. The
        // MA and QQ views read the same tail, which is one more reason for the
        // three of them to share a fetch.
        //
        // Deliberately the *saved* threshold, not the live `sigThreshold`
        // control: that one is a client-side slider, and refetching a 17M-row
        // table on every drag to widen the tail is a worse trade than leaving
        // the newly-significant rows to the uniform sample of the middle.
        //
        // Skipped when nothing names the significance column: a table bound
        // through the `ma` alias may have none, and asking the server to keep
        // the tail of a column that is not there fails the whole fetch.
        ...(config.significance_col
          ? {
              tail: {
                column: config.significance_col,
                direction: config.significance_is_neg_log10 ? 'high' : ('low' as const),
                threshold: config.significance_is_neg_log10
                  ? -Math.log10(config.significance_threshold ?? 0.05)
                  : (config.significance_threshold ?? 0.05),
              },
            }
          : {}),
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

  // Every view draws a marker cloud, so the tile always competes for one of the
  // bounded WebGL slots. Without one it renders as SVG, see webglBudget.
  const glGranted = useWebglSlot(true);

  const figure = useMemo(() => {
    if (!rows) return null;
    const ids = (rows[config.feature_id_col] || []) as (string | number)[];
    const labels = config.label_col
      ? ((rows[config.label_col] || []) as (string | number)[])
      : ids;

    if (activeView === 'qq') {
      return buildQq({
        ps: (rows[pValueCol] || []) as number[],
        ids: config.feature_id_col ? ids : null,
        cats: config.category_col ? ((rows[config.category_col] || []) as (string | number)[]) : null,
        showCi,
        showIdentity,
        pointSize,
        topN,
        isDark,
        theme,
        glGranted,
      });
    }

    if (activeView === 'ma') {
      return buildMa({
        xs: (rows[config.avg_log_intensity_col ?? ''] || []) as number[],
        ys: (rows[maYCol] || []) as number[],
        sigRaw: (rows[config.significance_col] || []) as number[],
        ids,
        labels,
        xTitle: config.avg_log_intensity_col ?? '',
        yTitle: maYCol,
        sigTitle: config.significance_col,
        sigThreshold,
        fcThreshold,
        topN,
        search,
        showLabels,
        isDark,
        theme,
        glGranted,
      });
    }

    return buildVolcano({
      xs: (rows[config.effect_size_col] || []) as number[],
      sigRaw: (rows[config.significance_col] || []) as number[],
      ids,
      labels,
      isNegLog10: Boolean(config.significance_is_neg_log10),
      effectTitle: config.effect_size_col,
      sigTitle: config.significance_col,
      sigThreshold,
      effectThreshold,
      topN,
      search,
      showLabels,
      isDark,
      theme,
      glGranted,
    });
  }, [
    rows,
    config,
    activeView,
    pValueCol,
    maYCol,
    sigThreshold,
    effectThreshold,
    fcThreshold,
    topN,
    search,
    showLabels,
    showCi,
    showIdentity,
    pointSize,
    isDark,
    theme,
    glGranted,
  ]);

  // The view switch is an encoding control, not a cosmetic one: it says what
  // the tile is showing, so it belongs in the header tier rather than behind
  // the Settings icon. One offered view means nothing to switch.
  const viewControl = useMemo(
    () =>
      offered.length > 1 ? (
        <SegmentedControl
          size="xs"
          value={activeView}
          onChange={(next) => setView(next as DeView)}
          data={offered.map((name) => ({ value: name, label: VIEW_LABELS[name] }))}
        />
      ) : null,
    [offered, activeView, setView],
  );

  // Encoding tier: which view, which features count as significant, which get
  // labelled and which are searched for. Drawn as chips in the header, so every
  // control carries a fixed width and no description.
  const primaryControls = useMemo(
    () => (
      <>
        {viewControl}
        {activeView !== 'qq' ? (
          <Tooltip label="Significance threshold (raw p/padj)">
            <NumberInput
              size="xs"
              w={110}
              label="p / padj"
              value={sigThreshold}
              onChange={(v) => setSigThreshold(Number(v) || 0.05)}
              step={0.01}
              min={0}
              max={1}
              decimalScale={3}
            />
          </Tooltip>
        ) : null}
        {activeView === 'volcano' ? (
          <NumberInput
            size="xs"
            w={110}
            label="|effect|"
            value={effectThreshold}
            onChange={(v) => setEffectThreshold(Number(v) || 0)}
            step={0.1}
            min={0}
            decimalScale={2}
          />
        ) : null}
        {activeView === 'ma' ? (
          <NumberInput
            size="xs"
            w={110}
            label="|log2 FC|"
            value={fcThreshold}
            onChange={(v) => setFcThreshold(Number(v) || 0)}
            step={0.1}
            min={0}
            decimalScale={2}
          />
        ) : null}
        <NumberInput
          size="xs"
          w={110}
          label="Top-N labels"
          value={topN}
          onChange={(v) => setTopN(Math.max(0, Number(v) || 0))}
          min={0}
          max={500}
        />
        {activeView !== 'qq' ? (
          <TextInput
            size="xs"
            w={160}
            label="Search"
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            placeholder="gene / taxon"
          />
        ) : null}
      </>
    ),
    [viewControl, activeView, sigThreshold, effectThreshold, fcThreshold, topN, search],
  );

  // Cosmetic tier: how the same points are painted.
  // Memoised so AdvancedVizFrame's `extras` useMemo doesn't invalidate on
  // every render, otherwise the published popover JSX is republished on
  // each tick and AG Grid receives a fresh tierAnnotation reference, which
  // (combined with controlled `sort`) was clobbering user filter/sort.
  const controls = useMemo(
    () => (
      <Stack gap="xs">
        {activeView === 'qq' && figure?.lambdaOverall != null && !Number.isNaN(figure.lambdaOverall) ? (
          <Badge size="sm" color="grape" variant="light" radius="sm" fullWidth>
            λ = {figure.lambdaOverall.toFixed(3)}
          </Badge>
        ) : null}
        {activeView === 'qq' && figure?.lambdaByCat?.length ? (
          <Stack gap={2}>
            {figure.lambdaByCat.map((entry) => (
              <Badge key={entry.cat} size="xs" variant="light" radius="sm" fullWidth>
                {entry.cat}: λ = {entry.lambda.toFixed(3)}
              </Badge>
            ))}
          </Stack>
        ) : null}
        {activeView !== 'qq' ? (
          <Stack gap={4}>
            <Text size="xs" fw={500}>
              Labels
            </Text>
            <Switch
              size="xs"
              checked={showLabels}
              onChange={(e) => setShowLabels(e.currentTarget.checked)}
              label="Top-N labels"
            />
          </Stack>
        ) : null}
        {activeView === 'qq' ? (
          <>
            <Stack gap={4}>
              <Text size="xs" fw={500}>
                Identity
              </Text>
              <Switch
                size="xs"
                checked={showIdentity}
                onChange={(e) => setShowIdentity(e.currentTarget.checked)}
                label="Identity line"
              />
            </Stack>
            <Stack gap={4}>
              <Text size="xs" fw={500}>
                95%
              </Text>
              <Switch
                size="xs"
                checked={showCi}
                onChange={(e) => setShowCi(e.currentTarget.checked)}
                label="95% null CI band"
                disabled={Boolean(config.category_col)}
              />
            </Stack>
            <Group gap="xs" grow>
              <NumberInput
                size="xs"
                label="Point size"
                value={pointSize}
                onChange={(v) => setPointSize(Math.max(2, Math.min(14, Number(v) || 5)))}
                min={2}
                max={14}
              />
            </Group>
          </>
        ) : null}
      </Stack>
    ),
    [
      activeView,
      figure,
      showLabels,
      showCi,
      showIdentity,
      pointSize,
      config.category_col,
    ],
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
  //
  // `contextTraces: 'drop'` in the QQ view: the 95% band is the null envelope
  // for n points across the whole set, not for any group's subset. And every
  // view stays `facetable: false`, the QQ x coordinate is a rank *within the
  // plotted set*, so per-group panels would read as each group's own QQ while
  // being drawn against the cohort's quantiles.
  const groupedFigure = useMemo(
    () =>
      figure
        ? splitFigureByGroups(figure, {
            groupRender,
            identitySlot: 0,
            facetable: false,
            ...(activeView === 'qq' ? { contextTraces: 'drop' as const } : {}),
            showLegend: true,
          })
        : figure,
    [figure, groupRender, activeView],
  );
  // Whether any point matched, for the dispatch's "not grouped" badge.
  useReportGroupColouring(groupRender, figure, groupedFigure);

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Volcano plot'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
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

interface BuiltFigure {
  tiers?: DeTier[];
  counts?: Record<string, number>;
  data: any[];
  layout: any;
  lambdaOverall?: number;
  lambdaByCat?: { cat: string; lambda: number }[];
}

/** Effect size against significance: the view the tile is named for. */
function buildVolcano(input: {
  xs: number[];
  sigRaw: number[];
  ids: (string | number)[];
  labels: (string | number)[];
  isNegLog10: boolean;
  effectTitle: string;
  sigTitle: string;
  sigThreshold: number;
  effectThreshold: number;
  topN: number;
  search: string;
  showLabels: boolean;
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
  glGranted: boolean;
}): BuiltFigure {
  const { xs, sigRaw, ids, labels, isNegLog10 } = input;
  const ys = isNegLog10
    ? sigRaw
    : sigRaw.map((p) => (p == null || p <= 0 ? null : -Math.log10(p)));
  const sigThresholdY = isNegLog10 ? input.sigThreshold : -Math.log10(input.sigThreshold);

  // Classify each point: significant + above-threshold effect ⇒ "hit".
  // The `tiers` array carries UP / DN / NS for the hover badge so the user
  // doesn't have to mentally re-derive it from x/y.
  const tiers = classifyTiers(xs, input.effectThreshold, (i) => {
    const y = ys[i];
    return y != null && y >= sigThresholdY;
  });

  // Top-N label selection, by combined (|x| × y) so both axes matter.
  const topIdx = rankTopN(
    xs.map((x, i) => (Math.abs(x) || 0) * (ys[i] ?? 0)),
    input.topN,
  );
  const matchedIdx = matchSearch(ids, labels, input.search);

  const annotations = input.showLabels
    ? xs
        .map((x, i) => {
          const y = ys[i];
          if (y == null) return null;
          if (!(matchedIdx ? matchedIdx.has(i) : topIdx.has(i))) return null;
          // Place each label slightly above its point with a thin connector
          // arrow. This keeps the (x, y) anchor on the point while moving the
          // text bounding box up by 16px, far cleaner when several top-N
          // labels cluster near the same effect/significance corner.
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

  return {
    tiers,
    counts: tierCounts(tiers),
    data: [
      adaptGlTrace(
        {
          type: 'scattergl' as const,
          mode: 'markers' as const,
          x: xs,
          y: ys,
          text: ids.map((v) => String(v ?? '')),
          // customdata threads label, raw significance and tier badge into the
          // hover so the tooltip reads UP / DN / NS + values without separate
          // per-tier traces. Slot 0 is the identity `splitFigureByGroups` joins on.
          customdata: xs.map((_, i) => [
            String(labels[i] ?? ids[i] ?? ''),
            sigRaw[i] ?? null,
            tiers[i],
          ]),
          hovertemplate:
            `<b>%{customdata[0]}</b>  <span style="opacity:0.7">[%{customdata[2]}]</span>` +
            `<br>${input.effectTitle}: %{x:.3f}` +
            `<br>${input.sigTitle}: %{customdata[1]:.2e}` +
            `<br>-log10(sig): %{y:.2f}` +
            `<extra></extra>`,
          marker: {
            color: tiers.map((t) => TIER_COLOURS[t]),
            // Binary size scheme so significant hits visually pop out from the
            // grey NS cloud without distracting magnitude variation.
            size: tiers.map((t) => (t === 'NS' ? 5 : 7)),
            opacity: 0.85,
          },
        },
        input.glGranted,
      ),
    ],
    layout: {
      ...plotlyThemeFragment(input.isDark, input.theme),
      margin: { l: 50, r: 20, t: 30, b: 40 },
      xaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: { text: input.effectTitle },
        zeroline: true,
      },
      yaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: { text: isNegLog10 ? input.sigTitle : `-log10(${input.sigTitle})` },
      },
      shapes: [
        { type: 'line' as const, x0: -input.effectThreshold, x1: -input.effectThreshold, yref: 'paper', y0: 0, y1: 1, line: DOTTED_GUIDE },
        { type: 'line' as const, x0: input.effectThreshold, x1: input.effectThreshold, yref: 'paper', y0: 0, y1: 1, line: DOTTED_GUIDE },
        { type: 'line' as const, xref: 'paper', x0: 0, x1: 1, y0: sigThresholdY, y1: sigThresholdY, line: DOTTED_GUIDE },
      ],
      annotations,
      showlegend: false,
      autosize: true,
    },
  };
}

/**
 * Mean abundance against fold change, the Bland-Altman reading.
 *
 * Same tier scheme as the volcano, so a hit stays a hit across the switch. The
 * significance column only gates the tiers here; the axes are both effect.
 */
function buildMa(input: {
  xs: number[];
  ys: number[];
  sigRaw: number[];
  ids: (string | number)[];
  labels: (string | number)[];
  xTitle: string;
  yTitle: string;
  sigTitle: string;
  sigThreshold: number;
  fcThreshold: number;
  topN: number;
  search: string;
  showLabels: boolean;
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
  glGranted: boolean;
}): BuiltFigure {
  const { xs, ys, sigRaw, ids, labels } = input;
  const hasSig = sigRaw.length > 0;
  const tiers = classifyTiers(
    ys,
    input.fcThreshold,
    (i) => !hasSig || (sigRaw[i] != null && sigRaw[i] < input.sigThreshold),
  );

  // Top-N by |fold change| × -log10(sig) when available, else by |FC| alone.
  const topIdx = rankTopN(
    ys.map((fc, i) => {
      const sig = hasSig && sigRaw[i] > 0 ? -Math.log10(sigRaw[i]) : 1;
      return Math.abs(fc || 0) * sig;
    }),
    input.topN,
  );
  const matchedIdx = matchSearch(ids, labels, input.search);

  const annotations = input.showLabels
    ? xs
        .map((x, i) => {
          if (!(matchedIdx ? matchedIdx.has(i) : topIdx.has(i))) return null;
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

  return {
    tiers,
    counts: tierCounts(tiers),
    data: [
      adaptGlTrace(
        {
          type: 'scattergl' as const,
          mode: 'markers' as const,
          x: xs,
          y: ys,
          text: ids.map((v) => String(v ?? '')),
          customdata: xs.map((_, i) => [
            String(labels[i] ?? ids[i] ?? ''),
            hasSig ? sigRaw[i] ?? null : null,
            tiers[i],
          ]),
          hovertemplate:
            `<b>%{customdata[0]}</b>  <span style="opacity:0.7">[%{customdata[2]}]</span>` +
            `<br>${input.xTitle}: %{x:.3f}` +
            `<br>${input.yTitle}: %{y:.3f}` +
            (hasSig ? `<br>${input.sigTitle}: %{customdata[1]:.2e}` : '') +
            `<extra></extra>`,
          marker: {
            color: tiers.map((t) => TIER_COLOURS[t]),
            size: tiers.map((t) => (t === 'NS' ? 5 : 7)),
            opacity: 0.85,
          },
        },
        input.glGranted,
      ),
    ],
    layout: {
      ...plotlyThemeFragment(input.isDark, input.theme),
      margin: { l: 50, r: 20, t: 30, b: 40 },
      xaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: { text: input.xTitle },
        zeroline: false,
      },
      yaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: { text: input.yTitle },
        zeroline: true,
      },
      shapes: [
        { type: 'line' as const, xref: 'paper', x0: 0, x1: 1, y0: input.fcThreshold, y1: input.fcThreshold, line: DOTTED_GUIDE },
        { type: 'line' as const, xref: 'paper', x0: 0, x1: 1, y0: -input.fcThreshold, y1: -input.fcThreshold, line: DOTTED_GUIDE },
      ],
      annotations,
      showlegend: false,
      autosize: true,
    },
  };
}

/**
 * Observed significance against the uniform null, with the inflation factor.
 *
 * Independent axis ranges (qqman / Hail convention): x bounded by the largest
 * expected value (about log10(N)), y free to grow with the hits. The identity
 * line still spans both corners, so it visibly exits the x frame when the
 * observed tail breaks from the null, which is the point of the plot.
 */
function buildQq(input: {
  ps: number[];
  ids: (string | number)[] | null;
  cats: (string | number)[] | null;
  showCi: boolean;
  showIdentity: boolean;
  pointSize: number;
  topN: number;
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
  glGranted: boolean;
}): BuiltFigure {
  const { ps, ids, cats } = input;
  const traces: any[] = [];
  let expectedMax = 0;
  let observedMax = 0;
  let lambdaOverall = NaN;
  const lambdaByCat: { cat: string; lambda: number }[] = [];

  const hoverTemplate = (withId: boolean) =>
    (withId ? '<b>%{text}</b><br>' : '') + 'expected: %{x:.3f}<br>observed: %{y:.3f}<extra></extra>';

  if (cats) {
    const names = Array.from(new Set(cats.map(String))).sort();
    const colours = stableColorMap(names, resolveCategoricalPalette(input.theme, TAB10_PALETTE));
    const allPs: number[] = [];
    for (const name of names) {
      const indices: number[] = [];
      for (let i = 0; i < cats.length; i++) if (String(cats[i]) === name) indices.push(i);
      const series = qqSeries(ps, indices, ids);
      if (series.n === 0) continue;
      expectedMax = Math.max(expectedMax, series.expected[0]);
      observedMax = Math.max(observedMax, ...series.observed);
      allPs.push(...series.ps);
      lambdaByCat.push({ cat: name, lambda: genomicInflation(series.ps) });
      traces.push(
        adaptGlTrace(
          {
            type: 'scattergl' as const,
            mode: 'markers' as const,
            name,
            x: series.expected,
            y: series.observed,
            text: series.ids,
            // Slot 0 is the feature, and only when the binding names one: with
            // no id column there is no identity to carry.
            ...(ids ? { customdata: series.ids.map((id) => [id]) } : {}),
            hovertemplate: hoverTemplate(Boolean(series.ids[0])),
            marker: { color: colours.get(name), size: input.pointSize, opacity: 0.85 },
          },
          input.glGranted,
        ),
      );
    }
    lambdaOverall = genomicInflation(allPs.sort((a, b) => a - b));
  } else {
    const series = qqSeries(
      ps,
      ps.map((_, i) => i),
      ids,
    );
    expectedMax = series.expected[0] ?? 0;
    observedMax = Math.max(0, ...series.observed);
    lambdaOverall = genomicInflation(series.ps);
    traces.push(
      adaptGlTrace(
        {
          type: 'scattergl' as const,
          mode: 'markers' as const,
          x: series.expected,
          y: series.observed,
          text: series.ids,
          ...(ids ? { customdata: series.ids.map((id) => [id]) } : {}),
          hovertemplate: hoverTemplate(Boolean(series.ids[0])),
          marker: { color: '#4C72B0', size: input.pointSize, opacity: 0.85 },
        },
        input.glGranted,
      ),
    );

    // Top-N hit labels, overlay text trace on the strongest observations.
    if (input.topN > 0 && series.ids[0]) {
      const ranked = series.observed
        .map((observed, i) => ({ observed, i }))
        .sort((a, b) => b.observed - a.observed)
        .slice(0, input.topN);
      traces.push({
        type: 'scatter' as const,
        mode: 'text' as const,
        x: ranked.map((r) => series.expected[r.i]),
        y: ranked.map((r) => series.observed[r.i] + observedMax * 0.03),
        text: ranked.map((r) => series.ids[r.i]),
        textposition: 'top center' as const,
        textfont: { size: 10, color: input.isDark ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.85)' },
        hoverinfo: 'skip',
        showlegend: false,
      });
    }

    if (input.showCi) {
      const band = qqConfidenceBand(series.n);
      traces.unshift(
        {
          type: 'scatter' as const,
          mode: 'lines' as const,
          x: band.x,
          y: band.upper,
          line: { width: 0 },
          showlegend: false,
          hoverinfo: 'skip',
        },
        {
          type: 'scatter' as const,
          mode: 'lines' as const,
          x: band.x,
          y: band.lower,
          fill: 'tonexty',
          fillcolor: input.isDark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.08)',
          line: { width: 0 },
          showlegend: false,
          hoverinfo: 'skip',
        },
      );
    }
  }

  const xUpper = expectedMax * 1.05;
  const yUpper = observedMax * 1.05;
  const diagonalUpper = Math.max(xUpper, yUpper);
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
      font: { size: 12, color: input.isDark ? '#fff' : '#222' },
      bgcolor: input.isDark ? 'rgba(20,20,20,0.6)' : 'rgba(255,255,255,0.7)',
      bordercolor: input.isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.2)',
      borderwidth: 1,
      borderpad: 4,
    });
  }

  return {
    data: traces,
    layout: {
      ...plotlyThemeFragment(input.isDark, input.theme),
      margin: { l: 60, r: 20, t: 20, b: 50 },
      xaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: { text: '-log10(expected)' },
        range: [0, xUpper],
      },
      yaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: { text: '-log10(observed)' },
        range: [0, yUpper],
      },
      shapes: input.showIdentity
        ? [
            {
              type: 'line' as const,
              x0: 0,
              y0: 0,
              x1: diagonalUpper,
              y1: diagonalUpper,
              line: { dash: 'dash', color: input.isDark ? '#ddd' : '#444', width: 1 },
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
}

export default VolcanoRenderer;
