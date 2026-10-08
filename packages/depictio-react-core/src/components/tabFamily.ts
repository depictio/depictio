/**
 * A dashboard's tab family: the main tab and its child tabs.
 *
 * The editor needs the family wherever an author points at another tab by
 * name — a text tile's `tab:` accent, a card's link, a section's excluded
 * tabs, the tab a component is copied to — so the rule for which tabs belong
 * together and what each is called lives here once.
 */

/** The fields a family reads; `DashboardSummary` carries them all. */
export interface FamilyTab {
  dashboard_id: string;
  title?: string;
  parent_dashboard_id?: string | null;
  main_tab_name?: string;
  tab_order?: number;
}

/**
 * The name a tab is shown under, and answers to in `tab:` links and in
 * `exclude_tabs`: the main tab's `main_tab_name` when it has one, otherwise
 * the title.
 */
export function tabDisplayName(tab: FamilyTab): string {
  const name = tab.parent_dashboard_id ? tab.title : tab.main_tab_name || tab.title;
  return (name || tab.dashboard_id).trim();
}

/**
 * The family `dashboardId` belongs to, in sidebar order: the main tab first,
 * then the children by `tab_order`, title breaking ties. Empty when the
 * dashboard is not in `all` (the list has not loaded yet).
 */
export function tabFamilyOf<T extends FamilyTab>(all: readonly T[], dashboardId: string): T[] {
  const current = all.find((d) => d.dashboard_id === dashboardId);
  if (!current) return [];
  const parentId = current.parent_dashboard_id || current.dashboard_id;
  const family = all.filter(
    (d) => d.dashboard_id === parentId || d.parent_dashboard_id === parentId,
  );
  return family.sort((a, b) => {
    const ao = a.tab_order ?? (a.parent_dashboard_id ? 1 : 0);
    const bo = b.tab_order ?? (b.parent_dashboard_id ? 1 : 0);
    if (ao !== bo) return ao - bo;
    return (a.title || '').localeCompare(b.title || '');
  });
}
