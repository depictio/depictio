/**
 * Cross-DC "available values" intersection — supports greying out values in
 * interactive filter dropdowns that the metadata declares but that are not
 * present in any of the data collections actually loaded by the dashboard.
 *
 * Model
 * -----
 * The dashboard has N data collections used by figures / tables / multiqc.
 * If those DCs join on a shared column (typically sample_id), the set of
 * values "present in the loaded data" is the INTERSECTION of unique values of
 * that column across all participating DCs. A filter's source DC might
 * declare more values than are actually represented — we use the intersection
 * to mark the unrepresented values as disabled.
 *
 * Heuristic (v1, intentionally simple)
 * ------------------------------------
 * For a filter on (dc_id_F, column_F):
 *   1. Walk dashboard.stored_metadata for distinct dc_ids referenced by
 *      figure / table / multiqc / map / image components.
 *   2. For each such dc_id (including the filter's own), call
 *      `fetchUniqueValues(dc_id, column_F)`. DCs that don't have a column
 *      with that name return an error → we skip them silently. A DC missing
 *      the column is treated as "no constraint from this DC" rather than
 *      "everything excluded".
 *   3. Intersect the successful results.
 *   4. Cache the resulting Set keyed by `${dc_id_F}|${column_F}`.
 *
 * When fewer than 2 DCs return data the intersection is meaningless (no
 * cross-DC narrowing possible) — we return `null` and the consumer skips
 * the greying-out behavior entirely.
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { fetchMultiQCSampleMappings, fetchUniqueValues, StoredMetadata } from './api';

interface AvailableValuesContextValue {
  /** Trigger a compute for this (dc_id, column) if not already done. */
  request: (dcId: string, columnName: string) => void;
  /** Get the cached intersection or null if not yet computed / not applicable. */
  getSet: (dcId: string, columnName: string) => Set<string> | null;
}

const AvailableValuesContext =
  createContext<AvailableValuesContextValue | null>(null);

function key(dcId: string, columnName: string): string {
  return `${dcId}|${columnName}`;
}

interface DataDcEntry {
  dcId: string;
  /** ``component_type`` of the first metadata entry referencing this dc_id —
   *  used to pick the right "fetch unique values for this DC" path
   *  (deltatables for table/figure/map/image/card, multiqc sample mappings
   *  for multiqc DCs which don't expose row data via the delta endpoint). */
  type: string;
}

/** Walks the dashboard metadata and returns the distinct `dc_id`s that
 *  contribute to the "loaded data" view — figures, tables, multiqc, map,
 *  image. Cards count too (their values are computed against a DC), but
 *  they don't expose row data to the user so we still include them since
 *  the join semantics apply equally. */
function collectDataDcs(metadataList: StoredMetadata[] | undefined): DataDcEntry[] {
  if (!metadataList) return [];
  const byId = new Map<string, DataDcEntry>();
  for (const m of metadataList) {
    if (!m.dc_id) continue;
    const t = m.component_type;
    if (
      t === 'figure' ||
      t === 'table' ||
      t === 'multiqc' ||
      t === 'map' ||
      t === 'image' ||
      t === 'card'
    ) {
      if (!byId.has(m.dc_id)) byId.set(m.dc_id, { dcId: m.dc_id, type: t });
    }
  }
  return Array.from(byId.values());
}

export interface AvailableFilterValuesProviderProps {
  dashboardMetadata: StoredMetadata[] | undefined;
  /** Project ID — required to resolve MultiQC sample mappings (the
   *  `/links/{projectId}/multiqc/{dcId}/sample-mappings` endpoint is
   *  scoped per project). When absent, multiqc DCs are skipped and the
   *  intersection falls back to whatever delta-table DCs contribute. */
  projectId?: string;
  children: React.ReactNode;
}

export const AvailableFilterValuesProvider: React.FC<
  AvailableFilterValuesProviderProps
> = ({ dashboardMetadata, projectId, children }) => {
  const [cache, setCache] = useState<Record<string, Set<string> | null>>({});
  // Tracks which keys are currently being computed so we don't double-fetch.
  const inFlightRef = useRef<Set<string>>(new Set());

  const dcs = useMemo(
    () => collectDataDcs(dashboardMetadata),
    [dashboardMetadata],
  );
  const dcSignature = useMemo(
    () => dcs.map((d) => `${d.type}:${d.dcId}`).join('|'),
    [dcs],
  );

  // Reset cache when the dashboard's set of DCs changes — the intersection
  // becomes stale.
  useEffect(() => {
    setCache({});
    inFlightRef.current = new Set();
  }, [dcSignature]);

  const request = useCallback(
    (dcId: string, columnName: string) => {
      if (!dcId || !columnName) return;
      const k = key(dcId, columnName);
      if (k in cache) return;
      if (inFlightRef.current.has(k)) return;
      // No other DCs to intersect against → no narrowing possible.
      if (dcs.length < 2) {
        setCache((prev) => ({ ...prev, [k]: null }));
        return;
      }
      inFlightRef.current.add(k);

      // Dispatch per DC type: delta-table DCs (table/figure/map/image/card)
      // expose a per-column unique-values endpoint, multiqc DCs only expose
      // their sample list via the per-project sample-mappings endpoint.
      // Mapping returns `{canonical: [variants...]}` — flatten to a set of
      // all known sample names so it matches whatever convention the
      // metadata table uses (canonical or variant).
      const fetchOne = (entry: DataDcEntry): Promise<Set<string>> => {
        if (entry.type === 'multiqc') {
          if (!projectId) return Promise.reject(new Error('no projectId'));
          return fetchMultiQCSampleMappings(projectId, entry.dcId).then((mappings) => {
            const out = new Set<string>();
            for (const [canonical, variants] of Object.entries(mappings)) {
              out.add(canonical);
              if (Array.isArray(variants)) {
                for (const v of variants) out.add(v);
              }
            }
            return out;
          });
        }
        return fetchUniqueValues(entry.dcId, columnName).then((values) => new Set(values));
      };

      Promise.allSettled(dcs.map(fetchOne))
        .then((results) => {
          const sets: Set<string>[] = [];
          for (const r of results) {
            if (r.status === 'fulfilled') sets.push(r.value);
            // Rejected = column doesn't exist on that DC (or multiqc has no
            // sample mappings yet) — treated as "no constraint from this DC".
          }
          let intersection: Set<string> | null = null;
          if (sets.length >= 2) {
            // Start from the smallest set to minimize work.
            sets.sort((a, b) => a.size - b.size);
            intersection = new Set(sets[0]);
            for (let i = 1; i < sets.length; i++) {
              const next = sets[i];
              for (const v of intersection) {
                if (!next.has(v)) intersection.delete(v);
              }
            }
          }
          setCache((prev) => ({ ...prev, [k]: intersection }));
          inFlightRef.current.delete(k);
        })
        .catch(() => {
          // All requests failed — cache `null` so consumer skips the
          // greying behavior gracefully.
          setCache((prev) => ({ ...prev, [k]: null }));
          inFlightRef.current.delete(k);
        });
    },
    [cache, dcs, projectId],
  );

  const getSet = useCallback(
    (dcId: string, columnName: string): Set<string> | null => {
      return cache[key(dcId, columnName)] ?? null;
    },
    [cache],
  );

  const value = useMemo(() => ({ request, getSet }), [request, getSet]);

  return (
    <AvailableValuesContext.Provider value={value}>
      {children}
    </AvailableValuesContext.Provider>
  );
};

/** Hook for filter renderers — returns the available-value Set for the given
 *  (dc_id, column). The renderer should mark options NOT in the Set as
 *  disabled. Returns `null` when:
 *    - no provider is mounted (legacy use cases), OR
 *    - fewer than two DCs contribute data (nothing to intersect with), OR
 *    - the computation is still in flight.
 *  In all `null` cases the renderer should treat every option as available. */
export function useAvailableSet(
  dcId: string | undefined,
  columnName: string | undefined,
): Set<string> | null {
  const ctx = useContext(AvailableValuesContext);
  useEffect(() => {
    if (!ctx || !dcId || !columnName) return;
    ctx.request(dcId, columnName);
  }, [ctx, dcId, columnName]);
  if (!ctx || !dcId || !columnName) return null;
  return ctx.getSet(dcId, columnName);
}
