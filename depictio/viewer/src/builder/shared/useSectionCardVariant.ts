/**
 * The styles set by the grid section the component being built sits in: its
 * card style (`card_variant`) and its figure style (`figure_style`). Each is
 * null when the section sets none, the component has no section, or the
 * dashboard has not loaded.
 *
 * The card and figure builders use them twice: to tell the author that the
 * section already draws its tiles in a style, and to preview the tile the way
 * the grid will draw it. Both degrade to "no section style" on a failed fetch,
 * which only costs the hint: the grid resolves the style again on its own.
 */
import { useEffect, useState } from 'react';
import { fetchDashboard, normalizeCardVariant, normalizeFigureStyle } from 'depictio-react-core';
import type {
  CardVariant,
  DashboardData,
  FigureStyle,
  FilterSectionSpec,
} from 'depictio-react-core';

import { useBuilderStore } from '../store/useBuilderStore';
import { sectionsFor } from '../../components/sections/sectionMutations';

function useSectionSpec(): FilterSectionSpec | null {
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
  return sectionsFor(dashboard, 'grid').find((s) => s.name === name) ?? null;
}

export function useSectionCardVariant(): CardVariant | null {
  return normalizeCardVariant(useSectionSpec()?.card_variant);
}

export function useSectionFigureStyle(): FigureStyle | null {
  return normalizeFigureStyle(useSectionSpec()?.figure_style);
}
