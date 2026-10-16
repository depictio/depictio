import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  ColorSwatch,
  Group,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { usePinnedCategoryColors } from '../../hooks/useCategoryColors';
import { usePublishHighlight, useHighlight } from '../../highlight/bus';
import {
  filtersExcludingOwnResidue,
  residueEntityFromFilters,
  residueRangeFilters,
  residueRangeFromFilters,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import { demandForPx } from './contentDemand';
import {
  VizControlCell,
  VizControlGroup,
  VizSelect,
  VizSlider,
  VizSwitch,
} from './controls/VizControls';
import { MIN_LETTER_PX } from './protein/canvas';
import { panelColours } from './protein/panelTheme';
import {
  distinctColumns,
  firstValueOf,
  hasOwnResiduePick,
  scopeToEntity,
  withoutPositionSelections,
} from './protein/rendererData';
import { rgbCss } from './protein/residueColours';
import { SS_GLYPH_FILLS } from './protein/ssGlyphs';
import type { ResidueRange } from './protein/types';
import { useEntityPicker } from './protein/useEntityPicker';
import ZoomHintLabel from './protein/ZoomHint';
import { usePersistedVizControl } from './usePersistedVizControl';
import { compositionBadges } from './secstruct/compositionBadges';
import { naturalPanelHeight } from './secstruct/panelLanes';
import SecondaryStructurePanel from './secstruct/SecondaryStructurePanel';
import { DEFAULT_RIBBON_PX } from './secstruct/ribbonHeight';
import SegmentList, { SEGMENT_LIST_MAX_PX } from './secstruct/SegmentList';
import {
  agreementOf,
  buildSsModel,
  segmentsOf,
  type SsColumns,
} from './secstruct/ssModel';
import StateColourInput from './secstruct/StateColourInput';
import {
  effectiveStateColours,
  SS_COLOUR_CLASSES,
  withStateColour,
  type StateColourMap,
} from './secstruct/stateColours';

/**
 * Mirrors `SecondaryStructureConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys read here).
 */
interface SecondaryStructureConfig {
  entity_col?: string | null;
  position_col?: string;
  residue_col?: string | null;
  state_col?: string;
  source_col?: string | null;
  reference_source?: string | null;
  p_helix_col?: string | null;
  p_strand_col?: string | null;
  p_coil_col?: string | null;
  confidence_col?: string | null;
  show_probabilities?: boolean;
  show_agreement?: boolean;
  show_segments?: boolean;
  show_composition?: boolean;
  show_letters?: boolean;
  shade_confidence?: boolean;
  show_coil_segments?: boolean;
  residue_width?: number;
  ribbon_height?: number | null;
  state_colors?: Record<string, string>;
  min_segment_length?: number;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: SecondaryStructureConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no residue pick. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/** Tile furniture around the panel: frame header and badges, the legend row. */
const CHROME_PX = 110;
const LEGEND_PX = 24;

type Frame = Record<string, unknown[]>;

/** A column the config names, `null` meaning "not bound", `undefined` the model's default. */
function optionalColumn(value: string | null | undefined, fallback: string | null): string | null {
  if (value === undefined) return fallback;
  return value || null;
}

/**
 * `secondary_structure`: one protein's secondary structure from a per-residue
 * prediction table, as a topology ribbon (shaded by confidence), stacked
 * P(helix / strand / coil) lanes, one ribbon per additional prediction source
 * with a lane marking where they agree, the composition in percent and a list
 * of segments. Drawn by `SecondaryStructurePanel`; the model behind it is the
 * pure `secstruct/ssModel`.
 *
 * A brush or click on the ribbons, or a click on a segment, emits a
 * `residue_selection` (entity + position range); a hover publishes on the
 * highlight bus; the range and hover of the other protein tiles come back in
 * as a shaded range and a marked residue. The tile keeps all its rows when a
 * range is picked (it shades rather than narrows) and follows a single-value
 * filter on the entity column.
 */
const SecondaryStructureRenderer: React.FC<Props> = ({
  metadata,
  filters,
  refreshTick,
  onFilterChange,
}) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as SecondaryStructureConfig;
  const index = String(metadata.index);
  const entityCol = config.entity_col === undefined ? 'entity' : config.entity_col;
  const positionCol = config.position_col || 'position';
  const residueCol = optionalColumn(config.residue_col, 'residue');
  const stateCol = config.state_col || 'ss_code';
  const sourceCol = config.source_col || null;
  const referenceSource = config.reference_source || null;
  const pHelixCol = optionalColumn(config.p_helix_col, 'p_helix');
  const pStrandCol = optionalColumn(config.p_strand_col, 'p_strand');
  const pCoilCol = optionalColumn(config.p_coil_col, 'p_coil');
  const confidenceCol = config.confidence_col || null;
  const showProbabilities = config.show_probabilities !== false;
  const showAgreement = config.show_agreement !== false;
  const showSegments = config.show_segments !== false;
  const showComposition = config.show_composition !== false;
  const follow = config.follow_selection !== false;
  const brushEnabled = Boolean(onFilterChange) && config.selection_enabled !== false;

  const [showLetters, setShowLetters] = usePersistedVizControl(metadata, 'show_letters', true);
  const [shadeConfidence, setShadeConfidence] = usePersistedVizControl(metadata, 'shade_confidence', true);
  const [coilSegments, setCoilSegments] = usePersistedVizControl(metadata, 'show_coil_segments', false);
  // Pixels per residue; 0 fits the whole protein to the tile width.
  const [zoom, setZoom] = usePersistedVizControl<number>(metadata, 'residue_width', 0);
  // Null until chosen: the ribbon then keeps its default height and grows into
  // spare room; a chosen height is drawn exactly.
  const [ribbonHeight, setRibbonHeight] = usePersistedVizControl<number | null>(
    metadata,
    'ribbon_height',
    null,
  );
  // Class name to CSS colour, seeded from the config and rewritten by the Colours controls.
  const [userColours, setUserColours] = usePersistedVizControl<StateColourMap>(
    metadata,
    'state_colors',
    {},
  );
  const [minSegment, setMinSegment] = usePersistedVizControl<number>(metadata, 'min_segment_length', 1);
  const [pickedReference, setPickedReference] = useState<string | null>(null);
  const [drawn, setDrawn] = useState(false);

  // The tile's own residue pick never narrows its own fetch, and no residue
  // range does (it shades); everything else the dashboard filters applies.
  const withoutOwn = useMemo(() => filtersExcludingOwnResidue(filters, index), [filters, index]);
  const fetchFilters = useMemo(
    () => withoutPositionSelections(withoutOwn, [positionCol]),
    [withoutOwn, positionCol],
  );
  const followed = useMemo(() => residueEntityFromFilters(withoutOwn, entityCol), [withoutOwn, entityCol]);
  const picker = useEntityPicker(metadata.dc_id, entityCol, followed, refreshTick, {
    wfId: metadata.wf_id,
    vizKind: 'secondary_structure',
    filters: fetchFilters,
    shareKey: entityCol,
    owner: index,
  });

  // ---- residue table -------------------------------------------------------
  const columns = useMemo(
    () =>
      distinctColumns([
        entityCol,
        positionCol,
        residueCol,
        stateCol,
        sourceCol,
        pHelixCol,
        pStrandCol,
        pCoilCol,
        confidenceCol,
      ]),
    [entityCol, positionCol, residueCol, stateCol, sourceCol, pHelixCol, pStrandCol, pCoilCol, confidenceCol],
  );
  const [frame, setFrame] = useState<Frame | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // `filters` is a fresh array on every parent render: key the fetch on the
  // filters' content, as the other protein tiles do, or it refetches after
  // every render, its own brush included.
  const residueFilters = useMemo(
    () => scopeToEntity(fetchFilters, index, metadata.dc_id, entityCol, picker.entity),
    [fetchFilters, index, metadata.dc_id, entityCol, picker.entity],
  );
  const residueFiltersKey = JSON.stringify(residueFilters);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Secondary structure: missing data binding');
      setLoading(false);
      return;
    }
    if (picker.entities === null) return;
    if (entityCol && !picker.entity && !picker.failed) {
      setFrame({});
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns,
      filters: residueFilters,
      vizKind: 'secondary_structure',
    })
      .then((res) => {
        if (!cancelled) setFrame(res.rows);
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
    JSON.stringify(columns),
    residueFiltersKey,
    picker.entities,
    picker.entity,
    picker.failed,
    entityCol,
    refreshTick,
  ]);

  const entity = useMemo(
    () => picker.entity ?? firstValueOf(frame, entityCol),
    [picker.entity, frame, entityCol],
  );

  // ---- model -----------------------------------------------------------------
  const ssColumns = useMemo<SsColumns>(
    () => ({
      entity: entityCol,
      position: positionCol,
      residue: residueCol,
      state: stateCol,
      source: sourceCol,
      pHelix: pHelixCol,
      pStrand: pStrandCol,
      pCoil: pCoilCol,
      confidence: confidenceCol,
    }),
    [entityCol, positionCol, residueCol, stateCol, sourceCol, pHelixCol, pStrandCol, pCoilCol, confidenceCol],
  );
  const model = useMemo(
    () => buildSsModel(frame, ssColumns, entity, pickedReference ?? referenceSource),
    [frame, ssColumns, entity, pickedReference, referenceSource],
  );
  const agreement = useMemo(() => agreementOf(model), [model]);
  const segments = useMemo(
    () =>
      segmentsOf(model, 0).filter(
        (s) => (coilSegments || s.state !== 'coil') && s.length >= minSegment,
      ),
    [model, coilSegments, minSegment],
  );
  const sources = model.sources.length;
  const hasLetters = model.letters.some((l) => l != null);
  const hasProbabilities = model.sources.some((s) => s.hasProbabilities);
  const hasConfidence = model.sources.some((s) => s.confidence.some((c) => c != null));

  useEffect(() => setDrawn(false), [entity]);

  // ---- selections in ---------------------------------------------------------
  const ownResidue = useMemo(() => hasOwnResiduePick(filters, index), [filters, index]);
  const selectedRange = useMemo<ResidueRange | null>(() => {
    if (!follow && !ownResidue) return null;
    const r = residueRangeFromFilters(filters, entityCol, positionCol);
    if (!r || (r.entity && entity && r.entity !== entity)) return null;
    return { start: r.start, end: r.end };
  }, [filters, entityCol, positionCol, follow, ownResidue, entity]);

  const incoming = useHighlight(index, follow);
  const highlight = useMemo(() => {
    if (!incoming || (incoming.entity && entity && incoming.entity !== entity)) return null;
    // An event on another position column is on another axis entirely.
    if (incoming.positionColumn && incoming.positionColumn !== positionCol) return null;
    return { start: incoming.start, end: incoming.end };
  }, [incoming, entity, positionCol]);

  // ---- selections out --------------------------------------------------------
  const publish = usePublishHighlight(index);
  const onHover = useCallback(
    (position: number | null) => {
      if (position == null) {
        publish(null);
        return;
      }
      publish({ entity: entity ?? undefined, start: position, positionColumn: positionCol });
    },
    [publish, entity, positionCol],
  );

  // A brush, a click on a residue and a click on a segment all pick a range.
  const onPick = useCallback(
    (range: ResidueRange | null) => {
      if (!onFilterChange) return;
      const pair = residueRangeFilters(index, {
        entityColumn: entityCol,
        positionColumn: positionCol,
        entity,
        start: range ? range.start : null,
        end: range ? (range.end ?? range.start) : null,
        dcId: metadata.dc_id,
      });
      for (const f of pair) onFilterChange(f);
    },
    [onFilterChange, index, entityCol, positionCol, entity, metadata.dc_id],
  );
  // Clicking the segment that is already picked clears the pick, as a residue click does.
  const onPickSegment = useCallback(
    (range: ResidueRange) => {
      const same =
        selectedRange != null &&
        selectedRange.start === range.start &&
        (selectedRange.end ?? selectedRange.start) === (range.end ?? range.start);
      onPick(same ? null : range);
    },
    [onPick, selectedRange],
  );

  // ---- legend ----------------------------------------------------------------
  const colours = useMemo(() => panelColours(theme, isDark), [theme, isDark]);
  // Colours the dashboard pins for the states: under the state column's own
  // name, and under `category`, the column of the S4PRED residue table that
  // spells the state out. Values are read as states, so Helix and H both count.
  const pinnedByState = usePinnedCategoryColors(stateCol);
  const pinnedByCategory = usePinnedCategoryColors('category');
  // User / tile colours over the config's, over the dashboard's pins; classes
  // nobody colours keep the tile's defaults.
  const stateColours = useMemo(
    () =>
      effectiveStateColours([pinnedByCategory, pinnedByState], config.state_colors, userColours),
    [pinnedByCategory, pinnedByState, config.state_colors, userColours],
  );
  const hasTurn = useMemo(
    () => model.sources.some((s) => s.states.includes('turn')),
    [model.sources],
  );
  const legend = useMemo(() => {
    const items: { label: string; colour: string }[] = [
      { label: 'Helix', colour: stateColours.helix ?? SS_GLYPH_FILLS.helix },
      { label: 'Strand', colour: stateColours.strand ?? SS_GLYPH_FILLS.strand },
    ];
    if (hasTurn) items.push({ label: 'Turn', colour: stateColours.turn ?? SS_GLYPH_FILLS.turn });
    items.push({ label: 'Coil', colour: stateColours.coil ?? rgbCss(colours.neutral) });
    if (showAgreement && agreement) {
      items.push({ label: 'Agree', colour: theme.colors.teal[isDark ? 4 : 6] });
      items.push({ label: 'Differ', colour: theme.colors.red[isDark ? 4 : 6] });
    }
    return items;
  }, [hasTurn, stateColours, colours.neutral, showAgreement, agreement, theme, isDark]);

  // ---- chrome ----------------------------------------------------------------
  const entityChoices = picker.entities && picker.entities.length > 1 ? picker.entities : null;
  const mainSource = model.sources[0]?.name ?? null;
  const primaryControls = useMemo(
    () =>
      entityChoices || sources > 1 ? (
        <>
          {entityChoices ? (
            <VizSelect
              label="Entity"
              value={entity}
              onChange={(v) => v && picker.setEntity(v)}
              data={entityChoices}
              searchable
              limit={200}
              allowDeselect={false}
            />
          ) : null}
          {sources > 1 ? (
            <VizSelect
              label="Reference"
              value={mainSource}
              onChange={(v) => v && setPickedReference(v)}
              data={model.names}
              allowDeselect={false}
            />
          ) : null}
        </>
      ) : null,
    [entityChoices, picker.setEntity, entity, sources, mainSource, model.names],
  );

  // One input per class the tile draws, showing the colour in effect.
  const colourClasses = useMemo(
    () =>
      legend.length
        ? SS_COLOUR_CLASSES.filter((c) => c.state !== 'turn' || hasTurn).map((c) => ({
            ...c,
            colour: legend.find((l) => l.label === c.label)?.colour ?? '',
          }))
        : [],
    [legend, hasTurn],
  );
  const swatches = useMemo(
    () =>
      ['red', 'pink', 'grape', 'violet', 'indigo', 'blue', 'cyan', 'teal', 'green', 'lime', 'yellow', 'orange']
        .map((hue) => theme.colors[hue]?.[6])
        .filter((c): c is string => Boolean(c)),
    [theme],
  );

  const controls = useMemo(
    () => (
      <>
        <VizControlGroup title="Display">
          <VizSlider
            label={<ZoomHintLabel>Residue width</ZoomHintLabel>}
            aria-label="Residue width"
            title="Ctrl/Cmd + wheel to zoom"
            value={zoom}
            onChange={setZoom}
            min={0}
            max={24}
            step={1}
            thumbLabel={(v) => (v === 0 ? 'Fit' : `${v} px`)}
          />
          <VizSlider
            label="Ribbon height"
            value={ribbonHeight ?? DEFAULT_RIBBON_PX}
            onChange={setRibbonHeight}
            min={16}
            max={64}
            step={2}
            thumbLabel={(v) => `${v} px`}
          />
          <VizSwitch
            label="Letters"
            checked={showLetters}
            onChange={(e) => setShowLetters(e.currentTarget.checked)}
            disabled={!residueCol || !hasLetters}
          />
          <VizSwitch
            label="Confidence shading"
            checked={shadeConfidence}
            onChange={(e) => setShadeConfidence(e.currentTarget.checked)}
            disabled={!hasConfidence}
          />
          {showSegments ? (
            <>
              <VizSwitch
                label="Coil segments"
                checked={coilSegments}
                onChange={(e) => setCoilSegments(e.currentTarget.checked)}
              />
              <VizSlider
                label="Min segment"
                value={minSegment}
                onChange={setMinSegment}
                min={1}
                max={50}
                step={1}
                thumbLabel={(v) => `${v} aa`}
              />
            </>
          ) : null}
        </VizControlGroup>
        <VizControlGroup title="Colours">
          {colourClasses.map(({ key, label, state, colour }) => (
            <StateColourInput
              key={key}
              label={label}
              colour={colour}
              swatches={swatches}
              onCommit={(c) => setUserColours(withStateColour(userColours, state, c))}
            />
          ))}
          <VizControlCell>
            <Button
              size="compact-xs"
              variant="subtle"
              disabled={!Object.keys(userColours).length}
              onClick={() => setUserColours({})}
            >
              Reset colours
            </Button>
          </VizControlCell>
        </VizControlGroup>
      </>
    ),
    [
      zoom,
      ribbonHeight,
      colourClasses,
      swatches,
      userColours,
      showLetters,
      residueCol,
      hasLetters,
      shadeConfidence,
      hasConfidence,
      showSegments,
      coilSegments,
      minSegment,
    ],
  );

  const echo = useMemo(() => {
    if (!model.positions.length) return undefined;
    const parts = [entity, `${model.positions.length} residues`];
    if (sources > 1) parts.push(`${sources} sources`);
    if (selectedRange) {
      parts.push(`residues ${selectedRange.start}-${selectedRange.end ?? selectedRange.start}`);
    }
    return parts.filter(Boolean).join(' · ');
  }, [entity, model.positions.length, sources, selectedRange]);

  const badges = useMemo(() => {
    const list = compositionBadges(model, agreement, {
      composition: showComposition,
      agreement: showAgreement,
    });
    return list.length ? list : undefined;
  }, [model, agreement, showComposition, showAgreement]);

  const agreementShown = showAgreement && agreement != null;
  const probabilitiesShown = showProbabilities && hasProbabilities;
  const naturalPx = useMemo(
    () =>
      naturalPanelHeight({
        ribbonHeight,
        // Letters only get a lane once the cells are wide enough to read.
        letters: showLetters && hasLetters && zoom >= MIN_LETTER_PX,
        extraSources: Math.max(0, sources - 1),
        agreement: agreementShown,
        probabilities: probabilitiesShown,
      }) +
      LEGEND_PX +
      (showSegments ? SEGMENT_LIST_MAX_PX : 0),
    [ribbonHeight, showLetters, hasLetters, zoom, sources, agreementShown, probabilitiesShown, showSegments],
  );
  const contentDemand = useMemo(() => demandForPx(naturalPx + CHROME_PX), [naturalPx]);
  const onDrawn = useCallback(() => setDrawn(true), []);

  const noProteins = picker.entities !== null && picker.entities.length === 0 && !picker.failed;
  const emptyMessage = loading || error
    ? undefined
    : noProteins
      ? 'No protein in this collection'
      : model.positions.length === 0
        ? 'No residues for this entity'
        : !model.hasStates
          ? `No secondary-structure state in column "${stateCol}"`
          : undefined;
  const empty = model.positions.length === 0 || !model.hasStates;

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Secondary structure'}
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
      {!empty ? (
        <Box
          className="depictio-secondary-structure"
          data-secondary-structure-ready={drawn ? 'true' : undefined}
          style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', minHeight: 0 }}
        >
          {/* Absolutely filled so the panel gets a definite height to spread
              its lanes over, whatever the flex engine makes of percentages. */}
          <Box style={{ flex: '1 1 auto', minHeight: 60, position: 'relative' }}>
            <Box style={{ position: 'absolute', inset: 0 }}>
              <SecondaryStructurePanel
                model={model}
                agreement={agreement}
                showProbabilities={showProbabilities}
                showAgreement={showAgreement}
                showLetters={showLetters}
                shadeConfidence={shadeConfidence}
                ribbonHeight={ribbonHeight}
                stateColours={stateColours}
                selectedRange={selectedRange}
                highlight={highlight}
                onHover={onHover}
                onBrush={brushEnabled ? onPick : undefined}
                height="100%"
                cellWidth={zoom > 0 ? zoom : undefined}
                onCellWidthChange={setZoom}
                followSelection={follow}
                onDrawn={onDrawn}
              />
            </Box>
          </Box>
          <Group gap="sm" px={4} pt={4} wrap="wrap" style={{ flex: '0 0 auto' }}>
            {legend.map((item) => (
              <Group key={item.label} gap={4} wrap="nowrap">
                <ColorSwatch color={item.colour} size={10} withShadow={false} />
                <Text size="xs" c="dimmed">
                  {item.label}
                </Text>
              </Group>
            ))}
            {hasConfidence && shadeConfidence ? (
              <Text size="xs" c="dimmed">
                Lighter = less confident
              </Text>
            ) : null}
          </Group>
          {showSegments ? (
            <Box pt={4} style={{ flex: '0 0 auto' }}>
              <SegmentList
                segments={segments}
                selectedRange={selectedRange}
                onPick={brushEnabled ? onPickSegment : undefined}
                stateColours={stateColours}
              />
            </Box>
          ) : null}
        </Box>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default SecondaryStructureRenderer;
