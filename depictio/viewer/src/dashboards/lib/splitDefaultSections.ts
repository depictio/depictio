import type { DashboardListEntry } from 'depictio-react-core';

export interface GroupedDashboards {
  parent: DashboardListEntry;
  children: DashboardListEntry[];
}

export interface DefaultSections {
  owned: GroupedDashboards[];
  accessed: GroupedDashboards[];
  public_: GroupedDashboards[];
  nfcore: GroupedDashboards[];
  demo: GroupedDashboards[];
}

/** Demo dashboards: bundled example seeds covering the core viz patterns
 *  (Penguins, Iris, Advanced Visualisations). Identified by hardcoded
 *  MongoDB ObjectIds stamped at db_init time. Order in this array doubles
 *  as display order. */
export const DEMO_DASHBOARD_IDS: readonly string[] = [
  '646b0f3c1e4a2d7f8e5b8d00', // Advanced Visualisations (main tab, was overview)
  '6824cb3b89d2b72169309738', // Penguins Species Analysis
  '6824cb3b89d2b72169309737', // Iris Species Comparison
];

/** nf-core dashboards: ampliseq + viralrecon main tabs. Viralrecon's
 *  dashboard_id is reserved in `db_init_reference_datasets.STATIC_IDS`
 *  but its seed JSONs are generated locally — see
 *  `depictio/projects/nf-core/viralrecon/3.0.0/CLAUDE.md`. The entry stays
 *  in this list so once seeds exist the dashboard slots in automatically. */
export const NFCORE_DASHBOARD_IDS: readonly string[] = [
  '646b0f3c1e4a2d7f8e5b8ca2', // nf-core/ampliseq
  '746b0f3c1e4a2d7f8e5b9ca2', // nf-core/viralrecon
];

export function isDemoDashboard(d: DashboardListEntry): boolean {
  return DEMO_DASHBOARD_IDS.includes(String(d.dashboard_id));
}

export function isNfcoreDashboard(d: DashboardListEntry): boolean {
  return NFCORE_DASHBOARD_IDS.includes(String(d.dashboard_id));
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

/** Categorisation precedence: nf-core > Demo > Public > Accessed > Owned.
 *  Seed dashboards (advanced viz, penguins, iris, ampliseq, viralrecon) are
 *  owned by the admin user but surface under their dedicated sections for
 *  everyone, including the admin themselves. */
export function splitDefaultSections(
  entries: DashboardListEntry[],
  currentUserEmail: string | null,
): DefaultSections {
  const grouped = groupByParent(entries);
  const owned: GroupedDashboards[] = [];
  const accessed: GroupedDashboards[] = [];
  const publicList: GroupedDashboards[] = [];
  const nfcore: GroupedDashboards[] = [];
  const demo: GroupedDashboards[] = [];
  for (const g of grouped) {
    if (isNfcoreDashboard(g.parent)) {
      nfcore.push(g);
      continue;
    }
    if (isDemoDashboard(g.parent)) {
      demo.push(g);
      continue;
    }
    const isOwner = isOwnedByEmail(g.parent, currentUserEmail);
    const isPublic = Boolean(g.parent.is_public);
    if (isOwner) owned.push(g);
    else if (isPublic) publicList.push(g);
    else accessed.push(g);
  }
  // Sort grouped sections by the canonical IDs order so display stays stable
  // regardless of Mongo insertion order.
  sortByCanonicalIds(nfcore, NFCORE_DASHBOARD_IDS);
  sortByCanonicalIds(demo, DEMO_DASHBOARD_IDS);
  return { owned, accessed, public_: publicList, nfcore, demo };
}

function sortByCanonicalIds(
  groups: GroupedDashboards[],
  canonicalIds: readonly string[],
): void {
  groups.sort(
    (a, b) =>
      canonicalIds.indexOf(String(a.parent.dashboard_id)) -
      canonicalIds.indexOf(String(b.parent.dashboard_id)),
  );
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

/** Per-project `template_origin` blob (or string), keyed by project id, for
 *  the dashboard cards to render a TemplateChip without having to fetch the
 *  project again. Projects without a template_origin are omitted so a simple
 *  `.get(id)` doubles as a "was-this-from-a-template?" check. */
export function projectTemplateLookup(
  projects: { _id?: string; id?: string; template_origin?: unknown }[],
): Map<string, unknown> {
  const map = new Map<string, unknown>();
  for (const p of projects) {
    const id = String(p._id ?? p.id ?? '');
    if (!id) continue;
    if (p.template_origin) map.set(id, p.template_origin);
  }
  return map;
}
