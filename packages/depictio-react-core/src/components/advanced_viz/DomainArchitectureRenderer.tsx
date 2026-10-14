import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Box,
  ColorSwatch,
  Group,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';

import {
  fetchAdvancedVizData,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { stableColorMap } from '../../colors';
import { usePublishHighlight, useHighlight } from '../../highlight/bus';
import { usePinnedCategoryColors } from '../../hooks/useCategoryColors';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  filterColumn,
  filtersExcludingOwn,
  filtersExcludingOwnResidue,
  residueEntityFromFilters,
  residueRangeFilterIndex,
  residueRangeFilters,
  residueRangeFromFilters,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import { demandForItems } from './contentDemand';
import {
  VizControlGroup,
  VizMultiSelect,
  VizNumberInput,
  VizSegmented,
  VizSelect,
  VizSlider,
} from './controls/VizControls';
import {
  architectureRows,
  capProteins,
  filterHits,
  groupArchitectures,
  groupKey,
  hasSources,
  isPartial,
  parseDomainHits,
  partialEdges,
  proteinLengths,
  proteinRows,
  sortProteins,
  buildProteins,
  valueCounts,
  type ArchitectureGroup,
  type DomainColumns,
  type DomainHit,
  type PanelRow,
  type ProteinArch,
} from './domains/architecture';
import DomainArchitecturePanel, {
  type DomainHoverInfo,
  type EntitySpan,
} from './domains/DomainArchitecturePanel';
import { panelColours } from './protein/panelTheme';
import {
  distinctColumns,
  hasOwnResiduePick,
  stringOrNull,
  withoutPositionSelections,
} from './protein/rendererData';
import { usePersistedVizControl } from './usePersistedVizControl';

/**
 * Mirrors `DomainArchitectureConfig` in depictio/models/components/advanced_viz/configs.py
 * (`test_advanced_viz_config_alignment` enforces the keys a renderer reads).
 */
interface DomainArchitectureConfig {
  entity_col?: string;
  start_col?: string;
  end_col?: string;
  label_col?: string;
  protein_length_col?: string | null;
  hmm_from_col?: string | null;
  hmm_to_col?: string | null;
  hmm_length_col?: string | null;
  hmm_coverage_col?: string | null;
  evalue_col?: string | null;
  source_col?: string | null;
  description_col?: string | null;
  accession_col?: string | null;
  view?: 'proteins' | 'architectures';
  max_architectures?: number;
  max_proteins?: number;
  evalue_threshold?: number | null;
  sources?: string[] | null;
  scale?: 'shared' | 'per_protein';
  color_by?: 'label' | 'source';
  partial_coverage?: number;
  position_col_for_selection?: string;
  label_selection?: boolean;
  selection_enabled?: boolean;
  follow_selection?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: DomainArchitectureConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Absent on read-only hosts (catalog, project previews): no residue pick. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

type View = 'proteins' | 'architectures';
type Scale = 'shared' | 'per_protein';
type ColourBy = 'label' | 'source';

/** Canonical domtbl column with no config role, read by name for the tooltip
 *  (the per-domain bit score of a hmmsearch domain table). */
const SCORE_COLUMN = 'dom_score';
/** Above this many rows the tile says it is drawing a large table whole (its
 *  sampling policy is `none`). */
const LARGE_TABLE_ROWS = 50_000;
/** Legend entries, the most frequent first. */
const LEGEND_TOP = 12;
const ROW_PX = 26;
const CHROME_PX = 120;

const EVALUE_PRESETS = ['1', '0.1', '0.01', '0.001', '1e-5', '1e-10', '1e-20'];

/** A column role: the configured name, the default when the key is absent,
 *  none when it is explicitly null or empty. */
function optionalColumn(value: string | null | undefined, fallback: string): string | null {
  return value === undefined ? fallback : value || null;
}

/**
 * `domain_architecture`: protein domain architectures, as on Pfam, InterPro or
 * MGnifams pages, from a domain hit table (a hmmsearch domain table, or any
 * `entity, start, end, label` list). One row per protein with its domains on a
 * backbone, a zigzag edge where the HMM match is partial, overlapping hits in
 * sub-lanes; or the proteins grouped by architecture with counts.
 *
 * A domain click emits a `residue_selection` over its envelope (the structure,
 * the sequence track and the residue tables follow) and the domain's label as
 * a point selection; a protein name picks the whole protein; an architecture
 * group selects its proteins. The tile never narrows itself on the entity or
 * the label column: it keeps every protein and rings the picked ones.
 */
const DomainArchitectureRenderer: React.FC<Props> = ({
  metadata,
  filters,
  refreshTick,
  onFilterChange,
}) => {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as DomainArchitectureConfig;
  const index = String(metadata.index);

  const entityCol = config.entity_col || 'entity';
  const startCol = config.start_col || 'start';
  const endCol = config.end_col || 'end';
  const labelCol = config.label_col || 'label';
  const proteinLengthCol = optionalColumn(config.protein_length_col, 'protein_length');
  const hmmFromCol = optionalColumn(config.hmm_from_col, 'hmm_from');
  const hmmToCol = optionalColumn(config.hmm_to_col, 'hmm_to');
  const hmmLengthCol = optionalColumn(config.hmm_length_col, 'hmm_length');
  const hmmCoverageCol = optionalColumn(config.hmm_coverage_col, 'hmm_coverage');
  const evalueCol = optionalColumn(config.evalue_col, 'i_evalue');
  const sourceCol = optionalColumn(config.source_col, 'source');
  const descriptionCol = optionalColumn(config.description_col, 'description');
  const accessionCol = optionalColumn(config.accession_col, 'accession');
  const positionCol = config.position_col_for_selection || 'position';
  const partialCoverage = config.partial_coverage ?? 0.9;
  const follow = config.follow_selection !== false;
  const selectionEnabled = Boolean(onFilterChange) && config.selection_enabled !== false;
  const labelSelection = config.label_selection !== false;
  // The label column the point selection lands on (undefined when selection is off).
  const labelSelectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;

  const [view, setView] = usePersistedVizControl<View>(metadata, 'view', 'proteins');
  const [colourBy, setColourBy] = usePersistedVizControl<ColourBy>(metadata, 'color_by', 'label');
  const [scale, setScale] = usePersistedVizControl<Scale>(metadata, 'scale', 'shared');
  const [evalueThreshold, setEvalueThreshold] = usePersistedVizControl<number | null>(
    metadata,
    'evalue_threshold',
    null,
  );
  const [sources, setSources] = usePersistedVizControl<string[] | null>(metadata, 'sources', null);
  const [maxArchitectures, setMaxArchitectures] = usePersistedVizControl<number>(
    metadata,
    'max_architectures',
    15,
  );
  const [maxProteins, setMaxProteins] = usePersistedVizControl<number>(
    metadata,
    'max_proteins',
    2000,
  );
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  const [drawn, setDrawn] = useState(false);

  // ---- filters -------------------------------------------------------------
  // Every dashboard filter but this tile's own picks.
  const withoutOwn = useMemo(
    () =>
      filtersExcludingOwnResidue(filtersExcludingOwn(filters, index, 'scatter_selection'), index),
    [filters, index],
  );
  // The tile never narrows itself on what it selects: a selection (from any
  // tile) on the entity, the label or the residue position column is a place
  // to look, ringed and shaded, not a subset. A sidebar filter on those
  // columns has no source and still narrows.
  const fetchFilters = useMemo(
    () => withoutPositionSelections(withoutOwn, [positionCol, entityCol, labelCol]),
    [withoutOwn, positionCol, entityCol, labelCol],
  );
  const fetchFiltersKey = JSON.stringify(fetchFilters);

  // ---- data ------------------------------------------------------------------
  const columns = useMemo(
    () =>
      distinctColumns([
        entityCol,
        startCol,
        endCol,
        labelCol,
        proteinLengthCol,
        hmmFromCol,
        hmmToCol,
        hmmLengthCol,
        hmmCoverageCol,
        evalueCol,
        sourceCol,
        descriptionCol,
        accessionCol,
        SCORE_COLUMN,
      ]),
    [
      entityCol,
      startCol,
      endCol,
      labelCol,
      proteinLengthCol,
      hmmFromCol,
      hmmToCol,
      hmmLengthCol,
      hmmCoverageCol,
      evalueCol,
      sourceCol,
      descriptionCol,
      accessionCol,
    ],
  );
  const [frame, setFrame] = useState<Record<string, unknown[]> | null>(null);
  const [rowCount, setRowCount] = useState(0);
  const [degraded, setDegraded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Domain architecture: missing data binding');
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
      filters: JSON.parse(fetchFiltersKey) as InteractiveFilter[],
      vizKind: 'domain_architecture',
    })
      .then((res) => {
        if (cancelled) return;
        setFrame(res.rows);
        setRowCount(res.row_count ?? 0);
        setDegraded(Boolean(res.sampling?.degraded));
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
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(columns), fetchFiltersKey, refreshTick]);

  const domainColumns = useMemo<DomainColumns>(
    () => ({
      entity: entityCol,
      start: startCol,
      end: endCol,
      label: labelCol,
      proteinLength: proteinLengthCol,
      hmmFrom: hmmFromCol,
      hmmTo: hmmToCol,
      hmmLength: hmmLengthCol,
      hmmCoverage: hmmCoverageCol,
      evalue: evalueCol,
      source: sourceCol,
      description: descriptionCol,
      accession: accessionCol,
      score: SCORE_COLUMN,
    }),
    [
      entityCol,
      startCol,
      endCol,
      labelCol,
      proteinLengthCol,
      hmmFromCol,
      hmmToCol,
      hmmLengthCol,
      hmmCoverageCol,
      evalueCol,
      sourceCol,
      descriptionCol,
      accessionCol,
    ],
  );
  const parsed = useMemo(() => parseDomainHits(frame, domainColumns), [frame, domainColumns]);
  // Lengths from every hit, so a filter never shortens a backbone.
  const lengths = useMemo(() => proteinLengths(parsed.hits), [parsed]);
  const sourcesBound = useMemo(() => hasSources(parsed.hits), [parsed]);
  const sourceChoices = useMemo(
    () =>
      Array.from(
        new Set(parsed.hits.map((h) => h.source).filter((s): s is string => s != null)),
      ).sort(),
    [parsed],
  );
  const hits = useMemo(
    () => filterHits(parsed.hits, { evalueThreshold, sources }),
    [parsed, evalueThreshold, sources],
  );
  const proteins = useMemo(() => sortProteins(buildProteins(hits, lengths)), [hits, lengths]);
  const hiddenProteins = lengths.size - proteins.length;

  // ---- colours ---------------------------------------------------------------
  const effectiveColourBy: ColourBy =
    colourBy === 'source' && sourceCol && sourcesBound ? 'source' : 'label';
  const colourColumn = effectiveColourBy === 'source' ? sourceCol : labelCol;
  const colourKey = useCallback(
    (h: DomainHit): string => (effectiveColourBy === 'source' ? (h.source ?? 'unknown') : h.label),
    [effectiveColourBy],
  );
  // The column's whole universe, so a value keeps its colour while filters
  // come and go (the frame's own values when the lookup fails).
  const [universe, setUniverse] = useState<string[] | null>(null);
  useEffect(() => {
    if (!metadata.dc_id || !colourColumn) {
      setUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, colourColumn)
      .then((values) => {
        if (!cancelled) setUniverse(values.map(String));
      })
      .catch(() => {
        if (!cancelled) setUniverse(null);
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, colourColumn, refreshTick]);
  const colours = useMemo(() => panelColours(theme, isDark), [theme, isDark]);
  const pinned = usePinnedCategoryColors(colourColumn);
  const colourMap = useMemo(
    () => stableColorMap(universe ?? parsed.hits.map(colourKey), colours.categorical, pinned),
    [universe, parsed, colourKey, colours.categorical, pinned],
  );
  const colourOf = useCallback(
    (h: DomainHit) => colourMap.get(colourKey(h)),
    [colourMap, colourKey],
  );

  // ---- selections in -----------------------------------------------------------
  // A pick made elsewhere that names one protein: scrolled into view.
  const followed = useMemo(
    () => (follow ? residueEntityFromFilters(withoutOwn, entityCol) : null),
    [follow, withoutOwn, entityCol],
  );
  const ownResidue = useMemo(() => hasOwnResiduePick(filters, index), [filters, index]);
  const pickedRange = useMemo<EntitySpan | null>(() => {
    if (!follow && !ownResidue) return null;
    const r = residueRangeFromFilters(filters, entityCol, positionCol);
    return r && r.entity ? { entity: r.entity, start: r.start, end: r.end } : null;
  }, [filters, entityCol, positionCol, follow, ownResidue]);
  const pickedDomain = ownResidue ? pickedRange : null;

  // Entities a selection names on the entity column: this tile's own picks,
  // and the other tiles' when following.
  const ownIndices = useMemo(() => new Set([index, residueRangeFilterIndex(index)]), [index]);
  const pickedEntities = useMemo(() => {
    const out = new Set<string>();
    for (const f of filters) {
      if (!f.source || filterColumn(f) !== entityCol) continue;
      if (!follow && !ownIndices.has(f.index)) continue;
      const values = Array.isArray(f.value) ? f.value : [f.value];
      for (const v of values) if (v != null && v !== '') out.add(String(v));
    }
    return out;
  }, [filters, entityCol, follow, ownIndices]);

  // The point selection this tile holds (a domain's label, or a group's proteins).
  const ownPoint = useMemo(() => {
    const f = filters.find((x) => x.index === metadata.index && x.source === 'scatter_selection');
    const values = f && Array.isArray(f.value) ? f.value.map(String) : [];
    return { column: f ? filterColumn(f) : undefined, values };
  }, [filters, metadata.index]);

  const incoming = useHighlight(index, follow);
  const highlight = useMemo<EntitySpan | null>(() => {
    if (!incoming || !incoming.entity) return null;
    // An event on another position column is on another axis entirely.
    if (incoming.positionColumn && incoming.positionColumn !== positionCol) return null;
    return { entity: incoming.entity, start: incoming.start, end: incoming.end ?? incoming.start };
  }, [incoming, positionCol]);

  // ---- rows --------------------------------------------------------------------
  const capped = useMemo(
    () => capProteins(proteins, maxProteins, followed ? [followed] : null),
    [proteins, maxProteins, followed],
  );
  const grouping = useMemo(
    () => (view === 'architectures' ? groupArchitectures(proteins, maxArchitectures) : null),
    [view, proteins, maxArchitectures],
  );
  const rows = useMemo<PanelRow[]>(
    () =>
      grouping ? architectureRows(grouping, expanded, maxProteins) : proteinRows(capped.shown),
    [grouping, expanded, maxProteins, capped],
  );
  const selectedGroups = useMemo(() => {
    const out = new Set<string>();
    if (!grouping || ownPoint.column !== entityCol || !ownPoint.values.length) return out;
    const own = new Set(ownPoint.values);
    for (const g of grouping.groups) {
      if (g.members.length === own.size && g.members.every((m) => own.has(m.entity))) {
        out.add(groupKey(g.architecture));
      }
    }
    return out;
  }, [grouping, ownPoint, entityCol]);
  const revealKey = useMemo(() => {
    if (!followed) return null;
    if (!grouping) return capped.shown.some((p) => p.entity === followed) ? `p:${followed}` : null;
    const g = grouping.groups.find((x) => x.members.some((m) => m.entity === followed));
    if (!g) return null;
    const key = groupKey(g.architecture);
    return expanded.has(key) ? `${key}|${followed}` : key;
  }, [followed, grouping, capped, expanded]);

  // ---- selections out ----------------------------------------------------------
  const publish = usePublishHighlight(index);
  const onHoverDomain = useCallback(
    (h: DomainHoverInfo | null) => {
      if (!h) {
        publish(null);
        return;
      }
      publish({
        entity: h.protein.entity,
        start: h.hit.start,
        end: h.hit.end,
        positionColumn: positionCol,
      });
    },
    [publish, positionCol],
  );

  const emitRange = useCallback(
    (entity: string, start: number | null, end: number | null) => {
      if (!onFilterChange) return;
      const pair = residueRangeFilters(index, {
        entityColumn: entityCol,
        positionColumn: positionCol,
        entity,
        start,
        end,
        dcId: metadata.dc_id,
      });
      for (const f of pair) onFilterChange(f);
    },
    [onFilterChange, index, entityCol, positionCol, metadata.dc_id],
  );
  // Drop the point selection this tile holds (a label, or a group).
  const clearOwnPoint = useCallback(() => {
    if (!onFilterChange || !ownPoint.values.length) return;
    onFilterChange(advancedVizSelectionFilter(metadata, ownPoint.column ?? labelCol, []));
  }, [onFilterChange, ownPoint, metadata, labelCol]);

  const onClickDomain = useCallback(
    (protein: ProteinArch, hit: DomainHit) => {
      if (!onFilterChange) return;
      const same =
        pickedDomain != null &&
        pickedDomain.entity === protein.entity &&
        pickedDomain.start === hit.start &&
        pickedDomain.end === hit.end;
      emitRange(protein.entity, same ? null : hit.start, same ? null : hit.end);
      // The domain by name, beside its span: the raw label value, so a hit
      // shown under its accession (no label) selects nothing it does not hold.
      const label = stringOrNull(frame?.[labelCol]?.[hit.row]);
      if (labelSelection && labelSelectionColumn && label != null) {
        onFilterChange(
          advancedVizSelectionFilter(metadata, labelSelectionColumn, same ? [] : [label]),
        );
      } else {
        clearOwnPoint();
      }
    },
    [
      onFilterChange,
      pickedDomain,
      emitRange,
      frame,
      labelCol,
      labelSelection,
      labelSelectionColumn,
      metadata,
      clearOwnPoint,
    ],
  );

  const onClickProtein = useCallback(
    (protein: ProteinArch) => {
      const same =
        pickedDomain != null &&
        pickedDomain.entity === protein.entity &&
        pickedDomain.start === 1 &&
        pickedDomain.end === protein.length;
      emitRange(protein.entity, same ? null : 1, same ? null : protein.length);
      clearOwnPoint();
    },
    [pickedDomain, emitRange, clearOwnPoint],
  );

  const onClickGroup = useCallback(
    (group: ArchitectureGroup) => {
      if (!onFilterChange) return;
      const selected = selectedGroups.has(groupKey(group.architecture));
      if (ownResidue && pickedDomain) emitRange(pickedDomain.entity, null, null);
      onFilterChange(
        advancedVizSelectionFilter(
          metadata,
          entityCol,
          selected ? [] : group.members.map((m) => m.entity),
        ),
      );
    },
    [onFilterChange, selectedGroups, ownResidue, pickedDomain, emitRange, metadata, entityCol],
  );

  const onToggleGroup = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // ---- legend --------------------------------------------------------------------
  const legend = useMemo(() => valueCounts(hits, colourKey, LEGEND_TOP), [hits, colourKey]);
  const partials = useMemo(() => {
    let jagged = false;
    let dashed = false;
    for (const h of hits) {
      const e = partialEdges(h, partialCoverage);
      if (!isPartial(e)) continue;
      if (e.unknown) dashed = true;
      else jagged = true;
      if (jagged && dashed) break;
    }
    return { jagged, dashed };
  }, [hits, partialCoverage]);

  // ---- chrome --------------------------------------------------------------------
  const primaryControls = useMemo(
    () => (
      <>
        <VizSegmented
          label="View"
          value={view}
          onChange={(v) => setView(v as View)}
          data={[
            { value: 'proteins', label: 'Proteins' },
            { value: 'architectures', label: 'Architectures' },
          ]}
        />
        <VizSegmented
          label="Colour by"
          value={effectiveColourBy}
          onChange={(v) => setColourBy(v as ColourBy)}
          data={[
            { value: 'label', label: 'Domain' },
            { value: 'source', label: 'Source', disabled: !sourcesBound },
          ]}
        />
      </>
    ),
    [view, setView, effectiveColourBy, setColourBy, sourcesBound],
  );

  const evalueChoices = useMemo(() => {
    const data = [
      { value: 'none', label: 'Any' },
      ...EVALUE_PRESETS.map((v) => ({ value: v, label: `≤ ${v}` })),
    ];
    if (evalueThreshold != null && !EVALUE_PRESETS.some((v) => Number(v) === evalueThreshold)) {
      data.push({ value: String(evalueThreshold), label: `≤ ${evalueThreshold}` });
    }
    return data;
  }, [evalueThreshold]);
  const evalueValue =
    evalueThreshold == null
      ? 'none'
      : (EVALUE_PRESETS.find((v) => Number(v) === evalueThreshold) ?? String(evalueThreshold));

  const controls = useMemo(
    () => (
      <>
        <VizControlGroup title="Filters">
          <VizSelect
            label={evalueCol ? `E-value (${evalueCol})` : 'E-value'}
            value={evalueValue}
            onChange={(v) => setEvalueThreshold(!v || v === 'none' ? null : Number(v))}
            data={evalueChoices}
            allowDeselect={false}
            disabled={!evalueCol}
          />
          {sourceChoices.length ? (
            <VizMultiSelect
              label="Sources"
              placeholder={sources && sources.length ? undefined : 'All'}
              value={sources ?? []}
              onChange={(v) => setSources(v.length ? v : null)}
              data={sourceChoices}
              clearable
            />
          ) : null}
        </VizControlGroup>
        <VizControlGroup title="Display">
          <VizSegmented
            label="Scale"
            value={scale}
            onChange={(v) => setScale(v as Scale)}
            data={[
              { value: 'shared', label: 'Shared' },
              { value: 'per_protein', label: 'Per protein' },
            ]}
          />
          {view === 'architectures' ? (
            <VizSlider
              label="Architectures"
              value={maxArchitectures}
              onChange={setMaxArchitectures}
              min={1}
              max={100}
              step={1}
              thumbLabel={(v) => `Top ${v}`}
            />
          ) : null}
          <VizNumberInput
            label="Max proteins"
            value={maxProteins}
            onChange={(v) => setMaxProteins(Math.max(1, Math.min(20000, Number(v) || 2000)))}
            min={1}
            max={20000}
          />
        </VizControlGroup>
      </>
    ),
    [
      evalueCol,
      evalueValue,
      evalueChoices,
      setEvalueThreshold,
      sourceChoices,
      sources,
      setSources,
      scale,
      setScale,
      view,
      maxArchitectures,
      setMaxArchitectures,
      maxProteins,
      setMaxProteins,
    ],
  );

  const echo = useMemo(() => {
    if (!proteins.length) return undefined;
    const parts: string[] = [];
    if (grouping) {
      parts.push(`${grouping.architectures.toLocaleString()} architectures`);
      parts.push(`${grouping.proteins.toLocaleString()} proteins`);
    } else {
      const shown = capped.capped
        ? `${capped.shown.length.toLocaleString()} of ${capped.total.toLocaleString()}`
        : capped.total.toLocaleString();
      parts.push(`${shown} proteins`);
    }
    parts.push(`${hits.length.toLocaleString()} domains`);
    if (pickedRange) parts.push(`${pickedRange.entity} ${pickedRange.start}-${pickedRange.end}`);
    return parts.join(' · ');
  }, [proteins.length, grouping, capped, hits.length, pickedRange]);

  const badges = useMemo(() => {
    const out: React.ReactNode[] = [];
    if (!grouping && capped.capped) {
      out.push(
        <Badge
          key="cap"
          size="xs"
          color="gray"
          variant="light"
          title={`The tile draws at most ${maxProteins.toLocaleString()} proteins (max_proteins), the first in architecture order plus any picked elsewhere. Raise the cap, or narrow the dashboard, to see the rest.`}
        >
          {`${capped.shown.length.toLocaleString()} of ${capped.total.toLocaleString()} proteins`}
        </Badge>,
      );
    }
    if (hiddenProteins > 0) {
      out.push(
        <Badge
          key="hidden"
          size="xs"
          color="gray"
          variant="light"
          title="Proteins whose every hit is above the E-value threshold or from a source left out"
        >
          {`${hiddenProteins.toLocaleString()} proteins filtered out`}
        </Badge>,
      );
    }
    if (rowCount > LARGE_TABLE_ROWS) {
      out.push(
        <Badge
          key="large"
          size="xs"
          color="orange"
          variant="light"
          title={`${rowCount.toLocaleString()} rows arrived and the tile draws every one (it does not sample). Narrow the dashboard (a sample, a family) to keep it responsive.`}
        >
          Large table
        </Badge>,
      );
    }
    if (parsed.skipped > 0) {
      out.push(
        <Badge
          key="skipped"
          size="xs"
          color="orange"
          variant="light"
          title={`Rows without a protein (${entityCol}), a start (${startCol}) or an end (${endCol}) are not drawn`}
        >
          {`${parsed.skipped.toLocaleString()} rows skipped`}
        </Badge>,
      );
    }
    if (sources && sources.length && !sourcesBound) {
      out.push(
        <Badge
          key="sources"
          size="xs"
          color="orange"
          variant="light"
          title="No hit carries a source"
        >
          Source filter ignored
        </Badge>,
      );
    }
    return out.length ? out : undefined;
  }, [
    grouping,
    capped,
    maxProteins,
    hiddenProteins,
    rowCount,
    parsed.skipped,
    entityCol,
    startCol,
    endCol,
    sources,
    sourcesBound,
  ]);

  const contentDemand = useMemo(
    () => demandForItems(Math.min(rows.length, 20), ROW_PX, CHROME_PX),
    [rows.length],
  );
  const onDrawn = useCallback(() => setDrawn(true), []);
  // The data popover lists the columns the table actually has.
  const presentColumns = useMemo(
    () => columns.filter((c) => frame && c in frame),
    [columns, frame],
  );

  let emptyMessage: string | undefined;
  if (!loading && !error && frame) {
    if (parsed.hits.length === 0) {
      emptyMessage =
        parsed.skipped > 0
          ? `No row names a protein, a start and an end (${entityCol}, ${startCol}, ${endCol})`
          : 'No domain hits';
    } else if (proteins.length === 0) {
      emptyMessage = `No domain passes the filters (E-value, sources): ${parsed.hits.length.toLocaleString()} hits hidden`;
    }
  }

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Domain architecture'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      echo={echo}
      loading={loading}
      error={error}
      emptyMessage={emptyMessage}
      dataRows={frame ?? undefined}
      dataColumns={presentColumns}
      badges={badges}
      estimated={degraded}
    >
      {rows.length > 0 ? (
        <Box
          className="depictio-domain-architecture"
          data-domain-ready={drawn ? 'true' : undefined}
          style={{
            display: 'flex',
            flexDirection: 'column',
            width: '100%',
            height: '100%',
            minHeight: 0,
          }}
        >
          <Box style={{ flex: '1 1 auto', minHeight: 60, position: 'relative' }}>
            <Box style={{ position: 'absolute', inset: 0 }}>
              <DomainArchitecturePanel
                rows={rows}
                scale={scale}
                partialCoverage={partialCoverage}
                colourOf={colourOf}
                evalueColumn={evalueCol}
                pickedEntities={pickedEntities}
                selectedGroups={selectedGroups}
                pickedRange={pickedRange}
                pickedDomain={pickedDomain}
                highlight={highlight}
                revealKey={revealKey}
                onHoverDomain={onHoverDomain}
                onClickDomain={selectionEnabled ? onClickDomain : undefined}
                onClickProtein={selectionEnabled ? onClickProtein : undefined}
                onClickGroup={selectionEnabled ? onClickGroup : undefined}
                onToggleGroup={onToggleGroup}
                onDrawn={onDrawn}
              />
            </Box>
          </Box>
          {legend.items.length ? (
            <Group gap="sm" px={4} pt={4} wrap="wrap" style={{ flex: '0 0 auto' }}>
              {legend.items.map((item) => (
                <Group key={item.value} gap={4} wrap="nowrap">
                  <ColorSwatch color={colourMap.get(item.value)} size={10} withShadow={false} />
                  <Text size="xs" c="dimmed">
                    {`${item.value} (${item.count.toLocaleString()})`}
                  </Text>
                </Group>
              ))}
              {legend.more > 0 ? (
                <Text size="xs" c="dimmed">
                  {`+${legend.more.toLocaleString()} more`}
                </Text>
              ) : null}
              {partials.jagged ? (
                <Text size="xs" c="dimmed" fs="italic">
                  Zigzag edge: partial HMM match
                </Text>
              ) : null}
              {partials.dashed ? (
                <Text size="xs" c="dimmed" fs="italic">
                  Dashed outline: partial by coverage
                </Text>
              ) : null}
            </Group>
          ) : null}
        </Box>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default DomainArchitectureRenderer;
