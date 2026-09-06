import React, { useEffect, useMemo, useState } from 'react';
import {
  MultiSelect,
  SegmentedControl,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';

import {
  AdvancedVizKind,
  InteractiveFilter,
  StoredMetadata,
  fetchAdvancedVizData,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import AdvancedVizPlot from './AdvancedVizPlot';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeFragment,
} from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `GeneArrowTrackConfig` in
 *  `depictio/models/components/advanced_viz/configs.py`. Every key this file
 *  reads off `config` has to exist there — `test_advanced_viz_config_alignment`
 *  reads this source and fails the build otherwise. */
interface GeneArrowTrackConfig {
  contig_col: string;
  feature_id_col: string;
  start_col: string;
  end_col: string;
  strand_col: string;
  class_col?: string | null;
  label_col?: string | null;
  region_start_col?: string | null;
  region_end_col?: string | null;
  show_labels?: boolean;
  arrow_height?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: GeneArrowTrackConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

/** Always sent with the fetch: the kind is what selects the server's `"none"`
 *  sampling policy, and a uniform sample of a locus map is a gene
 *  neighbourhood with holes in it. */
const VIZ_KIND: AdvancedVizKind = 'gene_arrow_track';

/** Lane budget choices. A locus map is read a few contigs at a time; past ~10
 *  lanes the arrows are thinner than their own outline. */
const LANE_CHOICES = [
  { value: '4', label: '4 contigs' },
  { value: '8', label: '8 contigs' },
  { value: '16', label: '16 contigs' },
  { value: '32', label: '32 contigs' },
];

/** Class values that mean "not part of the cluster". Drawn grey rather than
 *  taking a palette hue, so the coloured core reads as the cluster and the
 *  neighbourhood reads as context. Recipes should spell it `flanking`. */
const NEUTRAL_CLASSES = new Set(['', 'flanking', 'flank', 'none', 'other', 'unknown', 'na', 'n/a']);

type Feature = {
  contig: string;
  id: string;
  label: string;
  start: number;
  end: number;
  /** Normalised to `+` / `-`; anything that is not minus draws pointing right. */
  strand: string;
  cls: string | null;
  regionStart: number | null;
  regionEnd: number | null;
};

type Lane = {
  contig: string;
  features: Feature[];
  /** Distinct highlighted intervals on this contig, in plot coordinates. */
  regions: Array<[number, number]>;
  min: number;
  max: number;
};

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

/** `+` unless the value reads as minus (`-`, `-1`, `minus`, `reverse`). */
const normStrand = (v: unknown): string => {
  const s = String(v ?? '').trim().toLowerCase();
  if (s.startsWith('-') || s === 'minus' || s === 'rev' || s === 'reverse' || s === 'r') return '-';
  return '+';
};

/**
 * The pentagon ring for one feature, in data coordinates.
 *
 * Five points plus an explicit closing point, so the trace can hold many rings
 * separated by nulls and still fill each of them (`fill: 'toself'` restarts at
 * every gap). The head is capped at the feature's own length, which turns a CDS
 * shorter than one head into a plain triangle rather than an inside-out arrow.
 */
const arrowRing = (
  x0: number,
  x1: number,
  y: number,
  half: number,
  headBp: number,
  strand: string,
): { xs: number[]; ys: number[] } => {
  const len = Math.max(x1 - x0, 0);
  const head = Math.min(len, headBp);
  if (strand === '-') {
    const xb = x0 + head;
    return {
      xs: [x1, xb, x0, xb, x1, x1],
      ys: [y - half, y - half, y, y + half, y + half, y - half],
    };
  }
  const xb = x1 - head;
  return {
    xs: [x0, xb, x1, xb, x0, x0],
    ys: [y - half, y - half, y, y + half, y + half, y - half],
  };
};

/**
 * Genomic neighbourhood viewer: one lane per contig, one strand-aware arrow per
 * coding sequence, positioned by base pair and coloured by class.
 *
 * Arrows are drawn as **filled scatter rings**, not layout shapes. Shapes are
 * the obvious way to draw a polygon in Plotly and are what the coverage track's
 * annotation strip uses — but a shape carries no hover and no legend entry, and
 * the whole point of a locus map is asking what a given arrow is. Grouping the
 * rings into one trace per class instead keeps the trace count at O(classes)
 * rather than O(features), gets a per-class legend for free, and leaves the
 * theming pass (`applyDataTheme`) something to work on. Hover then rides on a
 * separate transparent marker trace, three points across each arrow, because
 * `hoveron: 'fills'` reports one label for a whole multi-ring trace rather than
 * for the ring under the cursor.
 *
 * `gene_arrow_track` declares no selection, so this renderer emits none.
 */
const GeneArrowTrackRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const config = (metadata.config || {}) as GeneArrowTrackConfig;
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';

  const [showLabels, setShowLabels] = usePersistedVizControl<boolean>(metadata, 'show_labels', true);
  const [arrowHeight, setArrowHeight] = usePersistedVizControl<number>(metadata, 'arrow_height', 0.5);

  // View-only controls: the model has no field for any of these, and a config
  // key with no field is not merely unvalidated, it makes the whole component
  // unloadable (`extra="forbid"`). They stay local.
  const [selectedContigs, setSelectedContigs] = useState<string[]>([]);
  const [maxLanes, setMaxLanes] = useState<number>(8);
  const [align, setAlign] = useState<'absolute' | 'region'>('absolute');
  const [showRegions, setShowRegions] = useState<boolean>(true);
  const [laneOrder, setLaneOrder] = useState<'features' | 'name'>('features');

  const requiredCols = useMemo(() => {
    const cols = [
      config.contig_col,
      config.feature_id_col,
      config.start_col,
      config.end_col,
      config.strand_col,
      config.class_col,
      config.label_col,
      config.region_start_col,
      config.region_end_col,
    ];
    return Array.from(new Set(cols.filter((c): c is string => Boolean(c))));
  }, [
    config.contig_col,
    config.feature_id_col,
    config.start_col,
    config.end_col,
    config.strand_col,
    config.class_col,
    config.label_col,
    config.region_start_col,
    config.region_end_col,
  ]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const bound = Boolean(
    metadata.wf_id &&
      metadata.dc_id &&
      config.contig_col &&
      config.feature_id_col &&
      config.start_col &&
      config.end_col &&
      config.strand_col,
  );

  useEffect(() => {
    if (!bound) {
      setError('Gene arrow track: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id as string,
      dcId: metadata.dc_id as string,
      columns: requiredCols,
      filters,
      vizKind: VIZ_KIND,
      roles: {
        contig: config.contig_col,
        feature_id: config.feature_id_col,
        start: config.start_col,
        end: config.end_col,
        strand: config.strand_col,
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
    bound,
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filters),
    refreshTick,
  ]);

  /** Long rows to features, dropping anything without usable coordinates. */
  const features = useMemo<Feature[]>(() => {
    if (!rows) return [];
    const contigs = rows[config.contig_col] || [];
    const ids = rows[config.feature_id_col] || [];
    const starts = rows[config.start_col] || [];
    const ends = rows[config.end_col] || [];
    const strands = rows[config.strand_col] || [];
    const classes = config.class_col ? rows[config.class_col] : undefined;
    const labels = config.label_col ? rows[config.label_col] : undefined;
    const regionStarts = config.region_start_col ? rows[config.region_start_col] : undefined;
    const regionEnds = config.region_end_col ? rows[config.region_end_col] : undefined;

    const out: Feature[] = [];
    for (let i = 0; i < contigs.length; i++) {
      const s = num(starts[i]);
      const e = num(ends[i]);
      if (s === null || e === null) continue;
      const id = String(ids[i] ?? `feature ${i + 1}`);
      out.push({
        contig: String(contigs[i] ?? '(unknown)'),
        id,
        label: labels ? String(labels[i] ?? id) : id,
        // A GFF-style feature is stored low-to-high whatever the strand, but a
        // caller that writes start > end for a reverse gene must not vanish.
        start: Math.min(s, e),
        end: Math.max(s, e),
        strand: normStrand(strands[i]),
        cls: classes ? String(classes[i] ?? '') : null,
        regionStart: regionStarts ? num(regionStarts[i]) : null,
        regionEnd: regionEnds ? num(regionEnds[i]) : null,
      });
    }
    return out;
  }, [
    rows,
    config.contig_col,
    config.feature_id_col,
    config.start_col,
    config.end_col,
    config.strand_col,
    config.class_col,
    config.label_col,
    config.region_start_col,
    config.region_end_col,
  ]);

  const allContigs = useMemo(() => {
    const seen = new Map<string, number>();
    features.forEach((f) => seen.set(f.contig, (seen.get(f.contig) ?? 0) + 1));
    return Array.from(seen.entries())
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([contig]) => contig);
  }, [features]);

  /**
   * Lanes, in draw order, after the contig filter and the lane budget.
   *
   * `align: 'region'` re-expresses every coordinate as an offset from that
   * contig's region start, which is the only way lanes from unrelated contigs
   * line up on one shared x axis. Absolute stays the default: it is what the
   * bound columns actually say.
   */
  const lanes = useMemo<Lane[]>(() => {
    if (!features.length) return [];
    const wanted = selectedContigs.length ? new Set(selectedContigs) : null;
    const byContig = new Map<string, Feature[]>();
    features.forEach((f) => {
      if (wanted && !wanted.has(f.contig)) return;
      const arr = byContig.get(f.contig);
      if (arr) arr.push(f);
      else byContig.set(f.contig, [f]);
    });

    const built: Lane[] = [];
    byContig.forEach((feats, contig) => {
      const regionStarts = feats
        .map((f) => f.regionStart)
        .filter((v): v is number => v !== null);
      const offset =
        align === 'region' && regionStarts.length ? Math.min(...regionStarts) : 0;
      const shifted = offset
        ? feats.map((f) => ({
            ...f,
            start: f.start - offset,
            end: f.end - offset,
            regionStart: f.regionStart === null ? null : f.regionStart - offset,
            regionEnd: f.regionEnd === null ? null : f.regionEnd - offset,
          }))
        : feats;
      shifted.sort((a, b) => a.start - b.start);

      // One band per distinct interval, so a contig carrying two called
      // regions gets two bands rather than one that swallows the gap.
      const seenRegions = new Set<string>();
      const regions: Array<[number, number]> = [];
      shifted.forEach((f) => {
        if (f.regionStart === null || f.regionEnd === null) return;
        const key = `${f.regionStart}:${f.regionEnd}`;
        if (seenRegions.has(key)) return;
        seenRegions.add(key);
        regions.push([Math.min(f.regionStart, f.regionEnd), Math.max(f.regionStart, f.regionEnd)]);
      });

      built.push({
        contig,
        features: shifted,
        regions,
        min: Math.min(...shifted.map((f) => f.start)),
        max: Math.max(...shifted.map((f) => f.end)),
      });
    });

    built.sort((a, b) =>
      laneOrder === 'name'
        ? a.contig.localeCompare(b.contig)
        : b.features.length - a.features.length || a.contig.localeCompare(b.contig),
    );
    return built.slice(0, maxLanes);
  }, [features, selectedContigs, maxLanes, align, laneOrder]);

  const truncatedLanes = useMemo(() => {
    const shown = new Set(lanes.map((l) => l.contig));
    const pool = selectedContigs.length
      ? allContigs.filter((c) => selectedContigs.includes(c))
      : allContigs;
    return Math.max(pool.length - shown.size, 0);
  }, [lanes, allContigs, selectedContigs]);

  /** Mantine hues for the class colouring, same list the coverage track uses. */
  const palette = useMemo<string[]>(
    () => [
      theme.colors.blue[5],
      theme.colors.orange[5],
      theme.colors.green[5],
      theme.colors.grape[5],
      theme.colors.teal[5],
      theme.colors.red[5],
      theme.colors.violet[5],
      theme.colors.yellow[7],
      theme.colors.cyan[5],
      theme.colors.pink[5],
      theme.colors.lime[6],
      theme.colors.indigo[5],
    ],
    [theme.colors],
  );
  const neutralColor = isDark ? theme.colors.gray[6] : theme.colors.gray[5];

  const figure = useMemo<{ data: unknown[]; layout: Record<string, unknown> } | null>(() => {
    if (!lanes.length) return null;

    const xMin = Math.min(...lanes.map((l) => l.min));
    const xMax = Math.max(...lanes.map((l) => l.max));
    const span = Math.max(xMax - xMin, 1);
    const pad = span * 0.02;
    const half = Math.min(Math.max(arrowHeight, 0.1), 0.9) / 2;

    // Class -> colour, assigned over the classes actually on screen so the
    // legend never carries a hue nothing uses. Neutral classes keep grey.
    const classNames: string[] = [];
    lanes.forEach((lane) =>
      lane.features.forEach((f) => {
        const key = f.cls ?? '';
        if (!classNames.includes(key)) classNames.push(key);
      }),
    );
    classNames.sort((a, b) => a.localeCompare(b));
    const classColor = new Map<string, string>();
    let hue = 0;
    classNames.forEach((name) => {
      if (NEUTRAL_CLASSES.has(name.toLowerCase())) classColor.set(name, neutralColor);
      else classColor.set(name, palette[hue++ % palette.length]);
    });

    // ---- backbone: the contig line each lane's arrows sit on ---------------
    const backboneX: Array<number | null> = [];
    const backboneY: Array<number | null> = [];
    lanes.forEach((lane, i) => {
      backboneX.push(lane.min, lane.max, null);
      backboneY.push(i, i, null);
    });

    const traces: unknown[] = [
      {
        type: 'scatter',
        mode: 'lines',
        x: backboneX,
        y: backboneY,
        line: { color: isDark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.25)', width: 1 },
        hoverinfo: 'skip',
        showlegend: false,
      },
    ];

    // ---- arrows: one filled trace per class -------------------------------
    const ringsByClass = new Map<string, { xs: Array<number | null>; ys: Array<number | null> }>();
    const hoverX: number[] = [];
    const hoverY: number[] = [];
    const hoverData: unknown[][] = [];
    const annotations: Record<string, unknown>[] = [];

    lanes.forEach((lane, laneIdx) => {
      lane.features.forEach((f) => {
        const key = f.cls ?? '';
        const bucket = ringsByClass.get(key) ?? { xs: [], ys: [] };
        const len = Math.max(f.end - f.start, 1);
        const headBp = Math.max(span * 0.006, len * 0.3);
        const ring = arrowRing(f.start, f.end, laneIdx, half, headBp, f.strand);
        bucket.xs.push(...ring.xs, null);
        bucket.ys.push(...ring.ys, null);
        ringsByClass.set(key, bucket);

        // Three hover anchors across the body, so the target is the arrow
        // rather than a single pixel at its centre.
        const mid = (f.start + f.end) / 2;
        [f.start + len * 0.15, mid, f.end - len * 0.15].forEach((x) => {
          hoverX.push(x);
          hoverY.push(laneIdx);
          hoverData.push([f.label, f.contig, f.start, f.end, len, f.strand, f.cls ?? '']);
        });

        // Labels only where the arrow is wide enough to sit under one without
        // colliding with its neighbour, and only while the lanes are few
        // enough that a row of text still fits between them.
        if (showLabels && lanes.length <= 12 && len >= span * 0.03) {
          annotations.push({
            xref: 'x',
            yref: 'y',
            x: mid,
            y: laneIdx - half - 0.16,
            text: f.label,
            showarrow: false,
            font: { size: 9 },
            xanchor: 'center',
            yanchor: 'middle',
          });
        }
      });
    });

    const multiClass = Boolean(config.class_col) && classNames.length > 1;
    classNames.forEach((name) => {
      const bucket = ringsByClass.get(name);
      if (!bucket) return;
      const color = classColor.get(name) ?? palette[0];
      traces.push({
        type: 'scatter',
        mode: 'lines',
        x: bucket.xs,
        y: bucket.ys,
        fill: 'toself',
        fillcolor: `${color}${isDark ? 'AA' : 'BB'}`,
        line: { color, width: 1 },
        name: name || 'CDS',
        legendgroup: name || 'CDS',
        showlegend: multiClass,
        hoverinfo: 'skip',
      });
    });

    traces.push({
      type: 'scatter',
      mode: 'markers',
      x: hoverX,
      y: hoverY,
      marker: { size: 12, color: 'rgba(0,0,0,0)', line: { width: 0 } },
      customdata: hoverData,
      hovertemplate:
        '<b>%{customdata[0]}</b><br>%{customdata[1]}' +
        '<br>%{customdata[2]:,} to %{customdata[3]:,} bp (%{customdata[4]:,} bp, %{customdata[5]})' +
        (config.class_col ? '<br>class: %{customdata[6]}' : '') +
        '<extra></extra>',
      showlegend: false,
    });

    // ---- region bands ------------------------------------------------------
    const shapes: Record<string, unknown>[] = [];
    if (showRegions) {
      lanes.forEach((lane, laneIdx) => {
        lane.regions.forEach(([r0, r1]) => {
          shapes.push({
            type: 'rect',
            xref: 'x',
            yref: 'y',
            x0: r0,
            x1: r1,
            y0: laneIdx - 0.46,
            y1: laneIdx + 0.46,
            fillcolor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)',
            line: { width: 0 },
            layer: 'below',
          });
        });
      });
    }

    const layout: Record<string, unknown> = {
      ...plotlyThemeFragment(isDark, theme),
      margin: { l: 8, r: 16, t: 8, b: 40 },
      autosize: true,
      hovermode: 'closest',
      showlegend: multiClass,
      legend: { orientation: 'h', x: 0, y: 1.06, font: { size: 10 } },
      xaxis: {
        ...plotlyAxisOverrides(isDark, theme),
        title: {
          text: align === 'region' ? 'Offset from region start (bp)' : 'Position (bp)',
          font: { size: 11 },
        },
        range: [xMin - pad, xMax + pad],
        zeroline: false,
        automargin: true,
      },
      yaxis: {
        ...plotlyAxisOverrides(isDark, theme),
        tickmode: 'array',
        tickvals: lanes.map((_, i) => i),
        ticktext: lanes.map((l) => l.contig),
        tickfont: { size: 9 },
        // Reversed, so the first lane is the top one and adding lanes grows
        // downwards the way a stack of tracks is read.
        range: [lanes.length - 0.5, -0.6],
        showgrid: false,
        zeroline: false,
        automargin: true,
      },
      shapes,
      annotations,
    };

    return { data: traces, layout };
  }, [
    lanes,
    palette,
    neutralColor,
    isDark,
    theme,
    arrowHeight,
    showLabels,
    showRegions,
    align,
    config.class_col,
  ]);

  const hasRegions = Boolean(config.region_start_col && config.region_end_col);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <MultiSelect
          size="xs"
          label="Contigs"
          value={selectedContigs}
          onChange={setSelectedContigs}
          data={allContigs.map((c) => ({ value: c, label: c }))}
          placeholder={rows ? 'All contigs' : 'Loading…'}
          searchable
          clearable
        />
        <Select
          size="xs"
          label="Lanes shown"
          value={String(maxLanes)}
          onChange={(v) => setMaxLanes(Number(v ?? '8'))}
          data={LANE_CHOICES}
        />
        <Select
          size="xs"
          label="Lane order"
          value={laneOrder}
          onChange={(v) => setLaneOrder((v as 'features' | 'name') ?? 'features')}
          data={[
            { value: 'features', label: 'Most features first' },
            { value: 'name', label: 'Contig name' },
          ]}
        />
        {truncatedLanes > 0 ? (
          <Text size="xs" c="dimmed">
            {truncatedLanes} more contig{truncatedLanes === 1 ? '' : 's'} not shown — raise the lane
            budget or pick contigs above.
          </Text>
        ) : null}
        {hasRegions ? (
          <Stack gap={4}>
            <Text size="xs" fw={500}>
              Align lanes
            </Text>
            <SegmentedControl
              size="xs"
              fullWidth
              value={align}
              onChange={(v) => setAlign(v as 'absolute' | 'region')}
              data={[
                { value: 'absolute', label: 'Absolute bp' },
                { value: 'region', label: 'Region start' },
              ]}
            />
          </Stack>
        ) : null}
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Annotations
          </Text>
          {hasRegions ? (
            <Switch
              size="xs"
              checked={showRegions}
              onChange={(e) => setShowRegions(e.currentTarget.checked)}
              label="Highlight region"
            />
          ) : null}
          <Switch
            size="xs"
            checked={showLabels}
            onChange={(e) => setShowLabels(e.currentTarget.checked)}
            label="Feature labels"
          />
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Arrow height
          </Text>
          <Slider
            size="xs"
            min={0.2}
            max={0.9}
            step={0.05}
            value={arrowHeight}
            onChange={setArrowHeight}
            label={(v) => v.toFixed(2)}
          />
        </Stack>
      </Stack>
    ),
    [
      selectedContigs,
      allContigs,
      rows,
      maxLanes,
      laneOrder,
      truncatedLanes,
      hasRegions,
      align,
      showRegions,
      showLabels,
      arrowHeight,
      setShowLabels,
      setArrowHeight,
    ],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Gene arrow track'}
      subtitle={(metadata as { description?: string; subtitle?: string }).description}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={
        rows && (features.length === 0 || lanes.length === 0) ? 'No features to draw' : undefined
      }
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? (
        <AdvancedVizPlot
          data={applyDataTheme(figure.data, isDark, theme) as any}
          layout={
            applyLayoutTheme(
              { ...(figure.layout as any), width: undefined, height: undefined, autosize: true },
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

export default GeneArrowTrackRenderer;
