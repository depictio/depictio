/**
 * The height of the main ribbon lane. Pure, unit-tested in `ribbonHeight.test.ts`;
 * `panelLanes.ts` spreads the spare room of the panel with these numbers.
 *
 * A tile whose author or user has not chosen a height (`requested` null) keeps
 * the original behaviour: a lane of `DEFAULT_RIBBON_PX` that grows into spare
 * room up to `mainRibbonMax`. A chosen height is authoritative: the lane is
 * drawn at exactly that many pixels on a tile of any size, or the slider would
 * only ever move on a tile too short to grow, which reads as dead.
 */

/** The main ribbon's height when none is chosen (it may then grow). */
export const DEFAULT_RIBBON_PX = 30;
/** How tall an unchosen main ribbon grows into spare room, next to a probability lane. */
export const MAIN_RIBBON_MAX_PX = 52;
/** The same with no probability lane: the ribbon is the only data lane, and may
 *  grow as far as the "Ribbon height" slider goes. */
export const MAIN_RIBBON_SOLO_MAX_PX = 64;

/** A chosen height, or null for none (also for a value that is not a finite number). */
export function chosenRibbonHeight(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
}

/** The lane's height before it grows: the chosen one, else the default. */
export function baseRibbonHeight(requested: number | null | undefined): number {
  return chosenRibbonHeight(requested) ?? DEFAULT_RIBBON_PX;
}

/** Tallest an unchosen main ribbon gets. */
export function mainRibbonMax(hasProbabilities: boolean): number {
  return hasProbabilities ? MAIN_RIBBON_MAX_PX : MAIN_RIBBON_SOLO_MAX_PX;
}
