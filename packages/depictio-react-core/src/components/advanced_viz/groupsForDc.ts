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
 *
 * The Overlay of "What's new" hands every tile two groups of runs (on
 * `depictio_run_id`). A point is a sample or a feature, never a run, so those
 * groups are translated too, per component: to the ids whose rows came from
 * the runs. A component whose ids each hold rows of several runs gets none
 * back, and says so (`runsAmbiguous`).
 */

import { useEffect, useMemo, useState } from 'react';

import { fetchResolvedGroups, type ResolvedGroupsResult } from '../../api';
import type { GroupRenderDef, GroupRenderState } from '../../selectionGroups';

/** Written by the CLI on every Delta row: the run the row came from. The
 *  viewer's `RUN_COLUMN` (newsSplit.ts) names the same column; it stays
 *  apart because that file must run without this package. */
export const RUN_GROUP_COLUMN = 'depictio_run_id';

/** A group of runs, as the Overlay of "What's new" builds them. */
export function isRunGroup(g: GroupRenderDef): boolean {
  return g.column_name === RUN_GROUP_COLUMN && !g.dc_id;
}

/** Groups captured on a collection other than `dcId`. A group with no source
 *  collection is read against whatever it is handed, as before. */
export function foreignGroups(groups: GroupRenderDef[], dcId: string | undefined): GroupRenderDef[] {
  if (!dcId) return [];
  return groups.filter((g) => Boolean(g.dc_id) && g.dc_id !== dcId);
}

/** The groups the server must rewrite for this component: those of another
 *  collection and, with a component to aim at, the groups of runs. */
export function groupsToTranslate(
  groups: GroupRenderDef[],
  dcId: string | undefined,
  componentId: string | undefined,
): GroupRenderDef[] {
  const foreign = foreignGroups(groups, dcId);
  if (!dcId || !componentId) return foreign;
  return groups.filter((g) => foreign.includes(g) || isRunGroup(g));
}

/**
 * `groupRender` with each translated group replaced by its translation, in the
 * same order and with the same name and colour. A group the server could not
 * translate is dropped: it names nothing on this collection, and keeping it
 * would colour by values that mean something else here.
 */
export function withResolvedGroups(
  groupRender: GroupRenderState,
  dcId: string | undefined,
  resolved: ResolvedGroupsResult | null,
  componentId?: string,
): GroupRenderState {
  const translated = new Set(
    groupsToTranslate(groupRender.groups, dcId, componentId).map((g) => g.name),
  );
  if (translated.size === 0) return groupRender;
  const byName = new Map((resolved?.groups ?? []).map((g) => [g.name, g]));
  const groups = groupRender.groups.flatMap((g): GroupRenderDef[] => {
    if (!translated.has(g.name)) return [g];
    const hit = byName.get(g.name);
    return hit && hit.values.length > 0 ? [{ ...g, ...hit }] : [];
  });
  return { ...groupRender, groups };
}

/** Whether the server refused the groups of runs: some mark holds rows of runs
 *  on both sides, so it can be coloured as neither. */
export function runsAmbiguous(resolved: ResolvedGroupsResult | null): boolean {
  return (resolved?.status ?? []).some((s) => s.status === 'runs_ambiguous');
}

/** Translations in flight, by what was asked, so tiles mounting together on
 *  one collection share a request. Forgotten once settled: a re-ingest, a new
 *  link or another data version changes the answer, and a kept one would
 *  outlive all of them. */
const asked = new Map<string, Promise<ResolvedGroupsResult>>();

export interface GroupsForDc {
  groupRender: GroupRenderState | undefined;
  /** The groups of runs reach no mark of this component unambiguously. */
  runsAmbiguous: boolean;
}

/**
 * The groups an advanced viz on `dcId` should draw. Returns `groupRender`
 * itself when every group is native to the collection (nothing to ask) and,
 * while a translation is pending or when it fails, the groups that need none.
 * `componentId` lets the groups of runs be translated to the component's ids.
 */
export function useGroupsForDc(
  groupRender: GroupRenderState | undefined,
  dashboardId: string | undefined,
  dcId: string | undefined,
  componentId?: string,
): GroupsForDc {
  const active = Boolean(groupRender?.colorByGroup);
  const pending = useMemo(
    () => (active && groupRender ? groupsToTranslate(groupRender.groups, dcId, componentId) : []),
    [active, groupRender, dcId, componentId],
  );
  const runs = pending.some(isRunGroup) ? componentId : undefined;
  const key = useMemo(
    () =>
      pending.length && dashboardId && dcId ? JSON.stringify([dashboardId, dcId, runs ?? null, pending]) : null,
    [pending, dashboardId, dcId, runs],
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
        pending.map(({ name, column_name, values, color, dc_id }) => ({
          name,
          column_name,
          values,
          color,
          dc_id,
        })),
        undefined,
        runs,
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
  }, [key, dashboardId, dcId, pending, runs]);

  return useMemo(() => {
    if (!groupRender || !key) return { groupRender, runsAmbiguous: false };
    const result = done?.key === key ? done.result : null;
    return {
      groupRender: withResolvedGroups(groupRender, dcId, result, componentId),
      runsAmbiguous: runsAmbiguous(result),
    };
  }, [groupRender, key, dcId, done, componentId]);
}
