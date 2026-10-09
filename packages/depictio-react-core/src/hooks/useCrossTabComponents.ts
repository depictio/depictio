import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  fetchCrossTabComponents,
  type CrossTabComponentsResponse,
  type FloatingComponent,
  type PersistentSection,
} from '../api';

export interface CrossTabComponents {
  /** Parent dashboard id — the family key cross-tab state is stored under. */
  familyId: string | null;
  /** Floating maps across the whole tab family, in tab order. */
  floating: FloatingComponent[];
  /** Sections marked `persistent: true` anywhere in the family, in tab order. */
  persistentSections: PersistentSection[];
  /** True once the fetch has settled (also on failure — the fetcher resolves
   *  empty rather than throwing). */
  resolved: boolean;
  /** Fetch again, after a write that can change another tab of the family
   *  (a version restore). Does not call `onResolved` a second time. */
  reload: () => void;
}

type CrossTabState = Omit<CrossTabComponents, 'reload'>;

/**
 * One request per page load for everything the current tab renders on behalf
 * of its siblings: the family's floating maps and its persistent sections.
 *
 * `onResolved` fires once, with the raw response — the shell uses it to decide
 * which cross-tab filters hydrated from storage are still valid. It is read
 * once at fetch time on purpose: it is a shell callback that changes identity
 * on every filter change, and re-fetching on that would defeat the point of a
 * single request per page load.
 *
 * `versionId` reads the family as it was in that stored version, for a
 * `?version=` preview: the parent's sections and maps as they were then, not
 * today's drawn over the version's data.
 */
export function useCrossTabComponents(
  dashboardId: string,
  onResolved?: (result: CrossTabComponentsResponse) => void,
  versionId?: string | null,
): CrossTabComponents {
  const [state, setState] = useState<CrossTabState>({
    familyId: null,
    floating: [],
    persistentSections: [],
    resolved: false,
  });
  const [generation, setGeneration] = useState(0);
  const resolvedOnce = useRef(false);

  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    fetchCrossTabComponents(dashboardId, versionId).then((res) => {
      if (cancelled) return;
      setState({
        familyId: res.parent_dashboard_id,
        floating: res.floating,
        persistentSections: res.persistent_sections,
        resolved: true,
      });
      if (!resolvedOnce.current) {
        resolvedOnce.current = true;
        onResolved?.(res);
      }
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, versionId, generation]);

  const reload = useCallback(() => setGeneration((g) => g + 1), []);

  return useMemo(() => ({ ...state, reload }), [state, reload]);
}
