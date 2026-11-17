import React, { useMemo } from 'react';
import {
  GenomeBrowserTargetContext,
  isGenomicKind,
  jbrowseRank,
  useTabLinkResolver,
} from 'depictio-react-core';
import type {
  DashboardData,
  DashboardSummary,
  GenomeBrowserTarget,
} from 'depictio-react-core';

import { pickedSource, useFamilyPick, useGuideFamily } from '../guide/useGuideSources';

/**
 * Where "Open in genome browser" goes: the genome browser of the tab family,
 * found the way the Guide finds the one it describes (`jbrowseRank` over the
 * family's documents, the open tab first) and linked through the tab link
 * resolver, so the editor goes to the editor of that tab and the viewer to the
 * viewer.
 *
 * Mounted inside `TabLinkProvider`. The search (and the fetches of sibling
 * tabs it needs) runs only when the open tab has a genomic tile to act from;
 * any other dashboard pays nothing. `null` when the family has no browser,
 * which hides the action.
 */
const GenomeBrowserTargetProvider: React.FC<{
  dashboardId: string | null;
  dashboard: DashboardData | null;
  tabs: DashboardSummary[];
  children: React.ReactNode;
}> = ({ dashboardId, dashboard, tabs, children }) => {
  const resolveTab = useTabLinkResolver();
  const hasGenomicTile = useMemo(
    () =>
      (dashboard?.stored_metadata ?? []).some(
        (m) => m.component_type === 'advanced_viz' && isGenomicKind(m.viz_kind as string | undefined),
      ),
    [dashboard?.stored_metadata],
  );
  // The hooks run for every dashboard (their order cannot depend on one), on
  // an empty document until there is something to act from.
  const family = useGuideFamily(dashboardId ?? '', (dashboard ?? EMPTY) as DashboardData, tabs);
  const pick = useFamilyPick(family, jbrowseRank, { enabled: hasGenomicTile && Boolean(dashboard) });
  const source = pickedSource(family, pick);
  const familyId = tabs.find((t) => !t.parent_dashboard_id)?.dashboard_id ?? dashboardId ?? '';
  const href = source ? (resolveTab?.(source.dashboardId)?.href ?? null) : null;
  const target = useMemo<GenomeBrowserTarget | null>(
    () =>
      source && href && familyId
        ? {
            familyId,
            dashboardId: source.dashboardId,
            index: String(source.metadata.index),
            href,
            here: source.here,
          }
        : null,
    [source?.dashboardId, source?.metadata.index, source?.here, href, familyId],
  );
  return (
    <GenomeBrowserTargetContext.Provider value={target}>{children}</GenomeBrowserTargetContext.Provider>
  );
};

const EMPTY = { stored_metadata: [] } as unknown as DashboardData;

export default GenomeBrowserTargetProvider;
