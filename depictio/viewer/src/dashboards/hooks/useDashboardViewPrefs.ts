import { useCallback, useEffect, useState } from 'react';

import { asEnum, asList, asScalar } from 'depictio-react-core';

import {
  arrivedWithParams,
  readListingParams,
  replaceListingParams,
} from '../../lib/listingUrl';

export type ViewMode = 'thumbnails' | 'table';
export type GroupBy = 'none' | 'project' | 'owner' | 'visibility' | 'workflow';
export type SortBy = 'recent' | 'name' | 'owner';
export type Density = 'compact' | 'cozy';
export type VisibilityFilter = 'all' | 'public' | 'private';
/** Thumbnail grid columns at the widest breakpoint. `auto` is the responsive
 *  default; a number caps the grid at that many cards per row. */
export type CardsPerRow = 'auto' | 2 | 3 | 4 | 5 | 6;
/** The metadata badges a thumbnail card can show under its title. */
export type CardBadge =
  | 'project'
  | 'template'
  | 'owner'
  | 'visibility'
  | 'modified'
  | 'tabs';

export const CARDS_PER_ROW_OPTIONS: readonly CardsPerRow[] = ['auto', 2, 3, 4, 5, 6];
/** Every card badge, in the order the card renders them. Selections are kept
 *  in this order too, so toggling one off and on again never reshuffles the
 *  row. */
export const CARD_BADGES: readonly CardBadge[] = [
  'project',
  'template',
  'owner',
  'visibility',
  'modified',
  'tabs',
];

const VIEW_MODES: readonly ViewMode[] = ['thumbnails', 'table'];
const GROUP_BYS: readonly GroupBy[] = [
  'none',
  'project',
  'owner',
  'visibility',
  'workflow',
];
const SORT_BYS: readonly SortBy[] = ['recent', 'name', 'owner'];
const VISIBILITIES: readonly VisibilityFilter[] = ['all', 'public', 'private'];

export interface DashboardFilters {
  projects: string[];
  owners: string[];
  /** Pipeline templates, as `source` or `source/repo` — see
   *  `matchesTemplateFilter`. Resolved through the dashboard's owning
   *  project, which is where `template_origin` lives. */
  templates: string[];
  workflows: string[];
  visibility: VisibilityFilter;
}

export interface DashboardViewPrefs {
  view: ViewMode;
  /** True once the view came from the person: they picked one in the toolbar,
   *  or opened a link that named one. Until then the deployment's default
   *  (`DEPICTIO_VIEWER_DASHBOARDS_DEFAULT_VIEW`) may still change it under
   *  them, which is what lets an instance open on the table without
   *  overriding anybody's choice. */
  viewChosen: boolean;
  groupBy: GroupBy;
  sortBy: SortBy;
  search: string;
  filters: DashboardFilters;
  density: Density;
  onlyPinned: boolean;
  /** Thumbnails view only. Layout, like `density`, so it stays out of the
   *  URL: a shared link carries what is listed, not how the sender likes
   *  their cards laid out. */
  cardsPerRow: CardsPerRow;
  cardBadges: CardBadge[];
}

/** No filter at all. A factory rather than a constant: the toolbar's "Clear
 *  all" and the hook's `clearFilters` both need one, and a shared object would
 *  hand them the same arrays to hold. They can't drift as filters are added,
 *  and they can't alias each other either. */
export const emptyDashboardFilters = (): DashboardFilters => ({
  projects: [],
  owners: [],
  templates: [],
  workflows: [],
  visibility: 'all',
});

const STORAGE_KEY = 'depictio.dashboards.viewPrefs.v1';

/** URL params that narrow *what is listed*, as opposed to how it is laid out.
 *  Arriving with one of these is what makes a page load a "shared view". */
export const DASHBOARD_SCOPE_PARAMS = [
  'q',
  'template',
  'project',
  'owner',
  'workflow',
  'visibility',
  'pinned',
] as const;

const DEFAULT_PREFS: DashboardViewPrefs = {
  view: 'thumbnails',
  viewChosen: false,
  groupBy: 'none',
  sortBy: 'recent',
  search: '',
  filters: emptyDashboardFilters(),
  density: 'cozy',
  onlyPinned: false,
  cardsPerRow: 'auto',
  cardBadges: [...CARD_BADGES],
};

/** Stored prefs come back from localStorage untyped, and these feed the grid
 *  and the card directly: an unknown view, column count or badge key falls
 *  back to the default rather than reaching the layout. The view sanitizer
 *  also catches the retired `list` (Tiles) value left in older browsers. */
function sanitizeView(raw: unknown): ViewMode {
  return VIEW_MODES.find((v) => v === raw) ?? DEFAULT_PREFS.view;
}

function sanitizeCardsPerRow(raw: unknown): CardsPerRow {
  return CARDS_PER_ROW_OPTIONS.find((v) => v === raw) ?? DEFAULT_PREFS.cardsPerRow;
}

function sanitizeCardBadges(raw: unknown): CardBadge[] {
  if (!Array.isArray(raw)) return [...CARD_BADGES];
  return CARD_BADGES.filter((b) => raw.includes(b));
}

function loadPrefs(): DashboardViewPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw);
    return {
      ...DEFAULT_PREFS,
      ...parsed,
      filters: { ...DEFAULT_PREFS.filters, ...(parsed?.filters ?? {}) },
      view: sanitizeView(parsed?.view),
      viewChosen: parsed?.viewChosen === true,
      cardsPerRow: sanitizeCardsPerRow(parsed?.cardsPerRow),
      cardBadges: sanitizeCardBadges(parsed?.cardBadges),
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

/** Overlay whatever the URL asked for onto the stored preferences.
 *
 *  The link wins on every field it mentions and stays out of the way on the
 *  rest: a reviewer opening `?template=nf-core/rnaseq` gets that scope on top
 *  of their own habitual view mode and sort order, and a bare `/dashboards`
 *  is unchanged from what they left behind. The one asymmetry is deliberate —
 *  a link that names *any* filter clears the stored filters it doesn't
 *  mention, so a scoped link never silently inherits the recipient's leftover
 *  "owner: me" and shows them an empty page. */
function applyUrlParams(base: DashboardViewPrefs): DashboardViewPrefs {
  const params = readListingParams();
  const next: DashboardViewPrefs = {
    ...base,
    filters: { ...base.filters },
  };

  const urlView = asEnum(params.view, VIEW_MODES);
  if (urlView) {
    next.view = urlView;
    next.viewChosen = true;
  }
  next.groupBy = asEnum(params.group, GROUP_BYS) ?? next.groupBy;
  next.sortBy = asEnum(params.sort, SORT_BYS) ?? next.sortBy;

  const scoped = DASHBOARD_SCOPE_PARAMS.some(
    (key) => (params[key]?.length ?? 0) > 0,
  );
  if (!scoped) return next;

  next.search = asScalar(params.q) ?? '';
  next.onlyPinned = asScalar(params.pinned) === '1';
  next.filters = {
    projects: asList(params.project),
    owners: asList(params.owner),
    templates: asList(params.template),
    workflows: asList(params.workflow),
    visibility: asEnum(params.visibility, VISIBILITIES) ?? 'all',
  };
  return next;
}

/** The query string that reproduces these preferences. `defaultView` is the
 *  deployment's own default, which stays unnamed in the URL just like the
 *  built-in one: everyone on this instance resolves a bare link the same way. */
function toUrlParams(prefs: DashboardViewPrefs, defaultView: ViewMode) {
  return {
    q: prefs.search.trim(),
    template: prefs.filters.templates,
    project: prefs.filters.projects,
    owner: prefs.filters.owners,
    workflow: prefs.filters.workflows,
    visibility: prefs.filters.visibility === 'all' ? '' : prefs.filters.visibility,
    pinned: prefs.onlyPinned,
    view: prefs.view === defaultView ? '' : prefs.view,
    group: prefs.groupBy === DEFAULT_PREFS.groupBy ? '' : prefs.groupBy,
    sort: prefs.sortBy === DEFAULT_PREFS.sortBy ? '' : prefs.sortBy,
  };
}

export interface UseDashboardViewPrefsResult {
  prefs: DashboardViewPrefs;
  /** True when the page was opened on a link that already carried a filter. */
  arrivedScoped: boolean;
  setView: (v: ViewMode) => void;
  setGroupBy: (g: GroupBy) => void;
  setSortBy: (s: SortBy) => void;
  setSearch: (s: string) => void;
  setFilters: (f: DashboardFilters) => void;
  setDensity: (d: Density) => void;
  setOnlyPinned: (b: boolean) => void;
  setCardsPerRow: (c: CardsPerRow) => void;
  setCardBadges: (b: CardBadge[]) => void;
  clearFilters: () => void;
}

export function useDashboardViewPrefs(
  /** Deployment default, once the auth round-trip has delivered it. */
  serverDefaultView?: ViewMode | null,
): UseDashboardViewPrefsResult {
  const [prefs, setPrefs] = useState<DashboardViewPrefs>(() =>
    applyUrlParams(loadPrefs()),
  );
  const [arrivedScoped] = useState(() => arrivedWithParams(DASHBOARD_SCOPE_PARAMS));

  // The deployment default lands after the first paint, with the auth
  // response. It moves the listing only for someone who never chose, so it
  // can override neither a picked view nor a shared link.
  useEffect(() => {
    if (!serverDefaultView) return;
    setPrefs((p) =>
      p.viewChosen || p.view === serverDefaultView ? p : { ...p, view: serverDefaultView },
    );
  }, [serverDefaultView]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      /* quota or private mode — silently ignore */
    }
    // Keep the address bar showing the view on screen, so copying it out of
    // the browser is always equivalent to pressing the share button.
    replaceListingParams(toUrlParams(prefs, serverDefaultView ?? DEFAULT_PREFS.view));
  }, [prefs, serverDefaultView]);

  const setView = useCallback(
    (view: ViewMode) => setPrefs((p) => ({ ...p, view, viewChosen: true })),
    [],
  );
  const setGroupBy = useCallback(
    (groupBy: GroupBy) => setPrefs((p) => ({ ...p, groupBy })),
    [],
  );
  const setSortBy = useCallback(
    (sortBy: SortBy) => setPrefs((p) => ({ ...p, sortBy })),
    [],
  );
  const setSearch = useCallback(
    (search: string) => setPrefs((p) => ({ ...p, search })),
    [],
  );
  const setFilters = useCallback(
    (filters: DashboardFilters) => setPrefs((p) => ({ ...p, filters })),
    [],
  );
  const setDensity = useCallback(
    (density: Density) => setPrefs((p) => ({ ...p, density })),
    [],
  );
  const setOnlyPinned = useCallback(
    (onlyPinned: boolean) => setPrefs((p) => ({ ...p, onlyPinned })),
    [],
  );
  const setCardsPerRow = useCallback(
    (cardsPerRow: CardsPerRow) => setPrefs((p) => ({ ...p, cardsPerRow })),
    [],
  );
  const setCardBadges = useCallback(
    (cardBadges: CardBadge[]) => setPrefs((p) => ({ ...p, cardBadges })),
    [],
  );
  const clearFilters = useCallback(
    () =>
      setPrefs((p) => ({
        ...p,
        search: '',
        onlyPinned: false,
        filters: emptyDashboardFilters(),
      })),
    [],
  );

  return {
    prefs,
    arrivedScoped,
    setView,
    setGroupBy,
    setSortBy,
    setSearch,
    setFilters,
    setDensity,
    setOnlyPinned,
    setCardsPerRow,
    setCardBadges,
    clearFilters,
  };
}
