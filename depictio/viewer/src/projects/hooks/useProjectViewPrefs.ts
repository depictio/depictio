import { useCallback, useEffect, useState } from 'react';

import { asEnum, asList, asScalar } from 'depictio-react-core';

import {
  arrivedWithParams,
  readListingParams,
  replaceListingParams,
} from '../../lib/listingUrl';

export type ProjectTypeFilter = 'basic' | 'advanced';
/** Row height for the projects table. Mirrors the dashboards table's setting
 *  so both listings offer the same compact/cozy choice. */
export type Density = 'compact' | 'cozy';
export type VisibilityFilter = 'all' | 'public' | 'private';

const PROJECT_TYPES: readonly ProjectTypeFilter[] = ['basic', 'advanced'];
const VISIBILITIES: readonly VisibilityFilter[] = ['all', 'public', 'private'];

export interface ProjectFilters {
  types: ProjectTypeFilter[];
  visibility: VisibilityFilter;
  /** Pipeline templates, as `source` (`nf-core`) or `source/repo`
   *  (`nf-core/rnaseq`). Superseded the source-only `templateSources`, which
   *  could not tell one pipeline from another. */
  templates: string[];
}

export interface ProjectViewPrefs {
  search: string;
  filters: ProjectFilters;
  onlyPinned: boolean;
  density: Density;
}

const STORAGE_KEY = 'depictio.projects.viewPrefs.v1';

/** No filter at all. A factory rather than a constant: the toolbar's "Clear
 *  all" and `clearFilters` both need one, and a shared object would hand them
 *  the same arrays to hold. */
export const emptyProjectFilters = (): ProjectFilters => ({
  types: [],
  visibility: 'all',
  templates: [],
});

/** URL params that narrow what is listed, as opposed to how it is laid out.
 *  Arriving with one of these is what makes a page load a "shared view". */
export const PROJECT_SCOPE_PARAMS = [
  'q',
  'template',
  'type',
  'visibility',
  'pinned',
] as const;

const DEFAULT_PREFS: ProjectViewPrefs = {
  search: '',
  filters: emptyProjectFilters(),
  onlyPinned: false,
  density: 'cozy',
};

function loadPrefs(): ProjectViewPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw);
    const filters = { ...emptyProjectFilters(), ...(parsed?.filters ?? {}) };
    // Carry a preference saved before the filter learned about pipelines: the
    // old field held bare sources, which are still valid values.
    if (filters.templates.length === 0 && Array.isArray(parsed?.filters?.templateSources)) {
      filters.templates = parsed.filters.templateSources;
    }
    delete (filters as { templateSources?: unknown }).templateSources;
    return { ...DEFAULT_PREFS, ...parsed, filters };
  } catch {
    return DEFAULT_PREFS;
  }
}

/** Overlay whatever the URL asked for onto the stored preferences. A link
 *  that names any filter replaces the stored filters wholesale, so a scoped
 *  link never inherits the recipient's leftovers and shows them an empty
 *  page; a bare `/projects` leaves their own view untouched. */
function applyUrlParams(base: ProjectViewPrefs): ProjectViewPrefs {
  const params = readListingParams();
  const scoped = PROJECT_SCOPE_PARAMS.some((key) => (params[key]?.length ?? 0) > 0);
  if (!scoped) return base;

  const types = asList(params.type).filter((t): t is ProjectTypeFilter =>
    (PROJECT_TYPES as readonly string[]).includes(t),
  );
  return {
    ...base,
    search: asScalar(params.q) ?? '',
    onlyPinned: asScalar(params.pinned) === '1',
    filters: {
      types,
      visibility: asEnum(params.visibility, VISIBILITIES) ?? 'all',
      templates: asList(params.template),
    },
  };
}

/** The query string that reproduces these preferences. */
function toUrlParams(prefs: ProjectViewPrefs) {
  return {
    q: prefs.search.trim(),
    template: prefs.filters.templates,
    type: prefs.filters.types,
    visibility: prefs.filters.visibility === 'all' ? '' : prefs.filters.visibility,
    pinned: prefs.onlyPinned,
  };
}

export interface UseProjectViewPrefsResult {
  prefs: ProjectViewPrefs;
  /** True when the page was opened on a link that already carried a filter. */
  arrivedScoped: boolean;
  setSearch: (s: string) => void;
  setFilters: (f: ProjectFilters) => void;
  setOnlyPinned: (b: boolean) => void;
  setDensity: (d: Density) => void;
  clearFilters: () => void;
}

export function useProjectViewPrefs(): UseProjectViewPrefsResult {
  const [prefs, setPrefs] = useState<ProjectViewPrefs>(() =>
    applyUrlParams(loadPrefs()),
  );
  const [arrivedScoped] = useState(() => arrivedWithParams(PROJECT_SCOPE_PARAMS));

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

  const setSearch = useCallback(
    (search: string) => setPrefs((p) => ({ ...p, search })),
    [],
  );
  const setFilters = useCallback(
    (filters: ProjectFilters) => setPrefs((p) => ({ ...p, filters })),
    [],
  );
  const setOnlyPinned = useCallback(
    (onlyPinned: boolean) => setPrefs((p) => ({ ...p, onlyPinned })),
    [],
  );
  const setDensity = useCallback(
    (density: Density) => setPrefs((p) => ({ ...p, density })),
    [],
  );
  const clearFilters = useCallback(
    () =>
      setPrefs((p) => ({
        ...p,
        search: '',
        onlyPinned: false,
        filters: emptyProjectFilters(),
      })),
    [],
  );

  return {
    prefs,
    arrivedScoped,
    setSearch,
    setFilters,
    setOnlyPinned,
    setDensity,
    clearFilters,
  };
}
