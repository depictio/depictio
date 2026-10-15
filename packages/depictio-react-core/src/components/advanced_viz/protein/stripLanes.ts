/**
 * Where the lanes of a sequence strip sit in the height it is given. Pure, so
 * the layout is unit-tested (`stripLanes.test.ts`) and the sequence-track
 * renderer can ask the same question for its tile's natural height.
 *
 * Every lane has a base height (what the strip needs to be readable), a cap
 * (past which more height adds nothing: a 300 px tall residue letter or a
 * helix glyph is not a better one) and a weight (its share of the spare
 * height). Spare height goes to the lanes by weight, up to their caps; what
 * the caps cannot take widens the gaps between lanes a little, and the rest
 * centres the stack in the cell, so a tall cell reads as a compact figure with
 * air around it rather than as a strip with a blank half below it.
 *
 * All sizes are whole CSS pixels, so the canvas rules between lanes stay crisp.
 */
import type { StripResidue, StripDomain, StripVariant } from './types';
import { stackVariants, valueExtent } from './sequence';

export type LaneKey = 'ruler' | 'letters' | 'category' | 'value' | 'domains' | 'variants';

/** Which optional lanes the strip draws; the ruler is always there. */
export interface LanePresence {
  letters: boolean;
  category: boolean;
  value: boolean;
  domains: boolean;
  variants: boolean;
}

interface LaneSpec {
  /** Height with no spare room, px. */
  base: number;
  /** Tallest the lane gets, px. */
  max: number;
  /** Share of the spare height; 0 pins the lane at `base`. */
  weight: number;
}

/**
 * The lanes, top to bottom. The value and variants lanes carry the most
 * information per pixel (bars, lollipop stems), so they take most of the
 * spare room and have the highest caps; the letter, category and domain lanes
 * grow only a little, and the ruler never does.
 */
export const LANE_SPECS: Readonly<Record<LaneKey, LaneSpec>> = {
  ruler: { base: 18, max: 18, weight: 0 },
  letters: { base: 14, max: 18, weight: 1 },
  category: { base: 12, max: 24, weight: 1 },
  value: { base: 22, max: 96, weight: 3 },
  domains: { base: 18, max: 26, weight: 1 },
  variants: { base: 30, max: 120, weight: 3 },
};

const LANE_ORDER: readonly LaneKey[] = [
  'ruler',
  'letters',
  'category',
  'value',
  'domains',
  'variants',
];

/** Gap between lanes with no spare room, px. */
export const LANE_GAP = 3;
/** Widest the gaps open to when the lanes are at their caps, px. */
export const LANE_GAP_MAX = 8;

export interface PlacedLane {
  key: LaneKey;
  /** Top edge, px from the top of the canvas (the centring offset included). */
  y: number;
  h: number;
}

export interface LaneLayout {
  lanes: PlacedLane[];
  /** Gap after each lane, px. */
  gap: number;
  /** Top edge of the first lane: the room left above a centred stack. */
  top: number;
  /** Height of the drawn stack, from `top` down through the last gap. What
   *  the selection and hover bands span. */
  stackH: number;
  /** Height with every lane at its base: what a strip needs, and its height
   *  when it is given none. */
  naturalH: number;
}

/** The lanes present, in drawing order. */
export function presentLanes(present: LanePresence): LaneKey[] {
  return LANE_ORDER.filter((key) => key === 'ruler' || present[key]);
}

/** Height of the strip with every present lane at its base height. */
export function naturalStripHeight(present: LanePresence): number {
  return presentLanes(present).reduce((sum, key) => sum + LANE_SPECS[key].base + LANE_GAP, 0);
}

/**
 * Spread `spare` px over lanes by weight, none past its cap. A lane that hits
 * its cap hands its unused share to the rest, so the result is the same as
 * filling them in the order they saturate.
 */
function distribute(keys: readonly LaneKey[], spare: number): number[] {
  const grow = keys.map(() => 0);
  let active = keys.map((_, i) => i).filter((i) => {
    const s = LANE_SPECS[keys[i]];
    return s.weight > 0 && s.max > s.base;
  });
  let left = spare;
  while (active.length > 0 && left > 0) {
    const total = active.reduce((sum, i) => sum + LANE_SPECS[keys[i]].weight, 0);
    const share = (i: number) => (left * LANE_SPECS[keys[i]].weight) / total;
    const room = (i: number) => LANE_SPECS[keys[i]].max - LANE_SPECS[keys[i]].base;
    const full = active.filter((i) => share(i) >= room(i));
    if (full.length === 0) {
      for (const i of active) grow[i] = share(i);
      break;
    }
    // Settle the saturated lanes at their caps, then share what is left again.
    let spent = 0;
    for (const i of full) {
      grow[i] = room(i);
      spent += room(i);
    }
    left -= spent;
    active = active.filter((i) => !full.includes(i));
  }
  return grow;
}

/** Place the present lanes in a strip `viewH` px tall. */
export function layoutLanes(present: LanePresence, viewH: number): LaneLayout {
  const keys = presentLanes(present);
  const naturalH = naturalStripHeight(present);
  const height = Number.isFinite(viewH) ? Math.floor(viewH) : 0;
  const spare = Math.max(0, height - naturalH);

  const grow = distribute(keys, spare);
  const heights = keys.map((key, i) => LANE_SPECS[key].base + Math.floor(grow[i]));
  // What the caps and the rounding left over.
  let rest = Math.max(0, height - heights.reduce((s, h) => s + h, 0) - keys.length * LANE_GAP);
  const extraGap = Math.min(LANE_GAP_MAX - LANE_GAP, Math.floor(rest / keys.length));
  const gap = LANE_GAP + extraGap;
  rest -= extraGap * keys.length;
  const top = Math.floor(rest / 2);

  let y = top;
  const lanes = keys.map((key, i) => {
    const lane = { key, y, h: heights[i] };
    y += heights[i] + gap;
    return lane;
  });
  const stackH = y - top;
  return { lanes, gap, top, stackH, naturalH };
}

/**
 * Which lanes a strip draws for these inputs: the same tests the strip makes,
 * for a caller that has no strip to ask (the tile publishing its height).
 */
export function lanePresenceOf(
  residues: readonly StripResidue[],
  domains: readonly StripDomain[] = [],
  variants: readonly StripVariant[] = [],
  showLetters = true,
): LanePresence {
  return {
    letters: showLetters && residues.some((r) => Boolean(r.letter)),
    category: residues.some((r) => r.category != null && r.category !== ''),
    value: valueExtent(residues) !== null,
    domains: domains.length > 0,
    variants: stackVariants(variants).length > 0,
  };
}
