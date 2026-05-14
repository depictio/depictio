import { useCallback, useEffect, useState } from 'react';

export type ViewMode = 'thumbnails' | 'list' | 'table';
export type GroupBy = 'none' | 'project' | 'owner' | 'visibility' | 'workflow';
export type SortBy = 'recent' | 'name' | 'owner';
export type Density = 'compact' | 'cozy';

export interface DashboardFilters {
  projects: string[];
  owners: string[];
  visibility: 'all' | 'public' | 'private';
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

const STORAGE_KEY = 'depictio.dashboards.viewPrefs.v1';

const DEFAULT_PREFS: DashboardViewPrefs = {
  view: 'thumbnails',
  groupBy: 'none',
  sortBy: 'recent',
  search: '',
  filters: { projects: [], owners: [], visibility: 'all' },
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

export interface UseDashboardViewPrefsResult {
  prefs: DashboardViewPrefs;
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
  const [prefs, setPrefs] = useState<DashboardViewPrefs>(loadPrefs);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      /* quota or private mode — silently ignore */
    }
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
        filters: { projects: [], owners: [], visibility: 'all' },
      })),
    [],
  );

  return {
    prefs,
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
