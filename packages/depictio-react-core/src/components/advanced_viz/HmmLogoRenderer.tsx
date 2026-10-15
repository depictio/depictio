import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Box, Button, Text } from '@mantine/core';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { usePublishHighlight, useHighlight } from '../../highlight/bus';
import {
  filtersExcludingOwnResidue,
  isResidueFilter,
  residueEntityFromFilters,
  residueRangeFilters,
  residueRangeFromFilters,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import { demandForPx } from './contentDemand';
import {
  VizControlCell,
  VizControlGroup,
  VizMultiSelect,
  VizNumberInput,
  VizSegmented,
  VizSelect,
  VizSlider,
  VizSwitch,
} from './controls/VizControls';
import { addHidden, expandStub, type HiddenRange, type StubSegment } from './logo/collapse';
import type { HeightMode } from './logo/heights';
import { coverageDepth, formatEvalue, hitsFromFrame, selectHits, type LogoHit } from './logo/hitsModel';
import { layoutLanes } from './logo/layout';
import LogoPanel, { type LogoHover } from './logo/LogoPanel';
import { profileFromMsa, profileFromRows, residueRangeOfStates, stateSpanOfRange } from './logo/profileModel';
import { cleanTracks, TRACK_KEYS, TRACK_LABELS, type TrackKey } from './logo/tracks';
import type { MsaColourScheme, MsaRow, ResidueRange } from './protein';
import {
  distinctColumns,
  entitiesByRowCount,
  entityScopeFilter,
  firstValueOf,
  frameLength,
  hasOwnResiduePick,
  numberOrNull,
  rowIndicesWhere,
  scopeToEntity,
  stringOrNull,
  withoutFiltersOn,
  withoutPositionSelections,
} from './protein/rendererData';
import { useEntityPicker } from './protein/useEntityPicker';
import ZoomHintLabel from './protein/ZoomHint';
import { usePersistedVizControl, useVizConfigWriter } from './usePersistedVizControl';

/**
 * Mirrors `HmmLogoConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys a renderer reads).
 */
interface HmmLogoConfig {
  profile_source?: 'hmm' | 'msa';
  entity_col?: string;
  position_col?: string;
  model_col?: string;
  state_col?: string;
  letter_col?: string;
  emission_col?: string;
  insert_prob_col?: string | null;
  insert_length_col?: string | null;
  occupancy_col?: string | null;
  consensus_col?: string | null;
  rf_col?: string | null;
  cs_col?: string | null;
  msa_id_col?: string;
  seq_id_col?: string;
  sequence_col?: string;
  rank_col?: string | null;
  height_mode?: HeightMode;
  color_scheme?: MsaColourScheme;
  show_indel_rows?: boolean;
  show_consensus?: boolean;
  window_start?: number | null;
  window_end?: number | null;
  collapse_below_ic?: number | null;
  collapse_min_run?: number;
  hidden_tracks?: TrackKey[];
  collapsed_tracks?: TrackKey[];
  hits_wf_id?: string | null;
  hits_dc_id?: string | null;
  hits_dc_tag?: string | null;
  hits_model_col?: string;
  hits_entity_col?: string;
  hits_from_col?: string;
  hits_to_col?: string;
  hits_length_col?: string | null;
  hits_evalue_col?: string | null;
  hits_score_col?: string | null;
  hits_ali_from_col?: string | null;
  hits_ali_to_col?: string | null;
  hits_evalue_max?: number | null;
  max_hits?: number;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: HmmLogoConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no residue pick. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

type Frame = Record<string, unknown[]>;

/** Tile furniture around the panel: frame header, echo. */
const CHROME_PX = 90;
const DEFAULT_EVALUE_MAX = 0.01;

const HEIGHT_MODES: { value: HeightMode; label: string }[] = [
  { value: 'relent_abovebg', label: 'Above background (bits)' },
  { value: 'relent_all', label: 'All letters (bits)' },
  { value: 'probability', label: 'Probability' },
];

const SCHEMES: { value: MsaColourScheme; label: string }[] = [
  { value: 'clustal', label: 'Clustal X' },
  { value: 'zappo', label: 'Zappo' },
  { value: 'hydrophobicity', label: 'Hydrophobicity' },
  { value: 'identity', label: 'Percent identity' },
  { value: 'none', label: 'None' },
];

const EVALUE_PRESETS = [1, 0.1, 0.01, 1e-3, 1e-5, 1e-10, 1e-20];

/**
 * A state-number box that commits on blur or Enter, not per keystroke: typing
 * "30" in the end box passes through "3", which would be clamped under the
 * start and persisted. An empty box is an open side of the window.
 */
const StateBoundInput: React.FC<{
  label: string;
  value: number | null;
  placeholder: string;
  min: number;
  max: number;
  onCommit: (next: number | null) => void;
}> = ({ label, value, placeholder, min, max, onCommit }) => {
  const [draft, setDraft] = useState<number | string>(value ?? '');
  useEffect(() => setDraft(value ?? ''), [value]);
  const commit = () => {
    const n = typeof draft === 'number' ? Math.round(draft) : NaN;
    const next = Number.isFinite(n) ? Math.max(min, Math.min(max, n)) : null;
    setDraft(next ?? '');
    if (next !== value) onCommit(next);
  };
  return (
    <VizNumberInput
      label={label}
      value={draft}
      placeholder={placeholder}
      onChange={setDraft}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit();
      }}
      min={min}
      max={max}
      allowDecimal={false}
      hideControls
    />
  );
};

/** A config column that may be switched off with `null` (undefined keeps the default). */
const optionalColumn = (value: string | null | undefined, fallback: string): string | null =>
  value === undefined ? fallback : value || null;

/** Fetch rows, never throwing; `columns` empty or a missing id skips the fetch. */
function useRows(
  wfId: string | null | undefined,
  dcId: string | null | undefined,
  columns: string[],
  filters: InteractiveFilter[] | null,
  refreshTick: number | undefined,
): { rows: Frame | null; loading: boolean; error: string | null } {
  const [rows, setRows] = useState<Frame | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const filtersKey = filters ? JSON.stringify(filters) : null;
  useEffect(() => {
    if (!wfId || !dcId || !columns.length || filtersKey === null) {
      setRows(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData({
      wfId,
      dcId,
      columns,
      filters: JSON.parse(filtersKey) as InteractiveFilter[],
      vizKind: 'hmm_logo',
    })
      .then((res) => {
        if (!cancelled) setRows(res.rows ?? {});
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setRows(null);
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [wfId, dcId, JSON.stringify(columns), filtersKey, refreshTick]);
  return { rows, loading, error };
}

/**
 * The model whose reference is `entity` (hmm mode): when another tile names
 * one protein, the logo moves to a model mapped onto it. Reads the model
 * column alone, scoped to that entity; the model with the most rows (the
 * longest) wins. Null when no model of the table maps onto it.
 */
function useModelOfEntity(
  wfId: string | null | undefined,
  dcId: string | null | undefined,
  index: string,
  modelCol: string,
  entityCol: string,
  entity: string | null,
  refreshTick: number | undefined,
): string | null {
  const [model, setModel] = useState<string | null>(null);
  useEffect(() => {
    if (!wfId || !dcId || !entity) {
      setModel(null);
      return;
    }
    let cancelled = false;
    fetchAdvancedVizData({
      wfId,
      dcId,
      columns: [modelCol],
      filters: [entityScopeFilter(index, dcId, entityCol, entity)],
      vizKind: 'hmm_logo',
    })
      .then((res) => {
        if (!cancelled) setModel(entitiesByRowCount(res.rows?.[modelCol] ?? [])[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) setModel(null);
      });
    return () => {
      cancelled = true;
    };
  }, [wfId, dcId, index, modelCol, entityCol, entity, refreshTick]);
  return model;
}

/**
 * `hmm_logo`: the HMM logo of one profile HMM (Skylign / HMMER `hmmlogo`
 * semantics) on the canvas `LogoPanel`: letter stacks whose height is the
 * state's information, consensus / RF / CS rows, insert and occupancy lanes,
 * and, with a hits companion, where the hits of an hmmsearch land on the
 * model. One model at a time (picker; follows a model named elsewhere, such
 * as a domain click, or the protein a pick names when a model maps onto it).
 * A brush over states emits a `residue_selection` in the reference
 * sequence's numbering; a click on a hit bar picks the hit's aligned
 * residues on its own protein. The logo is never narrowed by residue picks:
 * its scope is the model, and it shades the picked range instead.
 */
const HmmLogoRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const config = (metadata.config || {}) as HmmLogoConfig;
  const index = String(metadata.index);
  const source: 'hmm' | 'msa' = config.profile_source === 'msa' ? 'msa' : 'hmm';
  const entityCol = config.entity_col || 'entity';
  const positionCol = config.position_col || 'position';
  const modelCol = config.model_col || 'hmm_name';
  const stateCol = config.state_col || 'hmm_position';
  const letterCol = config.letter_col || 'hmm_letter';
  const emissionCol = config.emission_col || 'emission';
  const insertProbCol = optionalColumn(config.insert_prob_col, 'insert_prob');
  const insertLengthCol = optionalColumn(config.insert_length_col, 'insert_length');
  const occupancyCol = optionalColumn(config.occupancy_col, 'occupancy');
  const consensusCol = optionalColumn(config.consensus_col, 'consensus');
  const rfCol = optionalColumn(config.rf_col, 'rf');
  const csCol = optionalColumn(config.cs_col, 'cs');
  const msaIdCol = config.msa_id_col || 'msa_id';
  const seqIdCol = config.seq_id_col || 'seq_id';
  const sequenceCol = config.sequence_col || 'aligned_sequence';
  const rankCol = optionalColumn(config.rank_col, 'rank');
  const hitsDcId = config.hits_dc_id || null;
  const hitsWfId = config.hits_wf_id || metadata.wf_id;
  const hitsModelCol = config.hits_model_col || 'label';
  const hitsEntityCol = config.hits_entity_col || 'entity';
  const hitsFromCol = config.hits_from_col || 'hmm_from';
  const hitsToCol = config.hits_to_col || 'hmm_to';
  const hitsLengthCol = optionalColumn(config.hits_length_col, 'hmm_length');
  const hitsEvalueCol = optionalColumn(config.hits_evalue_col, 'i_evalue');
  const hitsScoreCol = optionalColumn(config.hits_score_col, 'dom_score');
  const hitsAliFromCol = optionalColumn(config.hits_ali_from_col, 'ali_from');
  const hitsAliToCol = optionalColumn(config.hits_ali_to_col, 'ali_to');
  const follow = config.follow_selection !== false;
  const pickEnabled = Boolean(onFilterChange) && config.selection_enabled !== false;

  const [heightMode, setHeightMode] = usePersistedVizControl<HeightMode>(metadata, 'height_mode', 'relent_abovebg');
  const [colourScheme, setColourScheme] = usePersistedVizControl<MsaColourScheme>(metadata, 'color_scheme', 'clustal');
  const [showIndelRows, setShowIndelRows] = usePersistedVizControl<boolean>(metadata, 'show_indel_rows', true);
  const [showConsensus, setShowConsensus] = usePersistedVizControl<boolean>(metadata, 'show_consensus', true);
  const [maxHits, setMaxHits] = usePersistedVizControl<number>(metadata, 'max_hits', 200);
  // Parts of the profile left out of the drawing; null is open / off.
  const [windowStart, setWindowStart] = usePersistedVizControl<number | null>(metadata, 'window_start', null);
  const [windowEnd, setWindowEnd] = usePersistedVizControl<number | null>(metadata, 'window_end', null);
  const [collapseBelowIc, setCollapseBelowIc] = usePersistedVizControl<number | null>(metadata, 'collapse_below_ic', null);
  const [collapseMinRun, setCollapseMinRun] = usePersistedVizControl<number>(metadata, 'collapse_min_run', 4);
  // Tracks (lanes of the panel) taken out, or reduced to a thin strip.
  const [hiddenTracksRaw, setHiddenTracks] = usePersistedVizControl<TrackKey[]>(metadata, 'hidden_tracks', []);
  const [collapsedTracksRaw, setCollapsedTracks] = usePersistedVizControl<TrackKey[]>(
    metadata,
    'collapsed_tracks',
    [],
  );
  const hiddenTracks = useMemo(() => cleanTracks(hiddenTracksRaw), [hiddenTracksRaw]);
  const collapsedTracks = useMemo(() => cleanTracks(collapsedTracksRaw), [collapsedTracksRaw]);
  // Session only: ranges hidden by hand (column indices) and the folded runs the
  // user opened. Reset when the model, the window or the fold rule changes.
  const [hidden, setHidden] = useState<readonly HiddenRange[]>([]);
  const [expanded, setExpanded] = useState<readonly string[]>([]);
  // `null` is a real value here (draw every hit), which the persisted-control
  // hook would read as "unset": seeded by hand, written back on a pick.
  const writeConfig = useVizConfigWriter(metadata);
  const configuredEvalue = config.hits_evalue_max === undefined ? DEFAULT_EVALUE_MAX : config.hits_evalue_max;
  const [evalueMax, setEvalueMaxState] = useState<number | null>(configuredEvalue);
  useEffect(() => setEvalueMaxState(configuredEvalue), [configuredEvalue]);
  const setEvalueMax = useCallback(
    (next: number | null) => {
      setEvalueMaxState(next);
      writeConfig({ hits_evalue_max: next });
    },
    [writeConfig],
  );
  const [occupancyMode, setOccupancyMode] = useState<'occupancy' | 'delete'>('occupancy');
  // Px per state; 0 fits the model to the tile width.
  const [zoom, setZoom] = useState<number>(0);
  const [drawn, setDrawn] = useState(false);

  // ---- filters ---------------------------------------------------------------
  // Every filter but the tile's own pick; residue picks and selections on the
  // columns that say which protein or model is shown never narrow the logo:
  // its scope is the model, and it follows those names instead.
  const withoutOwn = useMemo(() => filtersExcludingOwnResidue(filters, index), [filters, index]);
  const fetchFilters = useMemo(
    () =>
      withoutPositionSelections(
        withoutOwn,
        source === 'msa'
          ? [positionCol, entityCol, msaIdCol, seqIdCol]
          : [positionCol, entityCol, modelCol, hitsModelCol, hitsEntityCol],
      ),
    [withoutOwn, source, positionCol, entityCol, msaIdCol, seqIdCol, modelCol, hitsModelCol, hitsEntityCol],
  );

  // ---- which model ------------------------------------------------------------
  const scopeCol = source === 'msa' ? msaIdCol : modelCol;
  const followedEntity = useMemo(() => residueEntityFromFilters(withoutOwn, entityCol), [withoutOwn, entityCol]);
  const followedName = useMemo(
    () =>
      source === 'msa'
        ? followedEntity ?? residueEntityFromFilters(withoutOwn, msaIdCol)
        : residueEntityFromFilters(withoutOwn, hitsModelCol) ?? residueEntityFromFilters(withoutOwn, modelCol),
    [source, followedEntity, withoutOwn, msaIdCol, hitsModelCol, modelCol],
  );
  // The profile's entity once loaded (set below), so a pick on the protein
  // already shown does not move the logo to another of its models.
  const [shownEntity, setShownEntity] = useState<string | null>(null);
  const modelOfEntity = useModelOfEntity(
    metadata.wf_id,
    metadata.dc_id,
    index,
    modelCol,
    entityCol,
    source === 'hmm' && !followedName && followedEntity && followedEntity !== shownEntity
      ? followedEntity
      : null,
    refreshTick,
  );
  const followed = followedName ?? (source === 'hmm' ? modelOfEntity : null);
  // An alignment is an entity like the msa tile's, so it agrees on the opening
  // one with the other protein tiles; a model is not (sharing model names under
  // the entity key would hold that key against the protein tiles). Both open on
  // the one still in scope: a sidebar family reaches this table through a link
  // the server applies, so the model list (unscoped) cannot tell which model
  // the dashboard narrowed to, and opening on its first would draw nothing.
  const picker = useEntityPicker(
    metadata.dc_id,
    scopeCol,
    followed,
    refreshTick,
    source === 'msa'
      ? { wfId: metadata.wf_id, vizKind: 'hmm_logo', filters: fetchFilters, shareKey: entityCol, owner: index }
      : { wfId: metadata.wf_id, vizKind: 'hmm_logo', filters: fetchFilters },
  );

  // ---- profile rows -------------------------------------------------------------
  const columns = useMemo(
    () =>
      source === 'msa'
        ? distinctColumns([msaIdCol, seqIdCol, sequenceCol, rankCol])
        : distinctColumns([
            entityCol,
            positionCol,
            modelCol,
            stateCol,
            letterCol,
            emissionCol,
            insertProbCol,
            insertLengthCol,
            occupancyCol,
            consensusCol,
            rfCol,
            csCol,
          ]),
    [
      source,
      msaIdCol,
      seqIdCol,
      sequenceCol,
      rankCol,
      entityCol,
      positionCol,
      modelCol,
      stateCol,
      letterCol,
      emissionCol,
      insertProbCol,
      insertLengthCol,
      occupancyCol,
      consensusCol,
      rfCol,
      csCol,
    ],
  );
  // Wait for the model list, then fetch the picked model. With no model to
  // pick (no model column: a one-model table, or the lookup failed) the fetch
  // goes out unscoped and the first model in it is shown.
  // The profile is the whole model: a filter on the position column, a sidebar
  // slider included, would drop states from it, so none reaches this fetch.
  const mainFilters = useMemo(
    () =>
      picker.entities === null
        ? null
        : scopeToEntity(
            withoutFiltersOn(fetchFilters, [positionCol]),
            index,
            metadata.dc_id,
            scopeCol,
            picker.entity,
          ),
    [picker.entities, picker.entity, fetchFilters, positionCol, index, metadata.dc_id, scopeCol],
  );
  const main = useRows(metadata.wf_id, metadata.dc_id, columns, mainFilters, refreshTick);
  const frame = main.rows;
  const modelName = useMemo(() => picker.entity ?? firstValueOf(frame, scopeCol), [picker.entity, frame, scopeCol]);

  const profile = useMemo(() => {
    if (!frame || frameLength(frame) === 0) return null;
    if (source === 'hmm') {
      return profileFromRows(
        frame,
        {
          entity: entityCol,
          position: positionCol,
          model: modelCol,
          state: stateCol,
          letter: letterCol,
          emission: emissionCol,
          insertProb: insertProbCol,
          insertLength: insertLengthCol,
          occupancy: occupancyCol,
          consensus: consensusCol,
          rf: rfCol,
          cs: csCol,
        },
        modelName,
      );
    }
    const ids = frame[seqIdCol] ?? [];
    const seqs = frame[sequenceCol] ?? [];
    const ranks = rankCol ? frame[rankCol] : undefined;
    const rows: MsaRow[] = [];
    for (const i of rowIndicesWhere(frame, msaIdCol, modelName)) {
      const sequence = stringOrNull(seqs[i]);
      if (!sequence) continue;
      rows.push({
        seqId: stringOrNull(ids[i]) ?? `row ${i + 1}`,
        sequence,
        rank: ranks ? numberOrNull(ranks[i]) : null,
      });
    }
    return profileFromMsa(rows, { entity: modelName });
  }, [
    frame,
    source,
    entityCol,
    positionCol,
    modelCol,
    stateCol,
    letterCol,
    emissionCol,
    insertProbCol,
    insertLengthCol,
    occupancyCol,
    consensusCol,
    rfCol,
    csCol,
    modelName,
    seqIdCol,
    sequenceCol,
    rankCol,
    msaIdCol,
  ]);
  const profileEntity = profile?.entity ?? null;
  useEffect(() => setShownEntity(profileEntity), [profileEntity]);
  useEffect(() => setDrawn(false), [modelName]);
  useEffect(() => setHidden([]), [modelName]);
  useEffect(() => setExpanded([]), [modelName, windowStart, windowEnd, collapseBelowIc, collapseMinRun]);
  const modelLength = profile && profile.states.length ? profile.states[profile.states.length - 1] : 0;

  // ---- hits companion -------------------------------------------------------------
  const hitsColumns = useMemo(
    () =>
      hitsDcId
        ? distinctColumns([
            hitsModelCol,
            hitsEntityCol,
            hitsFromCol,
            hitsToCol,
            hitsLengthCol,
            hitsEvalueCol,
            hitsScoreCol,
            hitsAliFromCol,
            hitsAliToCol,
          ])
        : [],
    [hitsDcId, hitsModelCol, hitsEntityCol, hitsFromCol, hitsToCol, hitsLengthCol, hitsEvalueCol, hitsScoreCol, hitsAliFromCol, hitsAliToCol],
  );
  // Hits keep their rows whatever residue is picked; scoped to the model.
  const hitsFilters = useMemo(() => {
    if (!hitsDcId || !modelName) return null;
    const kept = withoutOwn.filter((f) => !isResidueFilter(f));
    return scopeToEntity(kept, index, hitsDcId, hitsModelCol, modelName);
  }, [hitsDcId, modelName, withoutOwn, index, hitsModelCol]);
  const hitsFetch = useRows(hitsWfId, hitsDcId, hitsColumns, hitsFilters, refreshTick);
  const allHits = useMemo(
    () =>
      hitsFromFrame(
        hitsFetch.rows,
        {
          model: hitsModelCol,
          entity: hitsEntityCol,
          from: hitsFromCol,
          to: hitsToCol,
          length: hitsLengthCol,
          evalue: hitsEvalueCol,
          score: hitsScoreCol,
          aliFrom: hitsAliFromCol,
          aliTo: hitsAliToCol,
        },
        modelName,
      ),
    [hitsFetch.rows, hitsModelCol, hitsEntityCol, hitsFromCol, hitsToCol, hitsLengthCol, hitsEvalueCol, hitsScoreCol, hitsAliFromCol, hitsAliToCol, modelName],
  );
  const hitSelection = useMemo(
    () => selectHits(allHits, { evalueMax, maxHits: maxHits ?? 200 }),
    [allHits, evalueMax, maxHits],
  );
  const coverage = useMemo(
    () => (hitsDcId && modelLength > 0 ? coverageDepth(hitSelection.passing, modelLength) : null),
    [hitsDcId, modelLength, hitSelection.passing],
  );

  // ---- selections in ----------------------------------------------------------------
  const ownResidue = useMemo(() => hasOwnResiduePick(filters, index), [filters, index]);
  // A pick on a hit's protein, named on the hits' entity column.
  const pickedHitEntity = useMemo(
    () => (hitsDcId ? residueEntityFromFilters(filters, hitsEntityCol) : null),
    [hitsDcId, filters, hitsEntityCol],
  );
  const selectedRange = useMemo<ResidueRange | null>(() => {
    if (!follow && !ownResidue) return null;
    const r = residueRangeFromFilters(filters, entityCol, positionCol);
    if (!r) return null;
    const entity = r.entity ?? (hitsEntityCol !== entityCol ? pickedHitEntity : null);
    if (entity && profileEntity && entity !== profileEntity) return null;
    return { start: r.start, end: r.end };
  }, [follow, ownResidue, filters, entityCol, positionCol, hitsEntityCol, pickedHitEntity, profileEntity]);
  const hitRange = useMemo(
    () => (pickedHitEntity ? residueRangeFromFilters(filters, hitsEntityCol, positionCol) : null),
    [pickedHitEntity, filters, hitsEntityCol, positionCol],
  );
  const selectedHitKey = useMemo(() => {
    if (!hitRange || !pickedHitEntity) return null;
    const h = hitSelection.drawn.find(
      (x) => x.entity === pickedHitEntity && x.aliFrom === hitRange.start && (x.aliTo ?? x.aliFrom) === hitRange.end,
    );
    return h?.key ?? null;
  }, [hitRange, pickedHitEntity, hitSelection.drawn]);

  const incoming = useHighlight(index, follow);
  const highlight = useMemo(() => {
    if (!incoming) return null;
    if (incoming.positionColumn && incoming.positionColumn !== positionCol) return null;
    if (incoming.entity && profileEntity && incoming.entity !== profileEntity) return null;
    return { start: incoming.start, end: incoming.end };
  }, [incoming, positionCol, profileEntity]);
  const highlightHitEntity = hitsDcId ? (incoming?.entity ?? null) : null;

  // ---- selections out ----------------------------------------------------------------
  const emit = useCallback(
    (entityColumn: string, entity: string | null, range: { start: number; end: number } | null) => {
      if (!onFilterChange) return;
      const pair = residueRangeFilters(index, {
        entityColumn,
        positionColumn: positionCol,
        entity,
        start: range ? range.start : null,
        end: range ? range.end : null,
        dcId: metadata.dc_id,
      });
      for (const f of pair) onFilterChange(f);
    },
    [onFilterChange, index, positionCol, metadata.dc_id],
  );

  const onPickStates = useCallback(
    (a: number, b: number) => {
      if (!profile) return;
      const range = residueRangeOfStates(profile.positions, a, b);
      if (!range) return; // only reference deletions under the brush: nothing to name
      const same =
        ownResidue &&
        a === b &&
        selectedRange &&
        selectedRange.start === range.start &&
        (selectedRange.end ?? selectedRange.start) === range.end;
      emit(entityCol, profileEntity, same ? null : range);
    },
    [profile, ownResidue, selectedRange, emit, entityCol, profileEntity],
  );

  const onClickHit = useCallback(
    (hit: LogoHit) => {
      if (hit.aliFrom == null) return;
      const same = ownResidue && selectedHitKey === hit.key;
      emit(hitsEntityCol, hit.entity, same ? null : { start: hit.aliFrom, end: hit.aliTo ?? hit.aliFrom });
    },
    [ownResidue, selectedHitKey, emit, hitsEntityCol],
  );

  const onClear = useCallback(() => {
    if (ownResidue) emit(entityCol, null, null);
  }, [ownResidue, emit, entityCol]);

  const onExpandStub = useCallback(
    (stub: StubSegment) => {
      const next = expandStub({ hidden, expanded }, stub);
      setHidden(next.hidden);
      setExpanded(next.expanded);
    },
    [hidden, expanded],
  );
  // The states the shaded range covers, which "Hide selection" folds.
  const selectedStates = useMemo(
    () => (profile ? stateSpanOfRange(profile.positions, selectedRange) : null),
    [profile, selectedRange],
  );
  const hideSelection = useCallback(() => {
    if (selectedStates) setHidden((h) => addHidden(h, selectedStates));
  }, [selectedStates]);
  const showAll = useCallback(() => {
    setWindowStart(null);
    setWindowEnd(null);
    setCollapseBelowIc(null);
    setHidden([]);
    setExpanded([]);
  }, [setWindowStart, setWindowEnd, setCollapseBelowIc]);
  const folded = windowStart != null || windowEnd != null || collapseBelowIc != null || hidden.length > 0;

  const publish = usePublishHighlight(index);
  const onHover = useCallback(
    (h: LogoHover | null) => {
      if (!h || h.index == null || !profile) {
        publish(null);
        return;
      }
      if (h.hit) {
        if (h.hit.aliFrom == null) {
          publish(null);
          return;
        }
        publish({
          entity: h.hit.entity,
          start: h.hit.aliFrom,
          end: h.hit.aliTo ?? h.hit.aliFrom,
          positionColumn: positionCol,
        });
        return;
      }
      const pos = profile.positions[h.index];
      if (pos == null) {
        publish(null);
        return;
      }
      publish({ entity: profileEntity ?? undefined, start: pos, positionColumn: positionCol });
    },
    [publish, profile, profileEntity, positionCol],
  );

  // ---- tracks -------------------------------------------------------------------------
  // The tracks the panel can draw for this profile (a null column or a switched
  // off row set has no track to hide).
  const availableTracks = useMemo<TrackKey[]>(() => {
    if (!profile) return [];
    const present: Record<TrackKey, boolean> = {
      consensus: showConsensus && (profile.consensus != null || profile.rf != null || profile.cs != null),
      insert: showIndelRows && (profile.insertProb != null || profile.insertLength != null),
      occupancy: showIndelRows && profile.occupancy != null,
      hits: Boolean(hitsDcId),
      ruler: true,
    };
    return TRACK_KEYS.filter((t) => present[t]);
  }, [profile, showConsensus, showIndelRows, hitsDcId]);
  const shownTracks = useMemo(
    () => availableTracks.filter((t) => !hiddenTracks.includes(t)),
    [availableTracks, hiddenTracks],
  );
  const setShownTracks = useCallback(
    (values: string[]) => {
      const keep = hiddenTracks.filter((t) => !availableTracks.includes(t));
      const next = cleanTracks([...keep, ...availableTracks.filter((t) => !values.includes(t))]);
      setHiddenTracks(next);
      // The config refuses a track that is both hidden and collapsed.
      if (collapsedTracks.some((t) => next.includes(t))) {
        setCollapsedTracks(collapsedTracks.filter((t) => !next.includes(t)));
      }
    },
    [hiddenTracks, collapsedTracks, availableTracks, setHiddenTracks, setCollapsedTracks],
  );
  const onToggleTrack = useCallback(
    (track: TrackKey) => {
      setCollapsedTracks(
        collapsedTracks.includes(track) ? collapsedTracks.filter((t) => t !== track) : cleanTracks([...collapsedTracks, track]),
      );
    },
    [collapsedTracks, setCollapsedTracks],
  );
  const collapseAllTracks = useCallback(
    () => setCollapsedTracks(cleanTracks([...collapsedTracks, ...shownTracks])),
    [collapsedTracks, shownTracks, setCollapsedTracks],
  );
  const expandAllTracks = useCallback(() => setCollapsedTracks([]), [setCollapsedTracks]);
  const allCollapsed = shownTracks.every((t) => collapsedTracks.includes(t));

  // ---- chrome ----------------------------------------------------------------------
  const modelChoices = picker.entities && picker.entities.length > 1 ? picker.entities : null;
  const primaryControls = useMemo(
    () => (
      <>
        {modelChoices ? (
          <VizSelect
            label={source === 'msa' ? 'Alignment' : 'Model'}
            value={modelName}
            onChange={(v) => v && picker.setEntity(v)}
            data={modelChoices}
            searchable
            limit={200}
            allowDeselect={false}
          />
        ) : null}
        <VizSelect
          label="Heights"
          value={heightMode}
          onChange={(v) => v && setHeightMode(v as HeightMode)}
          data={HEIGHT_MODES}
          allowDeselect={false}
        />
        <VizSelect
          label="Colour scheme"
          value={colourScheme}
          onChange={(v) => v && setColourScheme(v as MsaColourScheme)}
          data={SCHEMES}
          allowDeselect={false}
        />
      </>
    ),
    [modelChoices, source, modelName, picker.setEntity, heightMode, setHeightMode, colourScheme, setColourScheme],
  );

  const evalueOptions = useMemo(() => {
    const values = new Set(EVALUE_PRESETS);
    if (evalueMax != null) values.add(evalueMax);
    return [
      { value: 'any', label: 'Any' },
      ...Array.from(values)
        .sort((a, b) => b - a)
        .map((v) => ({ value: String(v), label: `≤ ${formatEvalue(v)}` })),
    ];
  }, [evalueMax]);

  const controls = useMemo(
    () => (
      <>
        <VizControlGroup title="Display">
          <VizSlider
            label={<ZoomHintLabel>State width</ZoomHintLabel>}
            aria-label="State width"
            title="Ctrl/Cmd + wheel to zoom"
            value={zoom}
            onChange={setZoom}
            min={0}
            max={40}
            step={1}
            thumbLabel={(v) => (v === 0 ? 'Fit' : `${v} px`)}
          />
          <VizSwitch
            label="Consensus rows"
            checked={showConsensus}
            onChange={(e) => setShowConsensus(e.currentTarget.checked)}
          />
          <VizSwitch
            label="Insert and occupancy rows"
            checked={showIndelRows}
            onChange={(e) => setShowIndelRows(e.currentTarget.checked)}
          />
          {showIndelRows && profile?.occupancy ? (
            <VizSegmented
              label="Bars"
              value={occupancyMode}
              onChange={(v) => setOccupancyMode(v === 'delete' ? 'delete' : 'occupancy')}
              data={[
                { value: 'occupancy', label: 'Occupancy' },
                { value: 'delete', label: 'Deletion' },
              ]}
            />
          ) : null}
        </VizControlGroup>
        <VizControlGroup title="Tracks">
          <VizMultiSelect
            label="Shown tracks"
            aria-label="Shown tracks"
            value={shownTracks}
            onChange={setShownTracks}
            data={availableTracks.map((t) => ({ value: t, label: TRACK_LABELS[t] }))}
            placeholder={shownTracks.length ? undefined : 'Logo only'}
            clearable={false}
          />
          <VizControlCell>
            <Button
              size="xs"
              variant="light"
              onClick={collapseAllTracks}
              disabled={shownTracks.length === 0 || allCollapsed}
              title="Reduce every shown track to a thin strip; the logo takes the room"
            >
              Collapse all tracks
            </Button>
          </VizControlCell>
          <VizControlCell>
            <Button size="xs" variant="light" onClick={expandAllTracks} disabled={collapsedTracks.length === 0}>
              Expand all tracks
            </Button>
          </VizControlCell>
        </VizControlGroup>
        <VizControlGroup title="Hide parts">
          <StateBoundInput
            label="From state"
            value={windowStart}
            placeholder="1"
            min={1}
            max={Math.max(1, windowEnd ?? modelLength)}
            onCommit={setWindowStart}
          />
          <StateBoundInput
            label="To state"
            value={windowEnd}
            placeholder={modelLength ? String(modelLength) : ''}
            min={Math.max(1, windowStart ?? 1)}
            max={Math.max(1, modelLength)}
            onCommit={setWindowEnd}
          />
          <VizNumberInput
            label="Fold below (bits)"
            title="Fold runs of states whose information is under this many bits"
            value={collapseBelowIc ?? ''}
            placeholder="Off"
            onChange={(v) => setCollapseBelowIc(typeof v === 'number' && v >= 0 ? v : null)}
            min={0}
            step={0.1}
            decimalScale={2}
          />
          {collapseBelowIc != null ? (
            <VizNumberInput
              label="Shortest run"
              value={collapseMinRun}
              onChange={(v) => typeof v === 'number' && setCollapseMinRun(Math.max(1, Math.round(v)))}
              min={1}
              allowDecimal={false}
            />
          ) : null}
          <VizControlCell>
            <Button
              size="xs"
              variant="light"
              onClick={hideSelection}
              disabled={!selectedStates}
              title="Fold the shaded states into a stub; click a stub to open it"
            >
              Hide selection
            </Button>
          </VizControlCell>
          <VizControlCell>
            <Button size="xs" variant="light" onClick={() => setExpanded([])} disabled={expanded.length === 0}>
              Fold opened runs again
            </Button>
          </VizControlCell>
          <VizControlCell>
            <Button size="xs" variant="light" onClick={showAll} disabled={!folded}>
              Show all
            </Button>
          </VizControlCell>
        </VizControlGroup>
        {hitsDcId ? (
          <VizControlGroup title="Hits">
            <VizSelect
              label="E-value"
              value={evalueMax == null ? 'any' : String(evalueMax)}
              onChange={(v) => setEvalueMax(!v || v === 'any' ? null : Number(v))}
              data={evalueOptions}
              allowDeselect={false}
            />
            <VizNumberInput
              label="Max hits"
              value={maxHits}
              onChange={(v) => setMaxHits(Math.max(1, Math.min(2000, Math.round(Number(v)) || 200)))}
              min={1}
              max={2000}
            />
          </VizControlGroup>
        ) : null}
      </>
    ),
    [
      zoom,
      showConsensus,
      setShowConsensus,
      showIndelRows,
      setShowIndelRows,
      profile?.occupancy,
      shownTracks,
      setShownTracks,
      availableTracks,
      collapseAllTracks,
      allCollapsed,
      expandAllTracks,
      collapsedTracks.length,
      occupancyMode,
      hitsDcId,
      evalueMax,
      setEvalueMax,
      evalueOptions,
      maxHits,
      setMaxHits,
      windowStart,
      setWindowStart,
      windowEnd,
      setWindowEnd,
      modelLength,
      collapseBelowIc,
      setCollapseBelowIc,
      collapseMinRun,
      setCollapseMinRun,
      selectedStates,
      hideSelection,
      expanded.length,
      showAll,
      folded,
    ],
  );

  const echo = useMemo(() => {
    if (!profile) return undefined;
    const parts: (string | null)[] = [
      profile.model,
      `${profile.states.length} states`,
      profile.entity && profile.entity !== profile.model ? `reference ${profile.entity}` : null,
      profile.sequences != null ? `${profile.sequences} sequences` : null,
    ];
    if (hitsDcId && hitsFetch.rows) {
      const { passing, drawn: shown } = hitSelection;
      parts.push(
        passing.length > shown.length ? `${passing.length} hits (${shown.length} drawn)` : `${passing.length} hits`,
      );
    }
    if (selectedRange) {
      parts.push(`residues ${selectedRange.start}-${selectedRange.end ?? selectedRange.start}`);
    }
    return parts.filter(Boolean).join(' · ');
  }, [profile, hitsDcId, hitsFetch.rows, hitSelection, selectedRange]);

  const badges = useMemo(
    () =>
      hitsFetch.error
        ? [
            <Text key="hits" size="xs" c="orange" title={hitsFetch.error}>
              Hits unavailable
            </Text>,
          ]
        : undefined,
    [hitsFetch.error],
  );

  const contentDemand = useMemo(() => {
    if (!profile) return undefined;
    const natural = layoutLanes(0, {
      consensus: showConsensus && profile.consensus != null,
      rf: showConsensus && profile.rf != null,
      cs: showConsensus && profile.cs != null,
      insertProb: showIndelRows && profile.insertProb != null,
      insertLength: showIndelRows && profile.insertLength != null,
      occupancy: showIndelRows && profile.occupancy != null,
      hits: Boolean(hitsDcId),
      hitRows: Math.min(hitSelection.drawn.length, 16),
      hiddenTracks,
      collapsedTracks,
    }).natural;
    return demandForPx(natural + CHROME_PX);
  }, [profile, showConsensus, showIndelRows, hitsDcId, hitSelection.drawn.length, hiddenTracks, collapsedTracks]);

  const onDrawn = useCallback(() => setDrawn(true), []);

  const bound = Boolean(metadata.wf_id && metadata.dc_id);
  // A fetch about to start counts as loading, so no empty state flashes first.
  const loading =
    bound && (picker.entities === null || main.loading || (main.rows === null && main.error === null));
  const error = bound ? main.error : 'HMM logo: missing data binding';
  let emptyMessage: string | undefined;
  if (!loading && !error && !profile) {
    if (frameLength(frame) === 0) {
      emptyMessage = source === 'msa' ? 'No aligned sequences in this table' : 'No profile rows in this table';
    } else if (source === 'msa') {
      emptyMessage = 'No aligned sequences for this alignment, or its reference row is all gaps';
    } else {
      emptyMessage = `No profile rows for this model (columns ${stateCol}, ${letterCol} and ${emissionCol} are needed)`;
    }
  }

  return (
    <AdvancedVizFrame
      title={metadata.title || 'HMM logo'}
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
      {profile ? (
        <Box
          className="depictio-hmm-logo"
          data-hmm-logo-ready={drawn ? 'true' : undefined}
          style={{ width: '100%', height: '100%', minHeight: 0 }}
        >
          <LogoPanel
            profile={profile}
            heightMode={heightMode}
            colourScheme={colourScheme}
            showConsensus={showConsensus}
            showIndelRows={showIndelRows}
            occupancyMode={occupancyMode}
            hits={hitsDcId ? hitSelection.drawn : null}
            coverage={coverage}
            coverageCount={hitSelection.passing.length}
            modelLength={modelLength}
            selectedHitEntity={pickedHitEntity}
            selectedHitKey={selectedHitKey}
            highlightHitEntity={highlightHitEntity}
            selectedRange={selectedRange}
            highlight={highlight}
            onHover={onHover}
            onPickStates={pickEnabled ? onPickStates : undefined}
            onClickHit={pickEnabled ? onClickHit : undefined}
            onClear={pickEnabled ? onClear : undefined}
            cellWidth={zoom > 0 ? zoom : undefined}
            onCellWidthChange={setZoom}
            followSelection={follow}
            onDrawn={onDrawn}
            windowStart={windowStart}
            windowEnd={windowEnd}
            collapseBelowIc={collapseBelowIc}
            collapseMinRun={collapseMinRun}
            hidden={hidden}
            expanded={expanded}
            onExpandStub={onExpandStub}
            hiddenTracks={hiddenTracks}
            collapsedTracks={collapsedTracks}
            onToggleTrack={onToggleTrack}
          />
        </Box>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default HmmLogoRenderer;
