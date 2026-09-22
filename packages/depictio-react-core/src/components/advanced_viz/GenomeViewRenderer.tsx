import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import type { RootSpec } from '@genome-spy/core/spec/root.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { resolveCategoricalPalette } from '../../colors';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  genomeRegionFilters,
  regionFromFilters,
} from '../../selection';
import { useWebglSlot } from '../../webglBudget';
import type { GroupRenderState } from '../../selectionGroups';
import AdvancedVizFrame from './AdvancedVizFrame';
import { plotlyThemeColors } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';
import {
  ANNOTATION_ASSEMBLIES,
  BUILTIN_ASSEMBLIES,
  buildGenomeSpySpec,
  effectiveMark,
  latchSeedRows,
  regionFromInterval,
  requiredColumns,
  rowsToObjects,
} from './genomespy/genomeSpySpec';
import type { Contig, GenomeRegion, GenomeViewConfig } from './genomespy/genomeSpySpec';
import { loadGeneAnnotation } from './genomespy/geneAnnotations';
import type { GeneAnnotation } from './genomespy/geneAnnotations';
import { filtersForGenomeViewFetch, loadGenomeViewRows } from './genomespy/genomeViewData';
import {
  loadAssemblyContigs,
  setGenomeSpyRows,
  useGenomeSpy,
  zoomToRegion,
} from './genomespy/useGenomeSpy';

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
  /** Dashboard-wide analysis grouping. Not applied: this kind colours by
   *  chromosome or by its category column, and `GROUPING_MODE_BY_KIND` says
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

const GenomeViewRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as GenomeViewConfig;

  // Tier-2 controls. Defaults agree with GenomeViewConfig's own.
  const [mark, setMark] = usePersistedVizControl<'point' | 'rect' | 'bar'>(metadata, 'mark', 'point');
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
  const [followRegion, setFollowRegion] = usePersistedVizControl<boolean>(
    metadata,
    'follow_region_filter',
    false,
  );

  // ---- Selection as a cross-filter ---------------------------------------
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);
  const regionBrushEnabled = Boolean(onFilterChange) && config.region_filter_enabled !== false;

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
      follow_region_filter: followRegion,
      region_filter_enabled: regionBrushEnabled,
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

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFetchError(null);
    loadGenomeViewRows(fetchAdvancedVizData, {
      metadata,
      config: effectiveConfig,
      filters: filtersForFetch,
      selectionColumn,
    })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
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
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filtersForFetch),
    scoreThreshold,
    refreshTick,
  ]);

  // ---- Assets: built-in contigs and the gene lane -------------------------
  // Both are static per assembly and memoised process-wide, so four hg38 tiles
  // on one dashboard pay for them once.
  const [assemblyContigs, setAssemblyContigs] = useState<Contig[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    const name = effectiveConfig.assembly;
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
  }, [effectiveConfig.assembly]);

  const [geneAnnotation, setGeneAnnotation] = useState<GeneAnnotation | null>(null);
  useEffect(() => {
    let cancelled = false;
    loadGeneAnnotation(effectiveConfig.annotation).then((g) => {
      if (!cancelled) setGeneAnnotation(g);
    });
    return () => {
      cancelled = true;
    };
  }, [effectiveConfig.annotation]);

  // One GenomeSpy embed is one WebGL context, a third of what a Plotly
  // scattergl costs, so it competes for a slot like any point cloud. Without
  // one it draws on Canvas2D, which keeps every feature and just paints slower.
  const glGranted = useWebglSlot(true);
  const backend = glGranted ? 'webgl' : 'canvas';

  const themeColors = plotlyThemeColors(isDark, theme);
  const palette = resolveCategoricalPalette(theme);

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
      },
      assemblyContigs,
      genes: geneAnnotation?.genes ?? null,
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
  ]);
  const spec = (built?.spec ?? null) as RootSpec | null;
  const contigs = built?.contigs ?? null;

  const emitSelection = useCallback(
    (values: string[]) => {
      if (!onFilterChange || !selectionColumn) return;
      onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, values));
    },
    [onFilterChange, selectionColumn, metadata],
  );
  const handlePick = useCallback(
    (datum: Readonly<Record<string, unknown>>) => {
      if (!selectionColumn) return;
      const v = datum[selectionColumn];
      emitSelection(v === null || v === undefined ? [] : [String(v)]);
    },
    [emitSelection, selectionColumn],
  );

  const [brushedRegion, setBrushedRegion] = useState<string | null>(null);
  const handleBrush = useCallback(
    (interval: number[] | null) => {
      if (!onFilterChange || !contigs) return;
      const region = regionFromInterval(contigs, interval);
      setBrushedRegion(regionLabel(region));
      // Two entries, one per column: `mergeFiltersBySource` keys on
      // (index, source) and they carry different indices, so they coexist.
      for (const filter of genomeRegionFilters(
        metadata,
        config.chr_col,
        config.pos_col,
        region,
      )) {
        onFilterChange(filter);
      }
    },
    [onFilterChange, contigs, metadata, config.chr_col, config.pos_col],
  );

  const containerRef = useRef<HTMLDivElement | null>(null);
  const { api, error: embedError } = useGenomeSpy(containerRef, spec, {
    backend,
    onPick: selectionEnabled ? handlePick : undefined,
    onBrush: regionBrushEnabled ? handleBrush : undefined,
  });

  // Rows changed after the embed was built (filter moved, refresh tick): swap
  // the dataset in place. On the seed rows the spec already carries them, and
  // `datasets.set` with the same content is a harmless no-op. An empty fetch
  // swaps in an empty dataset rather than tearing the embed down.
  useEffect(() => {
    if (!api || !liveData) return;
    setGenomeSpyRows(api, liveData);
  }, [api, liveData]);

  // ---- Following someone else's region ------------------------------------
  const incomingRegion = useMemo(
    () => (followRegion ? regionFromFilters(filtersForFetch, config.chr_col, config.pos_col) : null),
    [followRegion, filtersForFetch, config.chr_col, config.pos_col],
  );
  useEffect(() => {
    if (!api || !followRegion) return;
    if (!incomingRegion) return;
    // A chromosome with no range means "the whole contig", which needs the
    // contig's own length rather than an infinite end.
    const size = contigs?.find((c) => c.name === incomingRegion.chrom)?.size;
    const end = Number.isFinite(incomingRegion.end)
      ? incomingRegion.end
      : (size ?? incomingRegion.start + 1);
    void zoomToRegion(api, { chrom: incomingRegion.chrom, start: incomingRegion.start, end });
  }, [api, followRegion, incomingRegion, contigs]);

  const counts = useMemo(() => {
    if (!rows) return undefined;
    const out: Record<string, number> = { rows: rowCount, [backend]: 1 };
    if (built?.facets.length) out.lanes = built.facets.length;
    if (built?.geneCount) out.genes = built.geneCount;
    return out;
  }, [rows, rowCount, backend, built?.facets.length, built?.geneCount]);

  // The frame replaces its children with `emptyMessage`, which would unmount
  // the container under a live embed and strand it on a detached node. So the
  // frame's message is only used before any embed exists; once one is up, an
  // empty fetch is reported by an overlay and the container stays mounted.
  const noRows = Boolean(rows) && rowCount === 0;

  const canFacet = Boolean(config.sample_col);
  const annotationHint =
    annotation !== 'none' && built && built.geneCount === 0
      ? 'No gene of this assembly falls on the contigs in view.'
      : null;

  const controls = (
    <Stack gap="xs">
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Mark
        </Text>
        <SegmentedControl
          size="xs"
          value={effectiveMark(effectiveConfig)}
          onChange={(v) => setMark(v as 'point' | 'rect' | 'bar')}
          data={[
            { value: 'point', label: 'Points' },
            { value: 'rect', label: 'Intervals', disabled: !config.end_col },
            { value: 'bar', label: 'Bars' },
          ]}
        />
        <Text size="xs" c="dimmed">
          {config.end_col
            ? 'Bars run from the baseline; intervals span start to end.'
            : 'Bind an end column to draw intervals. GenomeSpy has no line mark, so a coverage profile is drawn as bars.'}
        </Text>
      </Stack>
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Per-sample lanes
        </Text>
        <Switch
          size="xs"
          checked={facetBySample && canFacet}
          disabled={!canFacet}
          onChange={(e) => setFacetBySample(e.currentTarget.checked)}
          label={canFacet ? 'One lane per sample, shared genome axis' : 'Bind a sample column first'}
        />
        {facetBySample && canFacet ? (
          <NumberInput
            size="xs"
            label="Max lanes"
            min={1}
            max={40}
            value={maxFacets}
            onChange={(v) => setMaxFacets(typeof v === 'number' ? v : 8)}
          />
        ) : null}
        {built && built.droppedFacets > 0 ? (
          <Text size="xs" c="dimmed">
            {built.droppedFacets} more sample(s) not drawn.
          </Text>
        ) : null}
      </Stack>
      <NumberInput
        size="xs"
        label="Point size (px)"
        min={1}
        max={30}
        value={pointSize}
        onChange={(v) => setPointSize(typeof v === 'number' ? v : 5)}
      />
      <Stack gap={2}>
        <Text size="xs">Opacity</Text>
        <Slider size="xs" min={0.05} max={1} step={0.05} value={opacity} onChange={setOpacity} />
      </Stack>
      <NumberInput
        size="xs"
        label="Threshold rule"
        placeholder="none"
        value={scoreThreshold ?? ''}
        onChange={(v) => setScoreThreshold(typeof v === 'number' ? v : null)}
      />
      <Select
        size="xs"
        label="Assembly"
        description="Built-in chromosome sizes, or derive them from the data"
        clearable
        value={assembly}
        onChange={(v) => setAssembly(v)}
        data={BUILTIN_ASSEMBLIES.map((a) => ({ value: a, label: a }))}
        placeholder="from data"
      />
      <Select
        size="xs"
        label="Gene annotation lane"
        description="Protein-coding genes under the track; labels appear as you zoom in"
        value={annotation}
        onChange={(v) => setAnnotation((v as 'none' | 'hg38' | 'mm10') ?? 'none')}
        data={[
          { value: 'none', label: 'None' },
          ...ANNOTATION_ASSEMBLIES.map((a) => ({ value: a, label: a })),
        ]}
      />
      {annotationHint ? (
        <Text size="xs" c="dimmed">
          {annotationHint}
        </Text>
      ) : null}
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Region filter
        </Text>
        <Switch
          size="xs"
          checked={followRegion}
          onChange={(e) => setFollowRegion(e.currentTarget.checked)}
          label="Zoom to an incoming region instead of the whole genome"
        />
      </Stack>
      <Group gap={4}>
        <Badge size="xs" variant="light">
          {backend === 'webgl' ? 'WebGL' : 'Canvas fallback'}
        </Badge>
        {regionBrushEnabled ? (
          <Badge size="xs" variant="light">
            {brushedRegion ? `region ${brushedRegion}` : 'drag to filter a region'}
          </Badge>
        ) : null}
        {selectionEnabled ? (
          <Badge size="xs" variant="light">
            click filters {selectionColumn}
          </Badge>
        ) : null}
      </Group>
    </Stack>
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Genome view'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      counts={counts}
      controls={controls}
      loading={loading && !rows}
      error={fetchError ?? embedError}
      emptyMessage={noRows && !spec ? 'No rows' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {/* GenomeSpy sizes its canvas to this box; the tile's flex column gives
          it the height, so a fixed min keeps it visible in a short tile. */}
      <div
        ref={containerRef}
        className="depictio-genome-view"
        style={{ width: '100%', height: '100%', minHeight: 160, position: 'relative' }}
      />
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
