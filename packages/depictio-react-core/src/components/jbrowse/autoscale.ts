/**
 * "Rescale Y to visible region": put every score display of a linear view back
 * on a local autoscale, so its y axis follows what is on screen.
 *
 * What a display draws with is `domain`: the raw score range in `stats`
 * (re-fetched for the visible blocks while the autoscale is `local`), clamped
 * by `constraints.min` / `constraints.max`. A track stays stuck on an old range
 * when its autoscale is `global`, or when a fixed bound is set (the "Set
 * min/max score" dialog, a shared y scale). So a rescale is `setAutoscale
 * ('local')` plus lifting the fixed bounds; the stats autorun re-fetches on the
 * autoscale change, and the display redraws.
 *
 * The actions were read from the 4.3.0 sources of plugin-wiggle
 * (`shared/SharedWiggleMixin.js`: `setAutoscale`, `setMinScore`, `setMaxScore`)
 * and plugin-alignments (`LinearSNPCoverageDisplay` composes the wiggle model).
 * Everything here is pure; `JBrowseRenderer.tsx` owns the button, which runs this
 * together with `fitToContent.ts` (one click: heights and y axes).
 */
import type { Model } from './displaySettings';
import { scaleFamily, setBounds, sharedBounds } from './sharedScale';

/** Panels of an alignments wrapper that can hold a score display. */
const WRAPPER_PANELS = ['SNPCoverageDisplay', 'PileupDisplay'];

const get = (model: unknown, name: string): unknown => {
  if (!model || typeof model !== 'object') return undefined;
  try {
    return (model as Model)[name];
  } catch {
    return undefined;
  }
};

/** A display type with a y score scale: the wiggle family and SNP coverage. */
export const isScoreDisplayType = (type: unknown): boolean =>
  typeof type === 'string' && (type.includes('Wiggle') || type === 'LinearSNPCoverageDisplay');

/**
 * The score displays of a track list (`view.tracks`): each track's displays,
 * and the coverage panel nested in an alignments display.
 */
export function collectScoreDisplays(tracks: unknown): Model[] {
  if (!Array.isArray(tracks)) return [];
  const out: Model[] = [];
  const take = (display: unknown) => {
    if (display && typeof display === 'object' && isScoreDisplayType(get(display, 'type'))) {
      out.push(display as Model);
    }
  };
  for (const track of tracks) {
    const displays = get(track, 'displays');
    if (!Array.isArray(displays)) continue;
    for (const display of displays) {
      take(display);
      for (const panel of WRAPPER_PANELS) take(get(display, panel));
    }
  }
  return out;
}

/** Calls `model[name](value)`; false when it is missing or throws. */
function call(model: Model, name: string, value: unknown): boolean {
  const fn = model[name];
  if (typeof fn !== 'function') return false;
  try {
    (fn as (v: unknown) => void).call(model, value);
    return true;
  } catch {
    // A display torn down mid-flight.
    return false;
  }
}

/**
 * Rescale `displays` to the visible region and return how many took it.
 *
 * Per track (`shared` false): autoscale `local`, fixed bounds lifted. Under a
 * shared y scale the bounds are the point (the tracks of a family read at one
 * height), so they are recomputed over the visible region instead of lifted:
 * the union of the family's current stats, as `useSharedScale` writes them.
 * That reaction keeps them in step on the next pan; the autoscale change makes
 * it re-fetch the stats it needs.
 */
export function rescaleDisplays(displays: readonly Model[], shared: boolean): number {
  const bounds: ReturnType<typeof sharedBounds> = shared ? sharedBounds(displays) : new Map();
  let done = 0;
  for (const display of displays) {
    if (!call(display, 'setAutoscale', 'local')) continue;
    done += 1;
    const family = shared ? scaleFamily(get(display, 'type')) : null;
    const range = family ? bounds.get(family) : undefined;
    // `setBounds(display, undefined)` lifts both fixed bounds.
    setBounds(display, range);
  }
  return done;
}
