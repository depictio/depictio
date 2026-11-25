/**
 * What a map does when the dashboard's Analysis mode asks for groups.
 *
 * A map is not an advanced_viz kind, so it never went through the split
 * dispatch. This is the same decision, made for a map: deal it into one small
 * map per group (Split), or draw it whole and say so (Overlay, or a Split that
 * cannot be honoured). Kept free of React so the decisions can be tested.
 */

import type { GroupRenderState } from '../../selectionGroups';
import type { InteractiveFilter } from '../../api';
import { MAX_PANELS, panelsForGrouping } from '../../splitPanels';
import type { PanelSpec } from '../../splitPanels';
import { computeMapFit } from './fit';
import type { MapFitSpec } from './fit';

/** Why a map drawn whole wears a "not grouped" badge. */
export type MapGroupBadgeReason = 'overlay' | 'too_many' | 'unsplittable' | 'ineffective';

export type MapGroupPlan =
  | { kind: 'split'; panels: PanelSpec[] }
  | { kind: 'whole'; badge: MapGroupBadgeReason | null };

/** The framing every panel of a split shares. */
export interface MapSharedView {
  center: { lat: number; lon: number };
  zoom: number;
}

/**
 * Split, overlay or nothing, from the dashboard's grouping state.
 *
 * Overlay (`display` 'color') is not drawn on a map: the marks are coloured by
 * the component's own column, and recolouring them by group is not done here.
 * The tile is badged instead, so it does not pass for one that took the groups.
 */
export function mapGroupPlan(
  groupRender: GroupRenderState | undefined,
  filters: readonly InteractiveFilter[],
): MapGroupPlan {
  if (!groupRender) return { kind: 'whole', badge: null };
  if (groupRender.display !== 'facet') return { kind: 'whole', badge: 'overlay' };
  const panels = panelsForGrouping(groupRender, filters);
  if (panels.length > MAX_PANELS) return { kind: 'whole', badge: 'too_many' };
  if (panels.length <= 1) return { kind: 'whole', badge: 'unsplittable' };
  return { kind: 'split', panels };
}

/** The hover lines of the "not grouped" badge. Phrased like the ones in
 *  `groupStatus.ts`, which does not know about maps. */
export function mapGroupBadgeReasons(reason: MapGroupBadgeReason): string[] {
  switch (reason) {
    case 'overlay':
      return [
        'Groups are not drawn on maps in the overlay. Switch to Split to see one map per group.',
      ];
    case 'too_many':
      return [
        `There are too many groups to split this map: at most ${MAX_PANELS} maps fit side by side.`,
      ];
    case 'unsplittable':
      return ['The groups could not be dealt into separate maps, so this one is drawn whole.'];
    case 'ineffective':
      return [
        'The groups do not reach this map’s dataset, so every map would show the same points.',
      ];
  }
}

/** The measured drawing area of one panel. */
export interface PanelBox {
  width: number;
  height: number;
}

/**
 * One view for every panel: the unsplit data's fit, against the smallest panel
 * box. Using the smallest keeps every point inside every panel, and using one
 * box for all of them is what makes the zoom identical even when two panels
 * measure a pixel apart.
 *
 * `null` until there is something to fit and a box to fit it in.
 */
export function sharedMapView(
  spec: MapFitSpec | null,
  boxes: ReadonlyArray<PanelBox>,
): MapSharedView | null {
  if (!spec || boxes.length === 0) return null;
  const width = Math.min(...boxes.map((b) => b.width));
  const height = Math.min(...boxes.map((b) => b.height));
  if (!(width >= 1) || !(height >= 1)) return null;
  return computeMapFit(spec, width, height);
}

/** A cheap fingerprint of what a map drew, to tell "the filter narrowed this
 *  panel" from "every panel got the same data". Counts and end points, not a
 *  hash of everything: two different groups differ in at least one of them. */
export function figureSignature(
  figure: { data?: unknown[] } | null | undefined,
): string | null {
  if (!figure) return null;
  const traces = (figure.data as Array<Record<string, unknown>> | undefined) ?? [];
  return traces
    .map((trace) =>
      [
        String(trace?.type ?? ''),
        describeColumn(trace, ['lat', 'locations', 'z']),
        describeColumn(trace, ['lon']),
        describeColumn(trace, ['marker.color', 'marker.size']),
      ].join(','),
    )
    .join('|');
}

/** First of `paths` the trace carries, summarised: its length, both ends and a
 *  sparse sample. Plotly.py 6 ships numeric columns as `{dtype, bdata}`, a
 *  base64 string whose own length and ends stand in for the values. */
function describeColumn(trace: Record<string, unknown>, paths: string[]): string {
  for (const path of paths) {
    let value: unknown = trace;
    for (const part of path.split('.')) {
      value = value && typeof value === 'object' ? (value as Record<string, unknown>)[part] : undefined;
    }
    if (Array.isArray(value)) {
      let acc = 0;
      for (let i = 0; i < value.length; i += 7) acc = (acc * 31 + String(value[i]).length) | 0;
      const ends = value.length > 0 ? `${value[0]}/${value[value.length - 1]}` : '-';
      return `${value.length}:${ends}:${acc}`;
    }
    const bdata = (value as { bdata?: unknown } | null | undefined)?.bdata;
    if (typeof bdata === 'string') {
      return `b${bdata.length}:${bdata.slice(0, 24)}:${bdata.slice(-24)}`;
    }
  }
  return '-';
}

/** Every panel has settled on the same picture: the split narrowed nothing. */
export function allSignaturesEqual(signatures: ReadonlyArray<string | null>): boolean {
  if (signatures.length < 2) return false;
  if (signatures.some((s) => s == null)) return false;
  return signatures.every((s) => s === signatures[0]);
}
