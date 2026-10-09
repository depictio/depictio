/**
 * Which of a tab's collections the current data pins reach, for the banners.
 *
 * One small POST per change of pins (and per `refreshToken`, so a version list
 * reload after a prune re-checks a version that may be gone). A stale
 * `as_of_version` fails here like a render does, which raises the same
 * `DATA_VERSION_GONE_EVENT` the editor already listens for.
 */

import { useEffect, useRef, useState } from 'react';
import {
  fetchDataVersionStatus,
  type DataPinFields,
  type DataVersionCollectionStatus,
} from 'depictio-react-core';

export interface DataVersionStatusState {
  /** Null while loading, after a failure, or while nothing is pinned. */
  collections: DataVersionCollectionStatus[] | null;
  error: string | null;
}

export function useDataVersionStatus(
  dashboardId: string | null | undefined,
  /** The pins to describe; null while no data version is active. */
  pins: DataPinFields | null,
  refreshToken?: unknown,
): DataVersionStatusState {
  const [state, setState] = useState<DataVersionStatusState>({ collections: null, error: null });
  const pinKey = pins ? JSON.stringify(pins) : null;
  // The pins the status on screen describes. A refresh for the same pins keeps
  // it while it refetches; new pins clear it, so the banner never names the
  // previous selection's collections under the new one.
  const shownFor = useRef<string | null>(null);

  useEffect(() => {
    if (shownFor.current !== pinKey) {
      shownFor.current = pinKey;
      setState({ collections: null, error: null });
    }
    if (!dashboardId || !pins) return;
    let cancelled = false;
    fetchDataVersionStatus(dashboardId, pins)
      .then((res) => {
        if (!cancelled) setState({ collections: res.collections, error: null });
      })
      .catch((err) => {
        if (!cancelled) {
          setState({
            collections: null,
            error: err instanceof Error ? err.message : String(err),
          });
        }
      });
    return () => {
      cancelled = true;
    };
    // `pinKey` is the content of `pins`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, pinKey, refreshToken]);

  return state;
}
