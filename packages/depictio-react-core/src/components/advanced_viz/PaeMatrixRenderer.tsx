import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Box,
  ColorSwatch,
  Group,
  Text,
  Tooltip,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { useHighlight, usePublishHighlight } from '../../highlight/bus';
import {
  filtersExcludingOwnResidue,
  residueEntityFromFilters,
  residueRangeFilters,
  residueRangeFromFilters,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import { demandForPx } from './contentDemand';
import { VizControlGroup, VizSegmented, VizSelect, VizSwitch } from './controls/VizControls';
import { useIndexedManifest } from './molecule/hooks';
import { PLDDT_BANDS, rgbCss } from './protein';
import {
  chainSelectionFilter,
  distinctColumns,
  firstValueOf,
  hasOwnResiduePick,
  numberOrNull,
  rowIndicesWhere,
  scopeToEntity,
  stringOrNull,
  withoutOwnChainPick,
  withoutPositionSelections,
} from './protein/rendererData';
import { useEntityPicker } from './protein/useEntityPicker';
import {
  buildResidueAxis,
  indexRangeToSelection,
  isMultiChain,
  selectionToIndexRange,
  type AxisRow,
  type ResidueAxis,
} from './pae/axis';
import { sameRange, type BrushMode, type PaeGesture } from './pae/brush';
import {
  blockMean,
  buildLut,
  colourMax as resolveColourMax,
  colourScaleSampler,
  stopsSampler,
  themeRampStops,
} from './pae/paeImage';
import PaePanel from './pae/PaePanel';
import { isOfflineBundle, usePaeMatrix } from './pae/usePaeMatrix';

/**
 * Mirrors `PaeMatrixConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys a renderer reads).
 */
interface PaeMatrixConfig {
  entity_col?: string | null;
  position_col?: string;
  value_col?: string | null;
  chain_col?: string | null;
  pae_wf_id?: string | null;
  pae_dc_id?: string | null;
  pae_dc_tag?: string | null;
  max_pae?: number | null;
  colour_scale?: ColourScale | null;
  brush?: BrushMode;
  show_plddt?: boolean;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: PaeMatrixConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no residue pick. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/** The tile's colour control: a named scale, or the theme's AlphaFold ramp. */
type ColourChoice = ColourScale | 'theme';

const COLOUR_CHOICES = [
  { value: 'theme', label: 'AlphaFold (theme)' },
  ...COLOUR_SCALES.map((s) => ({ value: s, label: s })),
];

const PREVIEW_MESSAGE =
  'PAE matrix unavailable in this preview: the matrix is read from a file at render time';
/** Tile furniture around the square plot: frame header, legend. */
const CHROME_PX = 110;
const PLOT_NATURAL_PX = 380;

type Frame = Record<string, unknown[]>;

/** `12-40`, with the chain on a complex (`A 12-40`). */
function spanLabel(axis: ResidueAxis, k0: number, k1: number): string {
  const a = axis.residues[k0];
  const b = axis.residues[k1];
  if (!a || !b) return '';
  const chain = isMultiChain(axis) && a.chain != null ? `${a.chain} ` : '';
  return k0 === k1 ? `${chain}${a.position}` : `${chain}${a.position}–${b.position}`;
}

/**
 * `pae_matrix`: the predicted aligned error of one entity's structure as an
 * N x N heatmap on residue axes, as AlphaFold DB shows it (x the scored
 * residue, y the aligned residue), linked to the other protein tiles.
 *
 * The matrix is the entity's object in the companion `indexed_file`
 * collection of format `pae` (`pae_dc_id`), found in its manifest and fetched
 * like a structure file. The bound collection is the residue table: it numbers
 * the axes (see `pae/axis.ts`) and gives the pLDDT strips. A diagonal drag
 * picks the residues of a block on the diagonal, a rectangle drag (or
 * shift-drag) the scored range of any block, a click one residue; a hover
 * publishes the scored residue on the highlight bus. Picks and hovers from the
 * other tiles shade the matrix and draw a crosshair.
 */
const PaeMatrixRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as PaeMatrixConfig;
  const index = String(metadata.index);
  const entityCol = config.entity_col === undefined ? 'entity' : config.entity_col;
  const positionCol = config.position_col || 'position';
  const valueCol = config.value_col || null;
  const chainCol = config.chain_col || null;
  const paeDcId = config.pae_dc_id || null;
  const follow = config.follow_selection !== false;
  const selectable = Boolean(onFilterChange) && config.selection_enabled !== false;
  const offline = useMemo(() => isOfflineBundle(), []);

  // Tile controls, seeded from the config (and re-seeded when the builder
  // changes it). Plain state: the kind's model refuses a blob without its PAE
  // collection, so these are not written back as persisted controls.
  const [colourChoice, setColourChoice] = useState<ColourChoice>(config.colour_scale ?? 'theme');
  const [showPlddt, setShowPlddt] = useState<boolean>(config.show_plddt !== false);
  const [brushMode, setBrushMode] = useState<BrushMode>(config.brush ?? 'diagonal');
  useEffect(() => setColourChoice(config.colour_scale ?? 'theme'), [config.colour_scale]);
  useEffect(() => setShowPlddt(config.show_plddt !== false), [config.show_plddt]);
  useEffect(() => setBrushMode(config.brush ?? 'diagonal'), [config.brush]);
  const [pickedFile, setPickedFile] = useState<string | null>(null);
  const [drawn, setDrawn] = useState(false);

  // ---- which entity ------------------------------------------------------------
  // The tile's own pick never narrows its fetch, and no residue range or chain
  // pick does: the matrix is the whole protein, the range is shaded on it.
  const withoutOwn = useMemo(
    () => withoutOwnChainPick(filtersExcludingOwnResidue(filters, index), index),
    [filters, index],
  );
  const fetchFilters = useMemo(
    () => withoutPositionSelections(withoutOwn, [positionCol, chainCol]),
    [withoutOwn, positionCol, chainCol],
  );
  const followed = useMemo(() => residueEntityFromFilters(withoutOwn, entityCol), [withoutOwn, entityCol]);
  const picker = useEntityPicker(metadata.dc_id, entityCol, followed, refreshTick, {
    wfId: metadata.wf_id,
    vizKind: 'pae_matrix',
    filters: fetchFilters,
    shareKey: entityCol,
    owner: index,
  });

  // ---- residue table -----------------------------------------------------------
  const columns = useMemo(
    () => distinctColumns([entityCol, positionCol, valueCol, chainCol]),
    [entityCol, positionCol, valueCol, chainCol],
  );
  const residueFilters = useMemo(
    () => scopeToEntity(fetchFilters, index, metadata.dc_id, entityCol, picker.entity),
    [fetchFilters, index, metadata.dc_id, entityCol, picker.entity],
  );
  const residueFiltersKey = JSON.stringify(residueFilters);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [tableLoading, setTableLoading] = useState(true);
  const [tableError, setTableError] = useState<string | null>(null);
  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setTableError('PAE matrix: missing data binding');
      setTableLoading(false);
      return;
    }
    if (picker.entities === null) return;
    if (entityCol && !picker.entity && !picker.failed) {
      setFrame({});
      setTableLoading(false);
      return;
    }
    let cancelled = false;
    setTableLoading(true);
    setTableError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns,
      filters: residueFilters,
      vizKind: 'pae_matrix',
    })
      .then((res) => {
        if (!cancelled) setFrame(res.rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setTableError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setTableLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // The JSON keys stand for the arrays' content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(columns),
    residueFiltersKey,
    picker.entities,
    picker.entity,
    picker.failed,
    entityCol,
    refreshTick,
  ]);

  // ---- the PAE file ------------------------------------------------------------
  const manifest = useIndexedManifest(paeDcId, Boolean(paeDcId) && !offline, refreshTick);
  const fileEntities = useMemo(() => Array.from(manifest.data?.keys() ?? []), [manifest.data]);
  // With an entity column the residue table decides (and follows the
  // dashboard); without one the table holds one protein, and the PAE
  // collection's objects are the choice.
  const entity = entityCol
    ? (picker.entity ?? firstValueOf(frame, entityCol))
    : pickedFile && fileEntities.includes(pickedFile)
      ? pickedFile
      : (fileEntities[0] ?? null);
  const fileEntry = entity ? (manifest.data?.get(entity) ?? null) : null;
  const { reload: reloadManifest } = manifest;
  const renewUrl = useCallback(
    async () => (entity ? ((await reloadManifest())?.get(entity)?.url ?? null) : null),
    [reloadManifest, entity],
  );
  const pae = usePaeMatrix(
    offline ? null : (fileEntry?.url ?? null),
    fileEntry?.name ?? null,
    renewUrl,
  );
  const matrix = pae.data;
  useEffect(() => setDrawn(false), [matrix]);

  // ---- the residue axis ----------------------------------------------------------
  const entityRows = useMemo<AxisRow[]>(() => {
    if (!frame) return [];
    const pos = frame[positionCol] ?? [];
    const chains = chainCol ? frame[chainCol] : undefined;
    const values = valueCol ? frame[valueCol] : undefined;
    const out: AxisRow[] = [];
    for (const i of rowIndicesWhere(frame, entityCol, entity)) {
      const p = numberOrNull(pos[i]);
      if (p == null) continue;
      out.push({
        position: p,
        chain: chains ? stringOrNull(chains[i]) : null,
        value: values ? numberOrNull(values[i]) : null,
      });
    }
    return out;
  }, [frame, positionCol, chainCol, valueCol, entityCol, entity]);
  const axis = useMemo(
    () => (matrix ? buildResidueAxis(matrix.n, entityRows, { byChain: Boolean(chainCol) }) : null),
    [matrix, entityRows, chainCol],
  );
  const hasPlddt = Boolean(axis?.residues.some((r) => r.value != null));
  const stripsShown = showPlddt && hasPlddt;
  const multiChain = axis ? isMultiChain(axis) : false;

  // ---- colours ---------------------------------------------------------------------
  const lut = useMemo(() => {
    if (colourChoice !== 'theme') return buildLut(colourScaleSampler(colourChoice));
    const greens = theme.colors.green ?? theme.colors[theme.primaryColor] ?? theme.colors.blue;
    const background = isDark ? theme.colors.dark[7] : theme.white;
    return buildLut(stopsSampler(themeRampStops(greens, background, isDark)));
  }, [colourChoice, theme, isDark]);
  const maxPae = useMemo(() => resolveColourMax(config.max_pae, matrix), [config.max_pae, matrix]);

  // ---- selections in -----------------------------------------------------------------
  const ownResidue = useMemo(() => hasOwnResiduePick(filters, index), [filters, index]);
  const selected = useMemo<[number, number] | null>(() => {
    if (!axis || (!follow && !ownResidue)) return null;
    const r = residueRangeFromFilters(filters, entityCol, positionCol);
    if (!r || (r.entity && entity && r.entity !== entity)) return null;
    const chain = chainCol ? residueEntityFromFilters(filters, chainCol) : null;
    return selectionToIndexRange(axis, { start: r.start, end: r.end, chain });
  }, [axis, follow, ownResidue, filters, entityCol, positionCol, entity, chainCol]);

  const incoming = useHighlight(index, follow);
  const highlight = useMemo<[number, number] | null>(() => {
    if (!axis || !incoming || (incoming.entity && entity && incoming.entity !== entity)) return null;
    // An event on another position column is on another axis entirely.
    if (incoming.positionColumn && incoming.positionColumn !== positionCol) return null;
    return selectionToIndexRange(axis, {
      start: incoming.start,
      end: incoming.end,
      chain: incoming.chain,
    });
  }, [axis, incoming, entity, positionCol]);

  // The aligned range of this tile's last rectangle brush. Shown while the
  // pick in force is still the one it emitted: a later gesture anywhere
  // (last gesture wins) replaces the pick and retires the outline.
  const [rect, setRect] = useState<{ x: [number, number]; y: [number, number] } | null>(null);
  useEffect(() => setRect(null), [entity, matrix]);
  const outline = rect && sameRange(rect.x, selected) ? rect : null;

  // ---- selections out ------------------------------------------------------------------
  const publish = usePublishHighlight(index);
  const onHover = useCallback(
    (k: number | null) => {
      const r = k != null ? axis?.residues[k] : undefined;
      if (!r) {
        publish(null);
        return;
      }
      publish({
        entity: entity ?? undefined,
        chain: r.chain ?? undefined,
        start: r.position,
        positionColumn: positionCol,
      });
    },
    [publish, axis, entity, positionCol],
  );

  /** Emit an index range (null clears) as the residue_selection pair, plus the
   *  chain on a complex. Returns the indices the pick covers once clamped. */
  const emit = useCallback(
    (range: [number, number] | null): [number, number] | null => {
      if (!onFilterChange || !axis) return null;
      const sel = range ? indexRangeToSelection(axis, range[0], range[1]) : null;
      const pair = residueRangeFilters(index, {
        entityColumn: entityCol,
        positionColumn: positionCol,
        entity,
        start: sel ? sel.start : null,
        end: sel ? sel.end : null,
        dcId: metadata.dc_id,
      });
      for (const f of pair) onFilterChange(f);
      // A complex numbers each chain on its own: name the chain.
      if (chainCol && multiChain) {
        onFilterChange(chainSelectionFilter(index, metadata.dc_id, chainCol, sel ? sel.chain : null));
      }
      return sel ? sel.indices : null;
    },
    [onFilterChange, axis, index, entityCol, positionCol, entity, metadata.dc_id, chainCol, multiChain],
  );

  const onSelect = useCallback(
    (g: PaeGesture | null) => {
      if (!g) {
        if (selected) emit(null);
        setRect(null);
        return;
      }
      if (g.kind === 'residue') {
        // A second click on the residue already picked clears it.
        emit(sameRange(selected, [g.index, g.index]) ? null : [g.index, g.index]);
        setRect(null);
        return;
      }
      const covered = emit(g.x);
      setRect(g.mode === 'rectangle' && covered ? { x: covered, y: g.y } : null);
    },
    [emit, selected],
  );

  // ---- chrome ----------------------------------------------------------------------------
  // Memoised: the frame publishes these, and a hover re-renders the tile.
  const entityChoices = entityCol
    ? picker.entities && picker.entities.length > 1
      ? picker.entities
      : null
    : fileEntities.length > 1
      ? fileEntities
      : null;
  const { setEntity } = picker;
  const primaryControls = useMemo(
    () => (
      <>
        {entityChoices ? (
          <VizSelect
            label="Entity"
            value={entity}
            onChange={(v) => {
              if (!v) return;
              if (entityCol) setEntity(v);
              else setPickedFile(v);
            }}
            data={entityChoices}
            searchable
            limit={200}
            allowDeselect={false}
          />
        ) : null}
        <VizSelect
          label="Colours"
          value={colourChoice}
          onChange={(v) => v && setColourChoice(v as ColourChoice)}
          data={COLOUR_CHOICES}
          allowDeselect={false}
        />
      </>
    ),
    [entityChoices, entity, entityCol, setEntity, colourChoice],
  );

  const controls = useMemo(
    () => (
      <VizControlGroup title="Display">
        <VizSwitch
          label="pLDDT strips"
          checked={showPlddt}
          onChange={(e) => setShowPlddt(e.currentTarget.checked)}
          disabled={!valueCol}
        />
        {selectable ? (
          <VizSegmented
            label="Brush"
            value={brushMode}
            onChange={(v) => setBrushMode(v as BrushMode)}
            data={[
              { value: 'diagonal', label: 'Diagonal' },
              { value: 'rectangle', label: 'Rectangle' },
            ]}
          />
        ) : null}
      </VizControlGroup>
    ),
    [showPlddt, valueCol, selectable, brushMode],
  );

  const echo = useMemo(() => {
    if (!axis || !matrix) return undefined;
    const parts: string[] = [];
    if (entity) parts.push(entity);
    parts.push(`${matrix.n} residues`);
    if (outline) {
      const mean = blockMean(matrix.values, matrix.n, outline.y, outline.x);
      parts.push(
        `PAE of residues ${spanLabel(axis, outline.x[0], outline.x[1])} aligned on ${spanLabel(
          axis,
          outline.y[0],
          outline.y[1],
        )}${mean != null ? `: mean ${mean.toFixed(1)} Å` : ''}`,
      );
    } else if (selected) {
      const mean = blockMean(matrix.values, matrix.n, selected, selected);
      parts.push(
        `residues ${spanLabel(axis, selected[0], selected[1])}${
          mean != null && selected[1] > selected[0] ? `: mean PAE ${mean.toFixed(1)} Å` : ''
        }`,
      );
    }
    return parts.join(' · ');
  }, [axis, matrix, entity, outline, selected]);

  const badges = useMemo(() => {
    if (!axis || axis.fromTable || !matrix) return undefined;
    const why =
      axis.fallback === 'length_mismatch'
        ? `The residue table has ${axis.tableLength} residues for ${entity ?? 'this entity'}, the PAE matrix ${matrix.n}`
        : `The residue table has no rows for ${entity ?? 'this entity'}`;
    return [
      <Tooltip
        key="numbering"
        label={`${why}, so the axes are numbered 1 to ${matrix.n} and carry no pLDDT.`}
        multiline
        w={260}
        withinPortal
      >
        <Badge size="xs" radius="sm" variant="light" color="gray">
          {`Residues 1–${matrix.n}`}
        </Badge>
      </Tooltip>,
    ];
  }, [axis, matrix, entity]);

  const legend = stripsShown
    ? PLDDT_BANDS.map((b) => ({ label: b.label.split(' (')[0], colour: rgbCss(b.rgb) }))
    : [];

  const contentDemand = useMemo(() => demandForPx(PLOT_NATURAL_PX + CHROME_PX), []);
  const onDrawn = useCallback(() => setDrawn(true), []);

  // ---- frame state -----------------------------------------------------------------------
  let emptyMessage: string | undefined;
  let error: string | null = null;
  let loading = false;
  if (offline) {
    emptyMessage = PREVIEW_MESSAGE;
  } else if (!paeDcId) {
    emptyMessage = config.pae_dc_tag
      ? `PAE collection "${config.pae_dc_tag}" is not in this project`
      : 'No PAE collection bound to this tile (an indexed-file collection of format pae)';
  } else if (tableError) {
    error = tableError;
  } else if (manifest.error) {
    error = manifest.error.replace(/^Structure files/, 'PAE files');
  } else if (
    picker.entities === null ||
    (tableLoading && !matrix) ||
    (manifest.loading && !manifest.data) ||
    (pae.loading && !matrix)
  ) {
    loading = true;
  } else if (manifest.data && fileEntities.length === 0) {
    emptyMessage = 'No PAE files in the bound collection';
  } else if (!entity) {
    emptyMessage = 'No entity to show';
  } else if (!fileEntry) {
    emptyMessage = `No PAE file for ${entity}`;
  } else if (pae.error) {
    error = `PAE file for ${entity} could not be read: ${pae.error}`;
  } else if (!matrix) {
    loading = true;
  }
  const ready = Boolean(matrix && axis && !emptyMessage && !error);

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Predicted aligned error'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      echo={echo}
      loading={loading}
      error={error}
      emptyMessage={emptyMessage}
      dataRows={frame ?? undefined}
      dataColumns={columns}
      badges={badges}
    >
      {ready && matrix && axis ? (
        <Box
          className="depictio-pae-matrix"
          data-pae-ready={drawn ? 'true' : undefined}
          style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', minHeight: 0 }}
        >
          <Box style={{ flex: '1 1 auto', minHeight: 120, position: 'relative' }}>
            <Box style={{ position: 'absolute', inset: 0 }}>
              <PaePanel
                matrix={matrix}
                axis={axis}
                lut={lut}
                colourMax={maxPae}
                showStrips={stripsShown}
                brushMode={brushMode}
                selected={selected}
                outline={outline}
                highlight={highlight}
                onHover={onHover}
                onSelect={selectable ? onSelect : undefined}
                onDrawn={onDrawn}
                valueLabel="pLDDT"
              />
            </Box>
          </Box>
          {legend.length ? (
            <Group gap="sm" px={4} pt={4} wrap="wrap" style={{ flex: '0 0 auto' }}>
              {legend.map((item) => (
                <Group key={item.label} gap={4} wrap="nowrap">
                  <ColorSwatch color={item.colour} size={10} withShadow={false} />
                  <Text size="xs" c="dimmed">
                    {item.label}
                  </Text>
                </Group>
              ))}
            </Group>
          ) : null}
        </Box>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default PaeMatrixRenderer;
