/**
 * A linked record card laid out as its source's collapsible side panel.
 *
 * A record card whose `linked_component` names another tile, and which sits
 * beside that tile on the same row of the same section, is the detail half of
 * a master/detail pair. While nothing is picked the card has nothing to show,
 * so it folds away: the source takes the whole span the pair covered, and a
 * slim rail drawn on the source's edge (not a grid item: a grid column is far
 * wider than a rail needs) stands in for the card. A pick unfolds it again.
 * The swap is a derived layout handed to react-grid-layout, never a change to
 * the stored one, so the editor and the persisted dashboard only ever see the
 * author's own geometry.
 *
 * Pure functions only: DashboardGrid owns the state and the rendering. The
 * pairing rule is the one the shipped-template lint applies
 * (`side_panel_pairs` in depictio/models/components/advanced_viz/record_link.py).
 */

import type { Layout } from 'react-grid-layout';

import type { InteractiveFilter, StoredMetadata } from '../api';

/** Width of the rail a folded card leaves on its source's edge: enough for
 *  its icon, a vertical title and the unfold chevron. */
export const RECORD_PANEL_RAIL_PX = 32;

/** The selection sources a record card follows (see `recordSelection.ts`). */
const FOLLOWED_SOURCES = new Set(['scatter_selection', 'table_selection']);

export interface RecordSidePanel {
  cardId: string;
  sourceId: string;
  /** Which side of its source the card sits on. */
  side: 'left' | 'right';
}

/** Card index to source index, for every record card that names a source. */
export function recordPanelLinks(metadataList: readonly StoredMetadata[]): Map<string, string> {
  const links = new Map<string, string>();
  for (const m of metadataList) {
    if (m.component_type !== 'advanced_viz') continue;
    const config = (m.config ?? {}) as Record<string, unknown>;
    const kind = m.viz_kind ?? config.viz_kind;
    const linked = config.linked_component;
    if (kind !== 'record_card' || typeof linked !== 'string' || !linked) continue;
    if (linked !== m.index) links.set(m.index, linked);
  }
  return links;
}

/**
 * The cards of `layout` that sit directly beside their source: same row, and
 * touching it edge to edge. `layout` is one section's grid, so the section
 * rule holds by construction.
 */
export function findSidePanels(
  layout: readonly Layout[],
  links: ReadonlyMap<string, string>,
): RecordSidePanel[] {
  const byId = new Map(layout.map((item) => [item.i, item]));
  const panels: RecordSidePanel[] = [];
  for (const [cardId, sourceId] of links) {
    const card = byId.get(cardId);
    const source = byId.get(sourceId);
    if (!card || !source || card.y !== source.y) continue;
    if (card.x === source.x + source.w) panels.push({ cardId, sourceId, side: 'right' });
    else if (source.x === card.x + card.w) panels.push({ cardId, sourceId, side: 'left' });
  }
  return panels;
}

/**
 * `layout` with every collapsed panel folded: the card leaves the grid and its
 * source spans the columns the two covered together. Items that are not part
 * of a folded pair come back as they went in, in the same order.
 */
export function applyRecordPanels(
  layout: readonly Layout[],
  panels: readonly RecordSidePanel[],
  isCollapsed: (cardId: string) => boolean,
): Layout[] {
  const widened = new Map<string, Layout>();
  const folded = new Set<string>();
  for (const panel of panels) {
    if (!isCollapsed(panel.cardId)) continue;
    const card = layout.find((item) => item.i === panel.cardId);
    const source = layout.find((item) => item.i === panel.sourceId);
    if (!card || !source) continue;
    folded.add(card.i);
    widened.set(source.i, { ...source, x: Math.min(source.x, card.x), w: source.w + card.w });
  }
  if (folded.size === 0) return [...layout];
  return layout
    .filter((item) => !folded.has(item.i))
    .map((item) => widened.get(item.i) ?? item);
}

/** Whether the source tile currently holds a selection the card would follow.
 *  A cleared selection keeps its entry with an empty value list. */
export function linkedSelectionActive(
  filters: readonly InteractiveFilter[] | undefined,
  sourceId: string,
): boolean {
  return (filters ?? []).some(
    (f) =>
      f.index === sourceId &&
      Boolean(f.source && FOLLOWED_SOURCES.has(f.source)) &&
      Array.isArray(f.value) &&
      f.value.length > 0,
  );
}

/** Open when the reader said so, else open exactly while a pick is active. */
export function panelExpanded(selectionActive: boolean, override: boolean | undefined): boolean {
  return override ?? selectionActive;
}

/**
 * The reader's overrides once selection activity has moved on. A toggle holds
 * only until the card's source gains or loses its selection: a new pick
 * should open the panel even if it was folded by hand, and clearing the pick
 * should fold it even if it was opened by hand.
 */
export function reconcileOverrides(
  overrides: Readonly<Record<string, boolean>>,
  previouslyActive: Readonly<Record<string, boolean>>,
  active: Readonly<Record<string, boolean>>,
): Record<string, boolean> {
  let changed = false;
  const next: Record<string, boolean> = {};
  for (const [cardId, value] of Object.entries(overrides)) {
    if (Boolean(previouslyActive[cardId]) !== Boolean(active[cardId])) {
      changed = true;
      continue;
    }
    next[cardId] = value;
  }
  return changed ? next : (overrides as Record<string, boolean>);
}
