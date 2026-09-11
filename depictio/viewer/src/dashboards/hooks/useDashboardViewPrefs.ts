import { useCallback, useEffect, useState } from 'react';

import { asEnum, asList, asScalar } from 'depictio-react-core';

import {
  arrivedWithParams,
  readListingParams,
  replaceListingParams,
} from '../../lib/listingUrl';

export type ViewMode = 'thumbnails' | 'list' | 'table';
export type GroupBy = 'none' | 'project' | 'owner' | 'visibility' | 'workflow';
export type SortBy = 'recent' | 'name' | 'owner';
export type Density = 'compact' | 'cozy';
export type VisibilityFilter = 'all' | 'public' | 'private';

const VIEW_MODES: readonly ViewMode[] = ['thumbnails', 'list', 'table'];
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
  groupBy: GroupBy;
  sortBy: SortBy;
  search: string;
  filters: DashboardFilters;
  density: Density;
  onlyPinned: boolean;
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
  groupBy: 'none',
  sortBy: 'recent',
  search: '',
  filters: emptyDashboardFilters(),
  density: 'cozy',
  onlyPinned: false,
};

function loadPrefs(): DashboardViewPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw);
    return {
      ...DEFAULT_PREFS,
      ...parsed,
      filters: { ...DEFAULT_PREFS.filters, ...(parsed?.filters ?? {}) },
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

  next.view = asEnum(params.view, VIEW_MODES) ?? next.view;
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

/** The query string that reproduces these preferences. */
function toUrlParams(prefs: DashboardViewPrefs) {
  return {
    q: prefs.search.trim(),
    template: prefs.filters.templates,
    project: prefs.filters.projects,
    owner: prefs.filters.owners,
    workflow: prefs.filters.workflows,
    visibility: prefs.filters.visibility === 'all' ? '' : prefs.filters.visibility,
    pinned: prefs.onlyPinned,
    view: prefs.view === DEFAULT_PREFS.view ? '' : prefs.view,
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
  clearFilters: () => void;
}

export function useDashboardViewPrefs(): UseDashboardViewPrefsResult {
  const [prefs, setPrefs] = useState<DashboardViewPrefs>(() =>
    applyUrlParams(loadPrefs()),
  );
  const [arrivedScoped] = useState(() => arrivedWithParams(DASHBOARD_SCOPE_PARAMS));

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      /* quota or private mode — silently ignore */
    }
    // Keep the address bar showing the view on screen, so copying it out of
    // the browser is always equivalent to pressing the share button.
    replaceListingParams(toUrlParams(prefs));
  }, [prefs]);

  const setView = useCallback(
    (view: ViewMode) => setPrefs((p) => ({ ...p, view })),
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
    clearFilters,
  };
}
