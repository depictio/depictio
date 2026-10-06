import React, { useMemo } from 'react';
import { isImagePath, TabLinkContext, tabLinkKey, useBranding } from 'depictio-react-core';
import type { DashboardSummary, TabLinkResolver, TabLinkTarget } from 'depictio-react-core';

import { dashboardHref } from '../dashboards/lib/dashboardLinks';
import { resolveTabColor, resolveTabIcon } from './Sidebar';

/**
 * Lets text bodies link to a sibling tab by name (`[label](tab:Name)`).
 *
 * Mounted inside `BrandScope` so a link takes the same icon and colour the
 * sidebar pill of that tab shows, brand defaults included. A tab answers to
 * its displayed name; the parent also answers to the dashboard title.
 */
const TabLinkProvider: React.FC<{ tabs: DashboardSummary[]; children: React.ReactNode }> = ({
  tabs,
  children,
}) => {
  const brand = useBranding();
  const resolve = useMemo<TabLinkResolver>(() => {
    const byKey = new Map<string, TabLinkTarget>();
    for (const d of tabs) {
      const isParent = !d.parent_dashboard_id;
      const label = (isParent ? d.main_tab_name || d.title : d.title) || '';
      const image = d.tab_icon && isImagePath(d.tab_icon) ? d.tab_icon : null;
      const target: TabLinkTarget = {
        href: dashboardHref(d.dashboard_id),
        label,
        icon: image ?? resolveTabIcon(d, isParent),
        color: resolveTabColor(d, isParent, brand),
        description: d.subtitle?.trim() || null,
      };
      for (const name of [label, d.title]) {
        const key = name ? tabLinkKey(name) : '';
        if (key && !byKey.has(key)) byKey.set(key, target);
      }
    }
    return (name: string) => byKey.get(tabLinkKey(name)) ?? null;
  }, [tabs, brand]);
  return <TabLinkContext.Provider value={resolve}>{children}</TabLinkContext.Provider>;
};

export default TabLinkProvider;
