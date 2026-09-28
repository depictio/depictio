/**
 * "Force load" for the embedded linear genome view.
 *
 * JBrowse 4.3 refuses to draw a region that holds too much data (bytes over
 * the adapter's `fetchSizeLimit`, or features too dense on screen) and shows
 * a "Force load" button instead. That button (BaseLinearDisplay's
 * TooLargeMessage) calls `setFeatureDensityStatsLimit(stats)` then `reload()`
 * on the display. FeatureDensityMixin turns a limit carrying `bytes` into
 * `userByteSizeLimit` and anything else into `userBpPerPxLimit = view.bpPerPx`,
 * so calling it twice lifts both: the byte cap for good, the density cap up to
 * the current zoom — hence a re-lift when the user zooms out.
 *
 * Everything here is duck-typed against the display models and guarded so a
 * detached / destroyed node never throws into React.
 */

/** Byte limit used when force loading: effectively unbounded. */
export const FORCE_LOAD_BYTES = 1e12;

export interface DensityLimitedDisplay {
  setFeatureDensityStatsLimit?: (stats?: { bytes?: number }) => void;
  reload?: () => unknown;
  regionTooLarge?: boolean;
  userBpPerPxLimit?: number;
  userByteSizeLimit?: number;
  /** Sub-displays of an alignments display, each with its own limits. */
  PileupDisplay?: unknown;
  SNPCoverageDisplay?: unknown;
}

export type AliveCheck = (node: unknown) => boolean;

const alwaysAlive: AliveCheck = () => true;

function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

/** The display and its alignments sub-displays that carry density limits. */
export function densityTargets(
  display: unknown,
  alive: AliveCheck = alwaysAlive,
): DensityLimitedDisplay[] {
  if (!display || typeof display !== 'object') return [];
  const d = display as DensityLimitedDisplay;
  const candidates = [
    d,
    safe(() => d.PileupDisplay, undefined),
    safe(() => d.SNPCoverageDisplay, undefined),
  ];
  const out: DensityLimitedDisplay[] = [];
  for (const c of candidates) {
    if (!c || typeof c !== 'object' || out.includes(c as DensityLimitedDisplay)) continue;
    if (!safe(() => alive(c), false)) continue;
    const t = c as DensityLimitedDisplay;
    if (typeof t.setFeatureDensityStatsLimit === 'function') out.push(t);
  }
  return out;
}

/** True once a display's limits are already lifted for ``bpPerPx``. */
export function isLifted(d: DensityLimitedDisplay, bpPerPx: number | undefined): boolean {
  return safe(() => {
    const bytes = d.userByteSizeLimit ?? 0;
    const bpLimit = d.userBpPerPxLimit;
    return (
      bytes >= FORCE_LOAD_BYTES && bpLimit != null && bpPerPx != null && bpLimit >= bpPerPx
    );
  }, false);
}

/** Whether any of the display's targets carries a user-lifted limit (what
 *  switching force load off has to undo). */
export function hasLiftedLimits(display: unknown, alive: AliveCheck = alwaysAlive): boolean {
  return densityTargets(display, alive).some((d) =>
    safe(() => d.userByteSizeLimit != null || d.userBpPerPxLimit != null, false),
  );
}

/**
 * Lift the density limits of ``display`` (and its sub-displays).
 *
 * ``reload: 'always'`` reloads every target (the toggle was just switched on:
 * regions already refused must be fetched again). ``'ifBlocked'`` skips
 * targets already lifted at this zoom and only reloads those currently
 * showing the "too large" message — lifting the limit before the density
 * stats arrive is enough for the others, and it keeps zooming cheap.
 *
 * Returns how many targets were changed.
 */
export function liftDisplayLimits(
  display: unknown,
  opts: { bpPerPx?: number; reload: 'always' | 'ifBlocked'; alive?: AliveCheck },
): number {
  let changed = 0;
  for (const d of densityTargets(display, opts.alive)) {
    if (opts.reload === 'ifBlocked' && isLifted(d, opts.bpPerPx)) continue;
    try {
      const blocked = safe(() => Boolean(d.regionTooLarge), false);
      d.setFeatureDensityStatsLimit!({ bytes: FORCE_LOAD_BYTES });
      d.setFeatureDensityStatsLimit!(undefined);
      changed += 1;
      if (opts.reload === 'always' || blocked) {
        // BaseLinearDisplay.reload is async: swallow its rejection too.
        Promise.resolve(d.reload?.()).catch(() => undefined);
      }
    } catch (err) {
      console.warn('jbrowse: force load failed on a display', err);
    }
  }
  return changed;
}

/**
 * Which open tracks to hide and re-show (in this order) so the ``affected``
 * ones get fresh displays with the configured limits. ``showTrack`` appends
 * at the bottom, so everything from the first affected track down is
 * re-opened: the track order is kept exactly, and the tracks above it are
 * left alone.
 */
export function planForceLoadReset(open: string[], affected: Set<string>): string[] {
  const first = open.findIndex((id) => affected.has(id));
  return first < 0 ? [] : open.slice(first);
}
