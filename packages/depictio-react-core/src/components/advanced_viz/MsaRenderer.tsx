import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Badge, Box } from '@mantine/core';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { usePublishHighlight, useHighlight } from '../../highlight/bus';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  filtersExcludingOwn,
  filtersExcludingOwnResidue,
  residueEntityFromFilters,
  residueRangeFilters,
  residueRangeFromFilters,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import { demandForItems } from './contentDemand';
import {
  VizControlGroup,
  VizNumberInput,
  VizSelect,
  VizSlider,
  VizSwitch,
} from './controls/VizControls';
import {
  MsaPanel,
  type ChainSegment,
  type MsaColourScheme,
  type MsaHover,
  type MsaRow,
  type ResidueRange,
} from './protein';
import {
  chainRangeToConcat,
  concatRangeToChain,
  normaliseRows,
  orderMsaRows,
  parseChainLayout,
  type MsaSort,
} from './protein/alignment';
import {
  chainSelectionFilter,
  distinctColumns,
  firstValueOf,
  foreignValuesOn,
  frameLength,
  hasOwnResiduePick,
  numberOrNull,
  ownSelectionValues,
  rowIndicesWhere,
  scopeToEntity,
  stringOrNull,
  withoutPositionSelections,
} from './protein/rendererData';
import { useEntityPicker } from './protein/useEntityPicker';
import { usePersistedVizControl } from './usePersistedVizControl';

/**
 * Mirrors `MsaConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys read here).
 */
interface MsaConfig {
  msa_id_col?: string;
  seq_id_col?: string;
  sequence_col?: string;
  rank_col?: string | null;
  identity_col?: string | null;
  color_scheme?: MsaColourScheme;
  max_rows?: number;
  sort_by?: MsaSort;
  show_consensus?: boolean;
  show_conservation?: boolean;
  entity_col_for_selection?: string;
  position_col_for_selection?: string;
  chains_col?: string | null;
  chain_col_for_selection?: string | null;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: MsaConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/** Canonical MSA column with no config role (contract section 1), read by name. */
const COVERAGE_COLUMN = 'coverage';
const ROW_PX = 14;
const HEADER_PX = 90;

const SCHEMES: { value: MsaColourScheme; label: string }[] = [
  { value: 'clustal', label: 'Clustal X' },
  { value: 'zappo', label: 'Zappo' },
  { value: 'hydrophobicity', label: 'Hydrophobicity' },
  { value: 'identity', label: 'Percent identity' },
  { value: 'none', label: 'None' },
];

/**
 * `msa`: one alignment (one `msa_id`) at a time on the protein panel library's
 * `MsaPanel`. The alignment follows the entity another protein tile or a
 * sidebar selector names; a column brush emits a `residue_selection` in the
 * reference row's numbering (so the structure and the sequence track of the
 * same entity move with it) and a row click a `scatter_selection` on the
 * sequence id. Incoming residue ranges shade the columns, the hover bus draws
 * a crosshair, and its own selection rings rather than hides.
 */
const MsaRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const config = (metadata.config || {}) as MsaConfig;
  const index = String(metadata.index);
  const msaIdCol = config.msa_id_col || 'msa_id';
  const seqIdCol = config.seq_id_col || 'seq_id';
  const sequenceCol = config.sequence_col || 'aligned_sequence';
  const rankCol = config.rank_col === undefined ? 'rank' : config.rank_col;
  const identityCol = config.identity_col === undefined ? 'identity' : config.identity_col;
  const entityCol = config.entity_col_for_selection || 'entity';
  const positionCol = config.position_col_for_selection || 'position';
  // Chain layout of a complex's reference row (`A:1-664,B:665-1004`, see
  // `parseChainLayout`). The reference of a complex is its chains
  // concatenated while residue tables number each chain on its own, so with
  // a layout the brush is translated to one chain's own numbering and names
  // that chain on `chainCol`.
  const chainsCol = config.chains_col === undefined ? 'chains' : config.chains_col;
  const chainCol = config.chain_col_for_selection === undefined ? 'chain' : config.chain_col_for_selection;
  const follow = config.follow_selection !== false;
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const brushEnabled = Boolean(onFilterChange) && config.selection_enabled !== false;

  const [colourScheme, setColourScheme] = usePersistedVizControl<MsaColourScheme>(metadata, 'color_scheme', 'clustal');
  const [sortBy, setSortBy] = usePersistedVizControl<MsaSort>(metadata, 'sort_by', 'rank');
  const [maxRows, setMaxRows] = usePersistedVizControl<number>(metadata, 'max_rows', 200);
  const [showConsensus, setShowConsensus] = usePersistedVizControl<boolean>(metadata, 'show_consensus', true);
  const [showConservation, setShowConservation] = usePersistedVizControl<boolean>(metadata, 'show_conservation', true);
  // Pixels per column; 0 fits the alignment to the tile width.
  const [zoom, setZoom] = useState<number>(0);
  const [drawn, setDrawn] = useState(false);

  // Everything but this tile's own picks: it keeps drawing every row and
  // column and rings what it selected.
  const withoutOwn = useMemo(
    () => filtersExcludingOwnResidue(filtersExcludingOwn(filters, index, 'scatter_selection'), index),
    [filters, index],
  );
  const fetchFilters = useMemo(
    () => withoutPositionSelections(withoutOwn, [positionCol]),
    [withoutOwn, positionCol],
  );

  // The alignment on screen: the reader's pick, or the entity the dashboard names.
  const followed = useMemo(
    () =>
      residueEntityFromFilters(withoutOwn, entityCol) ??
      residueEntityFromFilters(withoutOwn, msaIdCol),
    [withoutOwn, entityCol, msaIdCol],
  );
  const picker = useEntityPicker(metadata.dc_id, msaIdCol, followed, refreshTick, {
    wfId: metadata.wf_id,
    vizKind: 'msa',
    filters: fetchFilters,
    shareKey: entityCol,
    owner: index,
  });

  const [frame, setFrame] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const columns = useMemo(
    () => distinctColumns([msaIdCol, seqIdCol, sequenceCol, rankCol, identityCol, COVERAGE_COLUMN, chainsCol]),
    [msaIdCol, seqIdCol, sequenceCol, rankCol, identityCol, chainsCol],
  );

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Sequence alignment: missing data binding');
      setLoading(false);
      return;
    }
    // Wait for the alignment list, unless it failed (then fetch unscoped).
    if (picker.entities === null) return;
    if (!picker.entity && !picker.failed) {
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
      filters: scopeToEntity(fetchFilters, index, metadata.dc_id, msaIdCol, picker.entity),
      vizKind: 'msa',
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
    index,
    msaIdCol,
    JSON.stringify(columns),
    JSON.stringify(fetchFilters),
    picker.entity,
    picker.entities,
    picker.failed,
    refreshTick,
  ]);

  // The alignment id actually drawn (the first one in the frame when the
  // distinct-values lookup failed and the fetch went out unscoped).
  const msaId = useMemo(
    () => picker.entity ?? firstValueOf(frame, msaIdCol),
    [picker.entity, frame, msaIdCol],
  );

  const { rows, width, ragged, total, chains } = useMemo(() => {
    if (!frame || frameLength(frame) === 0) {
      return { rows: [] as MsaRow[], width: 0, ragged: false, total: 0, chains: null };
    }
    const layouts = chainsCol ? frame[chainsCol] : undefined;
    let chains: ChainSegment[] | null = null;
    const ids = frame[seqIdCol] ?? [];
    const seqs = frame[sequenceCol] ?? [];
    const ranks = rankCol ? frame[rankCol] : undefined;
    const idents = identityCol ? frame[identityCol] : undefined;
    const covs = frame[COVERAGE_COLUMN];
    const raw: MsaRow[] = [];
    for (const i of rowIndicesWhere(frame, msaIdCol, msaId)) {
      const sequence = stringOrNull(seqs[i]);
      if (!sequence) continue;
      if (!chains && layouts) chains = parseChainLayout(stringOrNull(layouts[i]));
      raw.push({
        seqId: stringOrNull(ids[i]) ?? `row ${i + 1}`,
        sequence,
        rank: ranks ? numberOrNull(ranks[i]) : null,
        identity: idents ? numberOrNull(idents[i]) : null,
        coverage: covs ? numberOrNull(covs[i]) : null,
      });
    }
    const norm = normaliseRows(raw);
    const ordered = orderMsaRows(norm.rows, sortBy, maxRows);
    return {
      rows: ordered.rows,
      width: norm.width,
      ragged: norm.ragged,
      total: ordered.total,
      // One chain is the single-chain case: nothing to translate.
      chains: chains && chains.length > 1 ? chains : null,
    };
  }, [frame, msaIdCol, msaId, seqIdCol, sequenceCol, rankCol, identityCol, chainsCol, sortBy, maxRows]);

  useEffect(() => setDrawn(false), [msaId]);

  // ---- selections in -----------------------------------------------------
  const ownResidue = useMemo(() => hasOwnResiduePick(filters, index), [filters, index]);
  const selectedRange = useMemo<ResidueRange | null>(() => {
    if (!follow && !ownResidue) return null;
    const r = residueRangeFromFilters(filters, entityCol, positionCol);
    if (!r || (r.entity && msaId && r.entity !== msaId)) return null;
    if (!chains) return { start: r.start, end: r.end };
    // A complex: the range is in one chain's own numbering.
    const chain = residueEntityFromFilters(filters, chainCol);
    return chainRangeToConcat(chain, { start: r.start, end: r.end }, chains);
  }, [filters, entityCol, positionCol, chainCol, follow, ownResidue, msaId, chains]);

  const ownRows = useMemo(() => ownSelectionValues(filters, index), [filters, index]);
  const selectedRowKeys = useMemo(
    () =>
      Array.from(
        new Set([...ownRows, ...(follow ? foreignValuesOn(filters, index, seqIdCol) : [])]),
      ),
    [ownRows, follow, filters, index, seqIdCol],
  );

  const incoming = useHighlight(index, follow);
  const highlight = useMemo(() => {
    if (!incoming || (incoming.entity && msaId && incoming.entity !== msaId)) return null;
    // An event on another position column is on another axis entirely.
    if (incoming.positionColumn && incoming.positionColumn !== positionCol) return null;
    if (!chains) return { start: incoming.start, end: incoming.end, rowKeys: incoming.rowKeys };
    // The event's chain when the source knows it, else the first chain whose
    // numbering holds the residue.
    const named = incoming.chain && chains.some((c) => c.chain === incoming.chain);
    const span = chainRangeToConcat(
      named ? incoming.chain : null,
      { start: incoming.start, end: incoming.end },
      chains,
    );
    return span ? { ...span, rowKeys: incoming.rowKeys } : null;
  }, [incoming, msaId, positionCol, chains]);

  // ---- selections out ----------------------------------------------------
  const publish = usePublishHighlight(index);
  const onHoverColumn = useCallback(
    (h: MsaHover | null) => {
      if (!h || h.residue == null) {
        publish(null);
        return;
      }
      publish({
        entity: msaId ?? undefined,
        // Residue tables number a complex per chain.
        start: chains && h.chainPosition != null ? h.chainPosition : h.residue,
        chain: chains && h.chain ? h.chain : undefined,
        rowKeys: h.seqId ? [h.seqId] : undefined,
        positionColumn: positionCol,
      });
    },
    [publish, msaId, positionCol, chains],
  );

  const onBrushColumns = useCallback(
    (range: ResidueRange | null) => {
      if (!onFilterChange) return;
      // On a complex the brush lands in one chain's own numbering.
      const local = range && chains ? concatRangeToChain(range, chains) : null;
      const target = chains ? local : range;
      const pair = residueRangeFilters(index, {
        entityColumn: entityCol,
        positionColumn: positionCol,
        entity: msaId,
        start: target ? target.start : null,
        end: target ? (target.end ?? target.start) : null,
        dcId: metadata.dc_id,
      });
      for (const f of pair) onFilterChange(f);
      if (chains && chainCol) {
        onFilterChange(chainSelectionFilter(index, metadata.dc_id, chainCol, local?.chain ?? null));
      }
    },
    [onFilterChange, index, entityCol, positionCol, chainCol, msaId, metadata.dc_id, chains],
  );

  const onClickRow = useCallback(
    (seqId: string, mods: { shiftKey: boolean; metaKey: boolean }) => {
      if (!onFilterChange || !selectionColumn) return;
      let next: string[];
      if (mods.shiftKey || mods.metaKey) {
        next = ownRows.includes(seqId) ? ownRows.filter((v) => v !== seqId) : [...ownRows, seqId];
      } else {
        next = ownRows.length === 1 && ownRows[0] === seqId ? [] : [seqId];
      }
      onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, next));
    },
    [onFilterChange, selectionColumn, ownRows, metadata],
  );

  // ---- chrome ------------------------------------------------------------
  // Encoding tier: which alignment, how residues are coloured, how rows are
  // ordered. Everything else is how it is painted.
  const primaryControls = useMemo(
    () => (
      <>
        {picker.entities && picker.entities.length > 1 ? (
          <VizSelect
            label="Alignment"
            value={msaId}
            onChange={(v) => v && picker.setEntity(v)}
            data={picker.entities}
            searchable
            limit={200}
            allowDeselect={false}
          />
        ) : null}
        <VizSelect
          label="Colour scheme"
          value={colourScheme}
          onChange={(v) => v && setColourScheme(v as MsaColourScheme)}
          data={SCHEMES}
          allowDeselect={false}
        />
        <VizSelect
          label="Sort rows"
          value={sortBy}
          onChange={(v) => v && setSortBy(v as MsaSort)}
          data={[
            { value: 'rank', label: 'Rank' },
            { value: 'identity', label: 'Identity to reference' },
            { value: 'input', label: 'Input order' },
          ]}
          allowDeselect={false}
        />
      </>
    ),
    [picker.entities, picker.setEntity, msaId, colourScheme, sortBy, setColourScheme, setSortBy],
  );

  const controls = useMemo(
    () => (
      <>
        <VizControlGroup title="Display">
          <VizSlider
            label="Column width"
            value={zoom}
            onChange={setZoom}
            min={0}
            max={16}
            step={1}
            thumbLabel={(v) => (v === 0 ? 'Fit' : `${v} px`)}
          />
          <VizSwitch
            label="Consensus row"
            checked={showConsensus}
            onChange={(e) => setShowConsensus(e.currentTarget.checked)}
          />
          <VizSwitch
            label="Conservation bars"
            checked={showConservation}
            onChange={(e) => setShowConservation(e.currentTarget.checked)}
          />
        </VizControlGroup>
        <VizControlGroup title="Rows">
          <VizNumberInput
            label="Max rows"
            value={maxRows}
            onChange={(v) => setMaxRows(Math.max(1, Math.min(1000, Number(v) || 200)))}
            min={1}
            max={1000}
          />
        </VizControlGroup>
      </>
    ),
    [zoom, showConsensus, showConservation, maxRows, setShowConsensus, setShowConservation, setMaxRows],
  );

  const echo = useMemo(() => {
    if (!msaId || rows.length === 0) return undefined;
    const shown = total > rows.length ? `${rows.length} of ${total}` : String(rows.length);
    const range = selectedRange
      ? `, residues ${selectedRange.start}-${selectedRange.end ?? selectedRange.start}`
      : '';
    return `${msaId} · ${shown} sequences × ${width} columns${range}`;
  }, [msaId, rows.length, total, width, selectedRange]);

  const contentDemand = useMemo(
    () => demandForItems(Math.min(rows.length, 30), ROW_PX, HEADER_PX),
    [rows.length],
  );

  const badges = useMemo(
    () =>
      ragged
        ? [
            <Badge
              key="ragged"
              size="xs"
              color="orange"
              variant="light"
              title="Rows of this alignment differ in length; shorter rows were padded with gaps"
            >
              Ragged alignment
            </Badge>,
          ]
        : undefined,
    [ragged],
  );

  const onDrawn = useCallback(() => setDrawn(true), []);

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Sequence alignment'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      echo={echo}
      loading={loading}
      error={error}
      emptyMessage={!loading && rows.length === 0 ? 'No aligned sequences' : undefined}
      dataRows={frame ?? undefined}
      dataColumns={columns}
      badges={badges}
    >
      {rows.length > 0 ? (
        <Box
          className="depictio-msa"
          data-msa-ready={drawn ? 'true' : undefined}
          style={{ width: '100%', height: '100%', minHeight: 0 }}
        >
          <MsaPanel
            rows={rows}
            referenceIndex={0}
            chains={chains}
            colourScheme={colourScheme}
            selectedRange={selectedRange}
            highlight={highlight}
            selectedRowKeys={selectedRowKeys}
            onHoverColumn={onHoverColumn}
            onBrushColumns={brushEnabled ? onBrushColumns : undefined}
            onClickRow={selectionColumn ? onClickRow : undefined}
            cellWidth={zoom > 0 ? zoom : undefined}
            showConsensus={showConsensus}
            showConservation={showConservation}
            followSelection={follow}
            onDrawn={onDrawn}
          />
        </Box>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default MsaRenderer;
