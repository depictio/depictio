import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Box, ColorSwatch, Group, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { stableColorMap } from '../../colors';
import { usePublishHighlight, useHighlight } from '../../highlight/bus';
import {
  filtersExcludingOwnResidue,
  residueEntityFromFilters,
  residueRangeFilters,
  residueRangeFromFilters,
} from '../../selection';
import { COLORSCALE_NAMES } from '../../utils/colorScale';
import AdvancedVizFrame from './AdvancedVizFrame';
import { demandForPx } from './contentDemand';
import { VizControlGroup, VizSelect, VizSlider, VizSwitch } from './controls/VizControls';
import {
  PLDDT_BANDS,
  rgbCss,
  SequenceStrip,
  type ResidueRange,
  type StripDomain,
  type StripHover,
  type StripResidue,
  type StripVariant,
} from './protein';
import { panelColours } from './protein/panelTheme';
import {
  chainSelectionFilter,
  distinctColumns,
  firstValueOf,
  frameLength,
  hasOwnResiduePick,
  numberOrNull,
  rowIndicesWhere,
  scopeToEntity,
  stringOrNull,
  withoutOwnChainPick,
  withoutPositionSelections,
} from './protein/rendererData';
import { SECONDARY_STRUCTURE_COLOURS } from './protein/residueColours';
import { isPlddtLabel, looksLikeSecondaryStructure } from './protein/sequence';
import { useEntityPicker } from './protein/useEntityPicker';

/**
 * Mirrors `SequenceTrackConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys read here).
 */
interface SequenceTrackConfig {
  entity_col?: string | null;
  position_col?: string;
  residue_col?: string | null;
  value_col?: string | null;
  category_col?: string | null;
  value_label?: string | null;
  domains_wf_id?: string | null;
  domains_dc_id?: string | null;
  domain_start_col?: string;
  domain_end_col?: string;
  domain_label_col?: string;
  variants_wf_id?: string | null;
  variants_dc_id?: string | null;
  variant_position_col?: string;
  variant_label_col?: string | null;
  variant_category_col?: string | null;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: SequenceTrackConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/** Canonical columns of the companion tables with no config role, read by name
 *  (contract section 1): a domain's database, a variant's amino acids. */
const DOMAIN_SOURCE_COLUMN = 'source';
const VARIANT_REF_COLUMN = 'ref_aa';
const VARIANT_ALT_COLUMN = 'alt_aa';
/** Optional chain column of the residue table (contract section 1). A complex
 *  numbers each chain on its own, so the strip draws one chain at a time. */
const CHAIN_COLUMN = 'chain';
/** Tile furniture around the strip: frame header, legend. */
const CHROME_PX = 96;
const STRIP_NATURAL_PX = 150;

type Frame = Record<string, unknown[]>;

/** Fetch one companion table, scoped to the entity; never throws. */
function useCompanionRows(
  wfId: string | null | undefined,
  dcId: string | null | undefined,
  columns: string[],
  filters: InteractiveFilter[],
  refreshTick: number | undefined,
): { rows: Frame | null; error: string | null } {
  const [rows, setRows] = useState<Frame | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!wfId || !dcId || columns.length === 0) {
      setRows(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setError(null);
    fetchAdvancedVizData({ wfId, dcId, columns, filters, vizKind: 'sequence_track' })
      .then((res) => {
        if (!cancelled) setRows(res.rows);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setRows(null);
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [wfId, dcId, JSON.stringify(columns), JSON.stringify(filters), refreshTick]);
  return { rows, error };
}

/**
 * `sequence_track`: one protein's sequence with per-residue lanes, drawn by the
 * protein panel library's `SequenceStrip`. The bound collection is the residue
 * table (letters, a value such as pLDDT, a category such as secondary
 * structure); domain spans and variants come from two optional companion
 * tables. A brush emits a `residue_selection` (entity + position range), a
 * hover publishes on the highlight bus, and both come back in from the other
 * protein tiles as a shaded range and a crosshair.
 */
const SequenceTrackRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as SequenceTrackConfig;
  const index = String(metadata.index);
  const entityCol = config.entity_col === undefined ? 'entity' : config.entity_col;
  const positionCol = config.position_col || 'position';
  const residueCol = config.residue_col === undefined ? 'residue' : config.residue_col;
  const valueCol = config.value_col || null;
  const categoryCol = config.category_col || null;
  const variantPositionCol = config.variant_position_col || 'position';
  const variantLabelCol = config.variant_label_col === undefined ? 'label' : config.variant_label_col;
  const variantCategoryCol =
    config.variant_category_col === undefined ? 'category' : config.variant_category_col;
  const domainStartCol = config.domain_start_col || 'start';
  const domainEndCol = config.domain_end_col || 'end';
  const domainLabelCol = config.domain_label_col || 'label';
  const follow = config.follow_selection !== false;
  const brushEnabled = Boolean(onFilterChange) && config.selection_enabled !== false;

  const [valueScale, setValueScale] = useState<string>('Viridis');
  const [showLetters, setShowLetters] = useState(true);
  // Pixels per residue; 0 fits the whole protein to the tile width.
  const [zoom, setZoom] = useState<number>(0);
  const [drawn, setDrawn] = useState(false);
  const [pickedChain, setPickedChain] = useState<string | null>(null);

  // The tile's own residue pick never narrows its own fetch, and no residue
  // range or chain pick does (it shades, or picks the chain on screen);
  // everything else the dashboard filters applies.
  const withoutOwn = useMemo(
    () => withoutOwnChainPick(filtersExcludingOwnResidue(filters, index), index),
    [filters, index],
  );
  const fetchFilters = useMemo(
    () => withoutPositionSelections(withoutOwn, [positionCol, variantPositionCol, CHAIN_COLUMN]),
    [withoutOwn, positionCol, variantPositionCol],
  );
  // The chain another tile picked on a complex (an alignment brush).
  const followedChain = useMemo(
    () => residueEntityFromFilters(withoutOwn, CHAIN_COLUMN),
    [withoutOwn],
  );
  const followed = useMemo(() => residueEntityFromFilters(withoutOwn, entityCol), [withoutOwn, entityCol]);
  const picker = useEntityPicker(metadata.dc_id, entityCol, followed, refreshTick, {
    wfId: metadata.wf_id,
    vizKind: 'sequence_track',
    filters: fetchFilters,
    shareKey: entityCol,
    owner: index,
  });
  // The picker decides which protein is on screen, in every table it reads.
  const scoped = useCallback(
    (dcId: string | null | undefined) =>
      scopeToEntity(fetchFilters, index, dcId ?? undefined, entityCol, picker.entity),
    [entityCol, picker.entity, fetchFilters, index],
  );

  // ---- residue table -------------------------------------------------------
  const columns = useMemo(
    () => distinctColumns([entityCol, positionCol, residueCol, valueCol, categoryCol, CHAIN_COLUMN]),
    [entityCol, positionCol, residueCol, valueCol, categoryCol],
  );
  const [frame, setFrame] = useState<Frame | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // `filters` is a fresh array on every parent render (so `scoped` is a new
  // function): key the fetch on the filters' content, as the other protein
  // tiles do, or it refetches after every render, its own brush included.
  const residueFilters = useMemo(() => scoped(metadata.dc_id), [scoped, metadata.dc_id]);
  const residueFiltersKey = JSON.stringify(residueFilters);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Sequence track: missing data binding');
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
      vizKind: 'sequence_track',
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

  // Chains of the entity on screen, in table order; the strip shows one.
  const chains = useMemo<string[]>(() => {
    const col = frame?.[CHAIN_COLUMN];
    if (!frame || !col) return [];
    const seen = new Set<string>();
    for (const i of rowIndicesWhere(frame, entityCol, entity)) {
      const c = stringOrNull(col[i]);
      if (c != null) seen.add(c);
    }
    return Array.from(seen);
  }, [frame, entityCol, entity]);
  useEffect(() => {
    if (followedChain) setPickedChain(followedChain);
  }, [followedChain]);
  const chain = pickedChain && chains.includes(pickedChain) ? pickedChain : (chains[0] ?? null);
  const multiChain = chains.length > 1;

  const residues = useMemo<StripResidue[]>(() => {
    if (!frame || frameLength(frame) === 0) return [];
    const pos = frame[positionCol] ?? [];
    const chainOf = multiChain ? frame[CHAIN_COLUMN] : undefined;
    const letters = residueCol ? frame[residueCol] : undefined;
    const values = valueCol ? frame[valueCol] : undefined;
    const cats = categoryCol ? frame[categoryCol] : undefined;
    const out: StripResidue[] = [];
    for (const i of rowIndicesWhere(frame, entityCol, entity)) {
      const p = numberOrNull(pos[i]);
      if (p == null) continue;
      if (chainOf && stringOrNull(chainOf[i]) !== chain) continue;
      out.push({
        position: p,
        letter: letters ? stringOrNull(letters[i]) : null,
        value: values ? numberOrNull(values[i]) : null,
        category: cats ? stringOrNull(cats[i]) : null,
      });
    }
    return out;
  }, [frame, positionCol, residueCol, valueCol, categoryCol, entityCol, entity, multiChain, chain]);

  // ---- companion tables ------------------------------------------------------
  const domainCols = useMemo(
    () =>
      config.domains_dc_id
        ? distinctColumns([entityCol, domainStartCol, domainEndCol, domainLabelCol, DOMAIN_SOURCE_COLUMN])
        : [],
    [config.domains_dc_id, entityCol, domainStartCol, domainEndCol, domainLabelCol],
  );
  const domainFilters = useMemo(() => scoped(config.domains_dc_id), [scoped, config.domains_dc_id]);
  const domainsFetch = useCompanionRows(
    config.domains_wf_id || metadata.wf_id,
    config.domains_dc_id,
    domainCols,
    domainFilters,
    refreshTick,
  );
  const domains = useMemo<StripDomain[]>(() => {
    const f = domainsFetch.rows;
    if (!f) return [];
    const starts = f[domainStartCol] ?? [];
    const ends = f[domainEndCol] ?? [];
    const labels = f[domainLabelCol];
    const sources = f[DOMAIN_SOURCE_COLUMN];
    const out: StripDomain[] = [];
    for (const i of rowIndicesWhere(f, entityCol, entity)) {
      const s = numberOrNull(starts[i]);
      const e = numberOrNull(ends[i]);
      if (s == null || e == null) continue;
      out.push({
        start: Math.min(s, e),
        end: Math.max(s, e),
        label: labels ? stringOrNull(labels[i]) : null,
        source: sources ? stringOrNull(sources[i]) : null,
      });
    }
    return out;
  }, [domainsFetch.rows, domainStartCol, domainEndCol, domainLabelCol, entityCol, entity]);

  const variantCols = useMemo(
    () =>
      config.variants_dc_id
        ? distinctColumns([
            entityCol,
            variantPositionCol,
            variantLabelCol,
            variantCategoryCol,
            VARIANT_REF_COLUMN,
            VARIANT_ALT_COLUMN,
          ])
        : [],
    [config.variants_dc_id, entityCol, variantPositionCol, variantLabelCol, variantCategoryCol],
  );
  const variantFilters = useMemo(() => scoped(config.variants_dc_id), [scoped, config.variants_dc_id]);
  const variantsFetch = useCompanionRows(
    config.variants_wf_id || metadata.wf_id,
    config.variants_dc_id,
    variantCols,
    variantFilters,
    refreshTick,
  );
  const variants = useMemo<StripVariant[]>(() => {
    const f = variantsFetch.rows;
    if (!f) return [];
    const pos = f[variantPositionCol] ?? [];
    const labels = variantLabelCol ? f[variantLabelCol] : undefined;
    const cats = variantCategoryCol ? f[variantCategoryCol] : undefined;
    const refs = f[VARIANT_REF_COLUMN];
    const alts = f[VARIANT_ALT_COLUMN];
    const out: StripVariant[] = [];
    for (const i of rowIndicesWhere(f, entityCol, entity)) {
      const p = numberOrNull(pos[i]);
      if (p == null) continue;
      const ref = refs ? stringOrNull(refs[i]) : null;
      const alt = alts ? stringOrNull(alts[i]) : null;
      out.push({
        position: p,
        label: (labels ? stringOrNull(labels[i]) : null) ?? (ref && alt ? `p.${ref}${p}${alt}` : null),
        category: cats ? stringOrNull(cats[i]) : null,
      });
    }
    return out;
  }, [variantsFetch.rows, variantPositionCol, variantLabelCol, variantCategoryCol, entityCol, entity]);

  useEffect(() => setDrawn(false), [entity]);

  // ---- selections in ---------------------------------------------------------
  const ownResidue = useMemo(() => hasOwnResiduePick(filters, index), [filters, index]);
  const selectedRange = useMemo<ResidueRange | null>(() => {
    if (!follow && !ownResidue) return null;
    const r = residueRangeFromFilters(filters, entityCol, positionCol);
    if (!r || (r.entity && entity && r.entity !== entity)) return null;
    if (multiChain) {
      const picked = residueEntityFromFilters(filters, CHAIN_COLUMN);
      if (picked && picked !== chain) return null;
    }
    return { start: r.start, end: r.end };
  }, [filters, entityCol, positionCol, follow, ownResidue, entity, multiChain, chain]);

  const incoming = useHighlight(index, follow);
  const highlight = useMemo(() => {
    if (!incoming || (incoming.entity && entity && incoming.entity !== entity)) return null;
    // An event on another position column is on another axis entirely.
    if (incoming.positionColumn && incoming.positionColumn !== positionCol) return null;
    // On a complex, residues of another chain are not on this strip.
    if (multiChain && incoming.chain && incoming.chain !== chain) return null;
    return { start: incoming.start, end: incoming.end, rowKeys: incoming.rowKeys };
  }, [incoming, entity, positionCol, multiChain, chain]);

  // ---- selections out --------------------------------------------------------
  const publish = usePublishHighlight(index);
  const onHover = useCallback(
    (h: StripHover | null) => {
      if (!h) {
        publish(null);
        return;
      }
      const keys = h.variants.map((v) => v.label).filter((l): l is string => Boolean(l));
      publish({
        entity: entity ?? undefined,
        chain: chain ?? undefined,
        start: h.position,
        rowKeys: keys.length ? keys : undefined,
        positionColumn: positionCol,
      });
    },
    [publish, entity, chain, positionCol],
  );

  const onBrush = useCallback(
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
      // On a complex the range is in one chain's own numbering: name it.
      if (multiChain) {
        onFilterChange(chainSelectionFilter(index, metadata.dc_id, CHAIN_COLUMN, range ? chain : null));
      }
    },
    [onFilterChange, index, entityCol, positionCol, entity, metadata.dc_id, multiChain, chain],
  );

  // ---- legend ----------------------------------------------------------------
  const colours = useMemo(() => panelColours(theme, isDark), [theme, isDark]);
  const plddt = isPlddtLabel(config.value_label) && valueCol != null;
  const isSS = useMemo(() => looksLikeSecondaryStructure(residues.map((r) => r.category)), [residues]);
  const legend = useMemo(() => {
    const items: { label: string; colour: string }[] = [];
    if (plddt && residues.some((r) => r.value != null)) {
      for (const b of PLDDT_BANDS) items.push({ label: b.label.split(' (')[0], colour: rgbCss(b.rgb) });
    }
    if (isSS) {
      items.push({ label: 'Helix', colour: rgbCss(SECONDARY_STRUCTURE_COLOURS.helix) });
      items.push({ label: 'Strand', colour: rgbCss(SECONDARY_STRUCTURE_COLOURS.strand) });
    }
    // Variant consequences, in the colours the strip gives them (it builds the
    // same stable map from the same universe).
    const universe = new Set<string>();
    if (!isSS) for (const r of residues) if (r.category) universe.add(r.category);
    for (const v of variants) if (v.category) universe.add(v.category);
    for (const d of domains) if (d.label) universe.add(d.label);
    const map = stableColorMap(Array.from(universe), colours.categorical);
    const shown = new Set<string>();
    for (const v of variants) if (v.category) shown.add(v.category);
    if (!isSS) for (const r of residues) if (r.category) shown.add(r.category);
    Array.from(shown)
      .sort()
      .slice(0, 8)
      .forEach((c) => items.push({ label: c, colour: map.get(c) }));
    return items;
  }, [plddt, isSS, residues, variants, domains, colours.categorical]);

  // ---- chrome ----------------------------------------------------------------
  const entityChoices = picker.entities && picker.entities.length > 1 ? picker.entities : null;
  const primaryControls = useMemo(
    () =>
      entityChoices || multiChain ? (
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
          {multiChain ? (
            <VizSelect
              label="Chain"
              value={chain}
              onChange={(v) => v && setPickedChain(v)}
              data={chains}
              allowDeselect={false}
            />
          ) : null}
        </>
      ) : null,
    [entityChoices, picker.setEntity, entity, multiChain, chain, chains],
  );

  const controls = useMemo(
    () => (
      <VizControlGroup title="Display">
        <VizSlider
          label="Residue width"
          value={zoom}
          onChange={setZoom}
          min={0}
          max={24}
          step={1}
          thumbLabel={(v) => (v === 0 ? 'Fit' : `${v} px`)}
        />
        <VizSwitch
          label="Letters"
          checked={showLetters}
          onChange={(e) => setShowLetters(e.currentTarget.checked)}
          disabled={!residueCol}
        />
        {valueCol && !plddt ? (
          <VizSelect
            label="Value colours"
            value={valueScale}
            onChange={(v) => v && setValueScale(v)}
            data={COLORSCALE_NAMES}
            allowDeselect={false}
          />
        ) : null}
      </VizControlGroup>
    ),
    [zoom, showLetters, residueCol, valueCol, plddt, valueScale],
  );

  const echo = useMemo(() => {
    if (!residues.length && !variants.length) return undefined;
    const parts = [entity, multiChain && chain ? `chain ${chain}` : null, `${residues.length} residues`];
    if (variants.length) parts.push(`${variants.length} variants`);
    if (selectedRange) {
      parts.push(`residues ${selectedRange.start}-${selectedRange.end ?? selectedRange.start}`);
    }
    return parts.filter(Boolean).join(' · ');
  }, [entity, multiChain, chain, residues.length, variants.length, selectedRange]);

  const companionError = domainsFetch.error || variantsFetch.error;
  const badges = useMemo(
    () =>
      companionError
        ? [
            <Text key="companion" size="xs" c="orange" title={companionError}>
              Domains or variants unavailable
            </Text>,
          ]
        : undefined,
    [companionError],
  );

  const contentDemand = useMemo(() => demandForPx(STRIP_NATURAL_PX + CHROME_PX), []);
  const onDrawn = useCallback(() => setDrawn(true), []);
  const empty = residues.length === 0 && variants.length === 0 && domains.length === 0;

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Sequence track'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      echo={echo}
      loading={loading}
      error={error}
      emptyMessage={!loading && empty ? 'No residues for this entity' : undefined}
      dataRows={frame ?? undefined}
      dataColumns={columns}
      badges={badges}
    >
      {!empty ? (
        <Box
          className="depictio-sequence-track"
          data-sequence-ready={drawn ? 'true' : undefined}
          style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', minHeight: 0 }}
        >
          {/* Absolutely filled so the strip gets a definite height to spread
              its lanes over, whatever the flex engine makes of percentages. */}
          <Box style={{ flex: '1 1 auto', minHeight: 60, position: 'relative' }}>
            <Box style={{ position: 'absolute', inset: 0 }}>
              <SequenceStrip
                residues={residues}
                domains={domains}
                variants={variants}
                valueLabel={config.value_label ?? valueCol}
                valueScale={plddt ? 'plddt' : valueScale}
                selectedRange={selectedRange}
                highlight={highlight}
                onHover={onHover}
                onBrush={brushEnabled ? onBrush : undefined}
                height="100%"
                cellWidth={zoom > 0 ? zoom : undefined}
                showLetters={showLetters}
                followSelection={follow}
                onDrawn={onDrawn}
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

export default SequenceTrackRenderer;
