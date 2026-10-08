/**
 * A highlight: a figure that lives on another tab, shown again on this one.
 *
 * A landing page's showcase tiles are figures whose home is the tab that
 * explains them. A highlight shows one without copying it: the figure is
 * rendered from its own definition, on its own tab, so an edit there shows
 * here too. The highlight only says where the figure is (`source_tab` or
 * `source_dashboard_id`, and `source_component`) and how to draw it here
 * (`figure_style`, `minimal` unless set; `title`, `subtitle`, `icon_name`,
 * `icon_color`, `hide_legend`, each taking the source's when unset).
 *
 * The rules are kept here, free of React and of the network, so they can be
 * tested: which tab, which figure, what metadata the tile renders with, and
 * what "Highlight on…" adds to the tab it highlights on. HighlightBlock.tsx
 * does the fetching. Mirrors HighlightLiteComponent in
 * depictio/models/components/lite.py.
 */
import type { DashboardData, FigureStyleRequest, StoredMetadata } from '../api';
import { copyComponentToTab } from './copyToTab';
import { normalizeFigureStyle } from './figureStyle';
import type { TabLinkResolver, TabLinkTarget } from './tabLinks';
import { tabLinkKey } from './tabLinks';

/** What a highlight can show: a server-rendered figure, which it restyles, or
 *  an advanced visualisation, drawn as on its tab. */
const HIGHLIGHTABLE_TYPES = new Set(['figure', 'advanced_viz']);

export function canHighlight(m: Pick<StoredMetadata, 'component_type'>): boolean {
  return HIGHLIGHTABLE_TYPES.has(m.component_type);
}

export type HighlightRef = Pick<
  StoredMetadata,
  'source_tab' | 'source_dashboard_id' | 'source_component'
>;

const text = (v: unknown): string => (typeof v === 'string' ? v.trim() : '');

const OBJECT_ID = /^[0-9a-f]{24}$/i;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * The tab a highlight looks on: its id when the family knows it, else the tab
 * of that name. The id goes first because the editor writes it and a rename
 * does not change it; the name takes over when the id is unknown, as after a
 * re-import, which mints new ids. Without a resolver (a host with no tab
 * family), a written id is used as is, with no link.
 */
export function resolveHighlightTab(
  ref: HighlightRef,
  resolve: TabLinkResolver | null,
): { dashboardId: string | null; link: TabLinkTarget | null } {
  const id = text(ref.source_dashboard_id);
  const name = text(ref.source_tab);
  const link = (id && resolve?.(id)) || (name && resolve?.(name)) || null;
  if (link?.dashboardId) return { dashboardId: link.dashboardId, link };
  if (id) return { dashboardId: id, link };
  // A YAML author may have put the id in `source_tab`.
  if (OBJECT_ID.test(name)) return { dashboardId: name, link };
  return { dashboardId: null, link };
}

export type HighlightSourceResult =
  | { ok: true; component: StoredMetadata }
  | { ok: false; reason: 'missing' | 'unsupported'; component?: StoredMetadata };

/**
 * The component `ref` names on its tab: the one with that index, else the one
 * with that title (case and spacing ignored, first match). Found but of a type
 * a highlight cannot show is reported as such rather than as missing.
 */
export function findHighlightSource(
  components: StoredMetadata[] | undefined,
  ref: string | undefined,
): HighlightSourceResult {
  const wanted = text(ref);
  const all = components ?? [];
  if (!wanted) return { ok: false, reason: 'missing' };
  const key = tabLinkKey(wanted);
  const found =
    all.find((m) => String(m.index) === wanted) ??
    all.find((m) => canHighlight(m) && text(m.title) && tabLinkKey(text(m.title)) === key) ??
    all.find((m) => text(m.title) && tabLinkKey(text(m.title)) === key);
  if (!found) return { ok: false, reason: 'missing' };
  if (!canHighlight(found)) return { ok: false, reason: 'unsupported', component: found };
  return { ok: true, component: found };
}

/**
 * How a highlight names its figure: the figure's index when it is readable
 * (a template's `alpha-boxplot-by-group`), else its title when no other
 * component of its tab has the same one. An index minted by the editor is a
 * UUID that a re-import replaces, and a title is what survives it.
 */
export function highlightSourceRef(
  source: StoredMetadata,
  components: StoredMetadata[] | undefined,
): string {
  const index = String(source.index);
  if (!UUID.test(index)) return index;
  const title = text(source.title);
  if (!title) return index;
  const key = tabLinkKey(title);
  const same = (components ?? []).filter((m) => text(m.title) && tabLinkKey(text(m.title)) === key);
  return same.length === 1 ? title : index;
}

/**
 * The metadata a highlight tile renders with: the source's (data binding,
 * plot definition), under the highlight's own identity (index, section) and
 * look. Selection is switched off on a figure: the server reads the selection
 * column from the component stored under the emitting index, which is the
 * highlight, and it has none.
 */
export function highlightMetadata(highlight: StoredMetadata, source: StoredMetadata): StoredMetadata {
  const merged: StoredMetadata = {
    ...source,
    index: highlight.index,
    section: highlight.section,
    title: text(highlight.title) || source.title,
    subtitle: text(highlight.subtitle) || source.subtitle,
    icon_name: text(highlight.icon_name) || source.icon_name,
    icon_color: text(highlight.icon_color) || source.icon_color,
    hide_legend:
      typeof highlight.hide_legend === 'boolean' ? highlight.hide_legend : source.hide_legend,
    caption: text(highlight.caption) || source.caption,
    font_scale: highlight.font_scale ?? source.font_scale,
  };
  if (source.component_type === 'figure') {
    merged.figure_style = normalizeFigureStyle(highlight.figure_style) ?? 'minimal';
    merged.selection_enabled = false;
  }
  // The source's tag names the source; two components answering to it would
  // make the copy look like the original to anything that looks tags up.
  delete (merged as Record<string, unknown>).tag;
  return merged;
}

/** What the render request asks the server for, over the source's own style. */
export function highlightStyleRequest(merged: StoredMetadata): FigureStyleRequest {
  return {
    figure_style: normalizeFigureStyle(merged.figure_style) ?? 'minimal',
    header_title: Boolean(text(merged.title)),
    hide_legend: Boolean(merged.hide_legend),
  };
}

export interface HighlightOnTabInput {
  /** The figure, as stored on its own tab. */
  source: StoredMetadata;
  /** All components of its tab, to tell whether its title names it alone. */
  sourceComponents: StoredMetadata[] | undefined;
  /** Its tab: id, displayed name and `right_panel_layout_data` (for the size). */
  sourceDashboardId: string;
  sourceTabName: string;
  sourceLayoutData: unknown;
  /** The tab highlighted on, as fetched. */
  target: DashboardData;
  /** The highlight's index, a fresh UUID. */
  newId: string;
}

/**
 * The target tab with a highlight of `source` added, placed as "Copy to tab…"
 * places a copy: at the bottom, with the source's width and height. The tile
 * sets no title, subtitle or icon of its own, so it follows the source's until
 * the author gives it some.
 */
export function highlightOnTab({
  source,
  sourceComponents,
  sourceDashboardId,
  sourceTabName,
  sourceLayoutData,
  target,
  newId,
}: HighlightOnTabInput): { dashboard: DashboardData; component: StoredMetadata } {
  const highlight: StoredMetadata = {
    // The source's index for now, so the copy borrows its layout entry;
    // copyComponentToTab swaps in `newId`.
    index: source.index,
    component_type: 'highlight',
    source_tab: sourceTabName,
    source_dashboard_id: sourceDashboardId,
    source_component: highlightSourceRef(source, sourceComponents),
    last_updated: new Date().toISOString(),
  };
  return copyComponentToTab({ source: highlight, sourceLayoutData, target, newId });
}
