/**
 * The dashboard pieces the Guide's demos are built from.
 *
 * The demos use the dashboard's own components: a real key figure with a real
 * filter on its data, a real section that folds. They often live on another
 * tab than the one the Guide was opened on — the key figures on the main tab,
 * a foldable section on whichever tab has one — so this reads the open tab
 * first and fetches a sibling only when the open tab has nothing to offer.
 * Each fetch is one dashboard document, made once per Guide visit.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  fetchDashboard,
  foldableSectionsOf,
  pickFilterDemo,
  tabDisplayName,
} from 'depictio-react-core';
import type {
  DashboardData,
  DashboardSummary,
  FilterSectionSpec,
  GuideDemoSection,
  PersistentSection,
  StoredMetadata,
} from 'depictio-react-core';

export interface GuideSourcesInput {
  /** The open tab. */
  dashboardId: string;
  dashboard: DashboardData;
  /** The open tab's canvas components, as drawn. */
  components: readonly StoredMetadata[];
  /** The tab family, sidebar order, main tab first. */
  tabs: readonly DashboardSummary[];
  /** The family's pinned sections, whichever tab owns them. */
  persistentSections: readonly PersistentSection[];
}

/** A key figure and a filter on its data, and the tab they belong to. */
export interface FilterDemoSource {
  /** The tab the card is computed against. */
  dashboardId: string;
  tabLabel: string;
  card: StoredMetadata;
  control: StoredMetadata;
}

/** Sections that fold, from the open tab or the nearest tab that has some. */
export interface SectionsDemoSource {
  dashboardId: string;
  tabLabel: string;
  /** 'tab': the open tab's own; 'pinned': pinned sections of the family,
   *  drawn on other tabs; 'sibling': borrowed from another tab. */
  scope: 'tab' | 'pinned' | 'sibling';
  sections: GuideDemoSection[];
}

/** `undefined` while still looking, `null` when the dashboard has none. */
export interface GuideSources {
  filter: FilterDemoSource | null | undefined;
  sections: SectionsDemoSource | null | undefined;
}

const labelOf = (tabs: readonly DashboardSummary[], id: string, fallback = 'this tab') => {
  const tab = tabs.find((t) => t.dashboard_id === id);
  return tab ? tabDisplayName(tab) : fallback;
};

/** Up to two sections, so the demo has one open and one folded. */
const DEMO_SECTIONS = 2;

export function useGuideSources(input: GuideSourcesInput): GuideSources {
  const { dashboardId, dashboard, components, tabs, persistentSections } = input;
  const mainId = tabs.find((t) => !t.parent_dashboard_id)?.dashboard_id ?? dashboardId;

  // Sibling documents fetched for the demos, by id. The open tab is never
  // fetched: its document is already here.
  const [docs, setDocs] = useState<Record<string, DashboardData | null>>({});

  const ownSections = useMemo(
    () =>
      foldableSectionsOf(components, dashboard.grid_sections as FilterSectionSpec[] | undefined),
    [components, dashboard.grid_sections],
  );
  // Pinned sections are drawn on every tab with their members, so one owned
  // by any tab is a real section a reader meets, with no fetch.
  const familySections = useMemo(
    () =>
      persistentSections
        .filter((s) => s.kind === 'grid' && s.components.length > 0)
        .filter((s) => s.spec.appearance !== 'plain')
        .map((s) => ({
          ownerId: s.owner_dashboard_id,
          section: { spec: s.spec, members: s.components.map((c) => c.metadata) },
        })),
    [persistentSections],
  );

  const docFor = (id: string): DashboardData | null | undefined =>
    id === dashboardId ? dashboard : docs[id];

  // Which documents are still needed: the main tab for its key figures, and,
  // when neither this tab nor the family's pinned sections fold, siblings in
  // sidebar order until one does.
  const wanted = useMemo(() => {
    const ids: string[] = [];
    if (mainId !== dashboardId) ids.push(mainId);
    if (ownSections.length === 0 && familySections.length === 0) {
      for (const t of tabs) {
        if (t.dashboard_id === dashboardId || ids.includes(t.dashboard_id)) continue;
        ids.push(t.dashboard_id);
      }
    }
    return ids;
  }, [mainId, dashboardId, ownSections.length, familySections.length, tabs]);

  // The sections fetch stops at the first sibling with a foldable section.
  const foundSiblingSections = wanted.some((id) => {
    const doc = docs[id];
    return doc && foldableSectionsOf(doc.stored_metadata ?? [], doc.grid_sections).length > 0;
  });

  useEffect(() => {
    let cancelled = false;
    const next = wanted.find((id) => !(id in docs));
    if (!next) return;
    // Past the main tab, only keep going while no section has turned up.
    if (next !== mainId && foundSiblingSections) return;
    fetchDashboard(next)
      .then((doc) => !cancelled && setDocs((prev) => ({ ...prev, [next]: doc })))
      .catch(() => !cancelled && setDocs((prev) => ({ ...prev, [next]: null })));
    return () => {
      cancelled = true;
    };
  }, [wanted, docs, mainId, foundSiblingSections]);

  const filter = useMemo<FilterDemoSource | null | undefined>(() => {
    const main = docFor(mainId);
    if (main === undefined) return undefined;
    const fromMain = main ? pickFilterDemo(main.stored_metadata ?? []) : null;
    if (fromMain) return { dashboardId: mainId, tabLabel: labelOf(tabs, mainId), ...fromMain };
    const fromHere = pickFilterDemo(dashboard.stored_metadata ?? []);
    return fromHere
      ? { dashboardId, tabLabel: labelOf(tabs, dashboardId), ...fromHere }
      : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docs, mainId, dashboardId, dashboard, tabs]);

  const sections = useMemo<SectionsDemoSource | null | undefined>(() => {
    if (ownSections.length > 0) {
      return {
        dashboardId,
        tabLabel: labelOf(tabs, dashboardId),
        scope: 'tab',
        sections: ownSections.slice(0, DEMO_SECTIONS),
      };
    }
    if (familySections.length > 0) {
      const { ownerId } = familySections[0];
      return {
        dashboardId: ownerId,
        tabLabel: labelOf(tabs, ownerId),
        scope: 'pinned',
        sections: familySections
          .filter((s) => s.ownerId === ownerId)
          .slice(0, DEMO_SECTIONS)
          .map((s) => s.section),
      };
    }
    for (const id of wanted) {
      const doc = docs[id];
      if (doc === undefined) return undefined;
      if (!doc) continue;
      const found = foldableSectionsOf(doc.stored_metadata ?? [], doc.grid_sections);
      if (found.length > 0) {
        return {
          dashboardId: id,
          tabLabel: labelOf(tabs, id),
          scope: 'sibling',
          sections: found.slice(0, DEMO_SECTIONS),
        };
      }
    }
    return null;
  }, [ownSections, familySections, wanted, docs, dashboardId, tabs]);

  return { filter, sections };
}
