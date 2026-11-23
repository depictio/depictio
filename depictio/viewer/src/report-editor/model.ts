/**
 * The report editor's data model: how the layer (what the user changed) and the
 * outline (what the generator lays out) combine into the rows the page shows,
 * and the edits that write back to the layer. Pure functions, no React.
 */
import type {
  AnalysisState,
  InteractiveFilter,
  ReportCover,
  ReportDoc,
  ReportLayer,
  ReportOrientation,
  ReportOutlineEntry,
  ReportOutlineTab,
  ReportTab,
  ReportTabPlacement,
  ReportTile,
} from 'depictio-react-core';

export const EMPTY_COVER: ReportCover = { title: null, subtitle: null, authors: [], date: null };

/** A tile row as shown: the outline entry with the layer's choices on top. */
export interface TileView {
  entry: ReportOutlineEntry;
  componentId: string;
  tabId: string;
  /** The stored override, when there is one. */
  tile: ReportTile | null;
  inReport: boolean;
  inPdf: boolean;
  orientation: ReportOrientation;
  pageBreakBefore: boolean;
  /** The caption override ('' when the tile keeps its own). */
  caption: string;
  /** The section override ('' when the tile stays in its own section). */
  sectionOverride: string;
  /** The section the row sits under: the override, else the entry's own. */
  section: string | null;
  /** Where the row sorts: the stored order, else the outline's. */
  sort: number;
}

export interface TabView {
  tabId: string;
  title: string;
  placement: ReportTabPlacement;
  isMain: boolean;
  /** Section titles available to "Move to section". */
  sections: string[];
  tiles: TileView[];
}

export function findTile(layer: ReportLayer, tabId: string, componentId: string): ReportTile | null {
  return layer.tiles.find((t) => t.tab_id === tabId && t.component_id === componentId) ?? null;
}

function tileView(entry: ReportOutlineEntry, layer: ReportLayer): TileView {
  const componentId = entry.component_id as string;
  const tile = findTile(layer, entry.tab_id, componentId);
  const sectionOverride = tile?.section ?? '';
  return {
    entry,
    componentId,
    tabId: entry.tab_id,
    tile,
    inReport: tile ? tile.in_report : entry.in_report,
    inPdf: tile ? tile.in_pdf : entry.in_pdf,
    orientation: tile ? tile.orientation : entry.orientation,
    pageBreakBefore: tile ? tile.page_break_before : entry.page_break_before,
    caption: tile?.caption ?? '',
    sectionOverride,
    section: sectionOverride || entry.section,
    sort: tile?.order ?? entry.order ?? Number.MAX_SAFE_INTEGER,
  };
}

/** The tabs in report order, each with its component rows. */
export function buildTabViews(tabs: ReportOutlineTab[], layer: ReportLayer): TabView[] {
  const views = tabs.map((tab, tabIdx) => {
    const placement = layer.tabs.find((t) => t.tab_id === tab.tab_id)?.placement ?? tab.placement;
    const order = layer.tabs.find((t) => t.tab_id === tab.tab_id)?.order ?? tab.order;
    const sections = tab.entries.filter((e) => e.kind === 'section').map((e) => e.title);
    const rows = tab.entries
      .filter((e) => e.kind === 'component' && e.component_id)
      .map((e, i) => ({ view: tileView(e, layer), i }));
    rows.sort((a, b) => a.view.sort - b.view.sort || a.i - b.i);
    return {
      tabIdx,
      order,
      view: {
        tabId: tab.tab_id,
        title: tab.title,
        placement,
        isMain: tabIdx === 0,
        sections,
        tiles: rows.map((r) => r.view),
      } satisfies TabView,
    };
  });
  // The main tab stays first; the others follow by their order, then as listed.
  const [main, ...rest] = views;
  rest.sort((a, b) => (a.order ?? a.tabIdx) - (b.order ?? b.tabIdx) || a.tabIdx - b.tabIdx);
  return [main, ...rest].filter(Boolean).map((v) => v.view);
}

/** A tile record for an entry that has none yet: every field at what the
 *  outline already shows, nothing overridden (caption and section null). */
function baseTile(entry: ReportOutlineEntry): ReportTile {
  return {
    tab_id: entry.tab_id,
    component_id: entry.component_id as string,
    caption: null,
    in_report: entry.in_report,
    in_pdf: entry.in_pdf,
    order: null,
    orientation: entry.orientation,
    section: null,
    page_break_before: entry.page_break_before,
  };
}

/** Change one tile's stored choices. */
export function patchTile(
  layer: ReportLayer,
  entry: ReportOutlineEntry,
  patch: Partial<ReportTile>,
): ReportLayer {
  const existing = findTile(layer, entry.tab_id, entry.component_id as string);
  const next = { ...(existing ?? baseTile(entry)), ...patch };
  const tiles = existing
    ? layer.tiles.map((t) => (t === existing ? next : t))
    : [...layer.tiles, next];
  return { ...layer, tiles };
}

/** Move a tile one place within its tab, then write the tab's order as
 *  consecutive integers. */
export function moveTile(layer: ReportLayer, tab: TabView, from: number, to: number): ReportLayer {
  if (to < 0 || to >= tab.tiles.length || from === to) return layer;
  const ordered = [...tab.tiles];
  const [moved] = ordered.splice(from, 1);
  ordered.splice(to, 0, moved);
  let next = layer;
  ordered.forEach((view, i) => {
    next = patchTile(next, view.entry, { order: i });
  });
  return next;
}

/** Set a tab's placement (body or appendix). */
export function setTabPlacement(
  layer: ReportLayer,
  tabId: string,
  placement: ReportTabPlacement,
  fallbackOrder: number | null,
): ReportLayer {
  const existing = layer.tabs.find((t) => t.tab_id === tabId);
  const next: ReportTab = { tab_id: tabId, placement, order: existing?.order ?? fallbackOrder };
  return {
    ...layer,
    tabs: existing ? layer.tabs.map((t) => (t === existing ? next : t)) : [...layer.tabs, next],
  };
}

/** Swap a non-main tab with its neighbour and write every tab's order as
 *  consecutive integers (the main tab keeps 0). */
export function moveTab(layer: ReportLayer, tabs: TabView[], from: number, to: number): ReportLayer {
  // The main tab is first and fixed.
  if (from < 1 || to < 1 || to >= tabs.length || from === to) return layer;
  const ordered = [...tabs];
  const [moved] = ordered.splice(from, 1);
  ordered.splice(to, 0, moved);
  const stored = new Map(layer.tabs.map((t) => [t.tab_id, t]));
  const next: ReportTab[] = ordered.map((view, i) => ({
    tab_id: view.tabId,
    placement: stored.get(view.tabId)?.placement ?? view.placement,
    order: i,
  }));
  return { ...layer, tabs: next };
}

/** Cover fields: an empty one means "use the default", stored as null / []. */
export function setCoverField(
  layer: ReportLayer,
  patch: Partial<ReportCover>,
): ReportLayer {
  const merged: ReportCover = { ...(layer.cover ?? EMPTY_COVER), ...patch };
  const empty =
    !merged.title && !merged.subtitle && !merged.date && merged.authors.length === 0;
  return { ...layer, cover: empty ? null : merged };
}

/** True when a TipTap document holds no text. */
export function isEmptyDoc(doc: ReportDoc | null | undefined): boolean {
  if (!doc) return true;
  const content = doc.content ?? [];
  if (content.length === 0) return true;
  if (content.length > 1) return false;
  const only = content[0] as { type?: string; content?: unknown[] };
  return only.type === 'paragraph' && (only.content ?? []).length === 0;
}

/** The layer's state filters as the renderer takes them. */
export function stateFilters(state: AnalysisState | null): InteractiveFilter[] {
  if (!state) return [];
  return state.filters.map((f) => {
    const out: InteractiveFilter = { index: f.index, value: f.value ?? null };
    if (f.column_name != null) out.column_name = f.column_name;
    if (f.interactive_component_type != null) {
      out.interactive_component_type = f.interactive_component_type;
    }
    if (f.source != null) out.source = f.source as InteractiveFilter['source'];
    if (f.filter_expr != null) out.filter_expr = f.filter_expr;
    if (f.metadata) {
      out.metadata = {
        dc_id: f.metadata.dc_id ?? undefined,
        column_name: f.metadata.column_name ?? undefined,
        interactive_component_type: f.metadata.interactive_component_type ?? undefined,
        selection_column: f.metadata.selection_column ?? undefined,
        filter_expr: f.metadata.filter_expr ?? undefined,
      };
    }
    return out;
  });
}

/** Move a tile to row `to` of its tab. `section` is the section of the row it
 *  lands beside: a tile dropped among another section's rows joins that
 *  section, one moved among its own keeps its section. */
export function relocateTile(
  layer: ReportLayer,
  tab: TabView,
  from: number,
  to: number,
  section: string | null,
): ReportLayer {
  const moved = tab.tiles[from];
  if (!moved) return layer;
  const next = moveTile(layer, tab, from, to);
  // Rows of the section it already sits in: only the order changes, and an
  // override it carries stays (the outline holds no natural section to tell
  // an override from one, so it is never cleared by a mere reorder).
  if ((section || null) === (moved.section || null)) return next;
  return patchTile(next, moved.entry, { section: section || null });
}

/** The first words of a TipTap document, for a closed panel's one-line summary. */
export function docSummary(doc: ReportDoc | null | undefined, words = 10): string {
  if (isEmptyDoc(doc)) return 'Empty';
  const parts: string[] = [];
  const walk = (node: unknown) => {
    if (!node || typeof node !== 'object' || parts.length > words * 2) return;
    const n = node as { text?: string; content?: unknown[] };
    if (typeof n.text === 'string') parts.push(n.text);
    n.content?.forEach(walk);
  };
  walk(doc);
  const all = parts.join(' ').split(/\s+/).filter(Boolean);
  if (all.length === 0) return 'Empty';
  return all.slice(0, words).join(' ') + (all.length > words ? '…' : '');
}
