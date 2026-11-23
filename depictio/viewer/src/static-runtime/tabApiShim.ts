/**
 * Tab-family layer on top of the offline api shim.
 *
 * `vite.combined.config.ts` points every `depictio-react-core` api.ts import at
 * THIS module, which re-exports `apiShim.ts` (the render-path overrides) and
 * replaces only the two functions that have to know about a tab family:
 *
 *   - `fetchDashboard`  — must answer with the ACTIVE tab's document. The base
 *     shim memoizes a single document, which would pin a family to its entry
 *     tab for the life of the page.
 *   - `fetchAllDashboards` — must list the family, so App builds `tabSiblings`
 *     and the left rail renders real pills instead of "No sibling tabs".
 *
 * A separate module rather than more overrides inside `apiShim.ts`: the two
 * concerns (offline data path vs. tab navigation) move independently, and the
 * chain keeps this one out of the way of the render-path work. `moduleShim`
 * supports it via `extraShims` — see the plugin.
 */
import type {
  DashboardData,
  DashboardSummary,
} from '../../../../packages/depictio-react-core/src/api';

export * from './apiShim';
import { fetchDashboard as baseFetchDashboard } from './apiShim';

import { bundle, bundledTabs, tabSummaries } from './bundle';

export async function fetchDashboard(dashboardId: string): Promise<DashboardData> {
  // Single-tab bundle (and every manifest written before `tabs` existed): the
  // base shim owns the answer, including its legacy `wf_id` back-fill.
  if (bundledTabs().length === 0) return baseFetchDashboard(dashboardId);
  // Tab family: the tab the caller ASKED for — a highlight looks its figure up
  // on another tab with this call, and used to be handed the active tab back.
  // Unknown ids (App's own route-less fetch) resolve to the active tab, which
  // `bundle()` already points at. The documents are the manifest's own
  // objects, so identities stay stable across App's re-fetches. No `wf_id`
  // back-fill here — that compensates for bundles built before the producers
  // wrote a workflow id, all of which predate the `tabs` field and so take the
  // branch above.
  const tab = bundledTabs().find((t) => t.id === dashboardId);
  if (tab) return tab.doc as unknown as DashboardData;
  return bundle().dashboard.doc as unknown as DashboardData;
}

export async function fetchAllDashboards(): Promise<DashboardSummary[]> {
  // Empty for a single-tab bundle — same answer the base shim gives, and the
  // rail renders exactly as it does today.
  return tabSummaries();
}
