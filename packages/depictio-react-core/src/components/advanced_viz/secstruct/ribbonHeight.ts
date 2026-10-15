/**
 * The height of the main ribbon lane. Pure, unit-tested in `ribbonHeight.test.ts`.
 *
 * A tile whose author or user has not chosen a height (`requested` null) keeps
 * the original behaviour: a lane of `DEFAULT_RIBBON_PX` that grows into spare
 * room up to `MAIN_RIBBON_MAX_PX`. A chosen height is authoritative: the lane
 * is drawn at exactly that many pixels on a tile of any size, or the slider
 * would only ever move on a tile too short to grow, which reads as dead.
 */

/** The main ribbon's height when none is chosen (it may then grow). */
export const DEFAULT_RIBBON_PX = 30;
/** How tall an unchosen main ribbon grows into spare room. */
export const MAIN_RIBBON_MAX_PX = 52;

/** A chosen height, or null for none (also for a value that is not a finite number). */
export function chosenRibbonHeight(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
}

/** The lane's height before it grows: the chosen one, else the default. */
export function baseRibbonHeight(requested: number | null | undefined): number {
  return chosenRibbonHeight(requested) ?? DEFAULT_RIBBON_PX;
}

/**
 * The main ribbon lane's final height.
 *
 * @param requested the chosen height, null for none
 * @param spare px left over once every lane has its base height
 * @param growShare the share of `spare` the ribbon may take (the rest goes to
 *   the probability lanes when there are some)
 */
export function mainRibbonLaneHeight(
  requested: number | null | undefined,
  spare: number,
  growShare: number,
): number {
  const chosen = chosenRibbonHeight(requested);
  if (chosen != null) return chosen;
  const grow = Math.max(0, Math.min(MAIN_RIBBON_MAX_PX - DEFAULT_RIBBON_PX, spare * growShare));
  return DEFAULT_RIBBON_PX + grow;
}
