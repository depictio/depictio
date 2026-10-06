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
