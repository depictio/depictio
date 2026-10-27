import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  CloseButton,
  Group,
  Stack,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import type { RootSpec } from '@genome-spy/core/spec/root.js';

import {
  authFetch,
  fetchAdvancedVizData,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { columnCategoryColors } from '../../categoryColors';
import { resolveCategoricalPalette } from '../../colors';
import { useCategoryColorSource } from '../../hooks/useCategoryColors';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  genomeRegionFilters,
  regionFromFilters,
} from '../../selection';
import { useWebglSlot } from '../../webglBudget';
import { useHighlight, usePublishHighlight } from '../../highlight/bus';
import { hoverInterval } from '../../highlight/genomicHover';
import { useViewWindow } from '../../highlight/viewWindow';
import type { GroupRenderState } from '../../selectionGroups';
import type { GenomePoint, OpenLocusReader } from '../jbrowse/locusForAction';
import { useTrackSampleColours } from '../jbrowse/genomeTracksStore';
import AdvancedVizFrame from './AdvancedVizFrame';
import { plotlyThemeColors } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';
import {
  ANNOTATION_ASSEMBLIES,
  BUILTIN_ASSEMBLIES,
  buildGenomeSpySpec,
  effectiveMark,
  FACET_LANE_HEIGHT,
  latchSeedRows,
  regionFromInterval,
  requiredColumns,
  rowsToObjects,
} from './genomespy/genomeSpySpec';
import type { Contig, GenomeRegion, GenomeViewConfig } from './genomespy/genomeSpySpec';
import { loadGeneAnnotation } from './genomespy/geneAnnotations';
import type { GeneAnnotation } from './genomespy/geneAnnotations';
import {
  dataContigsInAssemblyOrder,
  defaultRegionFilters,
  opensOnFirstContig,
  ownRegionKey,
  ownRegionZoom,
} from './genomespy/defaultRegion';
import {
  filtersForGenomeViewFetch,
  loadGenomeViewRows,
  mergeWindowRows,
  navigatorWindow,
  navigatorWindowFilters,
  ownRegion,
} from './genomespy/genomeViewData';
import {
  announceDefaultRegion,
  DEFAULT_REGION_GATE_MS,
  settleDefaultRegion,
  useDefaultRegionGate,
  withdrawDefaultRegion,
} from './genomespy/defaultRegionGate';
import LocusInput from './genomespy/LocusInput';
import { rememberDefaultRegion } from './genomespy/defaultRegionMemo';
import {
  VizControlGroup,
  VizFullRow,
  VizNumberInput,
  VizSegmented,
  VizSelect,
  VizSlider,
  VizSwitch,
} from './controls/VizControls';
import {
  buildFileGenomeSpec,
  fetchIndexedFileManifest,
  fileTrackOptions,
} from './genomespy/fileSpec';
import type { IndexedFileManifest } from './genomespy/fileSpec';
import {
  clearGenomeSpyBrush,
  loadAssemblyContigs,
  readViewDomain,
  setGenomeSpyRows,
  useGenomeSpy,
  zoomToRegion,
} from './genomespy/useGenomeSpy';
import { useGenomeSpyOverlays } from './genomespy/useGenomeSpyOverlays';
import {
  compactRegion,
  hoverRows as buildHoverRows,
  paddedRegion,
  selectionRows as buildSelectionRows,
  windowInDomain,
  windowIsRegion,
  windowRows as buildWindowRows,
} from './genomespy/overlayRows';
import OverlayLegend from './genomespy/OverlayLegend';
import LinkedTileChip from '../genomeLink/LinkedTileChip';
import { setTileStats } from '../chrome/tileStats';
import { LINK_COLOR, tileTitle } from '../genomeLink/linkedTile';
import { describeFilters, traceGenome } from '../genomeLink/genomeDebug';

/**
 * `genome_view`: a genomic view drawn by GenomeSpy (issue #1083).
 *
 * Same `chr / pos / score` binding as the Manhattan plot, so every DC that
 * renderer reads renders here too, but the chromosome-concatenated axis, the
 * locus zoom, the region brush and the mark picking are GenomeSpy's own
 * grammar rather than rebuilt from Plotly primitives. The evaluation is in
 * docs/design/genomespy-eval.md.
 *
 * An advanced_viz tile binds exactly one data collection, so "multi-track"
 * means several of these tiles stacked in one dashboard section sharing a
 * region filter, not one tile reading N collections. The brush publishes the
 * region as an ordinary chromosome multi-select plus a position range
 * (`genomeRegionFilters`), and a tile with `follow_region_filter` zooms to an
 * incoming one instead of showing the whole genome. `sample_col` +
 * `facet_by_sample` stack per-sample lanes *within* one tile, which is the one
 * kind of multi-track a single collection can express.
 *
 * Selection follows the Manhattan rule exactly: inert unless the dashboard
 * opts in with `selection_column`, a click emits that column's value as a
 * `scatter_selection` filter, and this component never narrows itself by its
 * own selection.
 */

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: GenomeViewConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no picking, no
   *  region brush. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Dashboard-wide analysis grouping. Not applied: this kind colours by its
   *  category column or by sample, and `GROUPING_MODE_BY_KIND` says
   *  'none', so the chrome's badge reports that the groups did not reach this
   *  tile. */
  groupRender?: GroupRenderState;
}

/** The brushed region as the badge reports it: one chromosome with its position
 *  range, or the chromosome list when the brush spans several contigs. */
function regionLabel(region: GenomeRegion | null): string | null {
  if (!region) return null;
  if (!region.range) return region.chroms.join(', ');
  return `${region.chroms[0]}:${Math.round(region.range[0])}-${Math.round(region.range[1])}`;
}

/** No named overlay sources (a file-backed tile): the DOM fallback paints. */
const NO_OVERLAYS: never[] = [];
/** Fixed lane heights offered once lanes stop fitting the tile. */
const LANE_HEIGHTS = [
  { px: 40, label: 'S' },
  { px: 64, label: 'M' },
  { px: 100, label: 'L' },
];
/** The height lanes take when "Fit lanes to the tile" is switched off. */
const DEFAULT_FIXED_LANE_PX = 64;
/** Height of a lane's title, above the lane. */
const LANE_TITLE_PX = 16;
/** Room for the axis and the gene lane around the stacked lanes. */
const LANES_BASE_PX = 70;

const GenomeViewRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as GenomeViewConfig;

  /**
   * `source: 'file'` is a different data path, not a different look.
   *
   * A table-backed tile fetches rows and hands GenomeSpy a materialised
   * dataset; a file-backed one hands it presigned URLs and GenomeSpy range-
   * loads the visible window from the bucket itself. So in file mode this
   * component fetches a manifest instead of rows, builds the spec from
   * `fileSpec.ts` instead of `genomeSpySpec.ts`, and asks the embed hook for
   * the fat GenomeSpy bundle, which is the only one that registers the vcf /
   * bam / bigwig / bigbed / gff3 / tabix parsers.
   */
  const fileMode = config.source === 'file';

  // Tier-2 controls. Defaults agree with GenomeViewConfig's own.
  const [mark, setMark] = usePersistedVizControl<'point' | 'rect' | 'bar'>(metadata, 'mark', 'rect');
  const [pointSize, setPointSize] = usePersistedVizControl<number>(metadata, 'point_size', 5);
  const [opacity, setOpacity] = usePersistedVizControl<number>(metadata, 'opacity', 0.85);
  const [scoreThreshold, setScoreThreshold] = usePersistedVizControl<number | null>(
    metadata,
    'score_threshold',
    null,
  );
  const [assembly, setAssembly] = usePersistedVizControl<string | null>(metadata, 'assembly', null);
  const [annotation, setAnnotation] = usePersistedVizControl<'none' | 'hg38' | 'mm10'>(
    metadata,
    'annotation',
    'none',
  );
  const [facetBySample, setFacetBySample] = usePersistedVizControl<boolean>(
    metadata,
    'facet_by_sample',
    false,
  );
  const [maxFacets, setMaxFacets] = usePersistedVizControl<number>(metadata, 'max_facets', 8);
  const [dragMode, setDragMode] = usePersistedVizControl<'select' | 'pan'>(
    metadata,
    'drag_mode',
    config.drag_mode === 'pan' ? 'pan' : 'select',
  );
  const [laneHeight, setLaneHeight] = usePersistedVizControl<number | null>(metadata, 'lane_height', null);
  const [facetYScale, setFacetYScale] = usePersistedVizControl<'shared' | 'independent'>(
    metadata,
    'facet_y_scale',
    'shared',
  );
  const [followRegion, setFollowRegion] = usePersistedVizControl<boolean>(
    metadata,
    'follow_region_filter',
    false,
  );

  // ---- Selection as a cross-filter ---------------------------------------
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);
  const regionBrushEnabled = Boolean(onFilterChange) && config.region_filter_enabled !== false;

  // ---- Holding the first fetch for a default region -----------------------
  // A tile with a `default_region` to emit is a navigator: it announces that
  // to the section (`defaultRegionGate.ts`) so the tracks under it hold their
  // first fetch until the region lands instead of reading the whole genome
  // first. Every other table-backed tile is such a follower.
  const hasDefaultRegion =
    Boolean(onFilterChange) && regionBrushEnabled && Boolean((config.default_region ?? '').trim());
  // One decision per session, emitted or not (see the default-region effect).
  const defaultRegionDecided = useRef(false);
  // What the default-region decision came to, for this tile's own fetch hold.
  const [defaultOutcome, setDefaultOutcome] = useState<'pending' | 'emitted' | 'none'>('pending');
  // Announced while rendering, not in an effect: the followers mounted in the
  // same commit run their fetch effects before this tile's effects would.
  if (hasDefaultRegion && !defaultRegionDecided.current) announceDefaultRegion(metadata.index);
  useEffect(() => {
    if (!hasDefaultRegion) return undefined;
    if (!defaultRegionDecided.current) announceDefaultRegion(metadata.index);
    return () => withdrawDefaultRegion(metadata.index);
  }, [hasDefaultRegion, metadata.index]);
  const followerGateOpen = useDefaultRegionGate(
    filters,
    metadata.index,
    !fileMode && !hasDefaultRegion,
  );

  const effectiveConfig = useMemo<GenomeViewConfig>(
    () => ({
      ...config,
      mark,
      point_size: pointSize,
      opacity,
      score_threshold: scoreThreshold,
      assembly,
      annotation,
      facet_by_sample: facetBySample,
      max_facets: maxFacets,
      lane_height: laneHeight,
      facet_y_scale: facetYScale,
      follow_region_filter: followRegion,
      region_filter_enabled: regionBrushEnabled,
      drag_mode: dragMode,
      selection_enabled: selectionEnabled,
      selection_column: selectionColumn ?? null,
    }),
    [
      config,
      mark,
      pointSize,
      opacity,
      scoreThreshold,
      assembly,
      annotation,
      facetBySample,
      maxFacets,
      laneHeight,
      dragMode,
      facetYScale,
      followRegion,
      regionBrushEnabled,
      selectionEnabled,
      selectionColumn,
    ],
  );

  const requiredCols = useMemo(
    () => requiredColumns(effectiveConfig, selectionColumn).filter(Boolean),
    [effectiveConfig, selectionColumn],
  );

  // Both halves of this tile's own region filter are stripped before it
  // fetches, for the same reason every other selection source strips its own:
  // a tile narrowed by its own brush could never widen the brush again.
  const filtersForFetch = useMemo(
    () => filtersForGenomeViewFetch(filters, metadata.index),
    [filters, metadata.index],
  );

  // ---- Fetching the window around the tile's own region -------------------
  // With a built-in assembly the genome axis comes from the assembly, not from
  // the rows, so a navigator can fetch only the window around the region it
  // published (`navigatorWindow`) without losing a single contig. The same
  // condition lets it decide its default region before any row has arrived,
  // so its own first fetch waits for that decision (at most the gate timeout)
  // and is already a window.
  const builtinAssembly =
    !fileMode && Boolean(effectiveConfig.assembly && BUILTIN_ASSEMBLIES.includes(effectiveConfig.assembly));
  const [ownHoldExpired, setOwnHoldExpired] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setOwnHoldExpired(true), DEFAULT_REGION_GATE_MS);
    return () => clearTimeout(timer);
  }, []);

  // The fetch as read: the window when the tile is narrowed to one, else the
  // whole genome. `rows` (below) is what the tile draws.
  const [fetchedRows, setRows] = useState<Record<string, unknown[]> | null>(null);
  // The chromosome `fetchedRows` was narrowed to, null for a whole-genome
  // read: the merge below must use the window the rows came from, not the
  // one a newer brush asks for while its read is in flight.
  const [fetchedChrom, setFetchedChrom] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);

  // ---- File-backed tracks: the manifest, not the rows ---------------------
  const [manifest, setManifest] = useState<IndexedFileManifest | null>(null);
  useEffect(() => {
    if (!fileMode) {
      setManifest(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setFetchError(null);
    // The URLs in the manifest are presigned and expire (15 minutes), so this
    // re-runs on the refresh tick like any other fetch; a stale URL would
    // otherwise start 403ing mid-pan. Through `authFetch`: the endpoint reads a
    // bearer token, not the cookie, so a bare fetch is anonymous and 401s on
    // any instance that is not in public / single-user mode.
    fetchIndexedFileManifest(String(metadata.dc_id ?? ''), (url) => authFetch(url))
      .then((m) => {
        if (!cancelled) setManifest(m);
      })
      .catch((err: unknown) => {
        if (!cancelled) setFetchError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fileMode, metadata.dc_id, refreshTick]);

  // ---- Assets: built-in contigs and the gene lane -------------------------
  // Both are static per assembly and memoised process-wide, so four hg38 tiles
  // on one dashboard pay for them once.
  // In file mode the collection itself can name the assembly, which is the one
  // place that knows what the files were called against; the tile's own
  // setting still wins when it has one.
  const trackAssembly = fileMode
    ? (effectiveConfig.assembly ?? manifest?.assembly ?? null)
    : effectiveConfig.assembly;
  const [assemblyContigs, setAssemblyContigs] = useState<Contig[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    const name = trackAssembly;
    if (!name || !BUILTIN_ASSEMBLIES.includes(name)) {
      setAssemblyContigs(null);
      return undefined;
    }
    loadAssemblyContigs(name).then((c) => {
      if (!cancelled) setAssemblyContigs(c);
    });
    return () => {
      cancelled = true;
    };
  }, [trackAssembly]);

  // The window the fetch is narrowed to: the chromosome of this tile's own
  // region, and only when the axis does not depend on the rows. A new region
  // on the same chromosome (a brush, a locus typed nearby) keeps the window
  // and costs no refetch; another chromosome, or a cleared region, moves it.
  const ownRegionNow = useMemo(
    () => ownRegion(filters, metadata.index, config.chr_col, config.pos_col),
    [filters, metadata.index, config.chr_col, config.pos_col],
  );
  const fetchWindowChrom = builtinAssembly && assemblyContigs?.length ? (ownRegionNow?.chrom ?? null) : null;
  const fetchWindow = useMemo(
    () => (fetchWindowChrom ? navigatorWindow({ chrom: fetchWindowChrom, start: 0, end: Infinity }) : null),
    [fetchWindowChrom],
  );
  const windowFilters = useMemo(
    () => navigatorWindowFilters(metadata, config.chr_col, config.pos_col, fetchWindow),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [metadata.index, metadata.dc_id, config.chr_col, config.pos_col, fetchWindow],
  );
  // The navigator's own first fetch waits for its default-region decision and,
  // when it emitted, for that region to come back through the host's filters,
  // so the first read is already the window.
  const holdOwnFetch =
    hasDefaultRegion &&
    builtinAssembly &&
    !ownHoldExpired &&
    (defaultOutcome === 'pending' || (defaultOutcome === 'emitted' && !ownRegionNow));

  useEffect(() => {
    if (fileMode) return undefined;
    // Waiting for a default region (this tile's own, or a navigator's above):
    // the skeleton stays up instead of a whole-genome read that the region
    // would replace a moment later.
    if (holdOwnFetch || !followerGateOpen) {
      setLoading(true);
      return undefined;
    }
    let cancelled = false;
    const windowChrom = fetchWindowChrom;
    setLoading(true);
    setFetchError(null);
    loadGenomeViewRows(fetchAdvancedVizData, {
      metadata,
      config: effectiveConfig,
      filters: filtersForFetch,
      selectionColumn,
      windowFilters,
    })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setFetchedChrom(windowChrom);
        setEstimated(res.estimated);
      })
      .catch((err: unknown) => {
        if (!cancelled) setFetchError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    fileMode,
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filtersForFetch),
    JSON.stringify(windowFilters),
    holdOwnFetch,
    followerGateOpen,
    scoreThreshold,
    refreshTick,
  ]);

  // While narrowed to a window, the whole genome is read too, once per
  // filter set: the other chromosomes keep their marks around the region.
  // Not refetched on a brush or a chromosome change, only on the filters.
  const [genomeRows, setGenomeRows] = useState<Record<string, unknown[]> | null>(null);
  const needsGenome = Boolean(fetchWindow) && !holdOwnFetch && followerGateOpen;
  useEffect(() => {
    if (fileMode || !needsGenome) return undefined;
    let cancelled = false;
    loadGenomeViewRows(fetchAdvancedVizData, {
      metadata,
      config: effectiveConfig,
      filters: filtersForFetch,
      selectionColumn,
    })
      .then((res) => {
        if (!cancelled) setGenomeRows(res.rows);
      })
      // The window still draws; only the context around it is missing.
      .catch(() => {
        if (!cancelled) setGenomeRows(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    fileMode,
    needsGenome,
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filtersForFetch),
    scoreThreshold,
    refreshTick,
  ]);
  const knownContigs = useMemo(
    () => (assemblyContigs ? new Set(assemblyContigs.map((c) => c.name)) : null),
    [assemblyContigs],
  );
  const rows = useMemo(
    () =>
      fetchedRows && fetchedChrom && genomeRows
        ? mergeWindowRows(
            genomeRows,
            fetchedRows,
            effectiveConfig.chr_col,
            fetchedChrom,
            knownContigs,
          )
        : fetchedRows,
    [fetchedRows, fetchedChrom, genomeRows, effectiveConfig.chr_col, knownContigs],
  );

  const [geneAnnotation, setGeneAnnotation] = useState<GeneAnnotation | null>(null);
  // Whether the lane's gene table has been read (or there is none to read), so
  // a `default_region` naming a gene is not decided against a table that is
  // still loading.
  const [genesSettled, setGenesSettled] = useState(false);
  useEffect(() => {
    let cancelled = false;
    loadGeneAnnotation(effectiveConfig.annotation)
      .then((g) => {
        if (!cancelled) setGeneAnnotation(g);
      })
      .finally(() => {
        if (!cancelled) setGenesSettled(true);
      });
    return () => {
      cancelled = true;
    };
  }, [effectiveConfig.annotation]);

  // Gene symbols for the locus field. The lane above is opt-in (a navigator
  // usually hides it), but "type MYC" must still resolve, so the search table
  // falls back to the track's assembly when no lane is drawn.
  const [searchAnnotation, setSearchAnnotation] = useState<GeneAnnotation | null>(null);
  const searchAssembly =
    effectiveConfig.annotation && effectiveConfig.annotation !== 'none'
      ? effectiveConfig.annotation
      : trackAssembly;
  useEffect(() => {
    let cancelled = false;
    loadGeneAnnotation(searchAssembly).then((g) => {
      if (!cancelled) setSearchAnnotation(g);
    });
    return () => {
      cancelled = true;
    };
  }, [searchAssembly]);

  // One GenomeSpy embed is one WebGL context, a third of what a Plotly
  // scattergl costs, so it competes for a slot like any point cloud. Without
  // one it draws on Canvas2D, which keeps every feature and just paints slower.
  const glGranted = useWebglSlot(true);
  const backend = glGranted ? 'webgl' : 'canvas';

  const themeColors = plotlyThemeColors(isDark, theme);
  const palette = resolveCategoricalPalette(theme);
  // The selection, the window band and the hover rule wear the theme's
  // primary colour, as the other genomic tiles' cursors do.
  const overlayColor =
    theme.colors[theme.primaryColor]?.[isDark ? 4 : 7] ?? theme.colors.blue[isDark ? 4 : 7];
  // The browser's window wears the link's colour, as the tags of both tiles do.
  const linkColor = theme.colors[LINK_COLOR][isDark ? 4 : 6];
  const overlayColors = useMemo(
    () => ({
      windowColor: linkColor,
      hoverColor: overlayColor,
      selectionColor: overlayColor,
    }),
    [overlayColor, linkColor],
  );
  // A category (or a sample) wears the dashboard's colour for it. Keyed
  // by content below, so a refetched dashboard with the same colours does not
  // tear the embed down.
  const categorySource = useCategoryColorSource();
  const pinned = useMemo(() => {
    const out: Record<string, Record<string, string>> = {};
    for (const column of [effectiveConfig.category_col, effectiveConfig.sample_col]) {
      const colours = columnCategoryColors(categorySource, column);
      if (column && colours) out[column] = colours;
    }
    return Object.keys(out).length ? out : null;
  }, [categorySource, effectiveConfig.category_col, effectiveConfig.sample_col]);
  // A lane wears the colour the genome browser gives the same library's
  // tracks (e.g. one per design group), read from the browser tiles of this
  // dashboard; marks no colour names stay neutral.
  const laneColors = useTrackSampleColours();
  const neutralColor = isDark ? theme.colors.gray[5] : theme.colors.gray[6];

  // The rows as GenomeSpy reads them, from the *current* fetch: they feed the
  // dataset swap below and the row count the chrome reports.
  const liveData = useMemo(
    () =>
      rows
        ? rowsToObjects(rows, requiredCols, effectiveConfig.chr_col, effectiveConfig.pos_col)
        : null,
    [rows, requiredCols, effectiveConfig.chr_col, effectiveConfig.pos_col],
  );
  const rowCount = liveData?.length ?? 0;

  // The spec carries the *shape*: columns, mark, lanes, threshold, assembly,
  // colours. It is built from the first *non-empty* rows only; later rows go
  // through `setGenomeSpyRows` so a moved filter does not tear the embed down.
  // An empty first fetch is not a seed: it would fix an empty contig list into
  // the spec (see `latchSeedRows`), so the tile waits for rows instead.
  const seedRef = useRef<Record<string, unknown[]> | null>(null);
  seedRef.current = latchSeedRows(
    seedRef.current,
    rows,
    effectiveConfig.chr_col,
    effectiveConfig.pos_col,
  );
  const seed = seedRef.current;
  const built = useMemo(() => {
    if (!seed) return null;
    return buildGenomeSpySpec({
      rows: seed,
      config: effectiveConfig,
      colors: {
        textColor: themeColors.textColor,
        gridColor: themeColors.gridColor,
        ruleColor: themeColors.zeroLineColor,
        palette,
        pinned,
        laneColors,
        neutral: neutralColor,
        overlay: overlayColors,
      },
      assemblyContigs,
      genes: geneAnnotation?.genes ?? null,
      clickable: selectionEnabled,
    });
    // `seed` is null until the first non-empty fetch and the same object ever
    // after, so keying on it rebuilds exactly once, when it latches.
    // `palette` is a fresh array each render but its contents are stable for a
    // theme; key on the joined hues rather than the identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    seed,
    effectiveConfig,
    assemblyContigs,
    geneAnnotation,
    themeColors.textColor,
    themeColors.gridColor,
    themeColors.zeroLineColor,
    palette.join(','),
    JSON.stringify(pinned),
    laneColors,
    neutralColor,
    overlayColors,
    selectionEnabled,
  ]);
  // The file-backed spec. Built from the manifest, so it changes when the
  // presigned URLs are refreshed; that is a genuine remount, since the lazy
  // sources hold the old URLs.
  const [fileSpecError, setFileSpecError] = useState<string | null>(null);
  const builtFile = useMemo(() => {
    if (!fileMode || !manifest) return null;
    try {
      const out = buildFileGenomeSpec({
        manifest,
        options: fileTrackOptions(effectiveConfig, { opacity, pointSize }),
        colors: {
          textColor: themeColors.textColor,
          gridColor: themeColors.gridColor,
          ruleColor: themeColors.zeroLineColor,
          palette,
        },
        assemblyContigs,
        assembly: effectiveConfig.assembly ?? null,
        regionBrushEnabled,
      });
      setFileSpecError(null);
      return out;
    } catch (err) {
      setFileSpecError(err instanceof Error ? err.message : String(err));
      return null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    fileMode,
    manifest,
    effectiveConfig,
    opacity,
    pointSize,
    assemblyContigs,
    regionBrushEnabled,
    themeColors.textColor,
    themeColors.gridColor,
    themeColors.zeroLineColor,
    palette.join(','),
  ]);

  const spec = ((fileMode ? builtFile?.spec : built?.spec) ?? null) as RootSpec | null;
  const contigs = (fileMode ? builtFile?.contigs : built?.contigs) ?? null;

  const emitSelection = useCallback(
    (values: string[]) => {
      if (!onFilterChange || !selectionColumn) return;
      onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, values));
    },
    [onFilterChange, selectionColumn, metadata],
  );
  // The last mark the reader clicked, as a contig and a position: where "Open
  // in genome browser" goes, whether or not the tile selects. The visible
  // window is not offered: the brushed region (read off the filters by the
  // action) is what the tile's address bar shows.
  const lastPointRef = useRef<GenomePoint | null>(null);
  const handlePick = useCallback(
    (datum: Readonly<Record<string, unknown>>) => {
      const chrom = datum[config.chr_col];
      const pos = Number(datum[config.pos_col]);
      if (chrom != null && chrom !== '' && Number.isFinite(pos)) {
        lastPointRef.current = { chrom: String(chrom), pos };
      }
      if (!selectionColumn) return;
      const v = datum[selectionColumn];
      emitSelection(v === null || v === undefined ? [] : [String(v)]);
    },
    [emitSelection, selectionColumn, config.chr_col, config.pos_col],
  );
  const openLocus = useCallback<OpenLocusReader>(
    () => ({ point: lastPointRef.current }),
    [],
  );

  const [brushedRegion, setBrushedRegion] = useState<string | null>(null);
  // True while a zoom issued from code (locus field, default region, filter
  // reset, followed region) is in flight: a brush event fired by that zoom is
  // not the reader's gesture and must not be re-emitted as a filter.
  const zoomingFromCodeRef = useRef(false);
  // Key of the region this tile's own brush last published, so the own-region
  // zoom below can tell "the reader just dragged" from "the locus field moved".
  const brushedKeyRef = useRef<string | null>(null);
  const handleBrush = useCallback(
    (interval: number[] | null) => {
      if (!onFilterChange || !contigs) return;
      if (zoomingFromCodeRef.current) return;
      const region = regionFromInterval(contigs, interval);
      setBrushedRegion(regionLabel(region));
      traceGenome(String(metadata.index), region ? 'brush released' : 'brush emptied', region);
      // Two entries, one per column: `mergeFiltersBySource` keys on
      // (index, source) and they carry different indices, so they coexist.
      const pair = genomeRegionFilters(metadata, config.chr_col, config.pos_col, region);
      brushedKeyRef.current = ownRegionKey(pair, metadata.index) || null;
      for (const filter of pair) {
        onFilterChange(filter);
      }
    },
    [onFilterChange, contigs, metadata, config.chr_col, config.pos_col],
  );

  // ---- Hover → the other tiles ----------------------------------------------
  // The mark under the pointer goes out whole: a contig interval for a genome
  // browser, the row as `record` for a table or a plot reading its own columns.
  // Best effort (see `onHover` in useGenomeSpy). Overlay marks carry no
  // chromosome / position column of this tile's, so they publish nothing.
  const ownIndex = String(metadata.index);
  const publishHighlight = usePublishHighlight(ownIndex);
  const handleHover = useCallback(
    (datum: Readonly<Record<string, unknown>> | null) => {
      if (!datum) {
        publishHighlight(null);
        return;
      }
      const chrom = datum[config.chr_col];
      const pos = Number(datum[config.pos_col]);
      if (chrom == null || chrom === '' || !Number.isFinite(pos)) return;
      const rawEnd = config.end_col ? Number(datum[config.end_col]) : Number.NaN;
      const end = Number.isFinite(rawEnd) && rawEnd >= pos ? rawEnd : pos;
      const key = selectionColumn ? datum[selectionColumn] : undefined;
      publishHighlight({
        entity: String(chrom),
        start: pos,
        end,
        positionColumn: config.pos_col,
        rowKeys: key != null && key !== '' ? [String(key)] : undefined,
        genomic: { refName: String(chrom), start: pos, end },
        record: { ...datum },
      });
    },
    [publishHighlight, config.chr_col, config.pos_col, config.end_col, selectionColumn],
  );

  const containerRef = useRef<HTMLDivElement | null>(null);
  const { api, error: embedError, restoredView } = useGenomeSpy(containerRef, spec, {
    backend,
    // Only a file-backed spec needs the parsers, so only it pays for them.
    lazySources: fileMode,
    onPick: handlePick,
    onBrush: regionBrushEnabled ? handleBrush : undefined,
    onHover: handleHover,
    dragHint:
      regionBrushEnabled && dragMode !== 'pan'
        ? 'drag to select'
        : regionBrushEnabled
          ? 'drag to pan · shift + drag to select'
          : 'drag to pan',
  });

  // ---- Clearing the region: Escape (the chrome), double-click, the badge's x ----
  // The brush drawn on the axis goes with the filter, wherever the clear came
  // from: the tile's reset or Escape remove the filter, this follows.
  const clearOwnRegion = useCallback(() => {
    traceGenome(String(metadata.index), 'clear own region (double-click or badge)');
    setBrushedRegion(null);
    brushedKeyRef.current = null;
    if (api) clearGenomeSpyBrush(api);
    if (!onFilterChange) return;
    for (const filter of genomeRegionFilters(metadata, config.chr_col, config.pos_col, null)) {
      onFilterChange(filter);
    }
  }, [api, onFilterChange, metadata, config.chr_col, config.pos_col]);
  const hadOwnRegion = useRef(false);
  useEffect(() => {
    const has = Boolean(ownRegionNow);
    if (hadOwnRegion.current && !has && api) {
      // Cleared from outside: drop the drawing without publishing anything.
      traceGenome(String(metadata.index), 'own region cleared from outside: brush dropped, view stays');
      zoomingFromCodeRef.current = true;
      clearGenomeSpyBrush(api);
      zoomingFromCodeRef.current = false;
      setBrushedRegion(null);
      brushedKeyRef.current = null;
    }
    hadOwnRegion.current = has;
  }, [ownRegionNow, api, metadata.index]);

  // ---- The region in force -------------------------------------------------
  // Read off the *unstripped* filters, this tile's own included. The locus
  // field shows it (the field is the section's address bar, so it must show
  // where the reader is even when that is where they just sent everyone), and
  // the selection overlay frames it.
  const displayedRegion = useMemo(
    () => regionFromFilters(filters, config.chr_col, config.pos_col),
    [filters, config.chr_col, config.pos_col],
  );
  useEffect(() => {
    traceGenome(
      String(metadata.index),
      displayedRegion ? 'region in force' : 'no region in force (whole genome fetched)',
      displayedRegion ?? undefined,
    );
  }, [displayedRegion, metadata.index]);
  const selectionLabel = displayedRegion
    ? compactRegion(displayedRegion.chrom, displayedRegion.start, displayedRegion.end)
    : null;
  const selectionOverlayRows = useMemo(
    () =>
      buildSelectionRows(
        displayedRegion,
        contigs ?? [],
        selectionLabel ? `Filter ${selectionLabel}` : undefined,
      ),
    [displayedRegion, contigs, selectionLabel],
  );

  // ---- The genome browser's window and hover → a band and a rule ---------------
  // Both are drawn from named data sources (or a DOM overlay when the embed has
  // no such API): the window is a band, never a zoom, and the hover a rule at
  // the feature. Nothing is emitted back and no filter moves.
  const viewWindow = useViewWindow(ownIndex);
  const hovered = useHighlight(ownIndex);
  const overlayContigNames = useMemo(() => (contigs ?? []).map((c) => c.name), [contigs]);
  const windowBandRows = useMemo(() => {
    const rows = buildWindowRows(viewWindow, overlayContigNames);
    // The browser on the region in force: a band over the whole selection,
    // which the frame already marks.
    if (windowIsRegion(rows, displayedRegion ?? ownRegionNow)) return [];
    return rows.map((r) => ({ ...r, label: 'Browser view' }));
  }, [viewWindow, overlayContigNames, displayedRegion, ownRegionNow]);
  // The browser publishing that window, for the legend's chip.
  const browserIndex = viewWindow?.sourceIndex ?? null;
  const linkedBrowser = browserIndex
    ? { index: browserIndex, title: tileTitle(browserIndex) ?? 'Genome browser' }
    : null;
  const hoverRuleRows = useMemo(() => {
    if (!hovered) return [];
    // A browser's feature or a table row, else the plain cursor's contig.
    const interval =
      hoverInterval(hovered, config.chr_col, config.pos_col, config.end_col) ??
      (hovered.entity
        ? {
            refName: hovered.entity,
            start: hovered.start,
            end: hovered.end ?? hovered.start,
            aliases: hovered.entityAliases,
          }
        : null);
    return buildHoverRows(interval, overlayContigNames);
  }, [hovered, overlayContigNames, config.chr_col, config.pos_col, config.end_col]);
  useGenomeSpyOverlays({
    api,
    container: containerRef,
    overlays: (!fileMode && built?.overlays) || NO_OVERLAYS,
    contigs,
    window: windowBandRows,
    hover: hoverRuleRows,
    selection: selectionOverlayRows,
    colors: overlayColors,
  });

  // Rows changed after the embed was built (filter moved, refresh tick): swap
  // the dataset in place. On the seed rows the spec already carries them, and
  // `datasets.set` with the same content is a harmless no-op. An empty fetch
  // swaps in an empty dataset rather than tearing the embed down.
  useEffect(() => {
    // File mode has no `datasets` to swap: each lane's lazy source refetches
    // on its own when the domain moves.
    if (fileMode || !api || !liveData) return;
    setGenomeSpyRows(api, liveData);
  }, [fileMode, api, liveData]);

  // Every programmatic zoom goes through here so the brush handler can ignore
  // what it provokes. The flag drops a frame after the zoom settles, since
  // GenomeSpy publishes param changes on its own render tick.
  // The embed that has had its opening zoom: the first region an embed shows
  // opens on its whole chromosome (`default_view`), every later one zooms in.
  const openedApiRef = useRef<typeof api>(null);
  const zoomFromCode = useCallback(
    async (region: { chrom: string; start: number; end: number } | null) => {
      if (!api) return;
      zoomingFromCodeRef.current = true;
      try {
        const size = region ? contigs?.find((c) => c.name === region.chrom)?.size : null;
        const opening = !!region && openedApiRef.current !== api && config.default_view !== 'region';
        if (region) openedApiRef.current = api;
        // Opening: the whole chromosome, the region framed in it. Otherwise a
        // margin around the region, so its frame shows against the rest.
        const target = region
          ? opening && size
            ? { ...region, start: 0, end: size }
            : paddedRegion(region, size)
          : null;
        traceGenome(String(metadata.index), target ? 'zoom from code' : 'zoom from code: whole genome', target);
        await zoomToRegion(api, target, contigs);
      } catch {
        // A zoom on a view torn down mid-flight is not worth a tile error.
      } finally {
        requestAnimationFrame(() => {
          zoomingFromCodeRef.current = false;
        });
      }
    },
    [api, contigs, metadata.index, config.default_view],
  );

  // ---- Following someone else's region ------------------------------------
  const incomingRegion = useMemo(
    () => (followRegion ? regionFromFilters(filtersForFetch, config.chr_col, config.pos_col) : null),
    [followRegion, filtersForFetch, config.chr_col, config.pos_col],
  );
  const followedRef = useRef<{ api: typeof api; key: string }>({ api: null, key: '' });
  useEffect(() => {
    if (!api || !followRegion) return;
    if (!incomingRegion) return;
    const key = JSON.stringify(incomingRegion);
    const rebuilt = followedRef.current.api !== api;
    const same = followedRef.current.key === key;
    followedRef.current = { api, key };
    // A rebuilt embed that reopened on the old view is already there, wherever
    // the reader zoomed since following.
    if (rebuilt && same && restoredView) return;
    // A chromosome with no range means "the whole contig", which needs the
    // contig's own length rather than an infinite end.
    void zoomFromCode(incomingRegion);
  }, [api, followRegion, incomingRegion, zoomFromCode, restoredView]);

  // ---- The browser leaving the axis brings the axis along -------------------
  // The link runs both ways: when the genome browser moves out of what the axis
  // shows (next region, another chromosome), the axis moves to the browser's
  // chromosome, so its dashed band stays in sight. A view only, no filter.
  useEffect(() => {
    if (!api) return;
    const win = buildWindowRows(viewWindow, overlayContigNames)[0];
    if (!win || windowInDomain(readViewDomain(api), win, overlayContigNames)) return;
    const size = contigs?.find((c) => c.name === win.chrom)?.size;
    traceGenome(String(metadata.index), 'browser left the axis', win);
    void zoomFromCode(
      config.default_view === 'region' || !size ? win : { chrom: win.chrom, start: 0, end: size },
    );
  }, [api, viewWindow, overlayContigNames, contigs, config.default_view, metadata.index, zoomFromCode]);

  // ---- Zooming to the region this tile emitted ------------------------------
  // The fetch strips this tile's own region (so a brush can widen again), which
  // is also why the tile never followed its own locus field or default region.
  // The fetch stays whole-genome; only the visible domain moves here.
  // `ownRegionZoom` owns the decision; the refs own what it compares against.
  const ownRegionKeyRef = useRef('');
  const zoomedByCodeRef = useRef(false);
  const zoomedApiRef = useRef<typeof api>(null);
  useEffect(() => {
    if (!api) return;
    if (zoomedApiRef.current !== api) {
      zoomedApiRef.current = api;
      if (restoredView) {
        // A rebuilt embed (a mark, a lane or the theme changed) that reopened
        // on the view the old one showed: the region in force is already
        // framed, or zoomed past by the reader, and re-framing it would undo
        // that. The refs keep what they held for the old embed.
        traceGenome(String(metadata.index), 'embed rebuilt: view kept');
        openedApiRef.current = api;
        return;
      }
      // Otherwise it opens on the whole genome again, so the region in force
      // has to be re-applied to it.
      ownRegionKeyRef.current = '';
      zoomedByCodeRef.current = false;
    }
    const { decision, key } = ownRegionZoom({
      filters,
      componentIndex: metadata.index,
      chrColumn: config.chr_col,
      posColumn: config.pos_col,
      previousKey: ownRegionKeyRef.current,
      brushedKey: brushedKeyRef.current,
      zoomedByCode: zoomedByCodeRef.current,
      followedRegion: incomingRegion,
    });
    ownRegionKeyRef.current = key;
    if (decision.action !== 'none' || key !== '') {
      traceGenome(String(metadata.index), `own region: ${decision.action}`, {
        key,
        brushed: key !== '' && key === brushedKeyRef.current,
      });
    }
    if (decision.action === 'none') {
      // A brush of the reader's own supersedes any earlier zoom from code.
      if (key && key === brushedKeyRef.current) zoomedByCodeRef.current = false;
      return;
    }
    zoomedByCodeRef.current = decision.action === 'zoom';
    void zoomFromCode(decision.action === 'zoom' ? decision.region : null);
  }, [
    api,
    restoredView,
    filters,
    metadata.index,
    config.chr_col,
    config.pos_col,
    incomingRegion,
    zoomFromCode,
  ]);

  // ---- Opening on the section's default region ----------------------------
  // The section's address is written in the YAML rather than typed by the
  // reader, once, so a locus section never opens on the whole genome or on
  // nothing. `defaultRegionFilters` owns every reason not to emit; the ref
  // owns "once", which is what keeps a reader who clears the region from
  // being sent straight back to it.
  // With a built-in assembly the contig names are known before any row is:
  // that is what lets the navigator decide, and window its own fetch, first.
  // `first` names a contig of the data, which the assembly's axis does not
  // tell: read the column's distinct contigs, a small query, and order them
  // by the assembly. A failed read falls back to the axis.
  const firstFromData = builtinAssembly && hasDefaultRegion && opensOnFirstContig(config.default_region);
  const [dataContigNames, setDataContigNames] = useState<string[] | null>(null);
  useEffect(() => {
    if (!firstFromData) return undefined;
    let cancelled = false;
    fetchUniqueValues(String(metadata.dc_id ?? ''), config.chr_col)
      .then((values) => {
        if (!cancelled) setDataContigNames(values.map(String));
      })
      .catch(() => {
        if (!cancelled) setDataContigNames([]);
      });
    return () => {
      cancelled = true;
    };
  }, [firstFromData, metadata.dc_id, config.chr_col]);
  const contigNames = useMemo(() => {
    const axis = (contigs ?? (builtinAssembly ? assemblyContigs : null) ?? []).map((c) => c.name);
    if (!firstFromData) return axis;
    if (dataContigNames === null) return [];
    return dataContigNames.length ? dataContigsInAssemblyOrder(dataContigNames, axis) : axis;
  }, [contigs, builtinAssembly, assemblyContigs, firstFromData, dataContigNames]);
  useEffect(() => {
    if (defaultRegionDecided.current || !onFilterChange) return;
    // A locus is resolved against the contigs the data carries, so there is
    // nothing to decide before they are known: `chr7` and `7` are the same
    // place, and a filter carrying the wrong spelling selects no rows at all.
    if (!contigNames.length) return;
    if (!genesSettled) return;
    // One decision per session, emitted or not: coming back through here after
    // the reader has moved on would undo their move.
    defaultRegionDecided.current = true;
    const toEmit = defaultRegionFilters({
      metadata,
      chrColumn: config.chr_col,
      posColumn: config.pos_col,
      defaultRegion: config.default_region,
      enabled: regionBrushEnabled,
      contigs: contigNames,
      genes: geneAnnotation?.genes ?? null,
      filters,
    });
    settleDefaultRegion(metadata.index, Boolean(toEmit));
    traceGenome(
      String(metadata.index),
      toEmit ? 'default region emitted' : 'default region: none emitted',
      toEmit ? describeFilters(toEmit) : undefined,
    );
    setDefaultOutcome(toEmit ? 'emitted' : 'none');
    if (!toEmit) return;
    // Recorded before the emit, so the dispatch reads it on the re-render the
    // emit causes and keeps the tile's clear action hidden for a region the
    // reader did not choose.
    rememberDefaultRegion(metadata.index, ownRegionKey(toEmit, metadata.index));
    for (const filter of toEmit) onFilterChange(filter);
  }, [
    onFilterChange,
    contigNames,
    metadata,
    config.chr_col,
    config.pos_col,
    config.default_region,
    regionBrushEnabled,
    geneAnnotation,
    genesSettled,
    filters,
  ]);

  const locusControls = (
    <LocusInput
      metadata={metadata}
      chrColumn={config.chr_col}
      posColumn={config.pos_col}
      contigs={contigs}
      genes={searchAnnotation?.genes ?? null}
      onFilterChange={regionBrushEnabled ? onFilterChange : undefined}
      region={displayedRegion}
    />
  );

  const counts = useMemo(() => {
    if (fileMode) {
      if (!manifest) return undefined;
      // No row count to report: the browser only ever holds the window it is
      // looking at, so what the chrome can honestly say is how many files the
      // collection published and how many got a lane.
      const out: Record<string, number> = { files: manifest.files.length };
      if (builtFile?.lanes.length) out.lanes = builtFile.lanes.length;
      return out;
    }
    if (!rows) return undefined;
    const out: Record<string, number> = { rows: rowCount };
    if (built?.facets.length) out.lanes = built.facets.length;
    if (built?.geneCount) out.genes = built.geneCount;
    return out;
  }, [
    fileMode,
    manifest,
    builtFile?.lanes.length,
    rows,
    rowCount,
    backend,
    built?.facets.length,
    built?.geneCount,
  ]);
  // Published for the metadata panel, with the renderer, instead of header badges.
  useEffect(() => {
    setTileStats(
      String(metadata.index),
      counts ? { ...counts, renderer: backend === 'webgl' ? 'WebGL' : 'Canvas fallback' } : undefined,
    );
  }, [counts, backend, metadata.index]);

  // The frame replaces its children with `emptyMessage`, which would unmount
  // the container under a live embed and strand it on a detached node. So the
  // frame's message is only used before any embed exists; once one is up, an
  // empty fetch is reported by an overlay and the container stays mounted.
  // The height the stacked lanes need: exact with fixed lanes, a floor when
  // they fit the tile (each keeps FACET_LANE_HEIGHT). A tile shorter than that
  // scrolls rather than clipping the bottom lanes.
  const laneCount = !fileMode ? (built?.facets.length ?? 0) : 0;
  const lanesPx =
    laneCount > 1
      ? laneCount * ((laneHeight || FACET_LANE_HEIGHT) + LANE_TITLE_PX) + LANES_BASE_PX
      : null;
  const fixedLanes = Boolean(laneHeight) && lanesPx !== null;
  const noRows = fileMode
    ? Boolean(manifest) && (builtFile?.lanes.length ?? 0) === 0
    : Boolean(rows) && rowCount === 0;

  const canFacet = Boolean(config.sample_col);
  const annotationHint =
    annotation !== 'none' && built && built.geneCount === 0
      ? 'No gene of this assembly falls on the contigs in view.'
      : null;

  const fileControls = fileMode ? (
    <VizFullRow>
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          File-backed track
        </Text>
        <Text size="xs" c="dimmed">
          {manifest
            ? `${manifest.format.toUpperCase()} read from storage as you zoom in. ` +
              `${builtFile?.lanes.length ?? 0} of ${manifest.files.length} sample(s) drawn.`
            : 'Reading the collection manifest.'}
        </Text>
        {builtFile && builtFile.droppedLanes > 0 ? (
          <Text size="xs" c="dimmed">
            {builtFile.droppedLanes} more sample(s) not drawn; raise the lane cap on the tile.
          </Text>
        ) : null}
        <Text size="xs" c="dimmed">
          Marks, lanes and the threshold rule come from the file itself, so this tile only offers
          the cosmetic controls below.
        </Text>
      </Stack>
    </VizFullRow>
  ) : null;

  // The row-backed controls a file-backed track takes from the file itself.
  // They were hidden, not unmounted, before; their state lives in this
  // component either way, so leaving them out is the same behaviour.
  const controls = (
    <>
      {fileControls}
      <VizControlGroup title="Marks">
        {regionBrushEnabled ? (
          <VizSegmented
            label="Drag"
            value={dragMode}
            onChange={(v) => setDragMode(v === 'pan' ? 'pan' : 'select')}
            data={[
              { value: 'select', label: 'Select region' },
              { value: 'pan', label: 'Pan' },
            ]}
          />
        ) : null}
        {fileMode ? null : (
          <>
            <VizSegmented
              label="Mark"
              value={effectiveMark(effectiveConfig)}
              onChange={(v) => setMark(v as 'point' | 'rect' | 'bar')}
              data={[
                { value: 'point', label: 'Points' },
                { value: 'rect', label: 'Intervals', disabled: !config.end_col },
                { value: 'bar', label: 'Bars' },
              ]}
            />
            <VizFullRow>
              <Text size="xs" c="dimmed">
                {config.end_col
                  ? 'Bars run from the baseline; intervals span start to end.'
                  : 'Bind an end column to draw intervals. GenomeSpy has no line mark, so a coverage profile is drawn as bars.'}
              </Text>
            </VizFullRow>
          </>
        )}
        <VizNumberInput
          label="Point size (px)"
          min={1}
          max={30}
          value={pointSize}
          onChange={(v) => setPointSize(typeof v === 'number' ? v : 5)}
        />
        <VizSlider
          label="Opacity"
          min={0.05}
          max={1}
          step={0.05}
          value={opacity}
          onChange={setOpacity}
        />
        {fileMode ? null : (
          <VizNumberInput
            label="Threshold rule"
            placeholder="none"
            value={scoreThreshold ?? ''}
            onChange={(v) => setScoreThreshold(typeof v === 'number' ? v : null)}
          />
        )}
      </VizControlGroup>
      {fileMode ? null : (
        <VizControlGroup title="Lanes">
          <VizSwitch
            checked={facetBySample && canFacet}
            disabled={!canFacet}
            onChange={(e) => setFacetBySample(e.currentTarget.checked)}
            label={canFacet ? 'One lane per sample, shared genome axis' : 'Bind a sample column first'}
          />
          {facetBySample && canFacet ? (
            <VizNumberInput
              label="Max lanes"
              min={1}
              max={40}
              value={maxFacets}
              onChange={(v) => setMaxFacets(typeof v === 'number' ? v : 8)}
            />
          ) : null}
          {facetBySample && canFacet ? (
            <VizSwitch
              checked={!laneHeight}
              onChange={(e) => setLaneHeight(e.currentTarget.checked ? null : DEFAULT_FIXED_LANE_PX)}
              label="Fit lanes to the tile (off: fixed height, scroll)"
            />
          ) : null}
          {facetBySample && canFacet && laneHeight ? (
            <VizSegmented
              label="Lane height"
              value={String(laneHeight)}
              onChange={(v) => setLaneHeight(Number(v))}
              data={[
                ...LANE_HEIGHTS.map((h) => ({ value: String(h.px), label: h.label })),
                ...(!LANE_HEIGHTS.some((h) => h.px === laneHeight)
                  ? [{ value: String(laneHeight), label: `${laneHeight} px` }]
                  : []),
              ]}
            />
          ) : null}
          {facetBySample && canFacet ? (
            <VizSegmented
              label="Y scale"
              value={facetYScale}
              onChange={(v) => setFacetYScale(v === 'independent' ? 'independent' : 'shared')}
              data={[
                { value: 'shared', label: 'Shared' },
                { value: 'independent', label: 'Per lane' },
              ]}
            />
          ) : null}
          {built && built.droppedFacets > 0 ? (
            <VizFullRow>
              <Text size="xs" c="dimmed">
                {built.droppedFacets} more sample(s) not drawn.
              </Text>
            </VizFullRow>
          ) : null}
        </VizControlGroup>
      )}
      <VizControlGroup title="Genome">
        <VizSelect
          label="Assembly"
          description="Built-in chromosome sizes, or derive them from the data"
          clearable
          value={assembly}
          onChange={(v) => setAssembly(v)}
          data={BUILTIN_ASSEMBLIES.map((a) => ({ value: a, label: a }))}
          placeholder="from data"
        />
        {fileMode ? null : (
          <VizSelect
            label="Gene annotation lane"
            description="Protein-coding genes under the track; labels appear as you zoom in"
            value={annotation}
            onChange={(v) => setAnnotation((v as 'none' | 'hg38' | 'mm10') ?? 'none')}
            data={[
              { value: 'none', label: 'None' },
              ...ANNOTATION_ASSEMBLIES.map((a) => ({ value: a, label: a })),
            ]}
          />
        )}
        {annotationHint ? (
          <VizFullRow>
            <Text size="xs" c="dimmed">
              {annotationHint}
            </Text>
          </VizFullRow>
        ) : null}
        <VizSwitch
          checked={followRegion}
          onChange={(e) => setFollowRegion(e.currentTarget.checked)}
          label="Zoom to an incoming region instead of the whole genome"
        />
      </VizControlGroup>
      <VizFullRow>
        <Group gap={4}>
          {regionBrushEnabled ? (
            <Badge
              size="xs"
              variant="light"
              data-testid="genome-view-region-badge"
              rightSection={
                brushedRegion || ownRegionNow ? (
                  <CloseButton
                    size="xs"
                    aria-label="Clear region"
                    onClick={clearOwnRegion}
                    data-testid="genome-view-region-clear"
                  />
                ) : undefined
              }
            >
              {brushedRegion
                ? `region ${brushedRegion}`
                : 'drag to filter a region · double-click or Esc clears'}
            </Badge>
          ) : null}
          {selectionEnabled ? (
            <Badge size="xs" variant="light">
              click filters {selectionColumn}
            </Badge>
          ) : null}
        </Group>
      </VizFullRow>
    </>
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Genome view'}
      openLocus={openLocus}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      // The counts go to the metadata panel (`tileStats`): the header keeps the
      // link tag and the key to the overlays.
      // One header line: the link tag, then the key to the overlays it explains.
      badges={[
        ...(linkedBrowser
          ? [
              <LinkedTileChip
                key="link"
                role="drives"
                otherIndex={linkedBrowser.index}
                fallbackTitle={linkedBrowser.title}
                region={displayedRegion ? selectionLabel : null}
                explanation={
                  displayedRegion
                    ? `The region selected here filters the dashboard, and ${linkedBrowser.title} opens on it. ` +
                      'Its view is drawn here as a dashed band; moving it there moves the band, and this axis ' +
                      'follows when it leaves.'
                    : `${linkedBrowser.title} draws its view here as a dashed band.`
                }
                data-testid="genome-view-link-chip"
              />,
            ]
          : []),
        <OverlayLegend
          key="legend"
          selection={displayedRegion ? selectionLabel : null}
          selectionColor={overlayColor}
          window={
            windowBandRows.length
              ? compactRegion(windowBandRows[0].chrom, windowBandRows[0].start, windowBandRows[0].end)
              : null
          }
          windowColor={linkColor}
        />,
      ]}
      primaryControls={locusControls}
      controls={controls}
      loading={loading && !rows && !manifest}
      error={fetchError ?? fileSpecError ?? embedError}
      emptyMessage={
        noRows && !spec ? (fileMode ? 'No indexed file to draw' : 'No rows') : undefined
      }
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          // Lanes scroll when the tile is shorter than they need.
          overflowY: lanesPx ? 'auto' : undefined,
        }}
      >
        {/* GenomeSpy sizes its canvas to this box; the tile's flex column gives
            it the height, so a fixed min keeps it visible in a short tile. */}
        <div
          ref={containerRef}
          // A double-click drops the region brush (a single click picks a mark).
          onDoubleClick={regionBrushEnabled && ownRegionNow ? clearOwnRegion : undefined}
          className="depictio-genome-view"
          style={{
            width: '100%',
            // Fixed lanes: exactly their height. Fitted lanes: the tile's
            // height, never under the lanes' floor. A zero basis, not `auto`:
            // the canvas inside is as tall as the last layout, so an `auto`
            // basis would hold the box at that height and it never shrinks.
            flex: fixedLanes ? '0 0 auto' : '1 1 0',
            ...(fixedLanes ? { height: lanesPx! } : { minHeight: lanesPx ?? 160 }),
            position: 'relative',
          }}
        />
      </div>
      {noRows && spec ? (
        <Text
          size="sm"
          c="dimmed"
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            pointerEvents: 'none',
          }}
        >
          No rows
        </Text>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default GenomeViewRenderer;
