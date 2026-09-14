/**
 * Whether the analysis groups reached each tile on screen, pooled for the
 * Analysis panel.
 *
 * Each tile already knows its own answer (a figure from the server's
 * `group_colored`, an advanced viz from whether its split narrowed anything or
 * its recolour matched any point) and shows it as a badge. The panel needs the
 * sum: when every tile on the tab said no, the groups are doing nothing here,
 * and a reader looking at the panel rather than at each tile should be told so.
 *
 * A module-level store rather than a context: the panel and the grid are
 * mounted in different corners of each app, and a provider would have to be
 * threaded through both. Tiles report by component index and withdraw on
 * unmount, so the store only ever describes what is mounted.
 */

import { createContext, useContext, useEffect, useSyncExternalStore } from 'react';

import type { GroupRenderState } from './selectionGroups';

export interface GroupReachSnapshot {
  /** Tiles that were asked to draw the groups and know whether they did. */
  reported: number;
  /** Of those, the ones that drew them. */
  applied: number;
}

const outcomes = new Map<string, boolean>();
const listeners = new Set<() => void>();
let snapshot: GroupReachSnapshot = { reported: 0, applied: 0 };

function publish(): void {
  let applied = 0;
  for (const ok of outcomes.values()) if (ok) applied += 1;
  // A fresh object only when something changed: `useSyncExternalStore`
  // compares snapshots by identity.
  snapshot = { reported: outcomes.size, applied };
  listeners.forEach((listener) => listener());
}

/** Record whether the groups reached `componentId`. `null` withdraws the
 *  tile: it was not asked, or cannot tell. */
export function reportGroupReach(componentId: string, applied: boolean | null): void {
  if (!componentId) return;
  if (applied === null) {
    if (!outcomes.delete(componentId)) return;
  } else {
    if (outcomes.get(componentId) === applied) return;
    outcomes.set(componentId, applied);
  }
  publish();
}

export function subscribeGroupReach(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getGroupReach(): GroupReachSnapshot {
  return snapshot;
}

/** True when at least one tile answered and none of them drew the groups. */
export function noTileReceivesGroups(reach: GroupReachSnapshot): boolean {
  return reach.reported > 0 && reach.applied === 0;
}

/** The pooled answer, re-rendering whenever a tile's changes. */
export function useGroupReach(): GroupReachSnapshot {
  return useSyncExternalStore(subscribeGroupReach, getGroupReach, getGroupReach);
}

/** Report this tile's answer for as long as it holds, withdrawing it when the
 *  answer becomes `null` or the tile unmounts. */
export function useReportGroupReach(componentId: string | undefined, applied: boolean | null): void {
  useEffect(() => {
    if (!componentId || applied === null) return;
    reportGroupReach(componentId, applied);
    return () => reportGroupReach(componentId, null);
  }, [componentId, applied]);
}

/**
 * Where an advanced viz renderer drawn whole says whether its recolour matched.
 *
 * Only the renderer can tell: it recolours its finished figure with
 * `splitFigureByGroups`, which hands the figure back untouched when no point
 * belongs to a group, and an untouched tile looks exactly like one that
 * ignores grouping. A context rather than the store above, because the answer
 * is for the dispatch that mounted the renderer, which owns the tile's badge
 * and derives the tile's reach from it.
 */
export const GroupColouringReportContext = createContext<
  ((matched: boolean | null) => void) | null
>(null);

/** Whether the dashboard colours by groups and has some to colour by. */
export function groupColouringActive(groupRender: GroupRenderState | undefined): boolean {
  return Boolean(groupRender?.colorByGroup) && (groupRender?.groups.length ?? 0) > 0;
}

/** Whether recolouring `figure` by the groups drew any of them. `null` when
 *  there is nothing to judge: no active groups, or no figure yet. Otherwise an
 *  identity check, since `splitFigureByGroups` returns its input exactly when
 *  no point matched. */
export function groupColouringOutcome(
  groupRender: GroupRenderState | undefined,
  figure: unknown,
  groupedFigure: unknown,
): boolean | null {
  if (!groupColouringActive(groupRender) || !figure) return null;
  return groupedFigure !== figure;
}

/** Report this renderer's `groupColouringOutcome` to the dispatch, from an
 *  effect, withdrawing it when there is nothing to judge or the renderer
 *  unmounts. A no-op without a provider (the catalog, previews), and silent
 *  in a panel of a split, which is handed no groups. */
export function useReportGroupColouring(
  groupRender: GroupRenderState | undefined,
  figure: unknown,
  groupedFigure: unknown,
): void {
  const report = useContext(GroupColouringReportContext);
  const matched = groupColouringOutcome(groupRender, figure, groupedFigure);
  useEffect(() => {
    if (!report || matched === null) return;
    report(matched);
    return () => report(null);
  }, [report, matched]);
}
