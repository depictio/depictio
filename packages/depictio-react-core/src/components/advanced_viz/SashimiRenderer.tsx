import React, { useEffect, useMemo, useState } from 'react';
import {
  NumberInput,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';

import {
  type AdvancedVizKind,
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { resolveCategoricalPalette, stableColorMap } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import AdvancedVizPlot from './AdvancedVizPlot';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeColors,
  plotlyThemeFragment,
} from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `SashimiConfig` (depictio/models/components/advanced_viz/configs.py).
 *  Only keys declared there may be read — see
 *  `tests/models/test_advanced_viz_config_alignment.py`. */
interface SashimiConfig {
  chr_col: string;
  start_col: string;
  end_col: string;
  count_col: string;
  sample_col?: string | null;
  annotation_col?: string | null;
  min_count?: number;
  top_n?: number;
  log_width?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: SashimiConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

/** Sent so the server applies this kind's reduction policy: `sampling.py` maps
 *  sashimi to "none" — never sample, which is what a client-side top-N needs. */
const SASHIMI_KIND: AdvancedVizKind = 'sashimi';

/** Points sampled along each quadratic bezier. 40 is smooth at tile size and
 *  keeps a 50-arc panel under ~2 000 SVG points. */
const ARC_SAMPLES = 40;

/** Plotly sets line width per trace, not per point, so arcs are quantised into
 *  this many width levels and every arc in a level is concatenated (null
 *  separated) into one trace. Trace count is then lanes x categories x levels
 *  instead of one per junction — the difference between ~20 traces and ~400 on
 *  a faceted panel. */
const WIDTH_LEVELS = 7;
const MIN_ARC_WIDTH = 1;

/** Arc apexes span this fraction of a lane, scaled by junction span so nested
 *  junctions sit under the longer ones they fall inside rather than on top of
 *  them. The lane's y range leaves headroom above 1 for the count labels. */
const MIN_ARC_HEIGHT = 0.34;
const MAX_ARC_HEIGHT = 1;
const LANE_Y_RANGE: [number, number] = [-0.06, 1.3];

/** Panels past this are drawn but unreadable; the note in the controls says so. */
const MAX_LANES_HINT = 8;

/** Junctions further apart than this start a new locus. A whole chromosome is
 *  the wrong x range for arcs: the ctatsplicing megatest puts three gene loci
 *  (13.9 Mb, 55 Mb and 140.8 Mb) on chr7, and at that zoom every intron is a
 *  hairline spike. Splicing is local, so the picker offers loci and the busiest
 *  one is the opening view; whole-chromosome entries stay available under their
 *  own group. 1 Mb is far wider than any gene and far narrower than the gaps
 *  between the loci a targeted panel reports. */
const LOCUS_GAP_BP = 1_000_000;

/** How many loci the picker lists, busiest first. */
const MAX_LOCUS_OPTIONS = 30;

/** Count labels are drawn for the strongest junctions of each lane only —
 *  every apex labelled turns a dense locus into a wall of digits. */
const APEX_LABELS_PER_LANE = 12;

interface Junction {
  chrom: string;
  start: number;
  end: number;
  count: number;
  lane: string;
  annotation: string | null;
}

/** One readable x range: a cluster of junctions, or a whole chromosome. */
interface Region {
  key: string;
  label: string;
  chrom: string;
  start: number;
  end: number;
  n: number;
  whole: boolean;
}

const SINGLE_LANE = '(all)';

/** Number of the form 1_234_567, matching the bp axis ticks. */
const bp = (v: number) => v.toLocaleString();

/** Compact coordinate for a picker label. */
const shortPos = (v: number) =>
  v >= 1e6 ? `${(v / 1e6).toFixed(2)} Mb` : v >= 1e3 ? `${(v / 1e3).toFixed(1)} kb` : `${v} bp`;

const SashimiRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as SashimiConfig;

  const [minCount, setMinCount] = usePersistedVizControl<number>(metadata, 'min_count', 1);
  const [topN, setTopN] = usePersistedVizControl<number>(metadata, 'top_n', 50);
  const [logWidth, setLogWidth] = usePersistedVizControl<boolean>(metadata, 'log_width', true);
  // Local-only: no field on SashimiConfig carries them, and a region pick is a
  // reading position rather than an authored default.
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null);
  const [showCounts, setShowCounts] = useState<boolean>(true);
  const [maxArcWidth, setMaxArcWidth] = useState<number>(9);

  const requiredCols = useMemo(
    () =>
      [
        config.chr_col,
        config.start_col,
        config.end_col,
        config.count_col,
        ...(config.sample_col ? [config.sample_col] : []),
        ...(config.annotation_col ? [config.annotation_col] : []),
      ].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 4) {
      setError('Sashimi: missing data binding');
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
      vizKind: SASHIMI_KIND,
      roles: {
        chr: config.chr_col,
        start: config.start_col,
        end: config.end_col,
        count: config.count_col,
      },
    })
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
  }, [
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filters),
    refreshTick,
  ]);

  /** Every well-formed junction in the frame, before the min-count cut. */
  const junctions = useMemo<Junction[]>(() => {
    if (!rows) return [];
    const chrom = rows[config.chr_col] || [];
    const starts = rows[config.start_col] || [];
    const ends = rows[config.end_col] || [];
    const counts = rows[config.count_col] || [];
    const lanes = config.sample_col ? rows[config.sample_col] || [] : null;
    const notes = config.annotation_col ? rows[config.annotation_col] || [] : null;

    const out: Junction[] = [];
    for (let i = 0; i < starts.length; i++) {
      const start = Number(starts[i]);
      const end = Number(ends[i]);
      const count = Number(counts[i]);
      if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(count)) continue;
      // A junction with no span has no arc to draw; drawing one collapses to a
      // vertical spike at a single base.
      if (end === start) continue;
      out.push({
        chrom: String(chrom[i] ?? ''),
        start: Math.min(start, end),
        end: Math.max(start, end),
        count,
        lane: lanes ? String(lanes[i] ?? SINGLE_LANE) : SINGLE_LANE,
        annotation: notes ? String(notes[i] ?? '') || null : null,
      });
    }
    return out;
  }, [rows, config.chr_col, config.start_col, config.end_col, config.count_col, config.sample_col, config.annotation_col]);

  const supported = useMemo(
    () => junctions.filter((j) => j.count >= minCount),
    [junctions, minCount],
  );

  /** The x ranges worth opening on: one entry per junction cluster, busiest
   *  first, plus a whole-chromosome entry for each chromosome. */
  const regions = useMemo<Region[]>(() => {
    const byChrom = new Map<string, Junction[]>();
    for (const j of supported) {
      const bucket = byChrom.get(j.chrom);
      if (bucket) bucket.push(j);
      else byChrom.set(j.chrom, [j]);
    }
    const loci: Region[] = [];
    const whole: Region[] = [];
    for (const [chrom, arcs] of byChrom.entries()) {
      const sorted = arcs.slice().sort((a, b) => a.start - b.start);
      let start = sorted[0].start;
      let end = sorted[0].end;
      let n = 0;
      const flush = () => {
        loci.push({
          key: `locus:${chrom}:${start}-${end}`,
          label: `${chrom}:${shortPos(start)}-${shortPos(end)} (${n})`,
          chrom,
          start,
          end,
          n,
          whole: false,
        });
      };
      for (const j of sorted) {
        if (n > 0 && j.start - end > LOCUS_GAP_BP) {
          flush();
          start = j.start;
          end = j.end;
          n = 0;
        }
        end = Math.max(end, j.end);
        n += 1;
      }
      flush();
      whole.push({
        key: `chrom:${chrom}`,
        label: `${chrom} whole (${arcs.length})`,
        chrom,
        start: Math.min(...arcs.map((a) => a.start)),
        end: Math.max(...arcs.map((a) => a.end)),
        n: arcs.length,
        whole: true,
      });
    }
    loci.sort((a, b) => b.n - a.n || a.chrom.localeCompare(b.chrom) || a.start - b.start);
    whole.sort((a, b) => b.n - a.n || a.chrom.localeCompare(b.chrom));
    return [...loci.slice(0, MAX_LOCUS_OPTIONS), ...whole];
  }, [supported]);

  // Derived rather than stored so a filter change that empties the current
  // region falls back on its own instead of leaving an empty panel.
  const activeRegion =
    regions.find((r) => r.key === selectedRegion) ?? regions[0] ?? null;

  /** The junctions actually drawn: one region, strongest `top_n` per lane.
   *  Per lane rather than overall so a quiet sample keeps a panel of its own
   *  arcs instead of being crowded out by a deeply sequenced one. */
  const { lanes, visible } = useMemo(() => {
    const byLane = new Map<string, Junction[]>();
    for (const j of supported) {
      if (!activeRegion || j.chrom !== activeRegion.chrom) continue;
      if (!activeRegion.whole && (j.start < activeRegion.start || j.end > activeRegion.end))
        continue;
      const bucket = byLane.get(j.lane);
      if (bucket) bucket.push(j);
      else byLane.set(j.lane, [j]);
    }
    const laneNames = Array.from(byLane.keys()).sort((a, b) =>
      a.localeCompare(b, undefined, { numeric: true }),
    );
    const kept: Junction[] = [];
    for (const lane of laneNames) {
      const arcs = (byLane.get(lane) ?? []).slice().sort((a, b) => b.count - a.count);
      kept.push(...arcs.slice(0, Math.max(1, topN)));
    }
    return { lanes: laneNames, visible: kept };
  }, [supported, activeRegion, topN]);

  const annotationValues = useMemo(
    () => Array.from(new Set(junctions.map((j) => j.annotation).filter((a): a is string => !!a))),
    [junctions],
  );

  const figure = useMemo<{ data: unknown[]; layout: Record<string, unknown> } | null>(() => {
    if (!visible.length || !lanes.length) return null;
    const colors = plotlyThemeColors(isDark, theme);
    const palette = resolveCategoricalPalette(theme);
    const annotationColour = stableColorMap(annotationValues, palette);
    const baseColour = palette[0];

    const counts = visible.map((j) => j.count);
    const countMin = Math.min(...counts);
    const countMax = Math.max(...counts);
    const spans = visible.map((j) => j.end - j.start);
    const maxSpan = Math.max(...spans);
    const xMin = Math.min(...visible.map((j) => j.start));
    const xMax = Math.max(...visible.map((j) => j.end));
    const xPad = Math.max((xMax - xMin) * 0.03, 1);

    /** Read support -> width level. Log-scaled by default: junction support is
     *  heavy-tailed (a 1 000-read exon-exon junction beside a 3-read one), so
     *  a linear map draws every minor arc as the same hairline. */
    const levelFor = (count: number) => {
      const scale = (v: number) => (logWidth ? Math.log10(1 + Math.max(0, v)) : Math.max(0, v));
      const lo = scale(countMin);
      const hi = scale(countMax);
      const t = hi > lo ? (scale(count) - lo) / (hi - lo) : 1;
      return Math.max(0, Math.min(WIDTH_LEVELS - 1, Math.round(t * (WIDTH_LEVELS - 1))));
    };
    const widthForLevel = (level: number) =>
      MIN_ARC_WIDTH + (level / (WIDTH_LEVELS - 1)) * Math.max(0, maxArcWidth - MIN_ARC_WIDTH);

    /** Apex height, by span rather than by count: count is already the line
     *  width, and nesting is what the reader needs to see. */
    const heightFor = (span: number) =>
      MIN_ARC_HEIGHT +
      (MAX_ARC_HEIGHT - MIN_ARC_HEIGHT) * (maxSpan > 0 ? Math.sqrt(span / maxSpan) : 1);

    const laneRef = (laneIdx: number) => (laneIdx === 0 ? 'y' : `y${laneIdx + 1}`);

    type PathGroup = {
      x: (number | null)[];
      y: (number | null)[];
      text: string[];
      width: number;
      colour: string;
      category: string | null;
      yaxis: string;
    };
    const groups = new Map<string, PathGroup>();
    const annotations: Record<string, unknown>[] = [];
    const shapes: Record<string, unknown>[] = [];
    const endpointX: Record<string, number[]> = {};

    lanes.forEach((lane, laneIdx) => {
      const yref = laneRef(laneIdx);
      endpointX[lane] = [];
      shapes.push({
        type: 'line',
        xref: 'x',
        yref,
        x0: xMin - xPad,
        x1: xMax + xPad,
        y0: 0,
        y1: 0,
        line: { color: colors.zeroLineColor, width: 1 },
        layer: 'below',
      });

      const laneArcs = visible
        .filter((j) => j.lane === lane)
        .slice()
        .sort((a, b) => b.count - a.count);

      laneArcs.forEach((j, rank) => {
        const level = levelFor(j.count);
        const colour = j.annotation ? annotationColour.get(j.annotation) : baseColour;
        const key = `${laneIdx}|${j.annotation ?? ''}|${level}`;
        let group = groups.get(key);
        if (!group) {
          group = {
            x: [],
            y: [],
            text: [],
            width: widthForLevel(level),
            colour,
            category: j.annotation,
            yaxis: yref,
          };
          groups.set(key, group);
        }

        // Quadratic bezier from (start, 0) to (end, 0) with the control point
        // at twice the apex height, sampled into a path so every point on the
        // arc carries the junction's own hover text. x stays linear in t
        // because the control point sits at the midpoint.
        const apex = heightFor(j.end - j.start);
        const label =
          `${j.chrom}:${bp(j.start)}-${bp(j.end)}` +
          `<br>${config.count_col}: ${j.count.toLocaleString()}` +
          `<br>span: ${bp(j.end - j.start)} bp` +
          (config.sample_col ? `<br>${config.sample_col}: ${lane}` : '') +
          (j.annotation ? `<br>${config.annotation_col}: ${j.annotation}` : '');
        for (let k = 0; k <= ARC_SAMPLES; k++) {
          const t = k / ARC_SAMPLES;
          group.x.push(j.start + t * (j.end - j.start));
          group.y.push(4 * apex * t * (1 - t));
          group.text.push(label);
        }
        // A null break ends the path so the next arc in this group does not
        // inherit a segment from the previous one's acceptor.
        group.x.push(null);
        group.y.push(null);
        group.text.push('');

        endpointX[lane].push(j.start, j.end);

        if (showCounts && rank < APEX_LABELS_PER_LANE) {
          annotations.push({
            xref: 'x',
            yref,
            x: (j.start + j.end) / 2,
            y: apex,
            yanchor: 'bottom',
            text: j.count.toLocaleString(),
            showarrow: false,
            font: { size: 10, color: colors.textColor },
          });
        }
      });
    });

    const traces: unknown[] = [];
    const legendSeen = new Set<string>();
    for (const group of groups.values()) {
      const category = group.category;
      const showlegend = category != null && !legendSeen.has(category);
      if (category != null) legendSeen.add(category);
      traces.push({
        type: 'scatter',
        mode: 'lines',
        x: group.x,
        y: group.y,
        text: group.text,
        hovertemplate: '%{text}<extra></extra>',
        // Straight segments between the sampled bezier points: the curve is
        // already ours, and Plotly's spline fit would overshoot the baseline at
        // the donor and acceptor feet.
        line: { color: group.colour, width: group.width },
        name: category ?? 'Junctions',
        legendgroup: category ?? 'junctions',
        showlegend,
        connectgaps: false,
        xaxis: 'x',
        yaxis: group.yaxis,
      });
    }

    // Donor / acceptor ticks on the baseline: without them a tall arc's feet
    // are hard to place against the axis.
    lanes.forEach((lane, laneIdx) => {
      const xs = endpointX[lane] ?? [];
      if (!xs.length) return;
      traces.push({
        type: 'scatter',
        mode: 'markers',
        x: xs,
        y: xs.map(() => 0),
        marker: { symbol: 'line-ns-open', size: 7, color: colors.textColor, opacity: 0.55 },
        hoverinfo: 'skip',
        showlegend: false,
        xaxis: 'x',
        yaxis: laneRef(laneIdx),
      });
    });

    const layout: Record<string, unknown> = {
      ...plotlyThemeFragment(isDark, theme),
      margin: { l: lanes.length > 1 ? 88 : 24, r: 16, t: 8, b: 36 },
      autosize: true,
      hovermode: 'closest',
      showlegend: legendSeen.size > 0,
      legend: { orientation: 'h', x: 0, y: 1.06, font: { size: 10 } },
      shapes,
      annotations,
    };

    const rowSize = 1 / lanes.length;
    lanes.forEach((lane, laneIdx) => {
      const key = laneIdx === 0 ? 'yaxis' : `yaxis${laneIdx + 1}`;
      const bottom = 1 - (laneIdx + 1) * rowSize;
      layout[key] = {
        ...plotlyAxisOverrides(isDark, theme),
        domain: [bottom, bottom + rowSize - (lanes.length > 1 ? 0.02 : 0)],
        range: LANE_Y_RANGE,
        // Arc height encodes junction span, not a measurable quantity, so the
        // ticks would invite a reading that isn't there.
        showticklabels: false,
        showgrid: false,
        zeroline: false,
        fixedrange: true,
        title:
          lanes.length > 1
            ? { text: lane, font: { size: 10, color: colors.textColor }, standoff: 6 }
            : { text: '' },
      };
    });

    layout.xaxis = {
      ...plotlyAxisOverrides(isDark, theme),
      title: { text: `${activeRegion?.chrom ?? config.chr_col} (bp)`, font: { size: 11 } },
      range: [xMin - xPad, xMax + xPad],
      tickformat: ',d',
      zeroline: false,
      anchor: 'free',
      position: 0,
      automargin: true,
    };

    return { data: traces, layout };
  }, [
    visible,
    lanes,
    annotationValues,
    activeRegion,
    logWidth,
    maxArcWidth,
    showCounts,
    isDark,
    theme,
    config.chr_col,
    config.count_col,
    config.sample_col,
    config.annotation_col,
  ]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Select
          size="xs"
          label="Region"
          value={activeRegion?.key ?? null}
          onChange={setSelectedRegion}
          data={[
            {
              group: 'Loci',
              items: regions
                .filter((r) => !r.whole)
                .map((r) => ({ value: r.key, label: r.label })),
            },
            {
              group: 'Whole chromosome',
              items: regions.filter((r) => r.whole).map((r) => ({ value: r.key, label: r.label })),
            },
          ]}
          placeholder={rows ? 'No junctions' : 'Loading…'}
          disabled={regions.length < 2}
          searchable
          comboboxProps={{ withinPortal: true }}
        />
        <NumberInput
          size="xs"
          label="Min supporting reads"
          min={0}
          step={1}
          value={minCount}
          onChange={(v) => setMinCount(Math.max(0, Number(v) || 0))}
        />
        <NumberInput
          size="xs"
          label={config.sample_col ? 'Max junctions per sample' : 'Max junctions'}
          min={1}
          step={5}
          value={topN}
          onChange={(v) => setTopN(Math.max(1, Number(v) || 1))}
        />
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Arc width
          </Text>
          <Switch
            size="xs"
            checked={logWidth}
            onChange={(e) => setLogWidth(e.currentTarget.checked)}
            label="Log-scaled arc width"
          />
          <Text size="xs" c="dimmed">
            Thickest arc: {maxArcWidth} px
          </Text>
          <Slider size="xs" min={3} max={18} value={maxArcWidth} onChange={setMaxArcWidth} />
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Annotations
          </Text>
          <Switch
            size="xs"
            checked={showCounts}
            onChange={(e) => setShowCounts(e.currentTarget.checked)}
            label="Read count at each apex"
          />
        </Stack>
        {lanes.length > MAX_LANES_HINT ? (
          <Text size="xs" c="dimmed">
            {lanes.length} samples stacked. Filter down to a few for a readable panel.
          </Text>
        ) : null}
        {rows ? (
          <Text size="xs" c="dimmed">
            {visible.length.toLocaleString()} of {junctions.length.toLocaleString()} junctions
            {activeRegion ? ` in ${activeRegion.chrom}` : ''}
            {minCount > 1 ? `, at least ${minCount} reads` : ''}
          </Text>
        ) : null}
      </Stack>
    ),
    [
      activeRegion,
      regions,
      rows,
      minCount,
      topN,
      logWidth,
      showCounts,
      maxArcWidth,
      lanes.length,
      visible.length,
      junctions.length,
      config.sample_col,
    ],
  );

  /** The data popover shows the arcs on screen rather than the fetched frame:
   *  a sashimi drops most of its rows on purpose (one chromosome, min count,
   *  top-N), so the raw frame would not be the thing being looked at. */
  const dataRows = useMemo<Record<string, unknown[]> | undefined>(() => {
    if (!rows) return undefined;
    const out: Record<string, unknown[]> = {
      [config.chr_col]: visible.map((j) => j.chrom),
      [config.start_col]: visible.map((j) => j.start),
      [config.end_col]: visible.map((j) => j.end),
      [config.count_col]: visible.map((j) => j.count),
    };
    if (config.sample_col) out[config.sample_col] = visible.map((j) => j.lane);
    if (config.annotation_col) out[config.annotation_col] = visible.map((j) => j.annotation ?? '');
    return out;
  }, [rows, visible, config.chr_col, config.start_col, config.end_col, config.count_col, config.sample_col, config.annotation_col]);

  const emptyMessage = !rows
    ? undefined
    : junctions.length === 0
      ? 'No splice junctions in this data collection'
      : visible.length === 0
        ? `No junction with at least ${minCount} supporting read${minCount === 1 ? '' : 's'}`
        : undefined;

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Splice junctions'}
      subtitle={(metadata as { description?: string; subtitle?: string }).description}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={emptyMessage}
      dataRows={dataRows}
      dataColumns={requiredCols}
    >
      {figure ? (
        <AdvancedVizPlot
          data={applyDataTheme(figure.data, isDark, theme) as any}
          layout={
            applyLayoutTheme(
              { ...figure.layout, width: undefined, height: undefined, autosize: true },
              isDark,
              theme,
            ) as any
          }
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default SashimiRenderer;
