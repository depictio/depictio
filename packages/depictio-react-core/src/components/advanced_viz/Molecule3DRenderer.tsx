import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Center,
  Stack,
  Text,
  Tooltip,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { mantineCategoricalPalette, resolveCategoricalPalette, stableColorMap } from '../../colors';
import { useHighlight, usePublishHighlight } from '../../highlight/bus';
import { useSharedOpeningEntity } from '../../highlight/openingEntity';
import {
  residueEntityFromFilters,
  residueRangeFilterIndex,
  residueRangeFilters,
  residueRangeFromFilters,
} from '../../selection';
import { useWebglSlot } from '../../webglBudget';
import AdvancedVizFrame from './AdvancedVizFrame';
import { VizControlGroup, VizMultiSelect, VizSelect, VizSwitch } from './controls/VizControls';
import { usePersistedVizControl } from './usePersistedVizControl';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import { MsaPanel, SequenceStrip } from './protein';
import type { MsaHover, ResidueRange, StripHover, StripResidue, StripVariant } from './protein';
import {
  errorMessage,
  PREVIEW_UNAVAILABLE,
  useElementSize,
  useMsaRows,
  useResolvedStructure,
  useStructureManifest,
  useStructureText,
  useThreeDmolStatus,
} from './molecule/hooks';
import { modelCredit } from './molecule/resolve';
import {
  buildColouring,
  checkVariants,
  chooseEntity,
  clickRange,
  columnsToFetch,
  distinctEntities,
  filtersForMoleculeFetch,
  indexResidues,
  markRadius,
  markRows,
  parseResidueRows,
  resolverQuery,
  rowsForEntity,
  selectedValuesByColumn,
  type ColourMode,
  type ResidueColumns,
} from './molecule/residueData';
import { parseResidues, residueKey } from './molecule/structureText';
import {
  createStructureViewer,
  spanKey,
  type MarkSpec,
  type Representation,
  type ResidueRef,
  type ResidueSpan,
  type StructureViewer,
  type ViewerColours,
} from './molecule/viewer';
import {
  MoleculeCredit,
  MoleculeLegend,
  MoleculeTooltip,
  MoleculeViewButtons,
  type TooltipLine,
} from './molecule/Overlays';
import { SplitView, splitOrientation } from './molecule/SplitView';
import SequenceText from './molecule/SequenceText';
import { textKey, type TextResidue } from './molecule/sequenceLines';
import { plddtIsFractional } from './protein/residueColours';
import { chainRangeToConcat, concatRangeToChain } from './protein/alignment';
import { chainSelectionFilter, withoutOwnChainPick } from './protein/rendererData';

type Layout = 'structure' | 'structure_sequence' | 'structure_msa' | 'structure_text';

/** Mirrors `Molecule3DConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there (`test_advanced_viz_config_alignment`). */
interface Molecule3DConfig {
  structure_source?: 'file' | 'resolve';
  structure_wf_id?: string | null;
  structure_dc_id?: string | null;
  entity_col?: string | null;
  uniprot_col?: string | null;
  gene_col?: string | null;
  sequence_col?: string | null;
  taxon?: number;
  position_col?: string;
  chain_col?: string | null;
  value_col?: string | null;
  category_col?: string | null;
  ref_aa_col?: string | null;
  alt_aa_col?: string | null;
  label_col?: string | null;
  color_mode?: ColourMode;
  colour_scale?: ColourScale | null;
  representation?: Representation;
  representations?: Representation[] | null;
  highlight_site?: boolean;
  spin?: boolean;
  show_variants?: boolean;
  show_labels?: boolean;
  layout?: Layout;
  msa_wf_id?: string | null;
  msa_dc_id?: string | null;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: Molecule3DConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no residue pick. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

const COLOUR_MODES: { value: ColourMode; label: string }[] = [
  { value: 'plddt', label: 'pLDDT' },
  { value: 'chain', label: 'Chain' },
  { value: 'spectrum', label: 'N to C' },
  { value: 'value', label: 'Value' },
  { value: 'category', label: 'Category' },
  { value: 'secondary_structure', label: 'Secondary structure' },
  { value: 'residue_type', label: 'Residue type' },
  { value: 'hydrophobicity', label: 'Hydrophobicity' },
  { value: 'uniform', label: 'Uniform' },
];

const REPRESENTATIONS: { value: Representation; label: string }[] = [
  { value: 'cartoon', label: 'Cartoon' },
  { value: 'trace', label: 'Trace' },
  { value: 'stick', label: 'Sticks' },
  { value: 'sphere', label: 'Spheres' },
  { value: 'surface', label: 'Surface' },
];

/** Default share of the structure pane, per embedded layout. */
const DEFAULT_SPLIT: Record<Exclude<Layout, 'structure'>, number> = {
  structure_sequence: 0.75,
  structure_msa: 0.55,
  structure_text: 0.7,
};

/** Below this body size the tile is compact: the legend flows in rows. */
const COMPACT_WIDTH = 560;
const COMPACT_HEIGHT = 440;

const MAX_TOOLTIP_VARIANTS = 4;

interface HoverState {
  residue: ResidueRef;
  x: number;
  y: number;
}

function fileSafe(name: string): string {
  return name.replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 80) || 'structure';
}

function formatNumber(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) >= 10 ? 1 : 2);
}

function spanLabel(span: ResidueSpan): string {
  return span.start === span.end ? `residue ${span.start}` : `residues ${span.start}-${span.end}`;
}

function msaPlaceholder(loading: boolean, error: string | null): string {
  if (loading) return 'Loading the alignment';
  if (error) return `Alignment unavailable: ${error}`;
  return 'No alignment for this protein';
}

/**
 * `molecule_3d`: a protein structure in 3D (3Dmol.js), coloured and marked
 * from the tile's residue or variant table, linked to the rest of the
 * dashboard by residue.
 *
 * - Structure: an indexed_file object per entity (`structure_source: file`)
 *   or a model from the structure resolver (`resolve`: AlphaFold DB, then
 *   ESMFold). The entity shown is the one the dashboard filters name on
 *   `entity_col`, else the reader's pick, else the first.
 * - Colour: pLDDT bands, chain, N-to-C spectrum, the table's value or
 *   category, secondary structure, residue type, hydrophobicity, or one
 *   colour. Representations combine (a cartoon under a surface). The picked
 *   residue or range is drawn as red ball and stick (`highlight_site`), and the
 *   structure can spin. Variants are spheres on the alpha carbon, and a
 *   variant whose reference residue disagrees with the structure is listed as
 *   a numbering mismatch rather than drawn on the wrong residue.
 * - Links: a click emits a `residue_selection` (shift-click extends it), an
 *   incoming one is ringed and zoomed onto (`follow_selection`), a hover goes
 *   out on the highlight bus and one from another tile is ringed. Row
 *   selections on the table's position or label column emphasise their marks.
 * - Layouts: the structure alone, over its sequence strip, over its written
 *   sequence (one clickable letter per residue: a letter click picks and
 *   zooms like a 3D click, shift extends), or beside the alignment of
 *   `msa_dc_id`, sharing hover and selection inside the tile.
 *
 * WebGL: one slot (`useWebglSlot`). A tile without one says so and keeps its
 * sequence or alignment panel; the viewer is disposed, and its context
 * released, on unmount.
 */
const Molecule3DRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as Molecule3DConfig;
  const index = String(metadata.index ?? '');

  // ---- Controls -----------------------------------------------------------------
  const [colourMode, setColourMode] = usePersistedVizControl<ColourMode>(
    metadata,
    'color_mode',
    'plddt',
  );
  const [colourScale, setColourScale] = usePersistedVizControl<ColourScale>(
    metadata,
    'colour_scale',
    config.colour_scale ?? 'Viridis',
  );
  const [representations, setRepresentations] = usePersistedVizControl<Representation[]>(
    metadata,
    'representations',
    [config.representation ?? 'cartoon'],
  );
  const [layout, setLayout] = usePersistedVizControl<Layout>(metadata, 'layout', 'structure');
  const [showVariants, setShowVariants] = usePersistedVizControl<boolean>(
    metadata,
    'show_variants',
    true,
  );
  const [showLabels, setShowLabels] = usePersistedVizControl<boolean>(
    metadata,
    'show_labels',
    false,
  );
  const [followSelection, setFollowSelection] = usePersistedVizControl<boolean>(
    metadata,
    'follow_selection',
    true,
  );
  const [spinning, setSpinning] = useState(Boolean(config.spin));
  const highlightSite = config.highlight_site !== false;
  const [pickedEntity, setPickedEntity] = useState<string | null>(null);
  const [splits, setSplits] = useState(DEFAULT_SPLIT);

  const fileMode = (config.structure_source ?? 'file') === 'file';
  const entityCol = config.entity_col === undefined ? 'entity' : config.entity_col;
  const positionCol = config.position_col || 'position';
  const hasTable = Boolean(metadata.wf_id && metadata.dc_id);
  // Chain column a residue pick on a complex names (the residue tables' own).
  const chainFilterCol = config.chain_col || 'chain';
  const hasMsa = Boolean(config.msa_dc_id);
  const effectiveLayout: Layout = layout === 'structure_msa' && !hasMsa ? 'structure' : layout;
  const selectionEnabled = Boolean(onFilterChange) && config.selection_enabled !== false;

  // ---- Bound table ----------------------------------------------------------------
  const cols = useMemo<ResidueColumns>(
    () => ({
      entity: entityCol,
      chain: config.chain_col,
      position: positionCol,
      value: config.value_col,
      category: config.category_col,
      refAa: config.ref_aa_col,
      altAa: config.alt_aa_col,
      label: config.label_col,
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
      config.ref_aa_col,
      config.alt_aa_col,
      config.label_col,
      config.uniprot_col,
      config.gene_col,
      config.sequence_col,
    ],
  );
  const fetchCols = useMemo(() => columnsToFetch(cols), [cols]);
  const emphasisCols = useMemo(
    () => [positionCol, config.label_col].filter((c): c is string => Boolean(c)),
    [positionCol, config.label_col],
  );
  const filtersForFetch = useMemo(
    () => filtersForMoleculeFetch(withoutOwnChainPick(filters, index), index, emphasisCols),
    [filters, index, emphasisCols],
  );

  const [frame, setFrame] = useState<Record<string, unknown[]> | null>(null);
  const [rowsLoading, setRowsLoading] = useState(hasTable);
  const [rowsError, setRowsError] = useState<string | null>(null);
  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setFrame(null);
      setRowsLoading(false);
      return undefined;
    }
    let cancelled = false;
    setRowsLoading(true);
    setRowsError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns: fetchCols,
      filters: filtersForFetch,
      vizKind: 'molecule_3d',
      roles: { position: positionCol },
    })
      .then((res) => {
        if (!cancelled) setFrame(res.rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setRowsError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setRowsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // The JSON keys stand for the arrays' content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(fetchCols),
    JSON.stringify(filtersForFetch),
    positionCol,
    refreshTick,
  ]);

  const rows = useMemo(() => parseResidueRows(frame, cols), [frame, cols]);
  const hasEntityColumn = useMemo(() => rows.some((r) => r.entity !== null), [rows]);
  const rowEntities = useMemo(() => distinctEntities(rows), [rows]);

  // ---- Structure ------------------------------------------------------------------
  const threeDmol = useThreeDmolStatus();
  const previewOnly = threeDmol === 'unavailable';
  const manifest = useStructureManifest(config.structure_dc_id, fileMode && !previewOnly, refreshTick);
  const available = useMemo(
    () => (fileMode ? Array.from(manifest.data?.keys() ?? []) : rowEntities),
    [fileMode, manifest.data, rowEntities],
  );
  const fromFilters = useMemo(
    () => residueEntityFromFilters(filters, entityCol),
    [filters, entityCol],
  );
  // What this tile opens on by itself, once both its rows and its structure
  // list are in (null before: nothing is shared while half loaded), agreed
  // with the dashboard's other protein tiles under the entity column name so
  // they all open on the same entity. A filter or the reader's pick wins.
  const openingReady = !rowsLoading && (!fileMode || previewOnly || !manifest.loading);
  const ownOpening = useMemo(
    () =>
      openingReady
        ? chooseEntity({ fromFilters: null, picked: null, rowEntities, available })
        : null,
    [openingReady, rowEntities, available],
  );
  const opening = useSharedOpeningEntity(
    entityCol,
    index,
    ownOpening,
    openingReady ? available : null,
  );
  const entity = chooseEntity({
    fromFilters,
    picked: pickedEntity,
    rowEntities,
    available,
    opening,
  });
  // A dashboard filter naming an entity with no structure must not silently
  // show another protein instead.
  const missingEntity =
    fromFilters !== null && available.length > 0 && !available.includes(fromFilters)
      ? fromFilters
      : null;
  const entityRows = useMemo(
    () => rowsForEntity(rows, entity, hasEntityColumn),
    [rows, entity, hasEntityColumn],
  );

  const ask = useMemo(() => {
    if (fileMode) return null;
    const q = resolverQuery(entityRows);
    return q ? { ...q, taxon: config.taxon ?? 9606 } : null;
  }, [fileMode, entityRows, config.taxon]);
  const resolved = useResolvedStructure(ask, !fileMode && !previewOnly);

  const fileEntry = fileMode && entity ? (manifest.data?.get(entity) ?? null) : null;
  let structureUrl: string | null = null;
  if (!previewOnly) structureUrl = (fileMode ? fileEntry?.url : resolved.data?.url) ?? null;
  // A file's presigned URL expires: a refused download re-reads the manifest.
  const { reload: reloadManifest } = manifest;
  const renewFileUrl = useCallback(
    async () => (entity ? ((await reloadManifest())?.get(entity)?.url ?? null) : null),
    [reloadManifest, entity],
  );
  const structure = useStructureText(
    structureUrl,
    fileMode ? (fileEntry?.name ?? null) : 'model.pdb',
    fileMode ? renewFileUrl : undefined,
  );
  const residues = useMemo(
    () => (structure.data ? parseResidues(structure.data.text, structure.data.format) : []),
    [structure.data],
  );
  const residueIndex = useMemo(() => indexResidues(residues), [residues]);
  const plddtFractional = useMemo(
    () => plddtIsFractional(residues.map((r) => r.bfactor)),
    [residues],
  );

  // ---- Colours --------------------------------------------------------------------
  const palette = useMemo(
    () => resolveCategoricalPalette(theme, mantineCategoricalPalette(theme, isDark)),
    [theme, isDark],
  );
  const neutral = isDark ? theme.colors.dark[3] : theme.colors.gray[4];
  const uniform = theme.colors[theme.primaryColor]?.[isDark ? 4 : 6] ?? palette[0];
  const colouring = useMemo(
    () =>
      buildColouring(colourMode, {
        residues,
        rows: entityRows,
        palette,
        neutral,
        uniform,
        valueLabel: config.value_col,
        categoryLabel: config.category_col,
        valueScale: colourScale,
      }),
    [
      colourMode,
      colourScale,
      residues,
      entityRows,
      palette,
      neutral,
      uniform,
      config.value_col,
      config.category_col,
    ],
  );
  const viewerColours = useMemo<ViewerColours>(
    () => ({
      background: isDark ? theme.colors.dark[7] : theme.white,
      selection: theme.colors.grape[isDark ? 4 : 6],
      site: theme.colors.red[isDark ? 5 : 7],
      highlight: theme.colors.pink[isDark ? 3 : 5],
      labelText: isDark ? theme.colors.dark[0] : theme.black,
      labelBackground: isDark ? theme.colors.dark[5] : theme.colors.gray[0],
    }),
    [isDark, theme],
  );

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
  // A range covering the whole model (a sidebar position slider at its
  // bounds) selects nothing in particular: no ring, no zoom.
  const coversModel =
    incoming !== null &&
    residues.length > 0 &&
    incoming.start <= residues[0].position &&
    incoming.end >= residues[residues.length - 1].position;
  // On a complex, the chain a residue pick names (an alignment brush, a
  // click here), when this structure has it: the ring stays on that chain.
  const pickedChain = useMemo(() => {
    const c = residueEntityFromFilters(filters, chainFilterCol);
    return c && residues.some((r) => r.chain === c) ? c : null;
  }, [filters, chainFilterCol, residues]);
  const selectionSpan: ResidueSpan | null =
    incoming &&
    !coversModel &&
    (incoming.entity === null || entity === null || incoming.entity === entity)
      ? { chain: pickedChain, start: incoming.start, end: incoming.end }
      : null;
  const selectionIsOwn = ownRange !== null && selectionSpan !== null;
  // The tile always rings its own pick; another tile's only when following.
  const drawnSelection = selectionIsOwn || followSelection ? selectionSpan : null;

  const busEvent = useHighlight(index, followSelection);
  // The chain an event names, when this structure has it; otherwise the span
  // lands on every chain holding the positions, as for an event with none.
  const busChain =
    busEvent?.chain && residues.some((r) => r.chain === busEvent.chain) ? busEvent.chain : null;
  const busSpan: ResidueSpan | null =
    busEvent &&
    (!busEvent.entity || !entity || busEvent.entity === entity) &&
    (!busEvent.positionColumn || busEvent.positionColumn === positionCol)
      ? { chain: busChain, start: busEvent.start, end: busEvent.end ?? busEvent.start }
      : null;
  const busRowKeys = busSpan && busEvent?.rowKeys?.length ? busEvent.rowKeys.join('\u0000') : '';
  const [panelHover, setPanelHover] = useState<{ chain: string | null; position: number } | null>(
    null,
  );
  const highlightSpan: ResidueSpan | null =
    panelHover !== null
      ? { chain: panelHover.chain, start: panelHover.position, end: panelHover.position }
      : busSpan;
  const publishHighlight = usePublishHighlight(index);

  const selectedElsewhere = useMemo(
    () => selectedValuesByColumn(filters, index, emphasisCols),
    [filters, index, emphasisCols],
  );

  // ---- Marks ----------------------------------------------------------------------
  const candidates = useMemo(
    () =>
      showVariants
        ? markRows(entityRows, {
            hasAltColumn: Boolean(config.alt_aa_col),
            colourMode,
            residueCount: residues.length,
          })
        : [],
    [showVariants, entityRows, config.alt_aa_col, colourMode, residues.length],
  );
  const variantCheck = useMemo(() => checkVariants(candidates, residues), [candidates, residues]);
  // Colour universe = the whole fetched frame, so a consequence keeps its hue
  // when the entity changes.
  const markColours = useMemo(
    () => stableColorMap(rows.map((r) => r.category), palette),
    [rows, palette],
  );
  const markDefault = theme.colors.red[isDark ? 4 : 6];
  const marks = useMemo<MarkSpec[]>(() => {
    const { drawn: drawnMarks } = variantCheck;
    const values = drawnMarks.map((m) => m.value).filter((v): v is number => v !== null);
    const min = values.length ? Math.min(...values) : NaN;
    const max = values.length ? Math.max(...values) : NaN;
    const labelSet = config.label_col ? selectedElsewhere.get(config.label_col) : undefined;
    const posSet = selectedElsewhere.get(positionCol);
    // A hover elsewhere naming rows (a lollipop stem, a table row) lights
    // the same variants here.
    const hoveredKeys = new Set(busRowKeys ? busRowKeys.split('\u0000') : []);
    return drawnMarks.map((m) => ({
      chain: m.chain,
      position: m.position,
      radius: markRadius(m.value, min, max),
      colour: m.category ? markColours.get(m.category) : markDefault,
      label: m.label,
      emphasised:
        (selectionSpan !== null &&
          m.position >= selectionSpan.start &&
          m.position <= selectionSpan.end) ||
        Boolean(labelSet?.has(m.label)) ||
        Boolean(posSet?.has(String(m.position))) ||
        hoveredKeys.has(m.label),
    }));
  }, [
    variantCheck,
    markColours,
    markDefault,
    selectedElsewhere,
    config.label_col,
    positionCol,
    selectionSpan?.start,
    selectionSpan?.end,
    busRowKeys,
  ]);
  const marksByPosition = useMemo(() => {
    const out = new Map<number, string[]>();
    for (const m of marks) out.set(m.position, [...(out.get(m.position) ?? []), m.label]);
    return out;
  }, [marks]);

  // ---- Gestures -------------------------------------------------------------------
  const anchor = useRef<number | null>(null);
  // Set by a pick in the written sequence: the next selection zooms onto it.
  const zoomOwnPick = useRef(false);
  // A shift-click extends a range on the protein it started on only.
  useEffect(() => {
    anchor.current = null;
  }, [entity]);
  const multiChain = useMemo(() => new Set(residues.map((r) => r.chain)).size > 1, [residues]);
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
    (position: number, extend: boolean, chain: string | null = null) => {
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

  // ---- Viewer lifecycle -----------------------------------------------------------
  const glGranted = useWebglSlot(true);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<StructureViewer | null>(null);
  const [viewerReady, setViewerReady] = useState(false);
  const [viewerError, setViewerError] = useState<string | null>(null);
  const [drawn, setDrawn] = useState(false);
  const [hover, setHover] = useState<HoverState | null>(null);
  const pointer = useRef({ x: 0, y: 0 });
  const coloursRef = useRef(viewerColours);
  coloursRef.current = viewerColours;

  // The viewer is created once per structure and calls back through this ref,
  // so its callbacks always see the current entity, selection and marks.
  const callbacks = useRef({
    onHover: (_residue: ResidueRef | null) => {},
    onClick: (_residue: ResidueRef, _extend: boolean) => {},
  });
  callbacks.current = {
    onHover: (residue) => {
      if (!residue) {
        setHover(null);
        publishHighlight(null);
        return;
      }
      setHover({ residue, x: pointer.current.x, y: pointer.current.y });
      publishHighlight({
        entity: entity ?? undefined,
        chain: residue.chain || undefined,
        start: residue.position,
        positionColumn: positionCol,
        rowKeys: marksByPosition.get(residue.position),
      });
    },
    onClick: (residue, extend) => pickResidue(residue.position, extend, residue.chain || null),
  };

  const canDraw = glGranted && threeDmol === 'ready' && Boolean(structure.data);
  useEffect(() => {
    if (!canDraw) return undefined;
    const host = hostRef.current;
    if (!host) return undefined;
    let disposed = false;
    let created: StructureViewer | null = null;
    setViewerError(null);
    createStructureViewer(host, coloursRef.current, {
      onHover: (r) => callbacks.current.onHover(r),
      onClick: (r, e) => callbacks.current.onClick(r, e),
    })
      .then((viewer) => {
        if (disposed) {
          viewer.dispose();
          return;
        }
        created = viewer;
        viewerRef.current = viewer;
        setViewerReady(true);
      })
      .catch((err: unknown) => {
        if (!disposed) setViewerError(errorMessage(err));
      });
    return () => {
      disposed = true;
      setViewerReady(false);
      setDrawn(false);
      viewerRef.current = null;
      created?.dispose();
    };
  }, [canDraw]);

  // Effects run in declaration order: load, colours, style, selection, overlays.
  // A filter change that leaves the structure URL alone reaches none of the
  // first three (same text object from the cache), so nothing is re-parsed.
  useEffect(() => {
    if (!viewerReady || !structure.data) return;
    viewerRef.current?.load(structure.data.text, structure.data.format);
    setDrawn(true);
  }, [viewerReady, structure.data]);

  useEffect(() => {
    if (viewerReady && structure.data) viewerRef.current?.setColours(viewerColours);
  }, [viewerReady, structure.data, viewerColours]);

  const repsKey = representations.join(',');
  useEffect(() => {
    if (viewerReady && structure.data) {
      viewerRef.current?.setStyle(
        { colourOf: colouring.colourOf, scheme: colouring.scheme },
        representations,
      );
    }
    // `repsKey` carries `representations`' content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewerReady, structure.data, colouring, repsKey]);

  const selectionKey = spanKey(drawnSelection);
  useEffect(() => {
    if (!viewerReady || !structure.data) return;
    viewerRef.current?.setSelection(drawnSelection, highlightSite);
    // Zoom onto another tile's pick, and onto a letter picked in the written
    // sequence; a click in 3D leaves the camera where the reader put it.
    const zoomOwn = zoomOwnPick.current && drawnSelection !== null;
    zoomOwnPick.current = false;
    if ((followSelection && !selectionIsOwn) || zoomOwn) {
      viewerRef.current?.focus(drawnSelection);
    }
    // `selectionKey` carries `drawnSelection`'s content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewerReady, structure.data, selectionKey, selectionIsOwn, followSelection, highlightSite]);

  const highlightKey = spanKey(highlightSpan);
  useEffect(() => {
    if (!viewerReady || !structure.data) return;
    viewerRef.current?.setOverlay({ marks, showLabels, highlight: highlightSpan });
    // `highlightKey` carries `highlightSpan`'s content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewerReady, structure.data, marks, showLabels, highlightKey]);

  useEffect(() => {
    if (viewerReady) viewerRef.current?.setSpin(spinning);
  }, [viewerReady, spinning]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !viewerReady || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => viewerRef.current?.resize());
    ro.observe(host);
    return () => ro.disconnect();
  }, [viewerReady]);

  const snapshot = useCallback(() => {
    const uri = viewerRef.current?.snapshot();
    if (!uri) return;
    const a = document.createElement('a');
    a.href = uri;
    a.download = `${fileSafe(metadata.title || entity || 'structure')}.png`;
    a.click();
  }, [metadata.title, entity]);

  // ---- Embedded panels ------------------------------------------------------------
  const [bodyRef, bodySize] = useElementSize<HTMLDivElement>();
  const primaryChain = residueIndex.primaryChain;
  const stripResidues = useMemo<StripResidue[]>(() => {
    if (effectiveLayout !== 'structure_sequence') return [];
    const valueOf = new Map<number, number>();
    const categoryOf = new Map<number, string>();
    for (const r of entityRows) {
      if (r.position === null || (r.chain !== null && r.chain !== primaryChain)) continue;
      if (r.value !== null) {
        valueOf.set(r.position, Math.max(valueOf.get(r.position) ?? -Infinity, r.value));
      }
      if (r.category !== null && !categoryOf.has(r.position)) {
        categoryOf.set(r.position, r.category);
      }
    }
    const usePlddt = colourMode === 'plddt' || valueOf.size === 0;
    return residues
      .filter((r) => r.chain === primaryChain)
      .map((r) => ({
        position: r.position,
        letter: r.aa,
        value: usePlddt ? r.bfactor : (valueOf.get(r.position) ?? null),
        category: categoryOf.get(r.position) ?? null,
      }));
  }, [effectiveLayout, entityRows, residues, primaryChain, colourMode]);
  const stripValueLabel =
    colourMode === 'plddt' || !config.value_col ? 'pLDDT' : config.value_col;
  const stripVariants = useMemo<StripVariant[]>(
    () =>
      variantCheck.drawn.map((m) => ({
        position: m.position,
        label: m.label,
        category: m.category,
        value: m.value,
      })),
    [variantCheck],
  );

  const msa = useMsaRows({
    wfId: config.msa_wf_id || metadata.wf_id,
    dcId: config.msa_dc_id,
    msaId: entity,
    enabled: effectiveLayout === 'structure_msa' && !previewOnly,
    refreshTick,
  });

  // The alignment of a complex is drawn in concatenated reference numbering;
  // spans in and out of it go through its chain layout. The sequence strip
  // draws the primary chain only.
  const msaChains = effectiveLayout === 'structure_msa' ? (msa.data?.chains ?? null) : null;
  const stripChain = effectiveLayout === 'structure_sequence' ? primaryChain || null : null;
  const toPanel = useCallback(
    (span: ResidueSpan | null): ResidueRange | null => {
      if (!span) return null;
      if (msaChains) {
        const named = span.chain && msaChains.some((c) => c.chain === span.chain);
        return chainRangeToConcat(named ? span.chain : null, span, msaChains);
      }
      if (stripChain && multiChain && span.chain && span.chain !== stripChain) return null;
      return { start: span.start, end: span.end };
    },
    [msaChains, stripChain, multiChain],
  );
  const panelSelected = toPanel(selectionSpan);
  const panelHighlight = toPanel(
    hover
      ? { chain: hover.residue.chain || null, start: hover.residue.position, end: hover.residue.position }
      : busSpan,
  );
  const onPanelHover = useCallback(
    (chain: string | null, position: number | null) => {
      setPanelHover(position === null ? null : { chain, position });
      publishHighlight(
        position === null
          ? null
          : {
              entity: entity ?? undefined,
              chain: chain ?? undefined,
              start: position,
              positionColumn: positionCol,
            },
      );
    },
    [publishHighlight, entity, positionCol],
  );
  const onMsaHover = useCallback(
    (h: MsaHover | null) => {
      if (!h || h.residue == null) {
        onPanelHover(null, null);
      } else if (msaChains && h.chain && h.chainPosition != null) {
        onPanelHover(h.chain, h.chainPosition);
      } else {
        onPanelHover(null, h.residue);
      }
    },
    [onPanelHover, msaChains],
  );
  const onPanelBrush = useCallback(
    (range: ResidueRange | null) => {
      if (!range) {
        anchor.current = null;
        emitRange(null);
        return;
      }
      // A brush on a complex's alignment lands in one chain's own numbering.
      const local = msaChains ? concatRangeToChain(range, msaChains) : null;
      const start = local ? local.start : range.start;
      const end = local ? local.end : (range.end ?? range.start);
      anchor.current = start;
      emitRange({ start, end }, local ? local.chain : stripChain);
    },
    [emitRange, msaChains, stripChain],
  );

  // The written sequence: every chain of the structure, in its own numbering.
  const textResidues = useMemo<TextResidue[]>(
    () =>
      effectiveLayout === 'structure_text'
        ? residues.map((r) => ({ chain: r.chain, position: r.position, letter: r.aa }))
        : [],
    [effectiveLayout, residues],
  );
  const textVariants = useMemo(
    () => new Set(variantCheck.drawn.map((m) => textKey(m.chain, m.position))),
    [variantCheck],
  );
  // What the letters outline: the residue under the pointer in 3D or in the
  // text, else another tile's hover.
  const textHighlight: ResidueSpan | null = hover
    ? { chain: hover.residue.chain || null, start: hover.residue.position, end: hover.residue.position }
    : highlightSpan;
  const onTextHover = useCallback(
    (r: TextResidue | null) => onPanelHover(r ? r.chain || null : null, r ? r.position : null),
    [onPanelHover],
  );
  const onTextPick = useCallback(
    (r: TextResidue, extend: boolean) => {
      zoomOwnPick.current = true;
      pickResidue(r.position, extend, r.chain || null);
    },
    [pickResidue],
  );

  let panel: React.ReactNode | null = null;
  if (effectiveLayout === 'structure_text') {
    panel = textResidues.length ? (
      <SequenceText
        residues={textResidues}
        selected={selectionSpan}
        highlight={textHighlight}
        variants={textVariants}
        followSelection={followSelection}
        onHover={onTextHover}
        onPick={selectionEnabled ? onTextPick : undefined}
      />
    ) : (
      <Center h="100%">
        <Text size="xs" c="dimmed">
          No sequence to show yet
        </Text>
      </Center>
    );
  } else if (effectiveLayout === 'structure_sequence') {
    panel = stripResidues.length ? (
      <SequenceStrip
        residues={stripResidues}
        variants={stripVariants}
        valueLabel={stripValueLabel}
        valueScale={stripValueLabel === 'pLDDT' ? 'plddt' : colourScale}
        selectedRange={panelSelected}
        highlight={panelHighlight}
        followSelection={followSelection}
        onHover={(h: StripHover | null) => onPanelHover(stripChain, h ? h.position : null)}
        onBrush={selectionEnabled ? onPanelBrush : undefined}
        onClickVariant={(v: StripVariant) => pickResidue(v.position, false, stripChain)}
      />
    ) : (
      <Center h="100%">
        <Text size="xs" c="dimmed">
          No sequence to show yet
        </Text>
      </Center>
    );
  } else if (effectiveLayout === 'structure_msa') {
    panel =
      msa.data && msa.data.rows.length ? (
        <MsaPanel
          rows={msa.data.rows}
          chains={msaChains}
          selectedRange={panelSelected}
          highlight={panelHighlight}
          followSelection={followSelection}
          onHoverColumn={onMsaHover}
          onBrushColumns={selectionEnabled ? onPanelBrush : undefined}
        />
      ) : (
        <Center h="100%">
          <Text size="xs" c="dimmed" ta="center">
            {msaPlaceholder(msa.loading, msa.error)}
          </Text>
        </Center>
      );
  }
  // The sequence strip is a horizontal band, so it always goes below; the
  // alignment goes beside the structure in a wide tile, below in a tall one.
  // The written sequence reads as lines under the structure, like a figure
  // caption.
  const orientation =
    effectiveLayout === 'structure_sequence' || effectiveLayout === 'structure_text'
      ? 'column'
      : splitOrientation(bodySize.width, bodySize.height);
  const compact =
    bodySize.width > 0 && (bodySize.width < COMPACT_WIDTH || bodySize.height < COMPACT_HEIGHT);
  const splitKey = effectiveLayout === 'structure' ? null : effectiveLayout;

  // ---- Tooltip --------------------------------------------------------------------
  const tooltip = useMemo(() => {
    if (!hover) return null;
    const { residue } = hover;
    const structural = residueIndex.byKey.get(residueKey(residue.chain, residue.position));
    const lines: TooltipLine[] = [];
    if (residue.chain) lines.push({ label: 'Chain', value: residue.chain });
    if (structural?.bfactor != null) {
      const isPlddt = colourMode === 'plddt' || !fileMode;
      lines.push({
        label: isPlddt ? 'pLDDT' : 'B-factor',
        // Some predictors write pLDDT as 0-1; show it on the usual 0-100 scale.
        value: formatNumber(
          isPlddt && plddtFractional ? structural.bfactor * 100 : structural.bfactor,
        ),
      });
    }
    const here = entityRows.filter(
      (r) => r.position === residue.position && (r.chain === null || r.chain === residue.chain),
    );
    const value = here.find((r) => r.value !== null)?.value;
    if (value != null && config.value_col) {
      lines.push({ label: config.value_col, value: formatNumber(value) });
    }
    const category = here.find((r) => r.category !== null)?.category;
    if (category && config.category_col) lines.push({ label: config.category_col, value: category });
    const variants = marksByPosition.get(residue.position) ?? [];
    if (variants.length) {
      const shown = variants.slice(0, MAX_TOOLTIP_VARIANTS).join(', ');
      const more = variants.length - MAX_TOOLTIP_VARIANTS;
      lines.push({ label: 'Variants', value: more > 0 ? `${shown} and ${more} more` : shown });
    }
    const mismatched = variantCheck.mismatched.filter((m) => m.position === residue.position);
    if (mismatched.length) {
      lines.push({
        label: 'Numbering mismatch',
        value: mismatched.map((m) => `${m.label} (model ${m.structureAa})`).join(', '),
      });
    }
    const aa = structural?.aa ?? '';
    return { title: `${residue.resn || aa} ${residue.position}${aa ? ` (${aa})` : ''}`, lines };
  }, [
    hover,
    residueIndex,
    colourMode,
    fileMode,
    entityRows,
    config.value_col,
    config.category_col,
    marksByPosition,
    variantCheck,
    plddtFractional,
  ]);

  // ---- Frame state ----------------------------------------------------------------
  const loading =
    threeDmol === 'loading' ||
    (!structure.data &&
      (rowsLoading ||
        (fileMode && manifest.loading) ||
        (!fileMode && resolved.loading) ||
        structure.loading));

  let emptyMessage: string | undefined;
  let error: string | null = null;
  if (previewOnly || viewerError === PREVIEW_UNAVAILABLE) {
    emptyMessage = PREVIEW_UNAVAILABLE;
  } else if (rowsError) {
    error = rowsError;
  } else if (fileMode && manifest.error) {
    error = manifest.error;
  } else if (missingEntity) {
    emptyMessage = `No structure file for ${missingEntity}`;
  } else if (fileMode && manifest.data && available.length === 0) {
    emptyMessage = 'No structure files in the bound collection';
  } else if (!fileMode && !rowsLoading && ask === null) {
    emptyMessage = 'No UniProt accession, gene or sequence to look a structure up with';
  } else if (!fileMode && resolved.error) {
    // Disabled resolver, sign-in needed, nothing found, unreadable id: a state to explain,
    // not a failure to report.
    if (resolved.refusal && resolved.refusal !== 'upstream') emptyMessage = resolved.error;
    else error = resolved.error;
  } else if (structure.error) {
    error = structure.error;
  } else if (viewerError) {
    error = viewerError;
  }

  const credit = fileMode ? null : modelCredit(resolved.data?.origin);
  const echo = [
    entity,
    !fileMode && resolved.data?.accession && resolved.data.accession !== entity
      ? resolved.data.accession
      : null,
    residues.length ? `${residues.length} residues` : null,
    selectionSpan ? spanLabel(selectionSpan) : null,
  ]
    .filter(Boolean)
    .join(' · ');

  const badges: React.ReactNode[] = [];
  if (residues.length && variantCheck.mismatched.length) {
    const list = variantCheck.mismatched
      .slice(0, 12)
      .map((m) => `${m.label}: the model has ${m.structureAa || '?'} at ${m.position}`)
      .join('\n');
    badges.push(
      <Tooltip
        key="mismatch"
        label={<span style={{ whiteSpace: 'pre-line' }}>{list}</span>}
        multiline
        w={280}
        withinPortal
      >
        <Badge size="xs" radius="sm" variant="light" color="orange">
          {`${variantCheck.mismatched.length} numbering mismatch`}
        </Badge>
      </Tooltip>,
    );
  }
  if (residues.length && variantCheck.outside.length) {
    badges.push(
      <Tooltip
        key="outside"
        label="Positions the model does not cover (a truncated model or a construct)"
        multiline
        w={240}
        withinPortal
      >
        <Badge size="xs" radius="sm" variant="light" color="gray">
          {`${variantCheck.outside.length} outside the model`}
        </Badge>
      </Tooltip>,
    );
  }

  // ---- Controls -------------------------------------------------------------------
  // Encoding tier: which protein, what the colour means, how it is drawn and
  // what sits beside it. Marks, labels, following and spin are the second tier.
  const entityOptions = useMemo(() => available.map((e) => ({ value: e, label: e })), [available]);
  const colourOptions = COLOUR_MODES.filter(
    (m) =>
      (m.value !== 'value' || Boolean(config.value_col)) &&
      (m.value !== 'category' || Boolean(config.category_col)),
  );
  const layoutOptions = [
    { value: 'structure', label: 'Structure' },
    { value: 'structure_sequence', label: 'With sequence' },
    { value: 'structure_text', label: 'With written sequence' },
    ...(hasMsa ? [{ value: 'structure_msa', label: 'With alignment' }] : []),
  ];
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
          disabled={fromFilters !== null && !missingEntity}
        />
      ) : null}
      <VizSelect
        label="Colour by"
        value={colourMode}
        onChange={(v) => setColourMode((v as ColourMode) || 'plddt')}
        data={colourOptions}
        allowDeselect={false}
      />
      <VizMultiSelect
        label="Style"
        value={representations}
        // Drawing nothing is not a style: the last one stays.
        onChange={(v) => {
          if (v.length) setRepresentations(v as Representation[]);
        }}
        data={REPRESENTATIONS}
      />
      <VizSelect
        label="Layout"
        value={effectiveLayout}
        onChange={(v) => setLayout((v as Layout) || 'structure')}
        data={layoutOptions}
        allowDeselect={false}
      />
    </>
  );
  const controls = (
    <>
      {colourMode === 'value' ? (
        <VizControlGroup title="Colour">
          <VizSelect
            label="Colour scale"
            value={colourScale}
            onChange={(v) => setColourScale((v as ColourScale) || 'Viridis')}
            data={COLOUR_SCALES as unknown as string[]}
            allowDeselect={false}
          />
        </VizControlGroup>
      ) : null}
      <VizControlGroup title="Marks">
        <VizSwitch
          checked={showVariants}
          onChange={(e) => setShowVariants(e.currentTarget.checked)}
          label="Variants"
        />
        <VizSwitch
          checked={showLabels}
          onChange={(e) => setShowLabels(e.currentTarget.checked)}
          label="Labels"
        />
      </VizControlGroup>
      <VizControlGroup title="View">
        <VizSwitch
          checked={followSelection}
          onChange={(e) => setFollowSelection(e.currentTarget.checked)}
          label="Follow selection"
        />
        <VizSwitch
          checked={spinning}
          onChange={(e) => setSpinning(e.currentTarget.checked)}
          label="Spin"
        />
      </VizControlGroup>
    </>
  );

  const structurePane = glGranted ? (
    <div
      style={{ position: 'absolute', inset: 0 }}
      onMouseMove={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        pointer.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      }}
      onMouseLeave={() => {
        setHover(null);
        publishHighlight(null);
      }}
    >
      <div
        ref={hostRef}
        style={{ position: 'absolute', inset: 0, cursor: selectionEnabled ? 'pointer' : 'default' }}
      />
      {drawn ? (
        <>
          <MoleculeLegend legend={colouring.legend} compact={compact} />
          <MoleculeCredit text={credit} />
          <MoleculeViewButtons
            onReset={() => viewerRef.current?.resetView()}
            onSnapshot={snapshot}
            spinning={spinning}
            onSpin={() => setSpinning((s) => !s)}
          />
        </>
      ) : null}
      {tooltip && hover ? (
        <MoleculeTooltip
          x={hover.x}
          y={hover.y}
          title={tooltip.title}
          lines={tooltip.lines}
          bounds={{
            width: hostRef.current?.clientWidth ?? 0,
            height: hostRef.current?.clientHeight ?? 0,
          }}
        />
      ) : null}
    </div>
  ) : (
    <Center h="100%">
      <Stack gap={4} align="center" p="sm">
        <Text size="sm" c="dimmed" fw={500}>
          3D viewer paused
        </Text>
        <Text size="xs" c="dimmed" ta="center">
          Too many 3D views are open on this page. Scroll past or close another one to show this
          structure.
        </Text>
      </Stack>
    </Center>
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || '3D structure'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={emptyMessage}
      echo={echo || undefined}
      badges={badges.length ? badges : undefined}
      dataRows={frame ?? undefined}
      dataColumns={fetchCols}
    >
      <div
        ref={bodyRef}
        className="depictio-molecule-3d"
        data-molecule-ready={drawn ? 'true' : undefined}
        style={{ position: 'absolute', inset: 0 }}
      >
        <SplitView
          orientation={orientation}
          fraction={splitKey ? splits[splitKey] : 1}
          onFraction={(f) => {
            if (splitKey) setSplits((s) => ({ ...s, [splitKey]: f }));
          }}
          first={structurePane}
          second={panel}
        />
      </div>
    </AdvancedVizFrame>
  );
};

export default Molecule3DRenderer;
