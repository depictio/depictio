/**
 * Which collections of a tab a view on runs leaves whole (epic #1399).
 *
 * The run filter and the run split go to every tile. The server skips a
 * filter on a column the collection does not carry, so a collection whose
 * rows have no `depictio_run_id` (a sample sheet shared by every run, a table
 * ingested before runs existed) is drawn whole, which would read as "all of
 * this is new". The tile says so; this finds those collections.
 */
import { useEffect, useState } from 'react';

import { fetchPolarsSchema } from 'depictio-react-core';
import type { StoredMetadata } from 'depictio-react-core';

import { RUN_COLUMN } from './newsSplit';

/** Tiles that read rows. MultiQC splits on its own samples. */
const ROW_TYPES = new Set(['figure', 'table', 'card', 'advanced_viz', 'map']);

/** Per collection, whether its rows carry a run. Kept for the page's life:
 *  a collection gains the column only by a re-ingest, which reloads. */
const carriesRun = new Map<string, Promise<boolean | null>>();

function lookup(dcId: string): Promise<boolean | null> {
  let hit = carriesRun.get(dcId);
  if (!hit) {
    // Unknown (no table yet, no access): no badge rather than a wrong one.
    // A failure is not kept, so a timeout does not hide the badge for good.
    hit = fetchPolarsSchema(dcId).then(
      (schema) => RUN_COLUMN in schema,
      () => {
        carriesRun.delete(dcId);
        return null;
      },
    );
    carriesRun.set(dcId, hit);
  }
  return hit;
}

/** The tab's row collections, deduplicated, in a stable order. */
export function rowCollections(components: readonly StoredMetadata[]): string[] {
  const ids = new Set<string>();
  for (const m of components) {
    const type = (m as { component_type?: string }).component_type;
    const dcId = (m as { dc_id?: string | null }).dc_id;
    if (dcId && type && ROW_TYPES.has(type)) ids.add(String(dcId));
  }
  return [...ids].sort();
}

const NONE: ReadonlySet<string> = new Set<string>();

export function useRunUnscopedDcs(
  components: readonly StoredMetadata[],
  enabled: boolean,
): ReadonlySet<string> {
  const key = enabled ? rowCollections(components).join(',') : '';
  const [unscoped, setUnscoped] = useState<ReadonlySet<string>>(NONE);
  useEffect(() => {
    if (!key) {
      setUnscoped(NONE);
      return;
    }
    let live = true;
    const ids = key.split(',');
    Promise.all(ids.map(lookup)).then((has) => {
      if (!live) return;
      const out = ids.filter((_, i) => has[i] === false);
      setUnscoped(out.length ? new Set(out) : NONE);
    });
    return () => {
      live = false;
    };
  }, [key]);
  return unscoped;
}
