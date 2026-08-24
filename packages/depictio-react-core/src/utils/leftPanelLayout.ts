import type { Layout } from 'react-grid-layout';

import type { InteractiveGroup } from './groupInteractive';

/**
 * Ordering helpers for the left filter panel.
 *
 * `DashboardData.left_panel_layout_data` is a react-grid-layout array keyed by
 * component index. The editor writes it on every drag; the viewer used to
 * ignore it entirely, so a user's ordering silently applied in edit mode only.
 * These helpers let both apps read the same source of truth.
 *
 * Groups are ordered by the smallest `y` among their members, which keeps the
 * persisted format component-keyed. Layouts saved before grouping existed
 * therefore keep working, and no migration is needed.
 */

const DEFAULT_H = 2;

export function stripBoxPrefix(id: string): string {
  return id.startsWith('box-') ? id.slice(4) : id;
}

export function extractLayoutItems(layoutData: unknown): Layout[] {
  if (!layoutData) return [];
  if (Array.isArray(layoutData)) {
    return layoutData.filter(
      (i): i is Layout =>
        Boolean(i) && typeof i === 'object' && 'i' in i && 'x' in i && 'y' in i,
    );
  }
  if (typeof layoutData === 'object') {
    const obj = layoutData as Record<string, unknown>;
    const candidateKey =
      'lg' in obj ? 'lg' : Object.keys(obj).find((k) => Array.isArray(obj[k])) || '';
    if (candidateKey && Array.isArray(obj[candidateKey])) {
      return (obj[candidateKey] as Layout[]).filter(
        (i) => Boolean(i) && typeof i === 'object' && 'i' in i,
      );
    }
  }
  return [];
}

/** Component index → saved vertical position. */
function positionByIndex(layoutData: unknown): Map<string, number> {
  const out = new Map<string, number>();
  for (const item of extractLayoutItems(layoutData)) {
    const id = stripBoxPrefix(item.i);
    const y = typeof item.y === 'number' ? item.y : 0;
    const prev = out.get(id);
    if (prev === undefined || y < prev) out.set(id, y);
  }
  return out;
}

/**
 * Sort groups by their saved position. Groups with no saved entry keep their
 * original relative order and sort last, so newly added filters append to the
 * bottom rather than jumping to the top.
 */
export function orderGroupsByLayout(
  groups: InteractiveGroup[],
  layoutData: unknown,
): InteractiveGroup[] {
  const positions = positionByIndex(layoutData);
  if (positions.size === 0) return groups;

  const keyed = groups.map((g, originalIndex) => {
    let y = Infinity;
    for (const m of g.members) {
      const p = positions.get(m.index);
      if (p !== undefined && p < y) y = p;
    }
    return { g, y, originalIndex };
  });

  keyed.sort((a, b) => (a.y !== b.y ? a.y - b.y : a.originalIndex - b.originalIndex));
  return keyed.map((k) => k.g);
}

/** Rows a group card's header occupies in the editor grid. */
const GROUP_HEADER_H = 1;

/**
 * Rows one control needs.
 *
 * Two rows fit a title plus an input; a slider showing tick marks needs a
 * third, because its labels hang below the track and the grid item clips
 * anything past its own height — which is why sliders used to lose their scale
 * in the panel while the same control looked fine in the grid.
 */
function rowsForMember(member: InteractiveGroup['members'][number]): number {
  const type = member.interactive_component_type;
  if (type !== 'Slider' && type !== 'RangeSlider') return DEFAULT_H;
  return member.show_marks === false ? DEFAULT_H : DEFAULT_H + 1;
}

/**
 * Height a group needs in the editor grid.
 *
 * The grid clips its items (`overflow: hidden`) and forbids resizing, so a
 * height that ignores member count silently hides every control past the
 * first. A singleton keeps the historical single-control height; a real group
 * pays for its header plus one slot per member, and shrinks to just the header
 * while collapsed.
 */
export function groupRowSpan(group: InteractiveGroup, collapsed = false): number {
  if (!group.groupName) return rowsForMember(group.members[0]);
  if (collapsed) return GROUP_HEADER_H;
  return GROUP_HEADER_H + group.members.reduce((sum, m) => sum + rowsForMember(m), 0);
}

/**
 * Rows a card of `px` pixels needs, given the grid's own geometry.
 *
 * `groupRowSpan` can only estimate: a control's height depends on what it
 * renders (a slider's tick labels, a group card's compact member rows, a
 * collapsed body), and the same member is drawn differently on its own than
 * inside a group. The editor measures the card it actually drew and converts
 * back through this, so the item stops being taller than its contents.
 */
export function rowSpanForHeight(px: number, rowHeight: number, margin: number): number {
  if (!(px > 0)) return 1;
  return Math.max(1, Math.ceil((px + margin) / (rowHeight + margin)));
}

/**
 * One react-grid-layout row per group, in the order given.
 *
 * @param isCollapsed - reads the panel's collapse state so a folded group
 *   gives its space back instead of leaving a gap.
 * @param measured - group key → rows measured from the rendered card. Used
 *   where present; `groupRowSpan` is the first-paint estimate behind it.
 */
export function groupsToGridLayout(
  groups: InteractiveGroup[],
  isCollapsed?: (key: string) => boolean,
  measured?: Record<string, number>,
): Layout[] {
  const out: Layout[] = [];
  let y = 0;
  for (const g of groups) {
    const h = measured?.[g.key] ?? groupRowSpan(g, isCollapsed?.(g.key) ?? false);
    out.push({ i: g.key, x: 0, y, w: 1, h });
    y += h;
  }
  return out;
}

/**
 * Flatten a group-level layout back to the component-keyed array that gets
 * persisted, so `left_panel_layout_data` keeps the shape every other reader
 * (including older dashboards) expects.
 */
export function gridLayoutToMemberLayout(
  layout: Layout[],
  groups: InteractiveGroup[],
): Layout[] {
  const byKey = new Map(groups.map((g) => [g.key, g.members] as const));
  const ordered = [...layout].sort((a, b) => a.y - b.y);

  const out: Layout[] = [];
  let y = 0;
  for (const item of ordered) {
    const members = byKey.get(item.i);
    if (!members) continue;
    for (const m of members) {
      out.push({ i: m.index, x: 0, y, w: 1, h: DEFAULT_H });
      y += DEFAULT_H;
    }
  }
  return out;
}
