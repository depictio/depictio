import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  Slider,
  Stack,
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
  filtersExcludingOwn,
} from '../../selection';
import { useWebglSlot } from '../../webglBudget';
import type { GroupRenderState } from '../../selectionGroups';
import AdvancedVizFrame from './AdvancedVizFrame';
import { plotlyThemeColors } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';
import {
  BUILTIN_ASSEMBLIES,
  buildGenomeSpySpec,
  effectiveMark,
  requiredColumns,
  rowsToObjects,
} from './genomespy/genomeSpySpec';
import type { GenomeSpyTrackConfig } from './genomespy/genomeSpySpec';
import { setGenomeSpyRows, useGenomeSpy } from './genomespy/useGenomeSpy';

/**
 * `genomespy_track`: one genomic track drawn by GenomeSpy (issue #1083 spike).
 *
 * Same `chr / pos / score` binding as the Manhattan plot, so every DC that
 * renderer reads renders here too, but the chromosome-concatenated axis, the
 * locus zoom, the interval brush and the mark picking are GenomeSpy's own
 * grammar rather than rebuilt from Plotly primitives. The comparison the
 * issue asks for is documented in docs/design/genomespy-eval.md.
 *
 * Contract: the standard advanced_viz props. Selection follows the Manhattan
 * rule exactly — inert unless the dashboard opts in with `selection_column`,
 * a click emits that column's value as a `scatter_selection` filter, and this
 * component never narrows itself by its own selection.
 */

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: GenomeSpyTrackConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no picking. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Dashboard-wide analysis grouping. Not applied yet: the spike colours by
   *  chromosome only, and `GROUPING_MODE_BY_KIND` says so ('none'), so the
   *  chrome's badge reports that the groups did not reach this tile. */
  groupRender?: GroupRenderState;
}

const VIZ_KIND = 'genomespy_track' as const;

const GenomeSpyTrackRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as GenomeSpyTrackConfig;

  // Tier-2 controls. Defaults agree with GenomeSpyTrackConfig's own.
  const [mark, setMark] = usePersistedVizControl<'point' | 'rect'>(metadata, 'mark', 'point');
  const [pointSize, setPointSize] = usePersistedVizControl<number>(metadata, 'point_size', 5);
  const [opacity, setOpacity] = usePersistedVizControl<number>(metadata, 'opacity', 0.85);
  const [scoreThreshold, setScoreThreshold] = usePersistedVizControl<number | null>(
    metadata,
    'score_threshold',
    null,
  );
  const [assembly, setAssembly] = usePersistedVizControl<string | null>(metadata, 'assembly', null);

  // ---- Selection as a cross-filter ---------------------------------------
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);

  const effectiveConfig = useMemo<GenomeSpyTrackConfig>(
    () => ({
      ...config,
      mark,
      point_size: pointSize,
      opacity,
      score_threshold: scoreThreshold,
      assembly,
      selection_enabled: selectionEnabled,
      selection_column: selectionColumn ?? null,
    }),
    [config, mark, pointSize, opacity, scoreThreshold, assembly, selectionEnabled, selectionColumn],
  );

  const requiredCols = useMemo(
    () => requiredColumns(effectiveConfig, selectionColumn).filter(Boolean),
    [effectiveConfig, selectionColumn],
  );

  const filtersForFetch = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'scatter_selection'),
    [filters, metadata.index],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setFetchError('GenomeSpy track: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setFetchError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns: requiredCols,
      filters: filtersForFetch,
      vizKind: VIZ_KIND,
      roles: { chr: config.chr_col, pos: config.pos_col, score: config.score_col },
      // Like the Manhattan: the threshold is the cut the server must not
      // sample across, so the hits above it always arrive whole.
      tail:
        scoreThreshold != null
          ? { column: config.score_col, direction: 'high', threshold: scoreThreshold }
          : undefined,
    })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setEstimated(Boolean(res.sampling?.degraded));
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

  // One GenomeSpy embed is one WebGL context — a third of what a Plotly
  // scattergl costs — so it competes for a slot like any point cloud. Without
  // one it draws on Canvas2D, which keeps every feature and just paints slower.
  const glGranted = useWebglSlot(true);
  const backend = glGranted ? 'webgl' : 'canvas';

  const themeColors = plotlyThemeColors(isDark, theme);
  const palette = resolveCategoricalPalette(theme);

  // The spec carries the *shape*: columns, mark, threshold, assembly, colours.
  // It is built from the first rows only; later rows go through
  // `setGenomeSpyRows` so a moved filter does not tear the embed down.
  const firstRowsRef = useRef<Record<string, unknown[]> | null>(null);
  if (rows && !firstRowsRef.current) firstRowsRef.current = rows;
  const spec = useMemo<RootSpec | null>(() => {
    const seed = firstRowsRef.current;
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
    }) as unknown as RootSpec;
    // `palette` is a fresh array each render but its contents are stable for a
    // theme; key on the joined hues rather than the identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    Boolean(rows),
    effectiveConfig,
    themeColors.textColor,
    themeColors.gridColor,
    themeColors.zeroLineColor,
    palette.join(','),
  ]);

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

  const containerRef = useRef<HTMLDivElement | null>(null);
  const { api, error: embedError } = useGenomeSpy(containerRef, spec, {
    backend,
    onPick: selectionEnabled ? handlePick : undefined,
  });

  // Rows changed after the embed was built (filter moved, refresh tick): swap
  // the dataset in place. On the very first rows the spec already carries
  // them, and `datasets.set` with the same content is a harmless no-op.
  useEffect(() => {
    if (!api || !rows) return;
    setGenomeSpyRows(
      api,
      rowsToObjects(rows, requiredCols, effectiveConfig.chr_col, effectiveConfig.pos_col),
    );
  }, [api, rows, requiredCols, effectiveConfig.chr_col, effectiveConfig.pos_col]);

  const rowCount = rows ? (rows[config.chr_col]?.length ?? 0) : 0;
  const counts = useMemo(
    () => (rows ? { rows: rowCount, [backend]: 1 } : undefined),
    [rows, rowCount, backend],
  );

  const controls = (
    <Stack gap="xs">
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Mark
        </Text>
        <SegmentedControl
          size="xs"
          value={effectiveMark(effectiveConfig)}
          onChange={(v) => setMark(v as 'point' | 'rect')}
          data={[
            { value: 'point', label: 'Points' },
            { value: 'rect', label: 'Intervals', disabled: !config.end_col },
          ]}
        />
        {!config.end_col ? (
          <Text size="xs" c="dimmed">
            Bind an end column to draw intervals.
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
      <Group gap={4}>
        <Badge size="xs" variant="light">
          {backend === 'webgl' ? 'WebGL' : 'Canvas fallback'}
        </Badge>
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
      title={metadata.title || 'GenomeSpy track'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      counts={counts}
      controls={controls}
      loading={loading && !rows}
      error={fetchError ?? embedError}
      emptyMessage={rows && rowCount === 0 ? 'No rows' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {/* GenomeSpy sizes its canvas to this box; the tile's flex column gives
          it the height, so a fixed min keeps it visible in a short tile. */}
      <div
        ref={containerRef}
        className="depictio-genomespy-track"
        style={{ width: '100%', height: '100%', minHeight: 160, position: 'relative' }}
      />
    </AdvancedVizFrame>
  );
};

export default GenomeSpyTrackRenderer;
