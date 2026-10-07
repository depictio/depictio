/**
 * What the Guide's live demos are made of, picked from the dashboard itself.
 *
 * The demos use the dashboard's own components rather than invented ones: a
 * real key figure and a real filter on the same data, a real section that
 * folds. These are the pure choices behind them; the viewer does the fetching.
 */

import type { FilterSectionSpec, StoredMetadata } from '../api';
import { isStripSection } from '../components/interactive/strip/stripLayout';
import { advancedVizSelectionColumn, supportsSelectionGrouping } from '../selection';
import { groupDisplaysForKind, type GroupDisplays } from '../splitPanels';
import { sectionComponents } from '../utils/groupInteractive';
import { readMultiqcSelection } from '../utils/multiqcSelection';

/** A key figure and a filter whose values change it. */
export interface GuideFilterDemoPick {
  card: StoredMetadata;
  control: StoredMetadata;
}

/** Controls that pick values from a list: the ones a reader can try at once. */
const CATEGORICAL = new Set(['MultiSelect', 'Select', 'SegmentedControl']);

const isCard = (m: StoredMetadata) => m.component_type === 'card' && Boolean(m.dc_id);
const isControl = (m: StoredMetadata) =>
  m.component_type === 'interactive' && Boolean(m.dc_id) && Boolean(m.column_name);
const isCategorical = (m: StoredMetadata) =>
  CATEGORICAL.has(String(m.interactive_component_type ?? ''));

/**
 * The first card that a filter on the same data collection can change, with
 * that filter — a categorical one when there is one. A card with no filter on
 * its data falls back to the first card and the first filter: the server
 * carries a filter across linked data collections, so it may still apply.
 */
export function pickFilterDemo(
  components: readonly StoredMetadata[],
): GuideFilterDemoPick | null {
  const cards = components.filter(isCard);
  const controls = components.filter(isControl);
  const ordered = [...controls.filter(isCategorical), ...controls.filter((m) => !isCategorical(m))];
  for (const card of cards) {
    const control = ordered.find((c) => c.dc_id === card.dc_id);
    if (control) return { card, control };
  }
  return cards[0] && ordered[0] ? { card: cards[0], control: ordered[0] } : null;
}

/** A section that folds, with what it holds. */
export interface GuideDemoSection {
  spec: FilterSectionSpec;
  members: StoredMetadata[];
}

/**
 * The sections of a tab that fold, in canvas order: named, holding something,
 * and neither `plain` (a heading with no fold) nor a filter bar.
 */
export function foldableSectionsOf(
  components: readonly StoredMetadata[],
  gridSections: readonly FilterSectionSpec[] | null | undefined,
): GuideDemoSection[] {
  return sectionComponents([...components], [...(gridSections ?? [])])
    .filter(
      (s) =>
        s.sectionName &&
        s.members.length > 0 &&
        s.spec?.appearance !== 'plain' &&
        !isStripSection(s.spec),
    )
    .map((s) => ({
      spec: s.spec ?? { name: s.sectionName as string },
      members: s.members,
    }));
}

/**
 * The sections a "Read a tab" demo draws, out of the ones that fold: up to
 * `max`, in canvas order, around the first that holds cards — the section
 * whose folded header reads its key figures, which is the point of the demo.
 */
export function demoSectionsOf(found: readonly GuideDemoSection[], max = 2): GuideDemoSection[] {
  if (found.length <= max) return [...found];
  const anchor = Math.max(0, found.findIndex(hasCards));
  const start = Math.max(0, Math.min(anchor, found.length - max));
  return found.slice(start, start + max);
}

/** Whether a section holds a key figure, which its folded header then reads. */
export function hasCards(section: GuideDemoSection): boolean {
  return section.members.some((m) => m.component_type === 'card');
}

// ---------------------------------------------------------------------------
// Picking from the tab family
// ---------------------------------------------------------------------------

/** What a pick reads of a tab's document. */
export interface GuideFamilyDoc {
  stored_metadata?: readonly StoredMetadata[] | null;
}

/**
 * A component picked from the family, the tab it belongs to (what it is
 * fetched and computed against), or why there is none yet.
 */
export type GuideFamilyPick =
  | { status: 'found'; metadata: StoredMetadata; dashboardId: string }
  /** `need`: the tab whose document has to be fetched before deciding. */
  | { status: 'pending'; need: string }
  | { status: 'none' };

/**
 * Pick a component from the tab family: `order` is the tabs to look in, the
 * open tab first; `docFor` their documents (`undefined` while not fetched,
 * `null` when the fetch failed); `rank` scores a component, lower is better,
 * `null` for one that will not do.
 *
 * By default the first tab with any candidate wins, its best one taken — the
 * reader's own tab before a sibling's, whatever the sibling has. With
 * `acrossTabs`, the best rank in the whole family wins instead (a rank of 0
 * stops the search where it is found): for a pick that only works with the
 * right partner, like a table whose rows key the same column as the figure.
 */
export function pickFromFamily(
  order: readonly string[],
  docFor: (id: string) => GuideFamilyDoc | null | undefined,
  rank: (m: StoredMetadata) => number | null,
  opts: { acrossTabs?: boolean } = {},
): GuideFamilyPick {
  let best: { metadata: StoredMetadata; dashboardId: string; rank: number } | null = null;
  for (const id of order) {
    const doc = docFor(id);
    if (doc === undefined) return { status: 'pending', need: id };
    if (!doc) continue;
    for (const m of doc.stored_metadata ?? []) {
      const r = rank(m);
      if (r === null) continue;
      if (!best || r < best.rank) best = { metadata: m, dashboardId: id, rank: r };
    }
    if (best && (!opts.acrossTabs || best.rank === 0)) break;
  }
  return best
    ? { status: 'found', metadata: best.metadata, dashboardId: best.dashboardId }
    : { status: 'none' };
}

/** The tabs to look in: the open tab, then the others in sidebar order. */
export function familyOrder(currentId: string, tabIds: readonly string[]): string[] {
  return [currentId, ...tabIds.filter((id) => id !== currentId)];
}

const NUMERIC_AGGREGATIONS = new Set([
  'mean',
  'average',
  'median',
  'sum',
  'std',
  'variance',
  'min',
  'max',
  'range',
]);

/** A card whose number moves with what is selected: an average, a median. */
const isNumericCard = (m: StoredMetadata) =>
  NUMERIC_AGGREGATIONS.has(String(m.aggregation ?? '').toLowerCase());

const isFloatingMap = (m: StoredMetadata) =>
  m.component_type === 'map' && m.placement === 'floating';

/** A figure that sums up a tab: it links to it, in its header or its row. */
const linksToTab = (m: StoredMetadata) => typeof m.link === 'string' && m.link.startsWith('tab:');

/**
 * Which of the family's components the Guide shows a kind of tile's actions
 * on: one that carries the most of them. A scatter a selection can be made on
 * shows the reset and the lasso, a table with row selection its checkboxes.
 *
 * With `secondTo`, a second advanced view beside that one (see
 * `secondViewRank`).
 */
export function actionsTileRank(
  type: string,
  opts: { secondTo?: StoredMetadata | null } = {},
): (m: StoredMetadata) => number | null {
  if (opts.secondTo !== undefined) return secondViewRank(opts.secondTo);
  return (m) => {
    if (m.component_type !== type) return null;
    switch (type) {
      case 'figure':
        // Selection first; a link to a tab breaks the tie, being the only
        // way to show the row's "open in its tab" (the header's link, in the
        // minimal style).
        return (supportsSelectionGrouping(m, true) ? 0 : 2) + (linksToTab(m) ? 0 : 1);
      case 'card':
        return m.dc_id ? 0 : null;
      case 'table':
        return m.row_selection_enabled ? 0 : 1;
      case 'map':
        // A floating map draws in its own panel, beside the tab; any will do
        // in a tile, but one from the grid is the one readers know as a tile.
        if (isFloatingMap(m)) return 2;
        return supportsSelectionGrouping(m, true) ? 0 : 1;
      case 'advanced_viz': {
        if (supportsSelectionGrouping(m, true)) return 0;
        // Heavy to draw a second time, and a tree keys its plot by a page-wide
        // id that a copy beside the original would share.
        if (m.viz_kind === 'phylogenetic') return 3;
        if (m.viz_kind === 'complex_heatmap') return 2;
        return 1;
      }
      case 'text': {
        const body = typeof m.body === 'string' ? m.body : '';
        if (!body.trim() && !m.title) return null;
        // A link to a tab is one of the things a text tile does.
        return /\]\((tab:|\/dashboard\/)/.test(body) ? 0 : 1;
      }
      case 'interactive':
        if (!m.dc_id || !m.column_name) return null;
        return CATEGORICAL.has(String(m.interactive_component_type ?? '')) ? 0 : 1;
      case 'multiqc':
        // A plot of the report: its zoom, its camera, its legend. The General
        // Statistics tile is a table with toggles of its own, the one tile of
        // the kind that shows none of that, so it is shown only where the
        // report has nothing else.
        return readMultiqcSelection(m as Record<string, unknown>).isGeneralStats ? 1 : 0;
      default:
        return 0;
    }
  };
}

/**
 * A second advanced view, besides `first`, for the rows it lists behind its
 * table icon. The first is picked for its selection, and the one that comes
 * up on a tab is as often a tree, which lists rows only when it has tip
 * metadata. Every other kind lists the rows it drew. Another kind than the
 * first's beats a second of the same kind, a light one a heatmap.
 */
function secondViewRank(first: StoredMetadata | null): (m: StoredMetadata) => number | null {
  return (m) => {
    if (m.component_type !== 'advanced_viz' || m.index === first?.index) return null;
    // Heavy, its rows conditional, and a copy shares its plot's page-wide id.
    if (m.viz_kind === 'phylogenetic') return null;
    const heavy = m.viz_kind === 'complex_heatmap' ? 2 : 0;
    return heavy + (first && m.viz_kind === first.viz_kind ? 1 : 0);
  };
}

/** The selection column of a figure or view a group can be drawn from. */
export function selectionColumnOf(m: StoredMetadata): string | undefined {
  if (m.component_type === 'figure') {
    return typeof m.selection_column === 'string' ? m.selection_column : undefined;
  }
  if (m.component_type === 'table') {
    return typeof m.row_selection_column === 'string' ? m.row_selection_column : undefined;
  }
  if (m.component_type === 'advanced_viz') return advancedVizSelectionColumn(m);
  return undefined;
}

/** A figure or view points can be selected on, a group drawn from: selection
 *  on, and a column naming each point. */
export function takesSelection(m: StoredMetadata): boolean {
  if (m.component_type !== 'figure' && m.component_type !== 'advanced_viz') return false;
  return supportsSelectionGrouping(m, true) && Boolean(selectionColumnOf(m));
}

/**
 * How a figure or view draws the analysis groups, by the rules the app draws
 * them by: a figure as the server renders it (`figureDrawsGroups`, which
 * colours and splits it alike), a view by its kind (`groupDisplaysForKind`).
 * Anything else draws none.
 */
export function groupDisplaysOf(m: StoredMetadata): GroupDisplays {
  if (m.component_type === 'figure') {
    const drawn = figureDrawsGroups(m);
    return { overlay: drawn, split: drawn };
  }
  if (m.component_type === 'advanced_viz') {
    return groupDisplaysForKind(typeof m.viz_kind === 'string' ? m.viz_kind : '');
  }
  return { overlay: false, split: false };
}

/**
 * The figure the Analysis demo compares the groups on, best first:
 *
 *   0. one that draws them both overlaid and split, and takes a lasso;
 *   1. one that draws them both ways, the groups made in a table;
 *   2. one that takes a lasso and colours them, in one panel (an ordination);
 *   3. one that takes a lasso but draws no group (a code figure whose code
 *      does not spread them): the groups are still made, step 3 shows nothing.
 *
 * Its Overlay / Split switch is the point of step 3, so a figure that answers
 * both beats a nearer one that answers one. A figure ranked 1 needs a table to
 * make the groups; `analysisSelectableFigureRank` is the pick without one.
 */
export function analysisFigureRank(m: StoredMetadata): number | null {
  const lasso = takesSelection(m);
  const { overlay, split } = groupDisplaysOf(m);
  if (overlay && split) return lasso ? 0 : 1;
  if (!lasso) return null;
  return overlay ? 2 : 3;
}

/** `analysisFigureRank` among the figures that take a lasso: for a dashboard
 *  where no table can make the groups the best figure draws. */
export function analysisSelectableFigureRank(m: StoredMetadata): number | null {
  return takesSelection(m) ? analysisFigureRank(m) : null;
}

/** Plotly figures the server draws whole from its frame, columns it cannot
 *  reason about, so it never colours or splits them by group: mirrors
 *  `_WHOLE_FRAME_VISU` (depictio/api/v1/services/figure/figure_builder.py). */
const WHOLE_FRAME_VISU = new Set([
  'heatmap',
  'scatter_matrix',
  'parallel_coordinates',
  'parallel_categories',
  'imshow',
  'scatter_geo',
  'choropleth',
]);

/**
 * Whether the server colours this figure by the analysis groups, and splits
 * it into a panel per group: a figure built in the editor, unless drawn whole
 * from its frame; a code figure only when its code spreads
 * `depictio_group_kwargs`, the same kwargs, which carry the split too.
 */
export function figureDrawsGroups(m: StoredMetadata): boolean {
  if (m.mode !== 'code') return !WHOLE_FRAME_VISU.has(String(m.visu_type ?? '').toLowerCase());
  const code = typeof m.code_content === 'string' ? m.code_content : '';
  return code.includes('depictio_group_kwargs');
}

/** The column a figure or view names its points by: its selection column, or
 *  a view's sample column. What a table's ticked rows must be keyed on for a
 *  group made there to find the figure's points. */
function pointColumnOf(m: StoredMetadata): string | undefined {
  const selection = selectionColumnOf(m);
  if (selection) return selection;
  const config = (m.config ?? {}) as Record<string, unknown>;
  return typeof config.sample_id_col === 'string' && config.sample_id_col
    ? config.sample_id_col
    : undefined;
}

/**
 * A table whose rows can be ticked into a group: best one keying its rows on
 * the column that names the figure's points, so a group made on either is
 * drawn on the other, then one on the figure's data, then any.
 *
 * Not any, for a figure that takes no lasso: the table is then the only way
 * to make the groups it draws, and one that cannot reach its points would
 * leave step 3 empty. None of those is `null`, and the demo picks a figure
 * that takes a lasso instead.
 */
export function analysisTableRank(figure: StoredMetadata | null) {
  const column = figure ? pointColumnOf(figure) : undefined;
  const dcId = figure?.dc_id;
  const only = figure !== null && !takesSelection(figure);
  return (m: StoredMetadata): number | null => {
    if (m.component_type !== 'table' || !m.row_selection_enabled) return null;
    const own = selectionColumnOf(m);
    if (!own) return null;
    if (!figure || own === column) return 0;
    if (dcId && m.dc_id === dcId) return 1;
    return only ? null : 2;
  };
}

/**
 * A card to read per group: on the data the group was made on, and one whose
 * value differs from group to group (a median, not a count).
 */
export function analysisCardRank(dcIds: readonly (string | undefined)[]) {
  const same = new Set(dcIds.filter(Boolean));
  return (m: StoredMetadata): number | null => {
    if (m.component_type !== 'card' || !m.dc_id) return null;
    const near = same.has(m.dc_id);
    if (near && isNumericCard(m)) return 0;
    if (near) return 1;
    return isNumericCard(m) ? 2 : 3;
  };
}
