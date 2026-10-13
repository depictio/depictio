/**
 * Categories for a dashboard's tabs.
 *
 * A family of ten tabs reads better as "where the samples came from, then the
 * analysis, then QC" than as one flat list, so a child tab can name a
 * `tab_group`. Tabs naming the same group are drawn together under its name.
 */

/** The fields grouping reads; `DashboardSummary` carries both. */
export interface GroupableTab {
  parent_dashboard_id?: string | null;
  tab_group?: string | null;
}

export interface TabGroup<T> {
  /** The group's name, or null for the main tab and the ungrouped tabs. */
  group: string | null;
  tabs: T[];
}

/**
 * A tab's group name, or null when it has none. The main tab is never
 * grouped: it opens the family and sits above every category.
 */
export function tabGroupOf(tab: GroupableTab): string | null {
  if (!tab.parent_dashboard_id) return null;
  return tab.tab_group?.trim() || null;
}

/** Spellings that differ only in case or spacing name the same group. */
function groupKey(name: string): string {
  return name.toLowerCase().replace(/\s+/g, ' ');
}

/**
 * Splits tabs, given in `tab_order`, into the sections the sidebar draws.
 *
 * The ungrouped tabs come first, the main tab among them: a run of tabs with no
 * heading placed after a group would read as part of that group. Groups follow
 * in the order of their first tab, each keeping its tabs in the order given, so
 * a group whose tabs an author interleaved with another's still shows as one
 * block. A group takes the spelling of its first tab.
 */
export function groupTabs<T extends GroupableTab>(tabs: readonly T[]): TabGroup<T>[] {
  const ungrouped: T[] = [];
  const groups = new Map<string, TabGroup<T>>();
  for (const tab of tabs) {
    const name = tabGroupOf(tab);
    if (name === null) {
      ungrouped.push(tab);
      continue;
    }
    const key = groupKey(name);
    const existing = groups.get(key);
    if (existing) existing.tabs.push(tab);
    else groups.set(key, { group: name, tabs: [tab] });
  }
  const sections: TabGroup<T>[] = ungrouped.length ? [{ group: null, tabs: ungrouped }] : [];
  return sections.concat([...groups.values()]);
}

/** The family's group names, in the order the sidebar shows them. */
export function tabGroupNames(tabs: readonly GroupableTab[]): string[] {
  return groupTabs(tabs).flatMap((section) => (section.group ? [section.group] : []));
}

// ---------------------------------------------------------------------------
// Editing groups
//
// A group has no document of its own: it is the `tab_group` its tabs share.
// So renaming a group, moving it, or moving a tab into one all come down to
// patching `tab_group` on some tabs and renumbering `tab_order` for the
// family. The helpers below compute those two things; the caller sends them.
// ---------------------------------------------------------------------------

/** A groupable tab the editor can address. */
export interface EditableTab extends GroupableTab {
  dashboard_id: string;
}

/** True when two names denote the same group (case and spacing ignored). */
export function sameTabGroup(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  const ka = a?.trim() ? groupKey(a.trim()) : null;
  const kb = b?.trim() ? groupKey(b.trim()) : null;
  return ka === kb;
}

/** Ids of the child tabs in `group`, in the order given — the tabs a rename or
 *  an ungroup has to patch. */
export function tabIdsInGroup(tabs: readonly EditableTab[], group: string): string[] {
  return tabs
    .filter((t) => t.parent_dashboard_id && sameTabGroup(tabGroupOf(t), group))
    .map((t) => t.dashboard_id);
}

/** Child ids in the order the sidebar draws them; the main tab is left out,
 *  as it keeps tab_order 0 and is not part of a reorder. */
function childOrder<T extends EditableTab>(sections: TabGroup<T>[]): string[] {
  return sections
    .flatMap((s) => s.tabs.filter((t) => t.parent_dashboard_id))
    .map((t) => t.dashboard_id);
}

/**
 * The child-tab order after moving `group` one place up or down among the
 * other groups, or null when it cannot move that way (already first or last,
 * or no such group). The ungrouped tabs, the main tab among them, stay first:
 * a group never moves above them.
 */
export function tabOrderAfterGroupMove<T extends EditableTab>(
  tabs: readonly T[],
  group: string,
  direction: 'up' | 'down',
): string[] | null {
  const sections = groupTabs(tabs);
  const lead = sections[0]?.group === null ? 1 : 0;
  const idx = sections.findIndex((s) => s.group !== null && sameTabGroup(s.group, group));
  if (idx < 0) return null;
  const swap = direction === 'up' ? idx - 1 : idx + 1;
  if (swap < lead || swap >= sections.length) return null;
  [sections[idx], sections[swap]] = [sections[swap], sections[idx]];
  return childOrder(sections);
}

/**
 * The child-tab order after putting `tabIds` in `group` (null: no group).
 *
 * The moved tabs land at the end of the group they join, in their current
 * order; a group that does not exist yet is added after the others, so a new
 * group appears at the bottom of the list rather than wherever its first tab
 * happened to sit.
 */
export function tabOrderAfterRegroup<T extends EditableTab>(
  tabs: readonly T[],
  tabIds: readonly string[],
  group: string | null,
): string[] {
  const moving = new Set(tabIds);
  const moved = tabs.filter((t) => moving.has(t.dashboard_id) && t.parent_dashboard_id);
  const sections = groupTabs(tabs.filter((t) => !moving.has(t.dashboard_id)));
  const target = group?.trim() || null;
  const existing =
    target === null
      ? sections.find((s) => s.group === null)
      : sections.find((s) => s.group !== null && sameTabGroup(s.group, target));
  if (existing) existing.tabs.push(...moved);
  else if (target === null) sections.unshift({ group: null, tabs: moved });
  else sections.push({ group: target, tabs: moved });
  return childOrder(sections);
}

/** `tab_order` entries for a child order: 1-based, the main tab keeping 0. */
export function tabOrderEntries(
  childIds: readonly string[],
): { dashboard_id: string; tab_order: number }[] {
  return childIds.map((dashboard_id, i) => ({ dashboard_id, tab_order: i + 1 }));
}
