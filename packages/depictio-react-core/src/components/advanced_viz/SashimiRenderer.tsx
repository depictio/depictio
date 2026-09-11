import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  ColorInput,
  Group,
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
import {
  mantineCategoricalPalette,
  resolveCategoricalPalette,
  stableColorMap,
} from '../../colors';
import { useFullscreenPortalTarget } from '../chrome/useFullscreenPortalTarget';
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
  show_support_track?: boolean;
  show_gene_model?: boolean;
  support_track_height?: number;
  gene_model_height?: number;
  arc_height?: number;
  arc_colors?: Record<string, string> | null;
  coverage_wf_id?: string | null;
  coverage_dc_id?: string | null;
  coverage_chr_col?: string;
  coverage_position_col?: string;
  coverage_end_col?: string | null;
  coverage_value_col?: string;
  coverage_sample_col?: string | null;
  show_coverage?: boolean;
  coverage_height?: number;
  coverage_color?: string | null;
  coverage_log?: boolean;
  color_by?: 'annotation' | 'sample';
  max_arc_width?: number;
  arc_width_by_support?: boolean;
  arc_split?: 'annotation' | 'alternate';
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: SashimiConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

/** Sent so the server applies this kind's reduction policy: `sampling.py` maps
 *  sashimi to "none" — never sample, which is what a client-side top-N needs. */
const SASHIMI_KIND: AdvancedVizKind = 'sashimi';

/** How far in from each foot the arc's control points sit, as a share of the
 *  span. Small values give a pointed arc, large ones the flat-topped shape a
 *  sashimi is drawn with. */
const ARC_SHOULDER = 0.22;
/** How far an arc foot may walk along the coverage, in bins and as a share of
 *  the intron it spans, to find the exon edge it belongs on. */
const FOOT_SNAP_BINS = 3;
const FOOT_SNAP_SPAN_SHARE = 0.25;
/** What counts as the exon's plateau, as a share of the deepest bin in that
 *  window. The intron floor of a real RNA-seq track is a few percent of the
 *  exon around it, so half is a wide margin either way. */
const FOOT_PLATEAU_SHARE = 0.5;

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
const LANE_Y_RANGE: [number, number] = [-0.06, 1.42];

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

/** Key under which a custom colour is stored when the binding has no
 *  annotation column, so every arc shares one colour. */
const ARC_COLOR_ALL = '*';

/** The reduction policy the coverage DC is fetched under. A depth profile is
 *  read as a shape, so the server's uniform hash sample is the right one —
 *  unlike the junction table, which is fetched whole. */
const COVERAGE_KIND: AdvancedVizKind = 'coverage_track';

/** Coverage points drawn per lane after max-pooling. Pooling displaces the
 *  step edges of the silhouette by up to one bucket, and the arc feet are
 *  anchored on that silhouette, so the threshold is set well above what a
 *  binned profile over a gene locus produces (a 40 kb locus at 25 bp is ~1 600
 *  bins) and only catches per-base files, where the extra points land inside
 *  the same pixel anyway. Pooling by max rather than by mean keeps a one-bin
 *  dropout or spike visible. */
const COVERAGE_MAX_POINTS = 4000;

/** Two consecutive bins further apart than this many times the median bin
 *  width are a gap in the data, not a plateau: the area drops to zero between
 *  them instead of bridging across an unsequenced stretch. */
const COVERAGE_GAP_FACTOR = 3;

/** Room kept under the baseline for the downward half of the arcs, as a share
 *  of the lane. The support profile fills it when it is on and wider. */
const MIN_BELOW_SPACE = 0.34;

/** A zoom step. Chosen so three clicks roughly halve then halve again, which is
 *  the granularity a reader walking into an exon actually wants. */
const ZOOM_FACTOR = 0.6;

/** Terminal exons have no junction on their outer side, so their outer edge is
 *  unknown. They are drawn this fraction of the locus wide, and hatched, rather
 *  than left out — a gene model that starts at its second exon reads as a bug. */
const TERMINAL_EXON_FRACTION = 0.012;

/** An exon inferred from junction ends: the interval between an acceptor and
 *  the next donor. `support` is the read support of the junctions touching it,
 *  which is an estimate of its depth and NOT a coverage measurement — nothing
 *  in a junction table counts reads that never crossed a splice site. */
interface ExonBlock {
  start: number;
  end: number;
  terminal: boolean;
  /** Per-lane incident read support, keyed by lane. */
  support: Map<string, number>;
}

/** One coverage observation: a bin [pos, end) at `value` depth, or a single
 *  base when the DC has no end column (end === pos + 1). */
interface CoverageBin {
  pos: number;
  end: number;
  value: number;
}

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

/** Chromosome names for comparison across two data collections. A junction
 *  table from regtools says `chr12` where a mosdepth bed says `12`; treating
 *  those as different chromosomes would silently draw an empty coverage
 *  track, which reads as "no depth here" rather than "not matched". */
const sameChrom = (a: string, b: string) => {
  const strip = (v: string) => v.trim().toLowerCase().replace(/^chr/, '');
  return strip(a) === strip(b);
};


/** Number of the form 1_234_567, matching the bp axis ticks. */
const bp = (v: number) => v.toLocaleString();

/** Reduce a sorted profile to at most COVERAGE_MAX_POINTS bins, keeping the
 *  maximum of each bucket. Averaging would flatten the single-bin dropout an
 *  amplicon panel is read for; the maximum keeps peaks and, with them, the
 *  shape of the coverage. */
function poolCoverage(bins: CoverageBin[]): CoverageBin[] {
  if (bins.length <= COVERAGE_MAX_POINTS) return bins;
  const step = bins.length / COVERAGE_MAX_POINTS;
  const out: CoverageBin[] = [];
  for (let i = 0; i < COVERAGE_MAX_POINTS; i++) {
    const from = Math.floor(i * step);
    const to = Math.min(bins.length, Math.floor((i + 1) * step));
    if (to <= from) continue;
    let value = 0;
    for (let k = from; k < to; k++) if (bins[k].value > value) value = bins[k].value;
    out.push({ pos: bins[from].pos, end: bins[to - 1].end, value });
  }
  return out;
}

/** `#rrggbb` at a given alpha, for a fill that has to sit under the arcs
 *  without competing with them. Anything that is not a six-digit hex (a
 *  theme's own `rgba(...)` string) is returned untouched. */
const withAlpha = (colour: string, alpha: number) => {
  const m = /^#([0-9a-f]{6})$/i.exec(colour.trim());
  if (!m) return colour;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
};

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
  const [showSupport, setShowSupport] = usePersistedVizControl<boolean>(
    metadata,
    'show_support_track',
    true,
  );
  const [showGeneModel, setShowGeneModel] = usePersistedVizControl<boolean>(
    metadata,
    'show_gene_model',
    true,
  );
  const [supportHeight, setSupportHeight] = usePersistedVizControl<number>(
    metadata,
    'support_track_height',
    0.3,
  );
  const [geneModelHeight, setGeneModelHeight] = usePersistedVizControl<number>(
    metadata,
    'gene_model_height',
    0.14,
  );
  const [arcHeight, setArcHeight] = usePersistedVizControl<number>(metadata, 'arc_height', 1);
  /** Author-chosen arc colours, keyed by annotation value (or ARC_COLOR_ALL).
   *  Empty means "use the theme palette", which is what every binding gets
   *  until someone overrides a class. */
  const [arcColors, setArcColors] = usePersistedVizControl<Record<string, string>>(
    metadata,
    'arc_colors',
    {},
  );
  const [showCoverage, setShowCoverage] = usePersistedVizControl<boolean>(
    metadata,
    'show_coverage',
    true,
  );
  const [coverageHeight, setCoverageHeight] = usePersistedVizControl<number>(
    metadata,
    'coverage_height',
    0.6,
  );
  const [coverageLog, setCoverageLog] = usePersistedVizControl<boolean>(
    metadata,
    'coverage_log',
    false,
  );
  /** Empty means "use the theme's grid colour", which is what an unstyled
   *  binding gets. */
  const [coverageColor, setCoverageColor] = usePersistedVizControl<string>(
    metadata,
    'coverage_color',
    '',
  );
  /** What the arcs take their colour from. Annotation (known / novel) is the
   *  default when the binding has one; sample is the ggsashimi convention,
   *  where each track is one colour and the arcs belong to their track. */
  const [colorBy, setColorBy] = usePersistedVizControl<'annotation' | 'sample'>(
    metadata,
    'color_by',
    'annotation',
  );
  const [maxArcWidth, setMaxArcWidth] = usePersistedVizControl<number>(
    metadata,
    'max_arc_width',
    2,
  );
  const [widthBySupport, setWidthBySupport] = usePersistedVizControl<boolean>(
    metadata,
    'arc_width_by_support',
    false,
  );
  /** How an arc's side is chosen. By class, so known and novel never paint
   *  over each other; or alternating along the locus, which is the fallback
   *  when there is no class to split on. */
  const [arcSplit, setArcSplit] = usePersistedVizControl<'annotation' | 'alternate'>(
    metadata,
    'arc_split',
    'annotation',
  );
  // Local-only: no field on SashimiConfig carries them, and a region pick or a
  // zoom is a reading position rather than an authored default.
  const [selectedRegion, setSelectedRegion] = useState<string | null>(null);
  const [showCounts, setShowCounts] = useState<boolean>(true);
  /** Explicit x window, or null to fit the region. Set by the zoom buttons and
   *  by Plotly's own drag-zoom, so the two stay one state instead of fighting. */
  const [view, setView] = useState<[number, number] | null>(null);

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

  /** The coverage DC's columns, or none when no second collection is bound —
   *  which is the default and leaves every code path below inert. */
  const coverageCols = useMemo(() => {
    if (!config.coverage_dc_id) return [] as string[];
    return [
      config.coverage_chr_col,
      config.coverage_position_col,
      config.coverage_value_col,
      ...(config.coverage_end_col ? [config.coverage_end_col] : []),
      ...(config.coverage_sample_col ? [config.coverage_sample_col] : []),
    ].filter(Boolean) as string[];
  }, [
    config.coverage_dc_id,
    config.coverage_chr_col,
    config.coverage_position_col,
    config.coverage_value_col,
    config.coverage_end_col,
    config.coverage_sample_col,
  ]);

  const [coverageRows, setCoverageRows] = useState<Record<string, unknown[]> | null>(null);
  /** Kept apart from `error`: a coverage collection that fails to load must
   *  not blank the junctions, which are this component's subject. The controls
   *  say what happened instead. */
  const [coverageError, setCoverageError] = useState<string | null>(null);

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

  // Second collection, fetched independently so its size, its failures and
  // its absence are all decoupled from the junction table.
  useEffect(() => {
    const dcId = config.coverage_dc_id;
    const wfId = config.coverage_wf_id || metadata.wf_id;
    if (!dcId || !wfId || coverageCols.length < 3) {
      setCoverageRows(null);
      setCoverageError(null);
      return;
    }
    let cancelled = false;
    setCoverageError(null);
    fetchAdvancedVizData({
      wfId,
      dcId,
      columns: coverageCols,
      filters,
      vizKind: COVERAGE_KIND,
      roles: {
        chromosome: config.coverage_chr_col || 'chromosome',
        position: config.coverage_position_col || 'position',
        value: config.coverage_value_col || 'value',
      },
    })
      .then((res) => {
        if (!cancelled) setCoverageRows(res.rows);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setCoverageRows(null);
        setCoverageError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [
    config.coverage_dc_id,
    config.coverage_wf_id,
    config.coverage_chr_col,
    config.coverage_position_col,
    config.coverage_value_col,
    metadata.wf_id,
    JSON.stringify(coverageCols),
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

  /** Exons inferred from the junctions themselves, so the gene model and the
   *  support profile come out of the one table this component binds.
   *
   *  A junction is an intron: its start is a donor (the end of an exon) and its
   *  end is an acceptor (the start of the next one). So the interval between an
   *  acceptor and the next donor after it is exonic by construction, with no
   *  annotation file needed. What cannot be recovered is where the first exon
   *  begins and the last one ends, because nothing splices into or out of them;
   *  those two are drawn at a fixed width and marked terminal.
   *
   *  This is inference, not measurement. An exon nothing splices across in this
   *  run is invisible here, and the support figure counts spliced reads only. */
  const exons = useMemo<ExonBlock[]>(() => {
    if (!visible.length) return [];
    const donors = Array.from(new Set(visible.map((j) => j.start))).sort((a, b) => a - b);
    const acceptors = Array.from(new Set(visible.map((j) => j.end))).sort((a, b) => a - b);
    const span = Math.max(...donors, ...acceptors) - Math.min(...donors, ...acceptors);
    const flank = Math.max(Math.round(span * TERMINAL_EXON_FRACTION), 1);

    const bounds: Array<[number, number, boolean]> = [];
    for (const a of acceptors) {
      const d = donors.find((x) => x > a);
      if (d !== undefined) bounds.push([a, d, false]);
    }
    // The two ends of the locus, whose outer edge no junction pins down.
    bounds.push([donors[0] - flank, donors[0], true]);
    bounds.push([acceptors[acceptors.length - 1], acceptors[acceptors.length - 1] + flank, true]);

    const byKey = new Map<string, ExonBlock>();
    for (const [start, end, terminal] of bounds) {
      if (end <= start) continue;
      const key = `${start}:${end}`;
      if (!byKey.has(key)) byKey.set(key, { start, end, terminal, support: new Map() });
    }
    // Incident support: a junction landing on either edge of an exon is read
    // support for that exon, counted per lane so each sample keeps its own
    // profile the way each sample keeps its own arcs.
    for (const block of byKey.values()) {
      for (const j of visible) {
        if (j.end === block.start || j.start === block.end) {
          block.support.set(j.lane, (block.support.get(j.lane) ?? 0) + j.count);
        }
      }
    }
    return Array.from(byKey.values()).sort((a, b) => a.start - b.start);
  }, [visible]);

  /** The bound coverage collection, cut to what is on screen and pooled down
   *  to a drawable number of points, one profile per lane.
   *
   *  Unlike the inferred support track this IS a measurement: it is whatever
   *  the pipeline wrote (mosdepth bins, a bedGraph, a BigWig export), read
   *  from a second data collection and matched to the junction lanes by
   *  sample. When the coverage DC has no sample column there is one profile
   *  for the locus, and every lane shows it — the controls say so, because an
   *  aggregate drawn under each sample must not be read as per-sample depth.
   */
  const coverage = useMemo(() => {
    const byLane = new Map<string, CoverageBin[]>();
    const shared = !config.coverage_sample_col;
    if (!coverageRows || !activeRegion) return { byLane, max: 0, shared };
    const chrCol = config.coverage_chr_col || 'chromosome';
    const posCol = config.coverage_position_col || 'position';
    const valCol = config.coverage_value_col || 'value';
    const chroms = coverageRows[chrCol] || [];
    const positions = coverageRows[posCol] || [];
    const values = coverageRows[valCol] || [];
    const ends = config.coverage_end_col ? coverageRows[config.coverage_end_col] || [] : null;
    const samples = config.coverage_sample_col
      ? coverageRows[config.coverage_sample_col] || []
      : null;
    // Pool at the resolution being looked at, so zooming into an exon sharpens
    // the profile instead of magnifying the pooled steps of the whole locus.
    const [lo, hi] = view ?? [activeRegion.start, activeRegion.end];

    for (let i = 0; i < positions.length; i++) {
      if (!sameChrom(String(chroms[i] ?? ''), activeRegion.chrom)) continue;
      const pos = Number(positions[i]);
      const value = Number(values[i]);
      if (!Number.isFinite(pos) || !Number.isFinite(value)) continue;
      const rawEnd = ends ? Number(ends[i]) : NaN;
      const end = Number.isFinite(rawEnd) && rawEnd > pos ? rawEnd : pos + 1;
      if (end < lo || pos > hi) continue;
      const lane = samples ? String(samples[i] ?? SINGLE_LANE) : SINGLE_LANE;
      const bucket = byLane.get(lane);
      if (bucket) bucket.push({ pos, end, value });
      else byLane.set(lane, [{ pos, end, value }]);
    }

    let max = 0;
    for (const [lane, bins] of byLane) {
      bins.sort((a, b) => a.pos - b.pos);
      const pooled = poolCoverage(bins);
      byLane.set(lane, pooled);
      for (const b of pooled) if (b.value > max) max = b.value;
    }
    return { byLane, max, shared };
  }, [
    coverageRows,
    activeRegion,
    view,
    config.coverage_chr_col,
    config.coverage_position_col,
    config.coverage_value_col,
    config.coverage_end_col,
    config.coverage_sample_col,
  ]);

  /** Whether the coverage layer is drawn at all: bound, switched on, and with
   *  points in this region. */
  const coverageActive = !!config.coverage_dc_id && showCoverage && coverage.max > 0;

  /** The x window a reset returns to: every drawn junction, plus a margin. */
  const fitRange = useMemo<[number, number] | null>(() => {
    if (!visible.length) return null;
    const lo = Math.min(...visible.map((j) => j.start));
    const hi = Math.max(...visible.map((j) => j.end));
    const pad = Math.max((hi - lo) * 0.03, 1);
    return [lo - pad, hi + pad];
  }, [visible]);

  // A region pick is a different locus, so any zoom inside the previous one is
  // meaningless. Reset rather than carry a window the new region may not cover.
  useEffect(() => {
    setView(null);
  }, [activeRegion?.key]);

  /** Scale the window about its own centre. `factor` < 1 zooms in. */
  const zoomBy = useCallback(
    (factor: number) => {
      setView((prev) => {
        const current = prev ?? fitRange;
        if (!current) return prev;
        const [lo, hi] = current;
        const mid = (lo + hi) / 2;
        const half = ((hi - lo) / 2) * factor;
        // One base pair is the floor: past that the axis ticks repeat and the
        // arcs are wider than the range they span.
        if (half < 0.5) return [mid - 0.5, mid + 0.5];
        if (fitRange && half > (fitRange[1] - fitRange[0]) / 2) return null;
        return [mid - half, mid + half];
      });
    },
    [fitRange],
  );

  /** Slide the window by a share of its own width, keeping its span. */
  const panBy = useCallback(
    (share: number) => {
      setView((prev) => {
        const current = prev ?? fitRange;
        if (!current) return prev;
        const [lo, hi] = current;
        const step = (hi - lo) * share;
        return [lo + step, hi + step];
      });
    },
    [fitRange],
  );

  /** Plotly's own drag-zoom and double-click write the same state the buttons
   *  do, so the two never disagree about where the reader is looking. */
  const handleRelayout = useCallback((event: Record<string, unknown>) => {
    if (event['xaxis.autorange'] === true) {
      setView(null);
      return;
    }
    const lo = event['xaxis.range[0]'];
    const hi = event['xaxis.range[1]'];
    if (typeof lo === 'number' && typeof hi === 'number' && hi > lo) setView([lo, hi]);
  }, []);

  const annotationValues = useMemo(
    () => Array.from(new Set(junctions.map((j) => j.annotation).filter((a): a is string => !!a))),
    [junctions],
  );

  const figure = useMemo<{ data: unknown[]; layout: Record<string, unknown> } | null>(() => {
    if (!visible.length || !lanes.length) return null;
    const colors = plotlyThemeColors(isDark, theme);
    const palette = resolveCategoricalPalette(theme, mantineCategoricalPalette(theme, isDark));
    const paletteColour = stableColorMap(annotationValues, palette);
    // An override wins over the palette, per class, so two classes that the
    // stable map happened to give near neighbours can be pulled apart.
    const annotationColour = new Map(
      annotationValues.map((v) => [v, arcColors[v] || paletteColour.get(v) || palette[0]]),
    );
    const baseColour = arcColors[ARC_COLOR_ALL] || palette[0];
    /** One colour per sample lane, which is how a published sashimi separates
     *  its tracks. Used for the depth profile always, and for the arcs too
     *  when the reader asks for it. */
    const laneColour = (laneIdx: number) => palette[laneIdx % palette.length] ?? baseColour;

    const counts = visible.map((j) => j.count);
    const countMin = Math.min(...counts);
    const countMax = Math.max(...counts);
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
      widthBySupport
        ? MIN_ARC_WIDTH + (level / (WIDTH_LEVELS - 1)) * Math.max(0, maxArcWidth - MIN_ARC_WIDTH)
        : maxArcWidth;

    // ------------------------------------------------------------------
    // Lane geometry, laid out the way a published sashimi is: a zero line
    // with the depth profile rising off it, up-arcs springing from the top of
    // that profile at the donor and landing on it at the acceptor, and
    // down-arcs hanging under the line. Before this the profile was drawn
    // *under* the zero line as a strip, which is the one arrangement no
    // sashimi tool uses, and it read as decoration rather than as the depth
    // the arcs are quantifying.
    // ------------------------------------------------------------------

    /** The zero line of each lane. Everything below it is the room down-arcs
     *  hang in; everything above is profile plus up-arcs. */
    const baseY = MIN_BELOW_SPACE;
    const belowSpace = Math.max(baseY - 0.03, 0.1);
    /** Headroom above the line, shared between the profile and the up-arcs. */
    const headroom = Math.max(LANE_Y_RANGE[1] - baseY, 0.3);

    /** Share of the headroom the depth profile takes. Coverage supersedes the
     *  inferred support: showing a measurement and an estimate of the same
     *  quantity together invites reading one as the other. */
    const coverageFrac = coverageActive
      ? headroom * Math.min(Math.max(coverageHeight, 0.05), 0.8)
      : 0;
    const supportFrac =
      !coverageActive && showSupport && exons.length
        ? headroom * Math.min(Math.max(supportHeight, 0), 0.6)
        : 0;
    const profileFrac = Math.max(coverageFrac, supportFrac);
    /** What is left over the profile for the up-arcs to arch into. */
    const aboveSpace = Math.max(headroom - profileFrac, 0.2);

    /** Share of the whole figure given to the gene-model lane at the bottom. */
    const geneFrac =
      showGeneModel && exons.length ? Math.min(Math.max(geneModelHeight, 0.05), 0.4) : 0;

    /** Apex distance from the arc's own feet, as a share of the room on that
     *  side. By span rather than by count: count is already the line width,
     *  and nesting is what the reader needs to see. */
    const magnitudeFor = (span: number, ref: number) =>
      Math.max(0.05, arcHeight) *
      (MIN_ARC_HEIGHT +
        (MAX_ARC_HEIGHT - MIN_ARC_HEIGHT) * (ref > 0 ? Math.sqrt(Math.min(span / ref, 1)) : 1));

    // Both profiles are normalised against the strongest point across EVERY
    // lane rather than per lane, so a shallow sample looks shallow instead of
    // being stretched to full height. That is the choice ggsashimi exposes as
    // --fix-y-scale, made once and stated here.
    const covScale = (v: number) =>
      coverageLog ? Math.log10(1 + Math.max(0, v)) : Math.max(0, v);
    const covMax = covScale(coverage.max) || 1;
    const laneSupportMax = Math.max(1, ...exons.flatMap((e) => Array.from(e.support.values())));
    const pickLane = (from: Map<string, CoverageBin[]>, lane: string) =>
      from.get(lane) ?? (coverage.shared ? from.get(SINGLE_LANE) : undefined);
    const binsForLane = (lane: string) => pickLane(coverage.byLane, lane);

    /** Index of the bin that starts at or before `x`, by binary search — the
     *  bins are position-sorted and there are a few thousand of them per lane,
     *  which is too many to scan once per arc foot. -1 when `x` is ahead of
     *  the first bin. */
    const binIndexAt = (bins: CoverageBin[], x: number): number => {
      let lo = 0;
      let hi = bins.length - 1;
      let found = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (bins[mid].pos <= x) {
          found = mid;
          lo = mid + 1;
        } else {
          hi = mid - 1;
        }
      }
      return found;
    };

    /** Drawn height of one bin above the zero line. */
    const binHeight = (bin: CoverageBin) => coverageFrac * (covScale(bin.value) / covMax);

    /** Height of the depth profile above the zero line at one position, for
     *  one lane. Zero when no profile is drawn, and the arcs then spring off
     *  the line itself. */
    const profileAt = (lane: string, x: number): number => {
      if (coverageFrac > 0) {
        // The bins the silhouette is drawn from, not the unpooled ones: an
        // arc's foot has to land ON the line the reader can see, and pooling
        // can move that line. Reading anything else — a window maximum, the
        // raw bins behind a pooled one — floats the foot above the coverage,
        // which is exactly what it must not do.
        const bins = binsForLane(lane);
        if (!bins || !bins.length) return 0;
        const found = binIndexAt(bins, x);
        if (found < 0) return 0;
        const bin = bins[found];
        // Past the end of that bin is a gap in the profile: the silhouette is
        // at zero there and so is the foot.
        if (x > bin.end) return 0;
        return binHeight(bin);
      }
      if (supportFrac > 0) {
        const exon = exons.find((e) => x >= e.start && x <= e.end);
        if (!exon) return 0;
        return supportFrac * ((exon.support.get(lane) ?? 0) / laneSupportMax);
      }
      return 0;
    };

    /**
     * Where one foot of an arc meets the coverage: the position it is drawn at
     * and the height it stands on.
     *
     * Reading the profile straight at the junction coordinate is not enough.
     * Coverage arrives binned — 25 bp here, 200 bp from mosdepth — on a grid
     * that owes nothing to the splice sites, so the step up to the exon lands
     * a few bases off the donor or acceptor. A foot placed at the junction
     * coordinate then stands on the intron floor a hair outside the block it
     * belongs to, which reads as an arc starting from nowhere near the exon it
     * comes out of.
     *
     * So the foot is allowed to walk, on its own exon's side (`dir` is -1 for a
     * donor, whose exon is to the left, +1 for an acceptor), to the first bin
     * that is part of the local plateau, and is drawn at that bin's
     * junction-facing edge — a vertex the silhouette actually has. When the
     * junction already sits on the plateau, which is the per-base case and most
     * of the binned one, nothing moves.
     */
    const footFor = (lane: string, at: number, dir: 1 | -1, span: number) => {
      if (coverageFrac <= 0) return { x: at, h: profileAt(lane, at) };
      const bins = binsForLane(lane);
      if (!bins || !bins.length) return { x: at, h: 0 };
      const origin = binIndexAt(bins, at);
      if (origin < 0) return { x: at, h: 0 };
      // Never walk more than a corner's worth: three bins, and never so far
      // that a short intron's two feet could meet in the middle.
      const reach = Math.max(1, span * FOOT_SNAP_SPAN_SHARE);
      const window: { bin: CoverageBin; value: number; h: number }[] = [];
      for (let k = 0; k < FOOT_SNAP_BINS; k++) {
        const idx = origin + dir * k;
        if (idx < 0 || idx >= bins.length) break;
        const bin = bins[idx];
        const edge = dir < 0 ? bin.end : bin.pos;
        if (Math.abs(edge - at) > reach) break;
        // The bin `at` falls in may end before it — a gap in the profile, which
        // reads as zero the way `profileAt` does, so a foot is never anchored
        // to a stretch the silhouette does not cover. Every other bin in the
        // window is one the silhouette draws.
        const covered = k > 0 || at <= bin.end;
        window.push({ bin, value: covered ? covScale(bin.value) : 0, h: covered ? binHeight(bin) : 0 });
      }
      if (!window.length) return { x: at, h: 0 };
      const best = Math.max(...window.map((w) => w.value));
      // Nearest the junction first, so the foot settles on the bin at the edge
      // of the exon rather than sliding to whichever bin inside it is deepest.
      const chosen = window.find((w) => w.value >= best * FOOT_PLATEAU_SHARE) ?? window[0];
      // Already on the plateau: the junction coordinate is the honest place to
      // draw the foot, and it is on the silhouette there.
      if (chosen === window[0]) return { x: at, h: chosen.h };
      return { x: dir < 0 ? chosen.bin.end : chosen.bin.pos, h: chosen.h };
    };

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

    lanes.forEach((lane, laneIdx) => {
      const yref = laneRef(laneIdx);

      // Ordered by position, not by support, because the side an arc is drawn
      // on alternates along the locus. Two junctions that share a span — a
      // known intron and the novel site a few bases inside it — then land on
      // opposite sides instead of one being painted over the other, which is
      // the whole reason ggsashimi alternates.
      const laneArcs = visible
        .filter((j) => j.lane === lane)
        .slice()
        .sort((a, b) => a.start - b.start || a.end - b.end);
      // Labelling still goes to the strongest, so the digits land where the
      // reader is looking rather than on whatever came first along the axis.
      const labelled = new Set(
        laneArcs
          .slice()
          .sort((a, b) => b.count - a.count)
          .slice(0, APEX_LABELS_PER_LANE)
          .map((j) => `${j.start}:${j.end}`),
      );

      // One class per side beats alternating along the locus: it is
      // deterministic, it means the side itself carries information, and two
      // junctions sharing a span still never paint over each other. Falls back
      // to alternation when there is no class to split on.
      const sideOf = (j: Junction, idx: number): 1 | -1 => {
        const classIdx = j.annotation ? annotationValues.indexOf(j.annotation) : -1;
        if (arcSplit === 'annotation' && classIdx >= 0) return classIdx % 2 === 0 ? 1 : -1;
        return idx % 2 === 0 ? 1 : -1;
      };
      // Each side is scaled against its own longest span. Shared, the class
      // that happens to hold the long constitutive introns would push every
      // arc on the other side down to a flat scratch.
      const sides = laneArcs.map(sideOf);
      const spanRef = (side: 1 | -1) =>
        Math.max(
          1,
          ...laneArcs.filter((_, i) => sides[i] === side).map((a) => a.end - a.start),
        );
      const refUp = spanRef(1);
      const refDown = spanRef(-1);

      laneArcs.forEach((j, idx) => {
        const side = sides[idx];
        // A constant width keeps every level in one trace, which is the whole
        // point of the level grouping when nothing is being scaled.
        const level = widthBySupport ? levelFor(j.count) : 0;
        const byLane = colorBy === 'sample' || !j.annotation;
        const colour = byLane
          ? laneColour(laneIdx)
          : (annotationColour.get(j.annotation!) ?? baseColour);
        const category = byLane ? null : j.annotation;
        const key = `${laneIdx}|${category ?? ''}|${level}|${side}`;
        let group = groups.get(key);
        if (!group) {
          group = {
            x: [],
            y: [],
            text: [],
            width: widthForLevel(level),
            colour,
            category,
            yaxis: yref,
          };
          groups.set(key, group);
        }

        // An up-arc leaves the top of the donor exon's coverage and lands on
        // the top of the acceptor's: the two feet sit at different heights,
        // which is what visually ties the arc to the depth it is explaining.
        // A down-arc hangs off the zero line instead, so a lane's two sides
        // stay legible when arcs alternate. Both sides take their x from the
        // same reading, so the two ends of a junction line up with each other
        // and with the step in the coverage whichever way the arc is drawn.
        const span = j.end - j.start;
        const donor = footFor(lane, j.start, -1, span);
        const acceptor = footFor(lane, j.end, 1, span);
        const x0 = donor.x;
        const x1 = acceptor.x;
        const y0 = side > 0 ? baseY + donor.h : baseY;
        const y1 = side > 0 ? baseY + acceptor.h : baseY;
        const foot = Math.max(y0, y1);
        // Scaled by the junction's real span, not the snapped one: the arc's
        // height says how long the intron is, and that is a fact about the
        // annotation rather than about where the coverage happened to step.
        const mag = magnitudeFor(span, side > 0 ? refUp : refDown);
        const apex = side > 0 ? foot + aboveSpace * mag : baseY - belowSpace * Math.min(mag, 1);
        // Cubic bezier with both control points raised, sampled into a path so
        // every point on the arc carries the junction's own hover text. Solved
        // so the curve actually reaches `apex` at t = 0.5, where a cubic sits
        // at 0.125(y0 + y1) + 0.75 c.
        const control = (apex - 0.125 * (y0 + y1)) / 0.75;
        const cx0 = x0 + ARC_SHOULDER * (x1 - x0);
        const cx1 = x1 - ARC_SHOULDER * (x1 - x0);
        const label =
          `${j.chrom}:${bp(j.start)}-${bp(j.end)}` +
          `<br>${config.count_col}: ${j.count.toLocaleString()}` +
          `<br>span: ${bp(j.end - j.start)} bp` +
          (config.sample_col ? `<br>${config.sample_col}: ${lane}` : '') +
          (j.annotation ? `<br>${config.annotation_col}: ${j.annotation}` : '');
        for (let k = 0; k <= ARC_SAMPLES; k++) {
          const t = k / ARC_SAMPLES;
          const u = 1 - t;
          const a = u * u * u;
          const b = 3 * u * u * t;
          const c = 3 * u * t * t;
          const d = t * t * t;
          group.x.push(a * x0 + b * cx0 + c * cx1 + d * x1);
          group.y.push(a * y0 + b * control + c * control + d * y1);
          group.text.push(label);
        }
        // A null break ends the path so the next arc in this group does not
        // inherit a segment from the previous one's acceptor.
        group.x.push(null);
        group.y.push(null);
        group.text.push('');

        if (showCounts && labelled.has(`${j.start}:${j.end}`)) {
          annotations.push({
            xref: 'x',
            yref,
            x: (x0 + x1) / 2,
            y: apex,
            yanchor: side > 0 ? 'bottom' : 'top',
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

    // Real coverage, one filled area per lane, drawn from the second
    // collection. Normalised against the deepest point across every lane so a
    // shallow sample looks shallow — the same fixed-scale choice the support
    // track makes, and the one ggsashimi exposes as --fix-y-scale.
    if (coverageFrac > 0) {
      // One colour per lane, the way every published sashimi colours its
      // samples, rather than the theme's grid grey — which is 8% black and
      // vanishes under the arcs.
      lanes.forEach((lane, laneIdx) => {
        const bins = binsForLane(lane);
        if (!bins || !bins.length) return;
        const covBase = coverageColor || laneColour(laneIdx);
        const covFill = withAlpha(covBase, isDark ? 0.55 : 0.42);
        const covLine = withAlpha(covBase, 0.9);
        // Median bin width sets what counts as a gap, so a per-base file and a
        // 200-bp mosdepth file both break in the right places.
        const widths = bins.map((b) => b.end - b.pos).sort((a, b) => a - b);
        const medianWidth = widths[Math.floor(widths.length / 2)] || 1;
        const px: (number | null)[] = [];
        const py: (number | null)[] = [];
        const ptext: string[] = [];
        const push = (x: number, y: number, t: string) => {
          px.push(x);
          py.push(y);
          ptext.push(t);
        };
        let open = false;
        bins.forEach((b, i) => {
          const h = coverageFrac * (covScale(b.value) / covMax);
          const label =
            `${activeRegion?.chrom ?? ''}:${bp(Math.round(b.pos))}-${bp(Math.round(b.end))}` +
            `<br>${config.coverage_value_col ?? 'depth'}: ${b.value.toLocaleString()}` +
            (coverage.shared && lanes.length > 1
              ? '<br>coverage not split by sample'
              : config.coverage_sample_col
                ? `<br>${config.coverage_sample_col}: ${lane}`
                : '');
          const prev = i > 0 ? bins[i - 1] : null;
          if (!open || (prev && b.pos - prev.end > medianWidth * COVERAGE_GAP_FACTOR)) {
            if (open && prev) push(prev.end, baseY, '');
            push(b.pos, baseY, label);
            open = true;
          }
          push(b.pos, baseY + h, label);
          push(b.end, baseY + h, label);
        });
        if (open) push(bins[bins.length - 1].end, baseY, '');
        traces.push({
          type: 'scatter',
          mode: 'lines',
          x: px,
          y: py,
          text: ptext,
          // `toself` rather than `tozeroy`: the polygon is explicitly closed
          // along the zero line at baseY, and filling to y=0 would drop the
          // whole band below the line the arcs are anchored to.
          fill: 'toself',
          fillcolor: covFill,
          line: { color: covLine, width: 1 },
          hovertemplate: '%{text}<extra></extra>',
          showlegend: false,
          xaxis: 'x',
          yaxis: laneRef(laneIdx),
        });
      });
    }

    // Inferred support profile, the stand-in when no coverage DC is bound.
    if (supportFrac > 0) {
      lanes.forEach((lane, laneIdx) => {
        const px: (number | null)[] = [];
        const py: (number | null)[] = [];
        const ptext: string[] = [];
        for (const exon of exons) {
          const value = exon.support.get(lane) ?? 0;
          const h = supportFrac * (value / laneSupportMax);
          const label =
            `exon ${bp(exon.start)}-${bp(exon.end)}` +
            `<br>spliced read support: ${value.toLocaleString()}` +
            (exon.terminal ? '<br>terminal exon, outer edge unknown' : '');
          px.push(exon.start, exon.start, exon.end, exon.end, null);
          py.push(baseY, baseY + h, baseY + h, baseY, null);
          ptext.push(label, label, label, label, '');
        }
        const supportBase = laneColour(laneIdx);
        traces.push({
          type: 'scatter',
          mode: 'lines',
          x: px,
          y: py,
          text: ptext,
          fill: 'toself',
          fillcolor: withAlpha(supportBase, isDark ? 0.4 : 0.28),
          line: { color: withAlpha(supportBase, 0.7), width: 1 },
          hovertemplate: '%{text}<extra></extra>',
          showlegend: false,
          xaxis: 'x',
          yaxis: laneRef(laneIdx),
        });
      });
    }

    // Gene model, one shared lane at the bottom. Exons as blocks on a spine,
    // terminal ones faded because only one of their edges is known.
    const geneAxisIdx = lanes.length;
    if (geneFrac > 0) {
      const yref = `y${geneAxisIdx + 1}`;
      traces.push({
        type: 'scatter',
        mode: 'lines',
        x: [xMin, xMax],
        y: [0.5, 0.5],
        line: { color: colors.textColor, width: 1 },
        hoverinfo: 'skip',
        showlegend: false,
        xaxis: 'x',
        yaxis: yref,
      });
      for (const group of [false, true]) {
        const blocks = exons.filter((e) => e.terminal === group);
        if (!blocks.length) continue;
        const px: (number | null)[] = [];
        const py: (number | null)[] = [];
        const ptext: string[] = [];
        for (const exon of blocks) {
          const label =
            `exon ${bp(exon.start)}-${bp(exon.end)}` +
            `<br>width: ${bp(exon.end - exon.start)} bp` +
            (exon.terminal ? '<br>terminal, outer edge inferred' : '');
          px.push(exon.start, exon.start, exon.end, exon.end, null);
          py.push(0.16, 0.84, 0.84, 0.16, null);
          ptext.push(label, label, label, label, '');
        }
        traces.push({
          type: 'scatter',
          mode: 'lines',
          x: px,
          y: py,
          text: ptext,
          fill: 'toself',
          fillcolor: baseColour,
          opacity: group ? 0.3 : 0.85,
          line: { color: baseColour, width: 1 },
          hovertemplate: '%{text}<extra></extra>',
          showlegend: false,
          xaxis: 'x',
          yaxis: yref,
        });
      }
    }

    const layout: Record<string, unknown> = {
      ...plotlyThemeFragment(isDark, theme),
      margin: { l: lanes.length > 1 ? 88 : 24, r: 16, t: 8, b: 36 },
      autosize: true,
      hovermode: 'closest',
      showlegend: legendSeen.size > 0,
      legend: { orientation: 'h', x: 0, y: 1.06, font: { size: 10 } },
      annotations,
    };

    const rowSize = (1 - geneFrac) / lanes.length;
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

    if (geneFrac > 0) {
      layout[`yaxis${geneAxisIdx + 1}`] = {
        ...plotlyAxisOverrides(isDark, theme),
        domain: [0, Math.max(geneFrac - 0.02, 0.02)],
        range: [0, 1],
        showticklabels: false,
        showgrid: false,
        zeroline: false,
        fixedrange: true,
        title: {
          text: lanes.length > 1 ? 'Exons' : '',
          font: { size: 10, color: colors.textColor },
          standoff: 6,
        },
      };
    }

    layout.xaxis = {
      ...plotlyAxisOverrides(isDark, theme),
      title: { text: `${activeRegion?.chrom ?? config.chr_col} (bp)`, font: { size: 11 } },
      // A crosshair down every lane, so a coordinate read off one sample's
      // coverage can be carried to the others by eye. `spikesnap: 'cursor'`
      // keeps it under the pointer instead of jumping to the nearest sampled
      // point of whichever trace is closest.
      showspikes: true,
      spikemode: 'across',
      spikesnap: 'cursor',
      spikedash: 'dot',
      spikethickness: 1,
      spikecolor: colors.zeroLineColor,
      // The zoom window when the reader set one, the whole region otherwise.
      // Both the buttons and Plotly's own drag write the same state, so a drag
      // is not undone by the next control change.
      range: view ?? [xMin - xPad, xMax + xPad],
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
    widthBySupport,
    arcSplit,
    colorBy,
    showCounts,
    exons,
    arcColors,
    coverage,
    coverageActive,
    coverageHeight,
    coverageColor,
    coverageLog,
    config.coverage_value_col,
    config.coverage_sample_col,
    showSupport,
    showGeneModel,
    supportHeight,
    geneModelHeight,
    arcHeight,
    view,
    isDark,
    theme,
    config.chr_col,
    config.count_col,
    config.sample_col,
    config.annotation_col,
  ]);

  // Dropdowns inside the Settings popover portal to document.body by default,
  // which a fullscreen element's top layer never paints. Same target as the
  // popover itself.
  const fsPortalTarget = useFullscreenPortalTarget();

  /** Default colour a class would get with no override, so the picker opens on
   *  what is actually drawn rather than on an empty field. */
  const paletteDefaults = useMemo(() => {
    const palette = resolveCategoricalPalette(theme, mantineCategoricalPalette(theme, isDark));
    const map = stableColorMap(annotationValues, palette);
    return { map, palette };
  }, [annotationValues, theme, isDark]);

  const setArcColor = useCallback(
    (key: string, value: string | null) => {
      const next = { ...arcColors };
      if (value) next[key] = value;
      else delete next[key];
      setArcColors(next);
    },
    [arcColors, setArcColors],
  );

  const controls = useMemo(
    () => (
      <Stack gap="sm">
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Region
          </Text>
          <Select
            size="xs"
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
            comboboxProps={{ withinPortal: true, portalProps: { target: fsPortalTarget } }}
          />
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Junctions kept
          </Text>
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
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Zoom
          </Text>
          <Group gap={4} wrap="nowrap">
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => panBy(-0.25)}
            >
              ←
            </Button>
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => zoomBy(ZOOM_FACTOR)}
            >
              +
            </Button>
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => zoomBy(1 / ZOOM_FACTOR)}
            >
              −
            </Button>
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => panBy(0.25)}
            >
              →
            </Button>
            <Button
              size="compact-xs"
              variant="subtle"
              onClick={() => setView(null)}
              disabled={!view}
            >
              Fit
            </Button>
          </Group>
          <Text size="xs" c="dimmed">
            {view
              ? `${bp(Math.round(view[0]))}-${bp(Math.round(view[1]))} · ${bp(
                  Math.round(view[1] - view[0]),
                )} bp`
              : 'Whole region. Drag on the plot to zoom into a span.'}
          </Text>
        </Stack>
        {config.coverage_dc_id ? (
          <Stack gap={4}>
            <Text size="xs" fw={500}>
              Coverage
            </Text>
            <Switch
              size="xs"
              checked={showCoverage}
              onChange={(e) => setShowCoverage(e.currentTarget.checked)}
              label="Read depth under the arcs"
            />
            {showCoverage ? (
              <>
                <Text size="xs" c="dimmed">
                  Coverage height: {Math.round(coverageHeight * 100)}% of each lane
                </Text>
                <Slider
                  size="xs"
                  min={10}
                  max={80}
                  value={Math.round(coverageHeight * 100)}
                  onChange={(v) => setCoverageHeight(v / 100)}
                />
                <Switch
                  size="xs"
                  checked={coverageLog}
                  onChange={(e) => setCoverageLog(e.currentTarget.checked)}
                  label="Log depth axis"
                />
                <ColorInput
                  size="xs"
                  format="hex"
                  label="Coverage fill"
                  withEyeDropper={false}
                  popoverProps={{ withinPortal: true, portalProps: { target: fsPortalTarget } }}
                  swatches={paletteDefaults.palette.slice(0, 12)}
                  value={coverageColor}
                  onChange={(v) => setCoverageColor(v || '')}
                />
              </>
            ) : null}
            <Text size="xs" c="dimmed">
              {coverageError
                ? `Coverage collection failed to load: ${coverageError}`
                : coverageActive
                  ? `Measured depth, peaking at ${coverage.max.toLocaleString()}` +
                    (coverage.shared && lanes.length > 1
                      ? '. One profile for the locus: the coverage collection has no sample column, so the same depth is drawn under every lane.'
                      : '. Replaces the inferred exon support, which estimates the same thing from spliced reads only.')
                : 'No coverage in this region.'}
            </Text>
          </Stack>
        ) : null}
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Tracks
          </Text>
          <Switch
            size="xs"
            checked={showSupport}
            onChange={(e) => setShowSupport(e.currentTarget.checked)}
            label="Exon support under the arcs"
            disabled={coverageActive}
          />
          {showSupport ? (
            <>
              <Text size="xs" c="dimmed">
                Support height: {Math.round(supportHeight * 100)}% of each lane
              </Text>
              <Slider
                size="xs"
                min={10}
                max={60}
                value={Math.round(supportHeight * 100)}
                onChange={(v) => setSupportHeight(v / 100)}
              />
            </>
          ) : null}
          <Switch
            size="xs"
            checked={showGeneModel}
            onChange={(e) => setShowGeneModel(e.currentTarget.checked)}
            label="Exon model lane"
          />
          {showGeneModel ? (
            <>
              <Text size="xs" c="dimmed">
                Exon lane height: {Math.round(geneModelHeight * 100)}% of the panel
              </Text>
              <Slider
                size="xs"
                min={5}
                max={40}
                value={Math.round(geneModelHeight * 100)}
                onChange={(v) => setGeneModelHeight(v / 100)}
              />
            </>
          ) : null}
          <Text size="xs" c="dimmed">
            {coverageActive
              ? 'The exon model is inferred from the junction ends in this table. Support is off while measured coverage is shown.'
              : 'Both are inferred from the junction ends in this table, not read from an alignment or an annotation file. Support counts spliced reads only.'}
          </Text>
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Arcs
          </Text>
          {annotationValues.length > 1 ? (
            <Select
              size="xs"
              label="Sides"
              value={arcSplit}
              onChange={(v) => setArcSplit(v === 'alternate' ? 'alternate' : 'annotation')}
              data={[
                {
                  value: 'annotation',
                  label: `${annotationValues[0]} above, ${annotationValues[1]} below`,
                },
                { value: 'alternate', label: 'Alternate along the locus' },
              ]}
              allowDeselect={false}
              comboboxProps={{ withinPortal: true, portalProps: { target: fsPortalTarget } }}
            />
          ) : null}
          <Switch
            size="xs"
            checked={widthBySupport}
            onChange={(e) => setWidthBySupport(e.currentTarget.checked)}
            label="Scale width by read support"
          />
          {widthBySupport ? (
            <Switch
              size="xs"
              checked={logWidth}
              onChange={(e) => setLogWidth(e.currentTarget.checked)}
              label="Log-scaled arc width"
            />
          ) : null}
          <Text size="xs" c="dimmed">
            {widthBySupport ? `Thickest arc: ${maxArcWidth} px` : `Arc width: ${maxArcWidth} px`}
          </Text>
          <Slider size="xs" min={1} max={18} value={maxArcWidth} onChange={setMaxArcWidth} />
          <Text size="xs" c="dimmed">
            Arc height: {Math.round(arcHeight * 100)}%
          </Text>
          <Slider
            size="xs"
            min={30}
            max={150}
            value={Math.round(arcHeight * 100)}
            onChange={(v) => setArcHeight(v / 100)}
          />
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Arc colours
          </Text>
          {annotationValues.length ? (
            <Select
              size="xs"
              label="Colour arcs by"
              value={colorBy}
              onChange={(v) => setColorBy(v === 'sample' ? 'sample' : 'annotation')}
              data={[
                { value: 'annotation', label: config.annotation_col || 'Annotation' },
                { value: 'sample', label: config.sample_col || 'Sample' },
              ]}
              allowDeselect={false}
              comboboxProps={{ withinPortal: true, portalProps: { target: fsPortalTarget } }}
            />
          ) : null}
          {annotationValues.length ? (
            annotationValues.map((value) => (
              <ColorInput
                key={value}
                size="xs"
                format="hex"
                label={value}
                withEyeDropper={false}
                popoverProps={{ withinPortal: true, portalProps: { target: fsPortalTarget } }}
                swatches={paletteDefaults.palette.slice(0, 12)}
                value={arcColors[value] || paletteDefaults.map.get(value) || ''}
                onChange={(v) => setArcColor(value, v)}
              />
            ))
          ) : (
            <ColorInput
              size="xs"
              format="hex"
              label="All junctions"
              withEyeDropper={false}
              popoverProps={{ withinPortal: true, portalProps: { target: fsPortalTarget } }}
              swatches={paletteDefaults.palette.slice(0, 12)}
              value={arcColors[ARC_COLOR_ALL] || paletteDefaults.palette[0] || ''}
              onChange={(v) => setArcColor(ARC_COLOR_ALL, v)}
            />
          )}
          {Object.keys(arcColors).length ? (
            <Button size="compact-xs" variant="subtle" onClick={() => setArcColors({})}>
              Back to theme colours
            </Button>
          ) : null}
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Labels
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
      arcHeight,
      arcColors,
      arcSplit,
      setArcSplit,
      widthBySupport,
      setWidthBySupport,
      colorBy,
      setColorBy,
      setMaxArcWidth,
      setArcColors,
      setArcColor,
      paletteDefaults,
      annotationValues,
      fsPortalTarget,
      coverage,
      coverageActive,
      coverageError,
      coverageHeight,
      coverageColor,
      coverageLog,
      showCoverage,
      setShowCoverage,
      setCoverageHeight,
      setCoverageColor,
      setCoverageLog,
      config.coverage_dc_id,
      showSupport,
      showGeneModel,
      supportHeight,
      geneModelHeight,
      view,
      zoomBy,
      panBy,
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
          onRelayout={handleRelayout as any}
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default SashimiRenderer;
