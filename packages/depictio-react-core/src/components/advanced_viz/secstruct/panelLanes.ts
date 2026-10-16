/**
 * Where the lanes of the secondary-structure panel sit in the height it is
 * given. Pure, so the layout is unit-tested (`panelLanes.test.ts`) and the
 * renderer can ask the same question for its tile's natural height.
 *
 * It follows the sequence strip's layout (`protein/stripLanes.ts`) over this
 * panel's lanes. Every lane has a base height (what the panel needs to be
 * readable), a cap (past which more height adds nothing: a 200 px tall helix
 * bar is not a better one) and a weight (its share of the spare height). Spare
 * height goes to the lanes by weight, up to their caps; what the caps cannot
 * take widens the gaps between lanes a little, and the rest centres the stack
 * in the cell. The probability lanes carry the most information per pixel, so
 * they take most of the spare room and have the highest cap; the ruler, the
 * letters and the agreement lane stay small.
 *
 * A main ribbon height the author or user chose is drawn exactly, on a cell of
 * any size; only the default height grows.
 *
 * All sizes are whole CSS pixels, so the canvas rules between lanes stay crisp.
 */
import { baseRibbonHeight, chosenRibbonHeight, mainRibbonMax } from './ribbonHeight';

export type PanelLaneKey = 'ruler' | 'letters' | 'ribbon' | 'agreement' | 'probabilities';

/** Which lanes the panel draws. The ruler and the main ribbon are always there. */
export interface PanelLanePresence {
  /** Height of the main ribbon; null or omitted for the default, which grows. */
  ribbonHeight?: number | null;
  letters: boolean;
  /** Ribbons drawn under the main one, one per further prediction source. */
  extraSources: number;
  agreement: boolean;
  probabilities: boolean;
}

interface LaneSpec {
  /** Height with no spare room, px. */
  base: number;
  /** Tallest the lane gets, px. */
  max: number;
  /** Share of the spare height; 0 pins the lane at `base`. */
  weight: number;
}

/** Height of the ruler lane, px. */
export const RULER_PX = 18;
/** Height of the sequence-letters lane before it grows, px. */
export const LETTERS_PX = 14;
/** Height of the ribbon of each source after the main one, before it grows, px. */
export const EXTRA_RIBBON_PX = 16;
/** Height of the agreement lane before it grows, px. */
export const AGREEMENT_PX = 12;
/** Height of the stacked probability lane before it grows, px. */
export const PROB_PX = 44;
/** Tallest the stacked probability lane gets, px: enough to fill a linked-view
 *  pane, which is often 300 to 600 px tall. */
export const PROB_MAX_PX = 480;

/** Gap between lanes with no spare room, px. */
export const LANE_GAP = 3;
/** Widest the gaps open to when the lanes are at their caps, px. */
export const LANE_GAP_MAX = 8;

const RULER: LaneSpec = { base: RULER_PX, max: RULER_PX, weight: 0 };
const LETTERS: LaneSpec = { base: LETTERS_PX, max: 22, weight: 1 };
const EXTRA_RIBBON: LaneSpec = { base: EXTRA_RIBBON_PX, max: 28, weight: 1 };
const AGREEMENT: LaneSpec = { base: AGREEMENT_PX, max: 20, weight: 1 };
const PROBABILITIES: LaneSpec = { base: PROB_PX, max: PROB_MAX_PX, weight: 3 };
/** Share of the spare height of an unchosen main ribbon (it has little room to take). */
const MAIN_RIBBON_WEIGHT = 2;

export interface PlacedPanelLane {
  key: PanelLaneKey;
  /** Index of a ribbon lane's source (0 is the main one); 0 for the other lanes. */
  source: number;
  /** Top edge, px from the top of the canvas (the centring offset included). */
  y: number;
  h: number;
}

export interface PanelLayout {
  lanes: PlacedPanelLane[];
  /** Gap after each lane, px. */
  gap: number;
  /** Top edge of the first lane: the room left above a centred stack. */
  top: number;
  /** Height of the drawn stack, from `top` down through the last gap. What
   *  the selection and hover bands span. */
  stackH: number;
  /** Height with every lane at its base: what the panel needs, and its height
   *  when it is given none. */
  naturalH: number;
}

interface SpecLane {
  key: PanelLaneKey;
  source: number;
  spec: LaneSpec;
}

/** The lanes present with their specs, top to bottom. */
function specsOf(present: PanelLanePresence): SpecLane[] {
  const base = Math.max(1, Math.round(baseRibbonHeight(present.ribbonHeight)));
  const main: LaneSpec =
    chosenRibbonHeight(present.ribbonHeight) != null
      ? { base, max: base, weight: 0 }
      : { base, max: mainRibbonMax(present.probabilities), weight: MAIN_RIBBON_WEIGHT };
  const lanes: SpecLane[] = [{ key: 'ruler', source: 0, spec: RULER }];
  if (present.letters) lanes.push({ key: 'letters', source: 0, spec: LETTERS });
  lanes.push({ key: 'ribbon', source: 0, spec: main });
  for (let k = 1; k <= Math.max(0, present.extraSources); k++) {
    lanes.push({ key: 'ribbon', source: k, spec: EXTRA_RIBBON });
  }
  if (present.agreement) lanes.push({ key: 'agreement', source: 0, spec: AGREEMENT });
  if (present.probabilities) lanes.push({ key: 'probabilities', source: 0, spec: PROBABILITIES });
  return lanes;
}

/** Height of the panel with every present lane at its base height. */
export function naturalPanelHeight(present: PanelLanePresence): number {
  return specsOf(present).reduce((sum, l) => sum + l.spec.base + LANE_GAP, 0);
}

/**
 * Spread `spare` px over lanes by weight, none past its cap. A lane that hits
 * its cap hands its unused share to the rest, so the result is the same as
 * filling them in the order they saturate. Whole pixels: the pixels the
 * rounding down leaves go to the lanes with the largest fractions, so a cell
 * no cap holds back is filled to the pixel.
 */
function distribute(specs: readonly LaneSpec[], spare: number): number[] {
  const grow = specs.map(() => 0);
  let active = specs
    .map((_, i) => i)
    .filter((i) => specs[i].weight > 0 && specs[i].max > specs[i].base);
  let left = spare;
  while (active.length > 0 && left > 0) {
    const total = active.reduce((sum, i) => sum + specs[i].weight, 0);
    const share = (i: number) => (left * specs[i].weight) / total;
    const room = (i: number) => specs[i].max - specs[i].base;
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
  const whole = grow.map((g) => Math.floor(g));
  let extra = Math.round(grow.reduce((s, g) => s + g, 0)) - whole.reduce((s, g) => s + g, 0);
  const byFraction = grow
    .map((g, i) => ({ i, frac: g - Math.floor(g) }))
    .filter((e) => e.frac > 1e-9)
    .sort((a, b) => b.frac - a.frac);
  for (const { i } of byFraction) {
    if (extra <= 0) break;
    whole[i] += 1;
    extra -= 1;
  }
  return whole;
}

/** Place the present lanes in a panel `viewH` px tall. */
export function layoutPanelLanes(present: PanelLanePresence, viewH: number): PanelLayout {
  const lanes = specsOf(present);
  const naturalH = lanes.reduce((sum, l) => sum + l.spec.base + LANE_GAP, 0);
  const height = Number.isFinite(viewH) ? Math.floor(viewH) : 0;
  const spare = Math.max(0, height - naturalH);

  const grow = distribute(
    lanes.map((l) => l.spec),
    spare,
  );
  const heights = lanes.map((l, i) => l.spec.base + grow[i]);
  // What the caps left over.
  let rest = Math.max(0, height - heights.reduce((s, h) => s + h, 0) - lanes.length * LANE_GAP);
  const extraGap = Math.min(LANE_GAP_MAX - LANE_GAP, Math.floor(rest / lanes.length));
  const gap = LANE_GAP + extraGap;
  rest -= extraGap * lanes.length;
  const top = Math.floor(rest / 2);

  let y = top;
  const placed = lanes.map((l, i) => {
    const lane = { key: l.key, source: l.source, y, h: heights[i] };
    y += heights[i] + gap;
    return lane;
  });
  return { lanes: placed, gap, top, stackH: y - top, naturalH };
}
