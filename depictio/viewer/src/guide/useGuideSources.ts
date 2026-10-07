/**
 * The dashboard pieces the Guide's demos are built from.
 *
 * The demos use the dashboard's own components: a real key figure with a real
 * filter on its data, the tab's real sections, a real figure, table and card
 * of each kind. They often live on another tab than the one the Guide was
 * opened on — the key figures on the main tab, a scatter a group can be drawn
 * on wherever the author put one — so each demo looks in the open tab first
 * and fetches a sibling only when the open tab has nothing to offer. Each
 * fetch is one dashboard document, made once per Guide visit and shared by
 * every demo.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  analysisCardRank,
  analysisFigureRank,
  analysisSelectableFigureRank,
  analysisTableRank,
  demoSectionsOf,
  familyOrder,
  fetchDashboard,
  foldableSectionsOf,
  pickFilterDemo,
  pickFromFamily,
  tabDisplayName,
  takesSelection,
} from 'depictio-react-core';
import type {
  DashboardData,
  DashboardSummary,
  FilterSectionSpec,
  GuideDemoSection,
  GuideFamilyPick,
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

/** The tab family's documents, fetched as the demos ask for them. */
export interface GuideFamily {
  currentId: string;
  /** The tabs to look in: the open tab, then the others in sidebar order. */
  order: string[];
  tabs: readonly DashboardSummary[];
  /** `undefined` while not fetched, `null` when the fetch failed. */
  docFor: (id: string) => DashboardData | null | undefined;
  /** Fetch a tab's document, once. */
  request: (id: string) => void;
  /** The tab's name as the sidebar shows it. */
  labelOf: (id: string) => string;
}

/** A component the Guide draws, and the tab it is fetched against. */
export interface GuideComponentSource {
  dashboardId: string;
  tabLabel: string;
  metadata: StoredMetadata;
  /** Whether it is the open tab's own. */
  here: boolean;
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
  /** The owning tab's stored layout, for the grid to place the members. */
  layoutData: unknown;
}

/** What the Analysis demo selects on and reads, each from its own tab. */
export interface AnalysisDemoSource {
  /** What the groups are drawn on, overlaid or split; selected on too when
   *  it takes a lasso. */
  figure: GuideComponentSource | null;
  table: GuideComponentSource | null;
  card: GuideComponentSource | null;
}

/** `undefined` while still looking, `null` when the dashboard has none. */
export interface GuideSources {
  family: GuideFamily;
  filter: FilterDemoSource | null | undefined;
  sections: SectionsDemoSource | null | undefined;
  analysis: AnalysisDemoSource | null | undefined;
}

const labelFrom = (tabs: readonly DashboardSummary[], id: string, fallback = 'this tab') => {
  const tab = tabs.find((t) => t.dashboard_id === id);
  return tab ? tabDisplayName(tab) : fallback;
};

/** Up to two sections, so the demo has one open and one folded. */
const DEMO_SECTIONS = 2;

/** The family's documents: the open tab's as given, the others on demand. */
export function useGuideFamily(
  dashboardId: string,
  dashboard: DashboardData,
  tabs: readonly DashboardSummary[],
): GuideFamily {
  const [docs, setDocs] = useState<Record<string, DashboardData | null>>({});
  const asked = useRef(new Set<string>());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const request = useCallback(
    (id: string) => {
      if (id === dashboardId || asked.current.has(id)) return;
      asked.current.add(id);
      fetchDashboard(id)
        .then((doc) => mounted.current && setDocs((prev) => ({ ...prev, [id]: doc })))
        .catch(() => mounted.current && setDocs((prev) => ({ ...prev, [id]: null })));
    },
    [dashboardId],
  );
  const docFor = useCallback(
    (id: string) => (id === dashboardId ? dashboard : docs[id]),
    [dashboardId, dashboard, docs],
  );
  const order = useMemo(
    () =>
      familyOrder(
        dashboardId,
        tabs.map((t) => t.dashboard_id),
      ),
    [dashboardId, tabs],
  );
  const labelOf = useCallback((id: string) => labelFrom(tabs, id), [tabs]);
  return useMemo(
    () => ({ currentId: dashboardId, order, tabs, docFor, request, labelOf }),
    [dashboardId, order, tabs, docFor, request, labelOf],
  );
}

/**
 * `pickFromFamily` over the family, fetching the next tab while the pick
 * cannot be decided. `enabled` false holds the search (and its fetches) until
 * what the rank depends on is known.
 */
export function useFamilyPick(
  family: GuideFamily,
  rank: (m: StoredMetadata) => number | null,
  opts: { acrossTabs?: boolean; enabled?: boolean } = {},
): GuideFamilyPick | undefined {
  const { acrossTabs = false, enabled = true } = opts;
  const pick = useMemo(
    () => (enabled ? pickFromFamily(family.order, family.docFor, rank, { acrossTabs }) : undefined),
    [enabled, family, rank, acrossTabs],
  );
  const need = pick?.status === 'pending' ? pick.need : null;
  useEffect(() => {
    if (need) family.request(need);
  }, [need, family]);
  return pick;
}

/** A pick as the demos use it: `undefined` while looking, `null` for none. */
export function pickedSource(
  family: GuideFamily,
  pick: GuideFamilyPick | undefined,
): GuideComponentSource | null | undefined {
  if (!pick || pick.status === 'pending') return undefined;
  if (pick.status === 'none') return null;
  return {
    dashboardId: pick.dashboardId,
    tabLabel: family.labelOf(pick.dashboardId),
    metadata: pick.metadata,
    here: pick.dashboardId === family.currentId,
  };
}

/** A source's identity, for memoising on what was picked rather than on the
 *  object a render built around it. */
const sourceKey = (s: GuideComponentSource | null | undefined) =>
  s === undefined ? '…' : s === null ? '-' : `${s.dashboardId}/${s.metadata.index}`;

export function useGuideSources(input: GuideSourcesInput): GuideSources {
  const { dashboardId, dashboard, components, tabs, persistentSections } = input;
  const family = useGuideFamily(dashboardId, dashboard, tabs);
  const { docFor, request } = family;
  const mainId = tabs.find((t) => !t.parent_dashboard_id)?.dashboard_id ?? dashboardId;

  // ---- Filters: a key figure and a filter on its data, the main tab's first.
  useEffect(() => {
    request(mainId);
  }, [request, mainId]);
  const filter = useMemo<FilterDemoSource | null | undefined>(() => {
    const main = docFor(mainId);
    if (main === undefined) return undefined;
    const fromMain = main ? pickFilterDemo(main.stored_metadata ?? []) : null;
    if (fromMain) return { dashboardId: mainId, tabLabel: labelFrom(tabs, mainId), ...fromMain };
    const fromHere = pickFilterDemo(dashboard.stored_metadata ?? []);
    return fromHere
      ? { dashboardId, tabLabel: labelFrom(tabs, dashboardId), ...fromHere }
      : null;
  }, [docFor, mainId, dashboardId, dashboard, tabs]);

  // ---- Sections: this tab's that fold, else the family's pinned ones, else
  // the first sibling's.
  const ownSections = useMemo(
    () =>
      foldableSectionsOf(components, dashboard.grid_sections as FilterSectionSpec[] | undefined),
    [components, dashboard.grid_sections],
  );
  // Pinned sections are drawn on every tab with their members, so one owned
  // by any tab is a real section a reader meets, with no fetch.
  const pinned = useMemo(() => {
    const grid = persistentSections.filter(
      (s) => s.kind === 'grid' && s.components.length > 0 && s.spec.appearance !== 'plain',
    );
    const ownerId = grid[0]?.owner_dashboard_id;
    if (!ownerId) return null;
    const own = grid.filter((s) => s.owner_dashboard_id === ownerId);
    return {
      ownerId,
      sections: own.map((s) => ({ spec: s.spec, members: s.components.map((c) => c.metadata) })),
      layouts: own.flatMap((s) => s.layouts ?? []),
    };
  }, [persistentSections]);
  const siblingSearch = ownSections.length === 0 && !pinned;
  const siblingFound = useMemo(() => {
    if (!siblingSearch) return null;
    for (const id of family.order) {
      if (id === dashboardId) continue;
      const doc = docFor(id);
      if (doc === undefined) return { pending: id } as const;
      if (!doc) continue;
      const found = foldableSectionsOf(doc.stored_metadata ?? [], doc.grid_sections);
      if (found.length > 0) return { id, doc, found } as const;
    }
    return { none: true } as const;
  }, [siblingSearch, family.order, dashboardId, docFor]);
  const pendingSibling = siblingFound && 'pending' in siblingFound ? siblingFound.pending : null;
  useEffect(() => {
    if (pendingSibling) request(pendingSibling);
  }, [pendingSibling, request]);

  const sections = useMemo<SectionsDemoSource | null | undefined>(() => {
    if (ownSections.length > 0) {
      return {
        dashboardId,
        tabLabel: labelFrom(tabs, dashboardId),
        scope: 'tab',
        sections: demoSectionsOf(ownSections, DEMO_SECTIONS),
        layoutData: dashboard.right_panel_layout_data,
      };
    }
    if (pinned) {
      return {
        dashboardId: pinned.ownerId,
        tabLabel: labelFrom(tabs, pinned.ownerId),
        scope: 'pinned',
        sections: demoSectionsOf(pinned.sections, DEMO_SECTIONS),
        layoutData: pinned.layouts,
      };
    }
    if (!siblingFound || 'pending' in siblingFound) return undefined;
    if ('none' in siblingFound) return null;
    return {
      dashboardId: siblingFound.id,
      tabLabel: labelFrom(tabs, siblingFound.id),
      scope: 'sibling',
      sections: demoSectionsOf(siblingFound.found, DEMO_SECTIONS),
      layoutData: siblingFound.doc.right_panel_layout_data,
    };
  }, [ownSections, pinned, siblingFound, dashboardId, dashboard, tabs]);

  // ---- Analysis: a figure to draw the groups on, a table to tick, a card to
  // read per group. The figure is the best of the family's — one that draws
  // the groups both overlaid and split beats a nearer one that answers one of
  // the two (see `analysisFigureRank`). The table and the card follow it: a
  // table keying its rows on the figure's points, a card on its data. A figure
  // that takes no lasso is drawn the groups ticked in that table; with no
  // table to make them, the best figure that does take one stands in.
  const best = pickedSource(
    family,
    useFamilyPick(family, analysisFigureRank, { acrossTabs: true }),
  );
  const bestMeta = best?.metadata ?? null;
  const bestTableRank = useMemo(() => analysisTableRank(bestMeta), [bestMeta]);
  const bestTable = pickedSource(
    family,
    useFamilyPick(family, bestTableRank, { acrossTabs: true, enabled: best !== undefined }),
  );
  const stranded = bestMeta !== null && bestTable === null && !takesSelection(bestMeta);
  const selectable = pickedSource(
    family,
    useFamilyPick(family, analysisSelectableFigureRank, { acrossTabs: true, enabled: stranded }),
  );
  const selectableMeta = stranded ? (selectable?.metadata ?? null) : null;
  const selectableTableRank = useMemo(() => analysisTableRank(selectableMeta), [selectableMeta]);
  const selectableTable = pickedSource(
    family,
    useFamilyPick(family, selectableTableRank, {
      acrossTabs: true,
      enabled: stranded && selectable !== undefined,
    }),
  );
  const figure = stranded ? selectable : best;
  const table = stranded ? selectableTable : bestTable;
  const figureMeta = figure?.metadata ?? null;
  const tableDc = table?.metadata.dc_id as string | undefined;
  const figureDc = figureMeta?.dc_id as string | undefined;
  const cardRank = useMemo(() => analysisCardRank([tableDc, figureDc]), [tableDc, figureDc]);
  const card = pickedSource(
    family,
    useFamilyPick(family, cardRank, {
      acrossTabs: true,
      enabled: figure !== undefined && table !== undefined,
    }),
  );
  const analysisKey = [figure, table, card].map(sourceKey).join('|');
  const analysis = useMemo<AnalysisDemoSource | null | undefined>(() => {
    if (figure === undefined || table === undefined || card === undefined) return undefined;
    if (!figure && !table) return null;
    return { figure, table, card };
    // `analysisKey` is what was picked; the objects are rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisKey]);

  return { family, filter, sections, analysis };
}
