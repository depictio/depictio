import { useEffect, useState } from 'react';
import type { KindsMap } from '../types';

/**
 * The advanced_viz kind descriptors, from the build-generated `kinds.json`
 * (`depictio dev catalog kinds --json`, served from the app base).
 *
 * The snapshot IS depictio's `GET /advanced_viz/kinds` payload plus a `heavy`
 * flag — the same list the offline api shim serves to depictio's real
 * `AdvancedVizBuilder`. This hook narrows it to the map the Studio's own
 * grounding and render-card labelling read.
 */
export interface KindDescriptorPayload {
  viz_kind: string;
  label: string;
  description: string;
  icon: string;
  category: string;
  required_roles: string[];
  roles: Record<string, { required: boolean; dtypes: string[]; description: string }>;
  heavy: boolean;
}

export function kindsMapFrom(payload: KindDescriptorPayload[]): KindsMap {
  const map: KindsMap = {};
  for (const k of payload) {
    map[k.viz_kind] = {
      label: k.label,
      heavy: k.heavy,
      required_roles: k.required_roles,
      roles: Object.fromEntries(
        Object.entries(k.roles ?? {}).map(([role, spec]) => [role, spec.dtypes]),
      ),
    };
  }
  return map;
}

export function useKinds(): { kinds: KindsMap; loading: boolean } {
  const [kinds, setKinds] = useState<KindsMap>({});
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    fetch(`${import.meta.env.BASE_URL}kinds.json`)
      .then((r) => r.json())
      .then((data: { kinds?: KindDescriptorPayload[] }) => {
        if (!cancelled) setKinds(kindsMapFrom(data?.kinds ?? []));
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
