import { DIRECTION_COLORS } from '../../palettes.generated';

/** Direction colours of a differential result: up, down, not significant.
 *  One definition, so a volcano and a dot plot of the same analysis agree. */
export const DE_TIER_COLOURS = {
  UP: DIRECTION_COLORS.up.light,
  DN: DIRECTION_COLORS.down.light,
  NS: 'rgba(160,160,160,0.55)',
} as const;
