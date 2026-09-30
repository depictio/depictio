import { useEffect, useState } from 'react';

import {
  fetchAdvancedVizData,
  fetchUniqueValues,
  type AdvancedVizKind,
  type InteractiveFilter,
} from '../../../api';
import { entitiesByRowCount } from './rendererData';

export interface EntityPicker {
  /** Every entity the bound table holds, sorted; null while loading. */
  entities: string[] | null;
  /** The entity on screen: the reader's pick, else the followed one, else the
   *  one with the most rows (the one molecule_3d opens on), else the first. */
  entity: string | null;
  setEntity: (next: string | null) => void;
  /** The distinct-values lookup failed: fetch unscoped and pick client-side. */
  failed: boolean;
}

/** Where the picker reads the entity column's rows to find the opening entity. */
export interface EntityRowSource {
  wfId: string | null | undefined;
  vizKind: AdvancedVizKind;
  /** The tile's filters (its own picks left out): the opening entity is the
   *  largest one still in scope, so the tile follows the dashboard's pickers. */
  filters: InteractiveFilter[];
}

/**
 * One entity at a time (a protein, an alignment family), picked in the tile or
 * followed from the dashboard: when a filter names exactly one entity that the
 * table holds (another tile's residue pick, a sidebar selector), the tile moves
 * to it; the reader can still pick another until the followed value changes.
 * `column` null means the table holds one entity and no picker is shown.
 *
 * With `rows`, the tile opens on the entity with the most rows under the
 * current filters (the entity column alone is read for that), as molecule_3d
 * does, so the protein tiles of a dashboard start on the same protein. The
 * list itself stays sorted and unfiltered.
 */
export function useEntityPicker(
  dcId: string | undefined,
  column: string | null | undefined,
  followed: string | null,
  refreshTick?: number,
  rows?: EntityRowSource,
): EntityPicker {
  const [entities, setEntities] = useState<string[] | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const wfId = rows?.wfId ?? null;
  const vizKind = rows?.vizKind ?? null;
  const filtersKey = JSON.stringify(rows?.filters ?? []);

  useEffect(() => {
    if (!dcId || !column) {
      setEntities([]);
      setOpening(null);
      setFailed(false);
      return;
    }
    let cancelled = false;
    setEntities(null);
    fetchUniqueValues(dcId, column)
      .then((values) => {
        if (cancelled) return;
        const clean = Array.from(new Set(values.filter((v) => v != null && v !== '').map(String)));
        clean.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
        setEntities(clean);
        setFailed(false);
      })
      .catch(() => {
        if (cancelled) return;
        setEntities([]);
        setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId, column, refreshTick]);

  // The opening entity is a preference: without it the first one opens.
  useEffect(() => {
    if (!dcId || !column || !wfId || !vizKind) {
      setOpening(null);
      return;
    }
    let cancelled = false;
    const filters = JSON.parse(filtersKey) as InteractiveFilter[];
    fetchAdvancedVizData({ wfId, dcId, columns: [column], filters, vizKind })
      .then((res) => {
        if (!cancelled) setOpening(entitiesByRowCount(res.rows?.[column] ?? [])[0] ?? null);
      })
      .catch(() => {
        if (!cancelled) setOpening(null);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId, column, refreshTick, wfId, vizKind, filtersKey]);

  useEffect(() => {
    if (followed && entities?.includes(followed)) setPicked(followed);
  }, [followed, entities]);

  let entity: string | null = null;
  if (column && entities && entities.length) {
    if (picked && entities.includes(picked)) entity = picked;
    else if (opening && entities.includes(opening)) entity = opening;
    else entity = entities[0];
  }
  return { entities, entity, setEntity: setPicked, failed };
}
