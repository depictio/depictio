import { useCallback, useEffect, useState } from 'react';

export type ProjectTypeFilter = 'basic' | 'advanced';
export type VisibilityFilter = 'all' | 'public' | 'private';

export interface ProjectFilters {
  types: ProjectTypeFilter[];
  visibility: VisibilityFilter;
  templateSources: string[];
}

export interface ProjectViewPrefs {
  search: string;
  filters: ProjectFilters;
  onlyPinned: boolean;
}

const STORAGE_KEY = 'depictio.projects.viewPrefs.v1';

const DEFAULT_PREFS: ProjectViewPrefs = {
  search: '',
  filters: { types: [], visibility: 'all', templateSources: [] },
  onlyPinned: false,
};

function loadPrefs(): ProjectViewPrefs {
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

export interface UseProjectViewPrefsResult {
  prefs: ProjectViewPrefs;
  setSearch: (s: string) => void;
  setFilters: (f: ProjectFilters) => void;
  setOnlyPinned: (b: boolean) => void;
  clearFilters: () => void;
}

export function useProjectViewPrefs(): UseProjectViewPrefsResult {
  const [prefs, setPrefs] = useState<ProjectViewPrefs>(loadPrefs);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      /* quota or private mode — silently ignore */
    }
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
  const clearFilters = useCallback(
    () =>
      setPrefs((p) => ({
        ...p,
        search: '',
        onlyPinned: false,
        filters: { types: [], visibility: 'all', templateSources: [] },
      })),
    [],
  );

  return { prefs, setSearch, setFilters, setOnlyPinned, clearFilters };
}
