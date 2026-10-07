import type { ControlsPlacement } from './controlsPlacement';

/**
 * Which node the frame publishes as each tier, given where the tile's controls
 * are drawn.
 *
 * Pure so the node-environment vitest can cover it. The rule it adds: `header`
 * only ever drew the encoding tier, so a renderer that passes no
 * `primaryControls` got an empty strip and a pin that did nothing visible.
 * There, the cosmetic tier is promoted into the strip, and since the dispatch
 * leaves only the cosmetic tier in the popover under `header`, promoting it
 * also empties the popover: the controls live in exactly one place.
 *
 * `popover` and `rail` keep both tiers as given (the popover lists both, the
 * rail draws both), so the promotion would change nothing there.
 */
export interface FrameTiers<T> {
  /** Drawn in the header strip, first in the rail, first in the popover. */
  primary?: T;
  /** Left in the popover under `header`, second in the rail. */
  cosmetic?: T;
}

export function frameTiers<T>(
  placement: ControlsPlacement,
  primary: T | null | undefined,
  cosmetic: T | null | undefined,
): FrameTiers<T> {
  const tiers: FrameTiers<T> = {};
  if (placement === 'header' && !primary) {
    if (cosmetic) tiers.primary = cosmetic;
    return tiers;
  }
  if (primary) tiers.primary = primary;
  if (cosmetic) tiers.cosmetic = cosmetic;
  return tiers;
}
