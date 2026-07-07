import { useEffect, useState } from 'react';
import type { KindsMap } from '../types';

/**
 * Load the build-generated kinds.json (advanced_viz roles/dtypes). Served from
 * the app base (public/kinds.json). Returns an empty map until loaded.
 */
export function useKinds(): { kinds: KindsMap; loading: boolean } {
  const [kinds, setKinds] = useState<KindsMap>({});
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    fetch(`${import.meta.env.BASE_URL}kinds.json`)
      .then((r) => r.json())
      .then((data: KindsMap) => {
        if (!cancelled) setKinds(data);
      })
      .catch(() => {
        /* leave empty — advanced_viz validation degrades gracefully */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return { kinds, loading };
}

export function makeIsHeavy(kinds: KindsMap): (kind: string) => boolean {
  return (kind: string) => Boolean(kinds[kind]?.heavy);
}
