/**
 * The analysis groups, pointed at the collection an advanced viz draws.
 *
 * A group is captured on one collection (guide sequences, from a guide table)
 * and an advanced viz recolours its points by matching the group's values
 * against its own point keys (`splitFigureByGroups`). On a tab whose points are
 * libraries, a guide group matches nothing and the tile reads "not grouped",
 * although the project links guides to libraries. The server already
 * translates a group through those links for figures, cards and tables
 * (`POST /resolve_groups` is that translation on request); this swaps the
 * translated groups in before the renderer sees them.
 */

import { useEffect, useMemo, useState } from 'react';

import { fetchResolvedGroups, type ResolvedGroupsResult } from '../../api';
import type { GroupRenderDef, GroupRenderState } from '../../selectionGroups';

/** Groups captured on a collection other than `dcId`. A group with no source
 *  collection is read against whatever it is handed, as before. */
export function foreignGroups(groups: GroupRenderDef[], dcId: string | undefined): GroupRenderDef[] {
  if (!dcId) return [];
  return groups.filter((g) => Boolean(g.dc_id) && g.dc_id !== dcId);
}

/**
 * `groupRender` with each foreign group replaced by its translation, in the
 * same order and with the same name and colour. A foreign group the server
 * could not translate is dropped: it names nothing on this collection, and
 * keeping it would colour by values that mean something else here.
 */
export function withResolvedGroups(
  groupRender: GroupRenderState,
  dcId: string | undefined,
  resolved: ResolvedGroupsResult | null,
): GroupRenderState {
  const foreign = new Set(foreignGroups(groupRender.groups, dcId).map((g) => g.name));
  if (foreign.size === 0) return groupRender;
  const byName = new Map((resolved?.groups ?? []).map((g) => [g.name, g]));
  const groups = groupRender.groups.flatMap((g): GroupRenderDef[] => {
    if (!foreign.has(g.name)) return [g];
    const hit = byName.get(g.name);
    return hit && hit.values.length > 0 ? [{ ...g, ...hit }] : [];
  });
  return { ...groupRender, groups };
}

/** Translations in flight, by what was asked, so tiles mounting together on
 *  one collection share a request. Forgotten once settled: a re-ingest, a new
 *  link or another data version changes the answer, and a kept one would
 *  outlive all of them. */
const asked = new Map<string, Promise<ResolvedGroupsResult>>();

/**
 * The groups an advanced viz on `dcId` should draw. Returns `groupRender`
 * itself when every group is native to the collection (nothing to ask) and,
 * while a translation is pending or when it fails, the groups that need none.
 */
export function useGroupsForDc(
  groupRender: GroupRenderState | undefined,
  dashboardId: string | undefined,
  dcId: string | undefined,
): GroupRenderState | undefined {
  const active = Boolean(groupRender?.colorByGroup);
  const foreign = useMemo(
    () => (active && groupRender ? foreignGroups(groupRender.groups, dcId) : []),
    [active, groupRender, dcId],
  );
  const key = useMemo(
    () => (foreign.length && dashboardId && dcId ? JSON.stringify([dashboardId, dcId, foreign]) : null),
    [foreign, dashboardId, dcId],
  );
  const [done, setDone] = useState<{ key: string; result: ResolvedGroupsResult | null } | null>(null);
  useEffect(() => {
    if (!key || !dashboardId || !dcId) return;
    let cancelled = false;
    let request = asked.get(key);
    if (!request) {
      request = fetchResolvedGroups(
        dashboardId,
        dcId,
        foreign.map(({ name, column_name, values, color, dc_id }) => ({
          name,
          column_name,
          values,
          color,
          dc_id,
        })),
      );
      asked.set(key, request);
      const forget = () => asked.delete(key);
      request.then(forget, forget);
    }
    request.then(
      (result) => !cancelled && setDone({ key, result }),
      () => !cancelled && setDone({ key, result: null }),
    );
    return () => {
      cancelled = true;
    };
  }, [key, dashboardId, dcId, foreign]);

  return useMemo(() => {
    if (!groupRender || !key) return groupRender;
    return withResolvedGroups(groupRender, dcId, done?.key === key ? done.result : null);
  }, [groupRender, key, dcId, done]);
}
