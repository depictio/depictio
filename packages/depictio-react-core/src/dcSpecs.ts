/**
 * Session-wide access to `/deltatables/specs/{dcId}` plus the small pure
 * helpers that decide which data collections a specs or unique-values call may
 * target.
 *
 * Two request floods motivated this module:
 *   - the available-values intersection asked every DC of the tab for the
 *     unique values of every filtered column, so each DC lacking the column
 *     answered 404 (`Column 'X' not found`);
 *   - MultiQC DCs have no Delta table, so any specs request for one answers
 *     404 (`No DeltaTable found`).
 * Specs are ingest-time aggregates that do not change within a session, so one
 * cached request per DC is enough to know which columns it carries.
 */
import { fetchSpecs, type StoredMetadata } from './api';

export interface SpecsEntry {
  name?: string;
  type?: string;
  specs?: { nunique?: number; [k: string]: unknown };
}

/** Normalise both specs shapes (list `[{name, type, specs}]` and the legacy
 *  dict `{column: {type, ...}}`) to the list shape. */
export function normaliseSpecs(specs: unknown): SpecsEntry[] {
  if (Array.isArray(specs)) return specs as SpecsEntry[];
  if (specs && typeof specs === 'object') {
    return Object.entries(specs as Record<string, Record<string, unknown>>).map(
      ([name, s]) => ({
        name,
        type: typeof s?.type === 'string' ? (s.type as string) : undefined,
        specs: (s ?? {}) as SpecsEntry['specs'],
      }),
    );
  }
  return [];
}

const specsCache = new Map<string, Promise<SpecsEntry[] | null>>();

/** Specs of one DC, fetched once per session. Resolves `null` when the specs
 *  are unavailable (no Delta table, network error); a failure is not cached so
 *  a later call can retry. */
export function fetchSpecsCached(dcId: string): Promise<SpecsEntry[] | null> {
  let pending = specsCache.get(dcId);
  if (!pending) {
    pending = fetchSpecs(dcId)
      .then((specs) => normaliseSpecs(specs))
      .catch(() => {
        specsCache.delete(dcId);
        return null;
      });
    specsCache.set(dcId, pending);
  }
  return pending;
}

/** DC ids bound to at least one `multiqc` component. MultiQC DCs have no Delta
 *  table: never ask `/deltatables/specs` or `/deltatables/unique_values`
 *  about their columns. */
export function multiqcDcIds(metadataList: StoredMetadata[] | undefined): Set<string> {
  const out = new Set<string>();
  for (const m of metadataList ?? []) {
    if (m.dc_id && m.component_type === 'multiqc') out.add(m.dc_id);
  }
  return out;
}

/** Whether a DC's specs list `columnName`. `null` specs (unavailable) count as
 *  "no": the unique-values endpoint would fail for that DC as well. */
export function specsHaveColumn(specs: SpecsEntry[] | null, columnName: string): boolean {
  return Boolean(specs?.some((e) => e?.name === columnName));
}
