import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { InteractiveFilter, StoredMetadata } from '../../api';
import { useHighlight, usePublishHighlight } from '../../highlight/bus';
import {
  residueEntityFromFilters,
  residueRangeFilterIndex,
  residueRangeFilters,
  residueRangeFromFilters,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import AdvancedVizPlot from './AdvancedVizPlot';
import { demandForPx } from './contentDemand';
import {
  VizControlGroup,
  VizMultiSelect,
  VizNumberInput,
  VizSelect,
  VizSwitch,
} from './controls/VizControls';
import { parseBackbone } from './molecule/backbone';
import { MoleculeCredit } from './molecule/Overlays';
import { clickRange, type ResidueColumns } from './molecule/residueData';
import { modelCredit } from './molecule/resolve';
import { applyDataTheme, applyLayoutTheme, plotlyThemeColors } from './plotlyTheme';
import { panelColours } from './protein/panelTheme';
import { chainSelectionFilter } from './protein/rendererData';
import { plddtIsFractional, rgbCss } from './protein/residueColours';
import {
  buildFigure,
  COLOUR_MODES,
  residueRing,
  summaryLine,
  type ColourMode,
  type FigureTheme,
  type HighlightRange,
} from './ramachandran/figure';
import { countFavoured, regionSetFor } from './ramachandran/regions';
import {
  annotatePoints,
  CLASS_LABELS,
  filterByClass,
  pointsFrame,
  RESIDUE_CLASSES,
  torsionPoints,
  type ResidueClass,
} from './ramachandran/torsions';
import { useStructureSource } from './ramachandran/useStructureSource';
import { usePersistedVizControl } from './usePersistedVizControl';

/**
 * Mirrors `RamachandranConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys a renderer reads).
 */
interface RamachandranConfig {
  structure_source?: 'file' | 'resolve';
  structure_wf_id?: string | null;
  structure_dc_id?: string | null;
  structure_dc_tag?: string | null;
  uniprot_col?: string | null;
  gene_col?: string | null;
  sequence_col?: string | null;
  taxon?: number;
  entity_col?: string;
  position_col?: string;
  chain_col?: string | null;
  value_col?: string | null;
  category_col?: string | null;
  color_mode?: 'plddt' | 'residue_class' | 'secondary_structure' | 'value' | 'category' | 'chain';
  show_regions?: boolean;
  residue_classes?: Array<'general' | 'glycine' | 'proline' | 'pre_proline'> | null;
  marker_size?: number;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: RamachandranConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no residue pick. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/** Room the plot wants (it is square), and the frame furniture around it. */
const PLOT_NATURAL_PX = 440;
const CHROME_PX = 96;

const PLOT_STYLE: React.CSSProperties = { width: '100%', height: '100%' };
const PLOT_CONFIG_SELECT = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['autoScale2d'],
  scrollZoom: false,
};
const PLOT_CONFIG_PLAIN = {
  ...PLOT_CONFIG_SELECT,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
};

const CLASS_OPTIONS = RESIDUE_CLASSES.map((c) => ({ value: c, label: CLASS_LABELS[c] }));

const NO_BACKBONE = 'No protein backbone found in this structure';
const NO_TORSIONS =
  'No residue has both φ and ψ: the model may hold only Cα atoms, or be too short or too fragmented';
const NO_CLASS_MATCH = 'No residue belongs to the selected residue classes';

/** Index of a Plotly point into the plotted residues, from its `customdata`. */
function pointIndex(point: { customdata?: unknown } | undefined): number | null {
  const raw = point?.customdata;
  const n = typeof raw === 'number' ? raw : Number(Array.isArray(raw) ? raw[0] : raw);
  return Number.isInteger(n) && n >= 0 ? n : null;
}

/**
 * `ramachandran`: the phi/psi backbone torsions of one protein structure, a
 * structure-quality check to sit beside the 3D tile.
 *
 * - Structure: the same sources and caches as molecule_3d (`structure_source`
 *   `file` or `resolve`), so both tiles on one protein share one download and
 *   open on the same entity. The angles are computed here, in the browser, from
 *   the N, CA and C atoms of the model (`molecule/backbone.ts`).
 * - Plot: one SVG scatter point per residue with both angles; glycine, proline
 *   and pre-proline have their own marker symbols. Coloured by pLDDT (the
 *   AlphaFold confidence bands), residue class, secondary structure (the bound
 *   category when it holds DSSP-like states, else the phi/psi regions, and the
 *   legend says which), the bound value or category, or chain. Schematic
 *   favoured regions can sit behind the points; they are labelled approximate,
 *   not MolProbity contours, and the line under the title counts the residues
 *   inside and outside them.
 * - Links: a click emits a `residue_selection` (shift-click extends it), a box
 *   or lasso emits the range of the residues it caught, a hover goes out on the
 *   highlight bus. An incoming range selects its residues here and dims the
 *   rest; a hover from another tile is ringed over the finished figure.
 *
 * The bound collection is the residue table (entity, position, optional chain,
 * value and category): it colours the points and lists the proteins to pick.
 */
const RamachandranRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as RamachandranConfig;
  const index = String(metadata.index ?? '');

  // ---- Controls -----------------------------------------------------------------
  const [colourMode, setColourMode] = usePersistedVizControl<ColourMode>(
    metadata,
    'color_mode',
    'plddt',
  );
  const [showRegions, setShowRegions] = usePersistedVizControl<boolean>(
    metadata,
    'show_regions',
    true,
  );
  const [markerSize, setMarkerSize] = usePersistedVizControl<number>(metadata, 'marker_size', 6);
  const [classes, setClasses] = usePersistedVizControl<ResidueClass[] | null>(
    metadata,
    'residue_classes',
    null,
  );
  const [followSelection, setFollowSelection] = usePersistedVizControl<boolean>(
    metadata,
    'follow_selection',
    true,
  );
  const [pickedEntity, setPickedEntity] = useState<string | null>(null);

  const fileMode = (config.structure_source ?? 'file') === 'file';
  const entityCol = config.entity_col || 'entity';
  const positionCol = config.position_col || 'position';
  // Chain column a residue pick on a complex names (the residue tables' own).
  const chainFilterCol = config.chain_col || 'chain';
  const selectionEnabled = Boolean(onFilterChange) && config.selection_enabled !== false;
  const hasValue = Boolean(config.value_col);
  const hasCategory = Boolean(config.category_col);
  // A mode whose column is not bound would paint everything neutral: use pLDDT.
  const mode: ColourMode =
    (colourMode === 'value' && !hasValue) || (colourMode === 'category' && !hasCategory)
      ? 'plddt'
      : colourMode;

  // ---- Structure and table --------------------------------------------------------
  const cols = useMemo<ResidueColumns>(
    () => ({
      entity: entityCol,
      chain: config.chain_col,
      position: positionCol,
      value: config.value_col,
      category: config.category_col,
      uniprot: config.uniprot_col,
      gene: config.gene_col,
      sequence: config.sequence_col,
    }),
    [
      entityCol,
      positionCol,
      config.chain_col,
      config.value_col,
      config.category_col,
      config.uniprot_col,
      config.gene_col,
      config.sequence_col,
    ],
  );
  const source = useStructureSource({
    wfId: metadata.wf_id,
    dcId: metadata.dc_id,
    index,
    filters,
    refreshTick,
    fileMode,
    structureDcId: config.structure_dc_id,
    cols,
    taxon: config.taxon ?? 9606,
    pickedEntity,
  });
  const { entity } = source;

  // ---- Torsions -------------------------------------------------------------------
  const torsions = useMemo(() => {
    const text = source.structure.data;
    return text ? torsionPoints(parseBackbone(text.text, text.format)) : null;
  }, [source.structure.data]);
  const annotated = useMemo(
    () => (torsions ? annotatePoints(torsions.points, source.entityRows) : []),
    [torsions, source.entityRows],
  );
  const plddtFractional = useMemo(
    () => plddtIsFractional(annotated.map((p) => p.bfactor)),
    [annotated],
  );
  const visible = useMemo(() => filterByClass(annotated, classes), [annotated, classes]);
  const regionSet = regionSetFor(classes);
  const chains = torsions?.chains ?? [];
  const multiChain = chains.length > 1;
  const categoryUniverse = useMemo(
    () => Array.from(new Set(source.rows.map((r) => r.category).filter((c): c is string => !!c))),
    [source.rows],
  );
  const positionSpan = useMemo(() => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const p of annotated) {
      if (p.position < lo) lo = p.position;
      if (p.position > hi) hi = p.position;
    }
    return annotated.length ? { lo, hi } : null;
  }, [annotated]);

  // ---- Selection and highlight ----------------------------------------------------
  const incoming = useMemo(
    () => residueRangeFromFilters(filters, entityCol, positionCol),
    [filters, entityCol, positionCol],
  );
  const ownRange = useMemo(() => {
    const own = new Set([index, residueRangeFilterIndex(index)]);
    return residueRangeFromFilters(
      filters.filter((f) => f.source === 'residue_selection' && own.has(f.index)),
      entityCol,
      positionCol,
    );
  }, [filters, index, entityCol, positionCol]);
  // A range covering the whole model (a sidebar position slider at its bounds)
  // selects nothing in particular: no dimming.
  const coversModel =
    incoming !== null &&
    positionSpan !== null &&
    incoming.start <= positionSpan.lo &&
    incoming.end >= positionSpan.hi;
  // On a complex, the chain a residue pick names (an alignment brush, a click
  // here), when this structure has it.
  const pickedChain = useMemo(() => {
    const c = residueEntityFromFilters(filters, chainFilterCol);
    return c && chains.includes(c) ? c : null;
  }, [filters, chainFilterCol, chains]);
  const selectionSpan: HighlightRange | null =
    incoming &&
    !coversModel &&
    (incoming.entity === null || entity === null || incoming.entity === entity)
      ? { start: incoming.start, end: incoming.end, chain: pickedChain }
      : null;
  // The tile always shows its own pick; another tile's only when following.
  const drawnSelection = ownRange !== null || followSelection ? selectionSpan : null;
  const selectionKey = drawnSelection
    ? `${drawnSelection.chain ?? ''}:${drawnSelection.start}-${drawnSelection.end}`
    : '';

  const busEvent = useHighlight(index, followSelection);
  const busChain = busEvent?.chain && chains.includes(busEvent.chain) ? busEvent.chain : null;
  const busStart = busEvent?.start ?? null;
  const busEnd = busEvent ? (busEvent.end ?? busEvent.start) : null;
  const busOnOurAxis =
    busEvent !== null &&
    (!busEvent.entity || !entity || busEvent.entity === entity) &&
    (!busEvent.positionColumn || busEvent.positionColumn === positionCol);
  const publishHighlight = usePublishHighlight(index);

  // ---- Figure ---------------------------------------------------------------------
  const colours = useMemo(() => panelColours(theme, isDark), [theme, isDark]);
  const plotColours = useMemo(() => plotlyThemeColors(isDark, theme), [isDark, theme]);
  const figureTheme = useMemo<FigureTheme>(
    () => ({
      text: plotColours.textColor,
      dimmed: colours.dimmed,
      grid: plotColours.gridColor,
      zeroLine: plotColours.zeroLineColor,
      accent: colours.accent,
      accentFill: colours.accentFill,
      highlight: colours.highlight,
      neutral: rgbCss(colours.neutral),
      categorical: colours.categorical,
      valueScale: 'Viridis',
    }),
    [colours, plotColours],
  );

  const built = useMemo(
    () =>
      buildFigure({
        points: visible,
        mode,
        markerSize,
        showRegions,
        regionSet,
        theme: figureTheme,
        plddtFractional,
        bfactorLabel: mode === 'plddt' || !fileMode ? 'pLDDT' : 'B-factor',
        valueLabel: config.value_col,
        categoryLabel: config.category_col,
        categoryUniverse,
        highlight: drawnSelection,
        dragmode: selectionEnabled ? 'select' : 'zoom',
        // Zoom and pan stay put across colour and filter changes, and reset
        // for another protein.
        uirevision: `ramachandran:${entity ?? ''}`,
        // Plotly keeps what the reader drew until this changes; a range moving
        // (this tile's own box, another tile's pick, a clear) makes the
        // residues of the range win.
        selectionrevision: `sel-${selectionKey}`,
      }),
    // `selectionKey` carries `drawnSelection`'s content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      visible,
      mode,
      markerSize,
      showRegions,
      regionSet,
      figureTheme,
      plddtFractional,
      fileMode,
      config.value_col,
      config.category_col,
      categoryUniverse,
      selectionKey,
      selectionEnabled,
      entity,
    ],
  );
  const themedData = useMemo(() => applyDataTheme(built.data, isDark, theme), [built.data, isDark, theme]);
  const themedLayout = useMemo(
    () => applyLayoutTheme(built.layout, isDark, theme),
    [built.layout, isDark, theme],
  );

  // A hover from another tile rings its residue over the finished figure: only
  // this small trace changes, never the points under it.
  const ring = useMemo(
    () =>
      busOnOurAxis && busStart !== null && busEnd !== null
        ? residueRing(
            visible,
            { start: busStart, end: busEnd, chain: busChain },
            figureTheme.highlight,
            markerSize,
          )
        : null,
    [busOnOurAxis, busStart, busEnd, busChain, visible, figureTheme.highlight, markerSize],
  );
  const plotData = useMemo(() => (ring ? [...themedData, ring] : themedData), [themedData, ring]);

  // ---- Gestures -------------------------------------------------------------------
  const anchor = useRef<number | null>(null);
  // A shift-click extends a range on the protein it started on only.
  useEffect(() => {
    anchor.current = null;
  }, [entity]);

  const emitRange = useCallback(
    (range: { start: number; end: number } | null, chain: string | null = null) => {
      if (!onFilterChange || !selectionEnabled) return;
      for (const f of residueRangeFilters(index, {
        entityColumn: entityCol,
        positionColumn: positionCol,
        entity,
        start: range ? range.start : null,
        end: range ? range.end : null,
        dcId: metadata.dc_id,
      })) {
        onFilterChange(f);
      }
      // A complex numbers each chain on its own: the pick names its chain.
      if (multiChain) {
        onFilterChange(
          chainSelectionFilter(index, metadata.dc_id, chainFilterCol, range ? chain : null),
        );
      }
    },
    [
      onFilterChange,
      selectionEnabled,
      index,
      entityCol,
      positionCol,
      entity,
      metadata.dc_id,
      multiChain,
      chainFilterCol,
    ],
  );

  const pickResidue = useCallback(
    (position: number, extend: boolean, chain: string | null) => {
      if (!selectionEnabled) return;
      if (
        !extend &&
        ownRange &&
        ownRange.start === position &&
        ownRange.end === position &&
        (!multiChain || pickedChain === chain)
      ) {
        // Clicking the one picked residue again clears the pick.
        anchor.current = null;
        emitRange(null);
        return;
      }
      const range = clickRange(anchor.current, position, extend);
      if (!extend || anchor.current === null) anchor.current = position;
      emitRange(range, chain);
    },
    [selectionEnabled, ownRange, emitRange, multiChain, pickedChain],
  );

  const handleClick = useCallback(
    (event: any) => {
      const i = pointIndex(event?.points?.[0]);
      const p = i === null ? undefined : visible[i];
      if (!p) return;
      pickResidue(p.position, Boolean(event?.event?.shiftKey), p.chain || null);
    },
    [visible, pickResidue],
  );

  // A box or lasso: the range of the residues it caught. A selection that is
  // not a drag (a click read as one) is the click handler's business.
  const handleSelected = useCallback(
    (event: any) => {
      if (!event?.range && !event?.lassoPoints) return;
      const caught = ((event.points ?? []) as Array<{ customdata?: unknown }>)
        .map((pt) => {
          const i = pointIndex(pt);
          return i === null ? undefined : visible[i];
        })
        .filter((p): p is NonNullable<typeof p> => p !== undefined);
      if (caught.length === 0) {
        anchor.current = null;
        emitRange(null);
        return;
      }
      let start = Infinity;
      let end = -Infinity;
      const chainsCaught = new Set<string>();
      for (const p of caught) {
        if (p.position < start) start = p.position;
        if (p.position > end) end = p.position;
        chainsCaught.add(p.chain);
      }
      anchor.current = start;
      // Positions of several chains are not one range of one chain: leave the
      // chain unnamed so the range applies to each.
      emitRange({ start, end }, chainsCaught.size === 1 ? Array.from(chainsCaught)[0] || null : null);
    },
    [visible, emitRange],
  );
  const handleDeselect = useCallback(() => {
    anchor.current = null;
    emitRange(null);
  }, [emitRange]);

  const handleHover = useCallback(
    (event: any) => {
      const i = pointIndex(event?.points?.[0]);
      const p = i === null ? undefined : visible[i];
      if (!p) return;
      publishHighlight({
        entity: entity ?? undefined,
        chain: p.chain || undefined,
        start: p.position,
        positionColumn: positionCol,
      });
    },
    [visible, publishHighlight, entity, positionCol],
  );
  const handleUnhover = useCallback(() => publishHighlight(null), [publishHighlight]);

  // ---- Frame state ----------------------------------------------------------------
  let emptyMessage = source.emptyMessage;
  if (!emptyMessage && !source.error && source.structure.data && torsions) {
    if (torsions.residues === 0) emptyMessage = NO_BACKBONE;
    else if (torsions.points.length === 0) emptyMessage = NO_TORSIONS;
    else if (visible.length === 0) emptyMessage = NO_CLASS_MATCH;
  }

  const favoured = useMemo(
    () => (showRegions && visible.length ? countFavoured(visible) : null),
    [showRegions, visible],
  );
  const echo = useMemo(() => {
    if (!torsions || visible.length === 0) return undefined;
    const label =
      source.accession && source.accession !== entity
        ? [entity, source.accession].filter(Boolean).join(' · ')
        : entity;
    return summaryLine({
      entity: label,
      plotted: visible.length,
      withoutTorsions: torsions.withoutTorsions,
      favoured,
      selection: drawnSelection ? { start: drawnSelection.start, end: drawnSelection.end } : null,
    });
    // `selectionKey` carries `drawnSelection`'s content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [torsions, visible.length, source.accession, entity, favoured, selectionKey]);

  const frameRows = useMemo(() => pointsFrame(visible), [visible]);
  const contentDemand = useMemo(() => demandForPx(PLOT_NATURAL_PX + CHROME_PX), []);
  const credit = fileMode ? null : modelCredit(source.origin);

  // ---- Controls -------------------------------------------------------------------
  // Encoding tier: which protein, what the colour says, which residues. Regions,
  // marker size and following are the second tier.
  const entityOptions = useMemo(
    () => source.available.map((e) => ({ value: e, label: e })),
    [source.available],
  );
  const colourOptions = COLOUR_MODES.filter(
    (m) =>
      (m.value !== 'value' || hasValue) &&
      (m.value !== 'category' || hasCategory) &&
      (m.value !== 'chain' || multiChain || colourMode === 'chain'),
  );
  const primaryControls = (
    <>
      {entityOptions.length > 1 ? (
        <VizSelect
          label="Protein"
          value={entity}
          onChange={(v) => setPickedEntity(v)}
          data={entityOptions}
          searchable
          allowDeselect={false}
          // A dashboard filter already picks the protein.
          disabled={source.fromFilters !== null && source.available.includes(source.fromFilters)}
        />
      ) : null}
      <VizSelect
        label="Colour by"
        value={mode}
        onChange={(v) => setColourMode((v as ColourMode) || 'plddt')}
        data={colourOptions}
        allowDeselect={false}
      />
      <VizMultiSelect
        label="Residue classes"
        value={classes ?? [...RESIDUE_CLASSES]}
        // Drawing nothing is not a plot: the last class stays. All four is the
        // unfiltered default, stored as null.
        onChange={(v) => {
          if (v.length === 0) return;
          setClasses(v.length === RESIDUE_CLASSES.length ? null : (v as ResidueClass[]));
        }}
        data={CLASS_OPTIONS}
      />
    </>
  );
  const controls = (
    <>
      <VizControlGroup title="Plot">
        <VizSwitch
          checked={showRegions}
          onChange={(e) => setShowRegions(e.currentTarget.checked)}
          label="Approximate favoured regions"
        />
        <VizNumberInput
          label="Marker size"
          value={markerSize}
          onChange={(v) => setMarkerSize(Math.max(2, Math.min(20, Math.round(Number(v)) || 6)))}
          min={2}
          max={20}
        />
      </VizControlGroup>
      <VizControlGroup title="View">
        <VizSwitch
          checked={followSelection}
          onChange={(e) => setFollowSelection(e.currentTarget.checked)}
          label="Follow selection"
        />
      </VizControlGroup>
    </>
  );

  const drawn = !emptyMessage && !source.error && visible.length > 0;
  // Plotly has painted the points (what an end-to-end walk waits for).
  const [plotted, setPlotted] = useState(false);
  useEffect(() => {
    if (!drawn) setPlotted(false);
  }, [drawn]);

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Ramachandran plot'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      echo={echo}
      scopeLabel={entity || undefined}
      loading={source.loading}
      error={source.error}
      emptyMessage={emptyMessage}
      dataRows={visible.length ? frameRows : undefined}
      dataColumns={visible.length ? Object.keys(frameRows) : undefined}
    >
      <Box
        className="depictio-ramachandran"
        data-ramachandran-ready={drawn && plotted ? 'true' : undefined}
        style={{ position: 'absolute', inset: 0 }}
      >
        {drawn ? (
          <AdvancedVizPlot
            data={plotData as any}
            layout={themedLayout as any}
            useResizeHandler
            style={PLOT_STYLE}
            config={(selectionEnabled ? PLOT_CONFIG_SELECT : PLOT_CONFIG_PLAIN) as any}
            onClick={selectionEnabled ? handleClick : undefined}
            onSelected={selectionEnabled ? handleSelected : undefined}
            onDeselect={selectionEnabled ? handleDeselect : undefined}
            onHover={handleHover}
            onUnhover={handleUnhover}
            onInitialized={() => setPlotted(true)}
          />
        ) : null}
        <MoleculeCredit text={drawn ? credit : null} />
      </Box>
    </AdvancedVizFrame>
  );
};

export default RamachandranRenderer;
