import type { DashboardListEntry } from 'depictio-react-core';

export interface GroupedDashboards {
  parent: DashboardListEntry;
  children: DashboardListEntry[];
}

export interface DefaultSections {
  owned: GroupedDashboards[];
  accessed: GroupedDashboards[];
  public_: GroupedDashboards[];
  examples: GroupedDashboards[];
}

/** Example dashboards are identified by hardcoded MongoDB ObjectIds — same
 *  list as Dash (`dashboards_management.py:1484-1488`). These IDs are
 *  stamped at db_init time on the seed dashboards (ampliseq, penguins, iris)
 *  and keep their assignment forever, regardless of ownership or public flag.
 *  Order in this array doubles as display order in the Examples section. */
export const EXAMPLE_DASHBOARD_IDS: readonly string[] = [
  '646b0f3c1e4a2d7f8e5b8ca2', // nf-core/ampliseq
  '6824cb3b89d2b72169309738', // Penguins Species Analysis
  '6824cb3b89d2b72169309737', // Iris Species Comparison
];

export function isExampleDashboard(d: DashboardListEntry): boolean {
  return EXAMPLE_DASHBOARD_IDS.includes(String(d.dashboard_id));
}

export function isOwnedByEmail(
  d: DashboardListEntry,
  email: string | null,
): boolean {
  if (!email) return false;
  const owners = d.permissions?.owners ?? [];
  return owners.some((o) => o?.email === email);
}

export function groupByParent(entries: DashboardListEntry[]): GroupedDashboards[] {
  const parents = entries.filter((d) => !d.parent_dashboard_id);
  const childrenByParent = new Map<string, DashboardListEntry[]>();
  for (const d of entries) {
    if (!d.parent_dashboard_id) continue;
    const list = childrenByParent.get(String(d.parent_dashboard_id)) ?? [];
    list.push(d);
    childrenByParent.set(String(d.parent_dashboard_id), list);
  }
  return parents.map((parent) => ({
    parent,
    children: (childrenByParent.get(parent.dashboard_id) ?? []).sort(
      (a, b) => (a.tab_order ?? 0) - (b.tab_order ?? 0),
    ),
  }));
}

/** Categorisation precedence (matches `dashboards_management.py:1476`):
 *  Example > Public > Accessed > Owned. The seed dashboards (ampliseq,
 *  penguins, iris) are owned by the admin user but should still surface
 *  under "Example" for everyone, including the admin themselves. */
export function splitDefaultSections(
  entries: DashboardListEntry[],
  currentUserEmail: string | null,
): DefaultSections {
  const grouped = groupByParent(entries);
  const owned: GroupedDashboards[] = [];
  const accessed: GroupedDashboards[] = [];
  const publicList: GroupedDashboards[] = [];
  const examples: GroupedDashboards[] = [];
  for (const g of grouped) {
    if (isExampleDashboard(g.parent)) {
      examples.push(g);
      continue;
    }
    const isOwner = isOwnedByEmail(g.parent, currentUserEmail);
    const isPublic = Boolean(g.parent.is_public);
    if (isOwner) owned.push(g);
    else if (isPublic) publicList.push(g);
    else accessed.push(g);
  }
  // Sort examples in the canonical order from EXAMPLE_DASHBOARD_IDS so
  // ampliseq always renders first regardless of insertion order in Mongo.
  examples.sort(
    (a, b) =>
      EXAMPLE_DASHBOARD_IDS.indexOf(String(a.parent.dashboard_id)) -
      EXAMPLE_DASHBOARD_IDS.indexOf(String(b.parent.dashboard_id)),
  );
  return { owned, accessed, public_: publicList, examples };
}

export function projectNameLookup(
  projects: { _id?: string; id?: string; name: string }[],
): Map<string, string> {
  const map = new Map<string, string>();
  for (const p of projects) {
    const id = String(p._id ?? p.id ?? '');
    if (id) map.set(id, p.name);
  }
  return map;
}
