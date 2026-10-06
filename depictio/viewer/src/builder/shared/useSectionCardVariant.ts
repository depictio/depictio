/**
 * The card style set by the grid section the component being built sits in
 * (`card_variant`), or null when the section sets none, the component has no
 * section, or the dashboard has not loaded.
 *
 * The card builder uses it twice: to tell the author that the section already
 * draws its cards in a style, and to preview the card the way the grid will
 * draw it. Both degrade to "no section style" on a failed fetch, which only
 * costs the hint: the grid resolves the style again on its own.
 */
import { useEffect, useState } from 'react';
import { fetchDashboard, normalizeCardVariant } from 'depictio-react-core';
import type { CardVariant, DashboardData } from 'depictio-react-core';

import { useBuilderStore } from '../store/useBuilderStore';
import { sectionsFor } from '../../components/sections/sectionMutations';

export function useSectionCardVariant(): CardVariant | null {
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const section = useBuilderStore((s) => (s.config as { section?: string }).section);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);

  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    fetchDashboard(dashboardId)
      .then((dash) => {
        if (!cancelled) setDashboard(dash);
      })
      .catch((err) => console.warn('[builder] section styles unavailable:', err));
    return () => {
      cancelled = true;
    };
  }, [dashboardId]);

  const name = section?.trim();
  if (!dashboard || !name) return null;
  const spec = sectionsFor(dashboard, 'grid').find((s) => s.name === name);
  return normalizeCardVariant(spec?.card_variant);
}
