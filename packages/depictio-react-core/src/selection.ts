/**
 * Helpers for chart/table/map selection-as-filter wiring.
 *
 * The Dash viewer stores selections in ``interactive-values-store`` with a
 * ``source`` discriminator (``scatter_selection`` / ``table_selection`` /
 * ``map_selection`` / ``tree_selection``) so passive components can merge them
 * alongside regular interactive filters. The React viewer mirrors that protocol via
 * ``InteractiveFilter.source`` and uses the helpers below to extract values
 * from Plotly/AG Grid events and to merge / clear by ``(index, source)``.
 */

import type { InteractiveFilter, InteractiveFilterSource, StoredMetadata } from './api';

/**
 * Values a given map currently has selected, read back out of the filter list.
 *
 * A map's own selection is stripped before it fetches (it must keep showing
 * every point), so the filter list is the only record of what is selected. The
 * map re-derives it from here to repaint the highlight — which matters most
 * after a tab switch, where the map remounts from scratch while the selection
 * it made is still filtering the rest of the dashboard.
 */
export function mapSelectionValues(
  filters: InteractiveFilter[],
  componentIndex: string,
): string[] {
  for (const f of filters) {
    if (f.index !== componentIndex || f.source !== 'map_selection') continue;
    if (Array.isArray(f.value)) return f.value.map((v) => String(v));
  }
  return [];
}

/**
 * The filter entry a map emits for a set of selected values.
 *
 * Shared so that every way of selecting on a map — lassoing points, clicking
 * one, ticking rows in its underlying-data table — produces the *same* entry.
 * They are all one selection: they land on the same `(index, 'map_selection')`
 * key, so whichever was used last replaces the others, and the map's highlight
 * reads back out of it. Passing `[]` clears.
 */
export function mapSelectionFilter(
  metadata: StoredMetadata,
  values: string[],
): InteractiveFilter {
  const selectionColumn =
    typeof metadata.selection_column === 'string'
      ? (metadata.selection_column as string)
      : undefined;
  return {
    index: metadata.index,
    value: values,
    source: 'map_selection',
    column_name: selectionColumn,
    interactive_component_type: 'MultiSelect',
    metadata: {
      dc_id: metadata.dc_id,
      column_name: selectionColumn,
      interactive_component_type: 'MultiSelect',
      selection_column: selectionColumn,
    },
  };
}

/**
 * Whether a map should emit selections at all.
 *
 * Choropleth is excluded because its shapes are non-point geometries that
 * Plotly's selection events don't cover. `hasHandler` folds in the caller's own
 * "is anyone listening" check, so read-only hosts light up no lasso affordance.
 */
export function isMapSelectionEnabled(metadata: StoredMetadata, hasHandler: boolean): boolean {
  return (
    Boolean(metadata.selection_enabled) &&
    (metadata.map_type as string) !== 'choropleth_map' &&
    hasHandler
  );
}

/** Kinds whose config model defaults `selection_enabled` to true. */
const SELECTION_ON_BY_DEFAULT: ReadonlySet<string> = new Set([
  'molecule_3d',
  'msa',
  'sequence_track',
]);

/**
 * The DC column an advanced_viz component emits its selection on, or
 * `undefined` when it cannot emit one at all.
 *
 * Only a few viz kinds carry a per-row (or per-curve) identity to select on;
 * every other kind aggregates (bins, taxa, intersections) and would emit an
 * envelope pointing at nothing. Each is opt-in per component, so a shipped
 * dashboard keeps the drag behaviour it has today until its YAML asks for the
 * lasso.
 *
 * Embedding falls back to `sample_id_col` because that is already the value it
 * writes into every point's customdata, and profile falls back to `series_col`
 * for the same reason: a profile point belongs to a curve, and the curve is
 * what the reader is picking. Manhattan has no defensible fallback: one point
 * there is a row of a long variant table keyed by (sample, chromosome,
 * position), so selecting on the sample column and selecting on a per-variant
 * label are two different questions and only the dashboard knows which one it
 * is asking.
 *
 * This is the single source of truth for the capability: the renderers gate
 * their Plotly handlers on it and `supportsSelectionGrouping` gates the
 * chrome's marker on it, so the affordance and the behaviour cannot disagree.
 */
export function advancedVizSelectionColumn(metadata: StoredMetadata): string | undefined {
  const config = (metadata.config ?? {}) as Record<string, unknown>;
  const kind = typeof metadata.viz_kind === 'string' ? metadata.viz_kind : '';
  // The protein kinds select by default (their models default
  // `selection_enabled` to true), so a stored blob that omits the key still
  // emits; every other kind stays opt-in.
  const enabled =
    typeof config.selection_enabled === 'boolean'
      ? config.selection_enabled
      : SELECTION_ON_BY_DEFAULT.has(kind);
  if (!enabled) return undefined;
  const configColumn = (key: string): string | undefined => {
    const value = config[key];
    return typeof value === 'string' && value ? value : undefined;
  };
  const named = configColumn('selection_column');
  switch (kind) {
    case 'embedding':
      return named ?? configColumn('sample_id_col');
    case 'manhattan':
      return named;
    case 'genome_view':
      // Same reasoning as the Manhattan: a mark is one feature at one locus and
      // the dashboard has to name the column a pick stands for. The region
      // brush is a separate path (`genomeRegionFilters` below) that needs no
      // opt-in, because a chromosome and a position range are never ambiguous.
      return named;
    case 'profile':
      return named ?? configColumn('series_col');
    case 'scatter_xy':
      // The label column, because that is what identifies a point: the axes are
      // numeric by definition and the colour column is a grouping, so filtering
      // on either would select a band rather than the points that were clicked.
      return named ?? configColumn('label_col');
    case 'genome_chord':
      // A chord is one named link between two loci, so its label is the
      // identifier. The two chromosome columns are a grouping and the positions
      // are numeric, so neither could stand in for it.
      return named ?? configColumn('label_col');
    case 'molecule_3d':
    case 'sequence_track':
      // A picked residue is a position; the entity half travels in the
      // `residue_selection` filter pair, not in this scatter-style column.
      return configColumn('position_col') ?? 'position';
    case 'msa':
      // A row click picks one sequence of the alignment.
      return configColumn('seq_id_col') ?? 'seq_id';
    case 'lollipop':
      // A stem is a variant at a position of a feature. Its label names it
      // when one is bound; otherwise the pick is the position, whose feature
      // half travels in the `residue_selection` pair like the protein kinds.
      return named ?? configColumn('label_col') ?? configColumn('position_col') ?? 'position';
    default:
      return undefined;
  }
}

/**
 * The filter entry an advanced_viz renderer emits for a set of selected
 * values, in the same `scatter_selection` shape FigureRenderer produces.
 *
 * Deliberately not a source of its own (the phylogeny's `tree_selection` is,
 * and that is exactly why its selections cross-filter but can never become an
 * analysis group: `SELECTION_SOURCES` in selectionGroups.ts does not list it).
 * Reusing `scatter_selection` means these renderers reach the Analysis panel
 * through the path scatter figures already use. Passing `[]` clears.
 */
export function advancedVizSelectionFilter(
  metadata: StoredMetadata,
  selectionColumn: string,
  values: string[],
): InteractiveFilter {
  return {
    index: metadata.index,
    value: values,
    source: 'scatter_selection',
    column_name: selectionColumn,
    interactive_component_type: 'MultiSelect',
    metadata: {
      dc_id: metadata.dc_id,
      column_name: selectionColumn,
      interactive_component_type: 'MultiSelect',
      selection_column: selectionColumn,
    },
  };
}

/** A genomic region as a `genome_view` brush reports it. */
export interface GenomeRegionSelection {
  /** Chromosomes the brush covers, in genome order. */
  chroms: string[];
  /** Position range inside the chromosome, or null when the brush spans
   *  several: one `[start, end]` pair has no meaning across contigs. */
  range: [number, number] | null;
}

/** Index suffix of the position-range half of a region selection.
 *
 *  `mergeFiltersBySource` dedupes by `(index, source)`, so the two halves of a
 *  region need two keys. Suffixing the emitting component's own index keeps
 *  them recognisably one selection, keeps "clear" able to drop each half, and
 *  keeps `clearFiltersBySource(filters, 'genome_selection')` able to drop
 *  both. */
export const GENOME_POS_INDEX_SUFFIX = '::pos';

export function genomePosFilterIndex(componentIndex: string): string {
  return `${componentIndex}${GENOME_POS_INDEX_SUFFIX}`;
}

/** True for either half of a genome region pair (`source: 'genome_selection'`). */
export function isRegionFilter(f: InteractiveFilter): boolean {
  return f.source === 'genome_selection';
}

/** A genome region or a residue range: a place to look, never a subset a
 *  card should summarise (see `cardScopedFilters`). */
function isLocusFilter(f: InteractiveFilter): boolean {
  return isRegionFilter(f) || isResidueFilter(f);
}

/**
 * The filters a card reads: every active filter except a genome region or a
 * residue range, unless the card opts in with `follow_region_filter`.
 *
 * A region is a place to look, not a subset to summarise, so a card keeps
 * summarising the whole collection while the tracks follow the locus (or the
 * protein tiles follow the residue pick). Mirrors
 * `depictio/api/v1/region_scope.py`, which applies the same rule server-side
 * in `bulk_compute_cards` and the card preview routes.
 */
export function cardScopedFilters(
  filters: InteractiveFilter[],
  card: { follow_region_filter?: unknown } | null | undefined,
): InteractiveFilter[] {
  if (card?.follow_region_filter === true) return filters;
  return filters.some(isLocusFilter) ? filters.filter((f) => !isLocusFilter(f)) : filters;
}

/**
 * The filter pair a `genome_view` region brush emits.
 *
 * A genomic region is not a value, it is a chromosome *and* a position range,
 * and the dashboard's filter pipeline only knows columns. So the brush becomes
 * two ordinary entries the existing backend already understands:
 *
 * - a `MultiSelect` on the tile's `chr_col`, carrying the brushed chromosomes;
 * - a `RangeSlider` on the tile's `pos_col`, carrying `[start, end]`
 *   (`deltatables_utils.add_filter` turns that into
 *   `col >= start & col <= end`).
 *
 * Both carry the emitting tile's `dc_id`, so a second tile bound to the *same*
 * collection narrows immediately, and a tile on a *different* collection
 * receives them through the project's links whenever that link joins on the
 * same chromosome / position columns. Nothing new is needed server-side.
 *
 * Passing `null` (or a region with no chromosomes) returns the cleared form of
 * both entries, which `mergeFiltersBySource` drops.
 */
export function genomeRegionFilters(
  metadata: StoredMetadata,
  chrColumn: string,
  posColumn: string,
  region: GenomeRegionSelection | null,
): InteractiveFilter[] {
  const chroms = region?.chroms ?? [];
  const range = chroms.length ? (region?.range ?? null) : null;
  return [
    {
      index: metadata.index,
      value: chroms,
      source: 'genome_selection',
      column_name: chrColumn,
      interactive_component_type: 'MultiSelect',
      metadata: {
        dc_id: metadata.dc_id,
        column_name: chrColumn,
        interactive_component_type: 'MultiSelect',
        selection_column: chrColumn,
      },
    },
    {
      index: genomePosFilterIndex(metadata.index),
      // `[]` rather than `null` so both halves clear through the same rule
      // `mergeFiltersBySource` applies to every other selection source.
      value: range ?? [],
      source: 'genome_selection',
      column_name: posColumn,
      interactive_component_type: 'RangeSlider',
      metadata: {
        dc_id: metadata.dc_id,
        column_name: posColumn,
        interactive_component_type: 'RangeSlider',
        selection_column: posColumn,
      },
    },
  ];
}

/**
 * The columns one genomic tile binds for the region roles.
 *
 * Every genomic kind names these three differently (`chr_col`/`pos_col`,
 * `chromosome_col`/`position_col`, `chrom_col`/`start_col`/`end_col`,
 * `contig_col`, `chrom1_col`/`start1_col`), so the mapping from a kind's
 * config to this shape lives in one place:
 * `components/advanced_viz/genomicAxis.ts`.
 */
export interface RegionRoleColumns {
  chrom: string;
  start: string;
  /** Interval kinds only (a bin, an exon, a segment). A range filter on the
   *  end column widens the region the same way one on the start column does. */
  end?: string;
}

/**
 * Read a region back out of the dashboard's filter list, for a tile that
 * follows one instead of emitting it.
 *
 * Deliberately column-keyed rather than index-keyed: the point of the region
 * filter is that *any* tile or sidebar control naming the same chromosome and
 * position columns drives it, so a plain `Chromosome` multi-select in the left
 * panel zooms a following tile exactly as another tile's brush does. Only a
 * single chromosome yields a region: "chr1 and chr7" is not somewhere to zoom.
 *
 * Two call shapes, because the roles a kind binds are not always two columns:
 * the historical `(filters, chrColumn, posColumn)` and a role map
 * `(filters, {chrom, start, end?})` for interval kinds, where a range filter
 * on either coordinate column contributes to the region.
 */
export function regionFromFilters(
  filters: InteractiveFilter[],
  roles: RegionRoleColumns,
): { chrom: string; start: number; end: number } | null;
export function regionFromFilters(
  filters: InteractiveFilter[],
  chrColumn: string,
  posColumn: string,
): { chrom: string; start: number; end: number } | null;
export function regionFromFilters(
  filters: InteractiveFilter[],
  chrOrRoles: string | RegionRoleColumns,
  posColumn?: string,
): { chrom: string; start: number; end: number } | null {
  const roles: RegionRoleColumns =
    typeof chrOrRoles === 'string'
      ? { chrom: chrOrRoles, start: posColumn ?? '' }
      : chrOrRoles;
  let chrom: string | null = null;
  let range: [number, number] | null = null;
  for (const f of filters) {
    const column = f.column_name ?? f.metadata?.column_name;
    if (column === roles.chrom && Array.isArray(f.value)) {
      if (f.value.length !== 1) return null;
      chrom = String(f.value[0]);
    } else if (
      (column === roles.start || (roles.end && column === roles.end)) &&
      Array.isArray(f.value) &&
      f.value.length === 2
    ) {
      const lo = Number(f.value[0]);
      const hi = Number(f.value[1]);
      if (Number.isFinite(lo) && Number.isFinite(hi) && hi > lo) {
        // Start and end columns of the same interval kind describe one span,
        // so two range filters widen to their union rather than the last seen.
        range = range
          ? [Math.min(range[0], lo), Math.max(range[1], hi)]
          : [lo, hi];
      }
    }
  }
  if (!chrom) return null;
  // A chromosome with no range is still somewhere to zoom: the contig.
  if (!range) return { chrom, start: 0, end: Number.POSITIVE_INFINITY };
  return { chrom, start: range[0], end: range[1] };
}

/** Index suffix of the position-range half of a residue selection, the
 *  `::pos` of a genome region for the same reason (two halves, two keys). */
export const RESIDUE_RANGE_INDEX_SUFFIX = '::res';

export function residueRangeFilterIndex(componentIndex: string): string {
  return `${componentIndex}${RESIDUE_RANGE_INDEX_SUFFIX}`;
}

/** Index suffix of the chain half of a residue pick on a complex, which
 *  numbers each chain on its own (`chainSelectionFilter` builds the entry). */
export const CHAIN_SELECTION_INDEX_SUFFIX = '::chain';

export function chainSelectionFilterIndex(componentIndex: string): string {
  return `${componentIndex}${CHAIN_SELECTION_INDEX_SUFFIX}`;
}

/** True for either half of a residue selection (`source: 'residue_selection'`). */
export function isResidueFilter(f: InteractiveFilter): boolean {
  return f.source === 'residue_selection';
}

/** The column a filter applies to, wherever it carries it. */
export function filterColumn(f: InteractiveFilter): string | undefined {
  return f.column_name ?? f.metadata?.column_name;
}

/** What a protein tile picked: a residue range on one entity. */
export interface ResidueRangeSelection {
  /** Column naming the protein (or family) the range belongs to. `null` or
   *  omitted when the bound tables hold one entity only: the range half is
   *  then emitted alone. */
  entityColumn?: string | null;
  /** Column holding the 1-based residue number. */
  positionColumn: string;
  /** The picked entity. `null` with a range means "this range, any entity". */
  entity?: string | null;
  /** First residue of the range; `null` clears the selection. */
  start: number | null;
  /** Last residue, inclusive. Defaults to `start` (a single residue). */
  end?: number | null;
  /** The emitting tile's DC, for the backend's link resolution. */
  dcId?: string;
}

/**
 * The filter pair a protein tile emits for a residue range.
 *
 * The genome region's shape (`genomeRegionFilters`) on protein coordinates:
 * a `MultiSelect` on the entity column carrying `[entity]` and a `RangeSlider`
 * on the position column carrying `[start, end]` (inclusive, so a single
 * residue is `[p, p]`). Both are ordinary column filters, so a residue or
 * variant table naming the same two columns narrows with no server change,
 * and every protein tile reads the range back by column name
 * (`residueRangeFromFilters`), whichever tile or sidebar control set it.
 *
 * `start: null` returns the cleared form of both halves (`value: []`), which
 * `mergeFiltersBySource` drops: that is how a tile resets its selection.
 */
export function residueRangeFilters(
  index: string,
  selection: ResidueRangeSelection,
): InteractiveFilter[] {
  const { entityColumn, positionColumn, dcId } = selection;
  const lo = selection.start;
  const hiRaw = selection.end ?? selection.start;
  const valid = lo != null && hiRaw != null && Number.isFinite(lo) && Number.isFinite(hiRaw);
  const range: [number, number] | [] = valid
    ? [Math.round(Math.min(lo, hiRaw)), Math.round(Math.max(lo, hiRaw))]
    : [];
  const entity = valid && selection.entity != null && selection.entity !== ''
    ? [String(selection.entity)]
    : [];
  const half = (
    halfIndex: string,
    value: string[] | [number, number] | [],
    column: string,
    componentType: 'MultiSelect' | 'RangeSlider',
  ): InteractiveFilter => ({
    index: halfIndex,
    value,
    source: 'residue_selection',
    column_name: column,
    interactive_component_type: componentType,
    metadata: {
      dc_id: dcId,
      column_name: column,
      interactive_component_type: componentType,
      selection_column: column,
    },
  });
  const rangeHalf = half(residueRangeFilterIndex(index), range, positionColumn, 'RangeSlider');
  return entityColumn
    ? [half(index, entity, entityColumn, 'MultiSelect'), rangeHalf]
    : [rangeHalf];
}

/** The entity a filter list names on `entityColumn`, when it names exactly
 *  one (any source: another tile's pick, a sidebar selector). */
export function residueEntityFromFilters(
  filters: readonly InteractiveFilter[],
  entityColumn: string | null | undefined,
): string | null {
  if (!entityColumn) return null;
  let entity: string | null = null;
  for (const f of filters) {
    if (filterColumn(f) !== entityColumn) continue;
    const v = f.value;
    if (Array.isArray(v)) {
      if (v.length === 0) continue;
      if (v.length !== 1) return null;
      entity = String(v[0]);
    } else if (typeof v === 'string' || typeof v === 'number') {
      entity = String(v);
    }
  }
  return entity;
}

/**
 * Read a residue range back out of the filter list, BY COLUMN NAME and from
 * any source, so another tile's click, a sidebar position slider or a table
 * of the same columns all drive a following tile the same way
 * (`regionFromFilters` for proteins).
 *
 * Returns `null` when no range is set on `positionColumn`, or when the entity
 * column carries several entities (a range on "A and B" is nowhere to look).
 * `entity` is `null` when nothing names one: the range then applies to
 * whichever entity the reading tile shows.
 */
export function residueRangeFromFilters(
  filters: readonly InteractiveFilter[],
  entityColumn: string | null | undefined,
  positionColumn: string,
): { entity: string | null; start: number; end: number } | null {
  let range: [number, number] | null = null;
  let entityValues = 0;
  let entity: string | null = null;
  for (const f of filters) {
    const column = filterColumn(f);
    if (entityColumn && column === entityColumn) {
      const v = f.value;
      const values = Array.isArray(v) ? v : v == null || v === '' ? [] : [v];
      if (values.length === 0) continue;
      entityValues = values.length;
      entity = values.length === 1 ? String(values[0]) : null;
    } else if (column === positionColumn && Array.isArray(f.value) && f.value.length === 2) {
      const lo = Number(f.value[0]);
      const hi = Number(f.value[1]);
      if (!Number.isFinite(lo) || !Number.isFinite(hi)) continue;
      const span: [number, number] = [Math.min(lo, hi), Math.max(lo, hi)];
      // Several range filters on the position column (a tile's pick and a
      // sidebar slider) all apply server-side, so what is left is their
      // intersection; an empty intersection selects nothing.
      range = range ? [Math.max(range[0], span[0]), Math.min(range[1], span[1])] : span;
    }
  }
  if (!range || range[0] > range[1]) return null;
  if (entityValues > 1) return null;
  return { entity, start: range[0], end: range[1] };
}

/**
 * `filters` without the position halves of every `residue_selection` on
 * `positionColumn`, whichever tile emitted them.
 *
 * For a tile that draws the whole protein along that column (a lollipop, a
 * per-residue profile): a picked range is a place to look, so the tile keeps
 * every position and shades the range instead of being clipped to it. The
 * entity half stays, so a pick on another protein still switches the tile to
 * that protein's rows.
 */
export function withoutResidueRanges(
  filters: InteractiveFilter[],
  positionColumn: string,
): InteractiveFilter[] {
  return filters.filter(
    (f) =>
      !(
        isResidueFilter(f) &&
        filterColumn(f) === positionColumn &&
        f.index.endsWith(RESIDUE_RANGE_INDEX_SUFFIX)
      ),
  );
}

/** The filter list a residue-emitting tile renders against: every filter
 *  except both halves of its own `residue_selection`, so it keeps drawing the
 *  whole protein and rings its pick instead of hiding the rest. */
export function filtersExcludingOwnResidue(
  filters: InteractiveFilter[],
  componentIndex: string,
): InteractiveFilter[] {
  const resIndex = residueRangeFilterIndex(componentIndex);
  return filters.filter(
    (f) => !(isResidueFilter(f) && (f.index === componentIndex || f.index === resIndex)),
  );
}

/**
 * The filter list a selection-source component should render against: every
 * dashboard filter *except* the one it emitted itself.
 *
 * A component that filtered on its own selection would only ever draw the rows
 * it already picked, so the selection could never be widened again. It keeps
 * every row and dims the excluded ones instead.
 */
export function filtersExcludingOwn(
  filters: InteractiveFilter[],
  componentIndex: string,
  source: InteractiveFilterSource,
): InteractiveFilter[] {
  return filters.filter((f) => !(f.index === componentIndex && f.source === source));
}

/**
 * The crossfilter rule for a selector tile: every dashboard filter except its
 * own selection AND every filter, from any source, on the column it selects
 * on (`selectionColumn`, see `advancedVizSelectionColumn`).
 *
 * Filters match by column name across data collections, so a protein tile's
 * residue pick (entity half on `entity`) or a sidebar picker on the same
 * column would otherwise narrow a scatter that selects on `entity` to the one
 * point it names, and the reader could no longer pick another. The tile keeps
 * every point and marks the named ones instead (`valuesOnColumn`). Filters on
 * any other column still narrow it. Without a selection column this is
 * `filtersExcludingOwn`.
 */
export function filtersForSelector(
  filters: InteractiveFilter[],
  componentIndex: string,
  source: InteractiveFilterSource,
  selectionColumn: string | null | undefined,
): InteractiveFilter[] {
  const others = filtersExcludingOwn(filters, componentIndex, source);
  return selectionColumn ? others.filter((f) => filterColumn(f) !== selectionColumn) : others;
}

/**
 * Every value the filters name on `column` (any source), as strings. With
 * `exclude`, the entry that component emitted from that source is skipped.
 */
export function valuesOnColumn(
  filters: readonly InteractiveFilter[],
  column: string | null | undefined,
  exclude?: { index: string; source: InteractiveFilterSource },
): Set<string> {
  const out = new Set<string>();
  if (!column) return out;
  for (const f of filters) {
    if (filterColumn(f) !== column) continue;
    if (exclude && f.index === exclude.index && f.source === exclude.source) continue;
    const v = f.value;
    const values = Array.isArray(v) ? v : v == null || v === '' ? [] : [v];
    for (const x of values) if (x != null && x !== '') out.add(String(x));
  }
  return out;
}

/** Whether the dashboard still holds a non-empty selection this component emitted. */
export function hasOwnSelection(
  filters: InteractiveFilter[],
  componentIndex: string,
  source: InteractiveFilterSource,
): boolean {
  return filters.some(
    (f) =>
      f.index === componentIndex &&
      f.source === source &&
      Array.isArray(f.value) &&
      f.value.length > 0,
  );
}

/**
 * The sources a tile's "clear selection" affordance covers: the selections a
 * reader makes by pointing at the tile itself (a lasso, a row pick, a map
 * polygon, a thumbnail, a genome brush).
 *
 * Left out on purpose: `tree_selection` and `axis_selection`, whose tiles
 * carry their own clear control and keep their visual state locally, so a
 * clear from the chrome would drop the filter and leave the clade or the brush
 * drawn; and `group_filter`, which is never in the user's filter list.
 */
const CLEARABLE_SELECTION_SOURCES: ReadonlySet<InteractiveFilterSource> = new Set([
  'scatter_selection',
  'table_selection',
  'map_selection',
  'image_selection',
  'genome_selection',
  'residue_selection',
]);

/** The selection one tile currently contributes to the dashboard. */
export interface OwnSelection {
  /** The non-empty entries this tile emitted, the region's position half
   *  included. Empty when the tile has nothing selected. */
  filters: InteractiveFilter[];
  /** How many values are selected, for the "Clear selection (N)" label. A
   *  region's position half is a range, not picked values, so it adds none. */
  count: number;
}

/**
 * Read back the selection a tile has emitted, keyed on its own index (and the
 * `::pos` / `::res` index of a region's or residue range's second half, and
 * the `::chain` index of a residue pick on a complex) so another tile's
 * selection on the same column never counts as this one's.
 */
export function ownSelection(
  filters: readonly InteractiveFilter[],
  componentIndex: string,
): OwnSelection {
  const posIndex = genomePosFilterIndex(componentIndex);
  const resIndex = residueRangeFilterIndex(componentIndex);
  const chainIndex = chainSelectionFilterIndex(componentIndex);
  const halves = new Set([componentIndex, posIndex, resIndex, chainIndex]);
  const own: InteractiveFilter[] = [];
  let count = 0;
  let residueHalfOnly = false;
  for (const f of filters) {
    if (!halves.has(f.index)) continue;
    if (!f.source || !CLEARABLE_SELECTION_SOURCES.has(f.source)) continue;
    const v = f.value;
    if (v == null || (Array.isArray(v) && v.length === 0)) continue;
    own.push(f);
    if (f.index === componentIndex) count += Array.isArray(v) ? v.length : 1;
    else if (f.index === resIndex || f.index === chainIndex) residueHalfOnly = true;
  }
  // A residue range on a single-entity tile has no entity half; it is still
  // one selection the reader can clear (so is a chain pick left on its own).
  if (count === 0 && residueHalfOnly) count = 1;
  return { filters: own, count };
}

/** The cleared form of each entry, the `[]` shape `mergeFiltersBySource`
 *  drops. Emitting these one by one is what "clear this tile" means. */
export function clearedSelectionFilters(
  filters: readonly InteractiveFilter[],
): InteractiveFilter[] {
  return filters.map((f) => ({ ...f, value: [] }));
}

/**
 * Pick selection values from a Plotly ``selectedData`` / ``clickData`` event.
 * Mirrors ``extract_scatter_selection_values`` in
 * ``depictio/dash/modules/figure_component/callbacks/selection.py``.
 *
 * Plotly puts the original row identifier into ``customdata`` (an array of
 * arrays). ``selectionColumnIndex`` is the offset within each customdata row
 * that holds the value to filter on.
 */
export function extractScatterSelection(
  eventData: { points?: Array<{ customdata?: unknown }> } | null | undefined,
  selectionColumnIndex: number,
): string[] {
  if (!eventData || !eventData.points || eventData.points.length === 0) return [];

  const out: string[] = [];
  const seen = new Set<string>();
  for (const pt of eventData.points) {
    const cd = pt?.customdata;
    // Plotly may deliver per-point customdata as a plain Array, OR — when the
    // trace was built with the typed-array transport (``{dtype, bdata, shape}``)
    // and expanded by ``_fullData`` — as an object with numeric keys (``{0: 1}``).
    // Both cases support ``cd[i]`` lookup, so we just guard against scalars/null.
    if (cd == null || (typeof cd !== 'object')) continue;
    const raw = (cd as Record<number, unknown>)[selectionColumnIndex];
    if (raw === null || raw === undefined) continue;
    const v = String(raw);
    if (seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

/**
 * Pick selection values from AG Grid's selected rows. Mirrors
 * ``extract_row_selection_values`` in
 * ``depictio/dash/modules/table_component/callbacks/selection.py``.
 */
export function extractRowSelection(
  selectedRows: Array<Record<string, unknown>> | null | undefined,
  selectionColumn: string,
): string[] {
  if (!selectedRows || selectedRows.length === 0) return [];

  const out: string[] = [];
  const seen = new Set<string>();
  for (const row of selectedRows) {
    const raw = row?.[selectionColumn];
    if (raw === null || raw === undefined) continue;
    const v = String(raw);
    if (seen.has(v)) continue;
    seen.add(v);
    out.push(v);
  }
  return out;
}

/**
 * Add or replace a filter, deduping by ``(index, source)``.
 *
 * Regular interactive components have ``source === undefined`` and are keyed
 * by ``index`` alone. Selection sources (scatter/table/map) coexist with the
 * same ``index`` because a chart can both be filtered as a passive component
 * AND emit a selection — so we key by the tuple.
 *
 * Passing ``value === null | undefined | []`` clears the matching entry.
 *
 * A ``residue_selection`` also replaces the ones other tiles made on the same
 * column: the protein tiles of a tab share one residue range, so the last
 * gesture wins instead of intersecting with an older pick (a click on residue
 * 22 in 3D then a brush over 40-70 in the alignment would match nothing).
 */
export function mergeFiltersBySource(
  filters: InteractiveFilter[],
  next: InteractiveFilter,
): InteractiveFilter[] {
  const sameResidueColumn = (f: InteractiveFilter) =>
    isResidueFilter(next) &&
    isResidueFilter(f) &&
    filterColumn(f) != null &&
    filterColumn(f) === filterColumn(next);
  const matches = (f: InteractiveFilter) =>
    (f.index === next.index && (f.source ?? null) === (next.source ?? null)) ||
    sameResidueColumn(f);

  const cleared =
    next.value === null ||
    next.value === undefined ||
    (Array.isArray(next.value) && next.value.length === 0);

  if (cleared) return filters.filter((f) => !matches(f));

  const without = filters.filter((f) => !matches(f));
  return [...without, next];
}

/**
 * Remove every filter with the given ``source``. Pass ``index`` to scope to a
 * single component (e.g. clearing one chart's lasso without touching others).
 */
export function clearFiltersBySource(
  filters: InteractiveFilter[],
  source: InteractiveFilterSource,
  index?: string,
): InteractiveFilter[] {
  return filters.filter((f) => {
    if (f.source !== source) return true;
    if (index !== undefined && f.index !== index) return true;
    return false;
  });
}

/**
 * True when at least one filter in the list comes from a selection event
 * (used to surface a "Clear all selections" affordance in the sidebar).
 */
export function hasSelectionFilters(filters: InteractiveFilter[]): boolean {
  return filters.some((f) => f.source !== undefined);
}

/**
 * Enrich an emitted filter with its source component's ``dc_id`` (looked up
 * from the dashboard's ``stored_metadata`` by index) so the backend's
 * link-resolver can map cross-DC filters. Interactive renderers don't carry
 * their own dc_id in the emitted shape — this lookup is the single source of
 * truth for the view and editor apps. Returns the update unchanged when a
 * dc_id is already present or no matching source can be found.
 */
export function enrichFilterWithDcId(
  update: InteractiveFilter,
  storedMetadata: StoredMetadata[] | undefined,
): InteractiveFilter {
  if (update.metadata?.dc_id) return update;
  const src = (storedMetadata ?? []).find((m) => String(m.index) === String(update.index));
  const dcId = src?.dc_id;
  if (!dcId) return update;
  return {
    ...update,
    metadata: {
      ...(update.metadata ?? {}),
      dc_id: dcId,
      column_name: update.column_name ?? update.metadata?.column_name,
      interactive_component_type:
        update.interactive_component_type ?? update.metadata?.interactive_component_type,
    },
  };
}

/**
 * Whether this component can produce a selection that becomes an analysis
 * group ("select & compare", issue #89).
 *
 * One predicate for all four selection sources, so the capability marker the
 * chrome draws and the gates the renderers use can never disagree about what
 * is selectable. Each arm mirrors its renderer's own enable check:
 *
 * - `figure` — only scatter / scatter_3d carry the per-row customdata a
 *   meaningful selection needs; aggregated visus emit per-bin envelopes.
 * - `table`  — row selection is opt-in per component.
 * - `map`    — see `isMapSelectionEnabled` (choropleth is excluded).
 * - `image`  — a gallery selects thumbnails, which requires an image column.
 * - `advanced_viz`: see `advancedVizSelectionColumn`, i.e. the embedding and
 *   Manhattan scatters, each opt-in and each needing a resolvable column.
 *
 * `hasHandler` folds in the caller's "is anyone listening" check, so read-only
 * hosts (catalog, project previews) advertise nothing.
 */
export function supportsSelectionGrouping(
  metadata: StoredMetadata,
  hasHandler: boolean,
): boolean {
  if (!hasHandler) return false;
  switch (metadata.component_type) {
    case 'figure':
      return (
        Boolean(metadata.selection_enabled) &&
        (metadata.visu_type === 'scatter' || metadata.visu_type === 'scatter_3d')
      );
    case 'table':
      return Boolean(metadata.row_selection_enabled);
    case 'map':
      return isMapSelectionEnabled(metadata, true);
    case 'image':
      return Boolean(metadata.image_column);
    case 'advanced_viz':
      return advancedVizSelectionColumn(metadata) !== undefined;
    default:
      return false;
  }
}
