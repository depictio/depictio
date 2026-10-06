/**
 * The tabs of the dashboard the builder is adding to: the main tab and its
 * siblings, in sidebar order. Builders offer them wherever a component points
 * at a tab by name (a text tile's `tab:` accent, a card's link), and the
 * previews resolve those names against them.
 *
 * Empty until the list loads, and for good if it fails: every field that uses
 * it still accepts a value typed in YAML, so a missing list only costs the
 * suggestions.
 */
import { useEffect, useState } from 'react';
import { fetchAllDashboards, tabFamilyOf } from 'depictio-react-core';
import type { DashboardSummary } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';

export function useTabFamily(): DashboardSummary[] {
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const [family, setFamily] = useState<DashboardSummary[]>([]);

  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    fetchAllDashboards()
      .then((all) => {
        if (!cancelled) setFamily(tabFamilyOf(all, dashboardId));
      })
      .catch((err) => console.warn('[builder] tab list unavailable:', err));
    return () => {
      cancelled = true;
    };
  }, [dashboardId]);

  return family;
}
