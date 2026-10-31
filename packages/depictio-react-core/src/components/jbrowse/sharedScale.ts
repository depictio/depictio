/**
 * One y scale for every quantitative track of a browser tile (`y_scale:
 * shared`), so two libraries read at the same height instead of each track
 * filling its own lane.
 *
 * JBrowse keeps a track's raw score range in `display.stats`, whatever bounds
 * are set, and draws with `domain`, which those bounds (`setMinScore` /
 * `setMaxScore`, its "Set min/max score" dialog) override. So the shared scale
 * is the union of the tracks' stats in view, written back as everyone's
 * bounds; a pan refreshes the stats, and the union with them.
 *
 * Signal tracks (bigWig) and the coverage panels of alignment tracks (read
 * depth) are different measures: each family shares a scale of its own.
 * Everything here is pure; `useSharedScale.ts` owns the reaction.
 */
import type { Model } from './displaySettings';

export type YScaleMode = 'per_track' | 'shared';

export type ScaleFamily = 'signal' | 'depth';

/** The family a display type shares its scale with, null for a non-quantitative one. */
export function scaleFamily(type: unknown): ScaleFamily | null {
  if (type === 'LinearWiggleDisplay' || type === 'MultiLinearWiggleDisplay') return 'signal';
  if (type === 'LinearSNPCoverageDisplay') return 'depth';
  return null;
}

const get = (model: Model, name: string): unknown => {
  try {
    return model[name];
  } catch {
    return undefined;
  }
};

const finite = (v: unknown): number | undefined =>
  typeof v === 'number' && Number.isFinite(v) ? v : undefined;

/**
 * The score range a display draws from, as JBrowse picks it: the mean stats
 * under a mean summary, else the min / max. Undefined before its stats load.
 */
export function displayRange(display: Model): [number, number] | undefined {
  const stats = get(display, 'stats') as Record<string, unknown> | undefined;
  if (!stats || typeof stats !== 'object') return undefined;
  const config = get(display, 'rendererConfig') as { summaryScoreMode?: unknown } | undefined;
  const mean = config?.summaryScoreMode === 'mean' || config?.summaryScoreMode === 'avg';
  const lo = finite(mean ? (stats.scoreMeanMin ?? stats.scoreMin) : stats.scoreMin);
  const hi = finite(mean ? (stats.scoreMeanMax ?? stats.scoreMax) : stats.scoreMax);
  return lo === undefined || hi === undefined ? undefined : [lo, hi];
}

/** The union of ranges, null when none is known yet. */
export function unionRange(ranges: Iterable<[number, number] | undefined>): [number, number] | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const r of ranges) {
    if (!r) continue;
    lo = Math.min(lo, r[0]);
    hi = Math.max(hi, r[1]);
  }
  return Number.isFinite(lo) && Number.isFinite(hi) ? [lo, hi] : null;
}

/**
 * The shared bounds per family. A family with a single track has nothing to
 * share and is left out, so that track keeps its own scale.
 */
export function sharedBounds(displays: readonly Model[]): Map<ScaleFamily, [number, number]> {
  const byFamily = new Map<ScaleFamily, Model[]>();
  for (const d of displays) {
    const family = scaleFamily(get(d, 'type'));
    if (!family) continue;
    byFamily.set(family, [...(byFamily.get(family) ?? []), d]);
  }
  const out = new Map<ScaleFamily, [number, number]>();
  for (const [family, members] of byFamily) {
    if (members.length < 2) continue;
    const range = unionRange(members.map(displayRange));
    if (range) out.set(family, range);
  }
  return out;
}

function call(model: Model, name: string, value: unknown): void {
  const fn = model[name];
  if (typeof fn !== 'function') return;
  try {
    (fn as (v: unknown) => void).call(model, value);
  } catch {
    // A display torn down mid-flight.
  }
}

/** Write a range as a display's bounds; undefined lifts them. */
export function setBounds(display: Model, range: [number, number] | undefined): void {
  call(display, 'setMinScore', range?.[0]);
  call(display, 'setMaxScore', range?.[1]);
}
