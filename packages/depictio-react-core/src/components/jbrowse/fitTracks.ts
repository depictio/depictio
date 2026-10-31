/** One open track, as `fitTrackHeights` sees it. */
export interface FitTrack {
  height: number;
  /** A signal track, which stretches; the others keep their own height. */
  fittable: boolean;
}

/** Below this a signal track stops reading as a signal. */
export const MIN_FIT_TRACK_PX = 40;

/** Signal displays share the free height; annotation and reads keep theirs. */
export const isFittableDisplay = (type: unknown): boolean =>
  typeof type === 'string' && type.includes('Wiggle');

/**
 * The height each fittable track takes so the view fills `hostPx`. Everything
 * in the view that is not a track (header, ruler, resize handles) is
 * `contentPx` minus the tracks, and stays as it is. Null when nothing can
 * stretch; never below `minPx`, so a crowded tile still scrolls.
 */
export function fitTrackHeights(
  tracks: FitTrack[],
  contentPx: number,
  hostPx: number,
  minPx = MIN_FIT_TRACK_PX,
): number | null {
  const fittable = tracks.filter((t) => t.fittable).length;
  if (!fittable || hostPx <= 0) return null;
  const tracksPx = tracks.reduce((sum, t) => sum + t.height, 0);
  const fixedPx = tracks.reduce((sum, t) => sum + (t.fittable ? 0 : t.height), 0);
  const overheadPx = contentPx - tracksPx;
  return Math.max(minPx, Math.floor((hostPx - overheadPx - fixedPx) / fittable));
}

/** Whether any open track can stretch; the "Fit tracks" option is offered only then. */
export const anyFittable = (displayTypes: readonly unknown[]): boolean =>
  displayTypes.some(isFittableDisplay);

/** Why the option is off when `anyFittable` is false. */
export const FIT_TRACKS_HINT = 'Only coverage/signal tracks can stretch';
