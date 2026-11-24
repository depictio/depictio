import { useEffect, useMemo, useState } from 'react';

import {
  fetchAdvancedVizData,
  fetchUniqueValues,
  type AdvancedVizKind,
  type InteractiveFilter,
} from '../../../api';
import { useSharedOpeningEntity } from '../../../highlight/openingEntity';
import {
  chooseEntity,
  compareEntityNames,
  entitiesByRowCount,
  heldEntities,
  withoutFiltersOn,
} from './rendererData';

/** Distinct values the picker asks for: every family or protein of a table,
 *  not the 1,000 a filter's option list stops at. The server caps it. */
export const ENTITY_LIST_LIMIT = 100_000;

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
  /** Share the opening entity with the dashboard's other protein tiles under
   *  this key (the entity column name residue picks travel on), so they all
   *  open on the same one (see `highlight/openingEntity.ts`). */
  shareKey?: string | null;
  /** The tile's index, owner of its claim on `shareKey`. */
  owner?: string;
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
 * does. With `rows.shareKey`, the first protein tile of the dashboard to know
 * its opening entity sets it for the others that hold it, so they start on
 * the same protein. The list itself stays sorted and unfiltered.
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
  // Every entity the dashboard's filters leave, when the read was whole.
  const [inScope, setInScope] = useState<ReadonlySet<string> | null>(null);
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
    fetchUniqueValues(dcId, column, null, null, ENTITY_LIST_LIMIT)
      .then((values) => {
        if (cancelled) return;
        const clean = Array.from(new Set(values.filter((v) => v != null && v !== '').map(String)));
        clean.sort(compareEntityNames);
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

  // Once the reader picks in the tile, the entities the dashboard's filters
  // leave for that pick: the tile's fetch replaces any filter on its own
  // column with the pick (`scopeToEntity`), so those filters are left out
  // here too, and only the others (a family linked from another table) can
  // exclude it. A pick they exclude would AND two entities into nothing.
  useEffect(() => {
    if (!picked || !dcId || !column || !wfId || !vizKind) {
      setInScope(null);
      return;
    }
    // A scope read for an earlier pick says nothing about this one.
    setInScope(null);
    let cancelled = false;
    const filters = withoutFiltersOn(JSON.parse(filtersKey) as InteractiveFilter[], [column]);
    fetchAdvancedVizData({ wfId, dcId, columns: [column], filters, vizKind })
      .then((res) => {
        if (cancelled) return;
        // A sampled read may miss entities: then nothing is known to be out.
        const whole = !res.sampled && res.sampling?.exact !== false;
        setInScope(whole ? new Set(entitiesByRowCount(res.rows?.[column] ?? [])) : null);
      })
      .catch(() => {
        if (!cancelled) setInScope(null);
      });
    return () => {
      cancelled = true;
    };
  }, [picked, dcId, column, refreshTick, wfId, vizKind, filtersKey]);

  // The listed entities plus the opening one, which the table holds even when
  // a cut list leaves it out.
  const held = useMemo(() => heldEntities(entities, opening), [entities, opening]);

  useEffect(() => {
    if (followed && held?.includes(followed)) setPicked(followed);
  }, [followed, held]);

  // The dashboard's agreed opening when this table holds it, else its own.
  const agreed = useSharedOpeningEntity(column ? rows?.shareKey : null, rows?.owner ?? '', opening, held);

  const entity = column ? chooseEntity(held, picked, agreed, inScope) : null;
  return { entities: held, entity, setEntity: setPicked, failed };
}
