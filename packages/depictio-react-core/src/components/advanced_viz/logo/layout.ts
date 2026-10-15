/**
 * Geometry of the logo panel: which lanes are drawn, top to bottom, and how
 * tall; the y axis of the logo; the colour ramp of the hit bars. Pure,
 * unit-tested in `layout.test.ts`.
 */

import type { RGB } from '../protein/residueColours';
import type { HeightMode } from './heights';
import {
  COLLAPSED_TRACK_PX,
  stackTracks,
  trackSpans,
  trackState,
  type TrackKey,
  type TrackSpan,
} from './tracks';

export type LaneKey =
  | 'logo'
  | 'consensus'
  | 'rf'
  | 'cs'
  | 'insertProb'
  | 'insertLength'
  | 'occupancy'
  | 'coverage'
  | 'hits'
  | 'ruler'
  /** A collapsed track: a thin strip standing for all of its lanes. */
  | 'strip';

export interface Lane {
  key: LaneKey;
  y: number;
  h: number;
  /** The track a collapsed `strip` stands for. */
  track?: TrackKey;
}

export interface LaneFlags {
  consensus: boolean;
  rf: boolean;
  cs: boolean;
  insertProb: boolean;
  insertLength: boolean;
  occupancy: boolean;
  /** A hits companion is bound (coverage area and bars). */
  hits: boolean;
  /** Packed rows of hit bars. */
  hitRows: number;
  /** Tracks left out entirely (wins over `collapsedTracks`). */
  hiddenTracks?: readonly TrackKey[];
  /** Tracks reduced to a thin strip. */
  collapsedTracks?: readonly TrackKey[];
}

/** The track each lane belongs to (null: the logo, never hidden). */
export const TRACK_OF_LANE: Readonly<Record<LaneKey, TrackKey | null>> = {
  logo: null,
  consensus: 'consensus',
  rf: 'consensus',
  cs: 'consensus',
  insertProb: 'insert',
  insertLength: 'insert',
  occupancy: 'occupancy',
  coverage: 'hits',
  hits: 'hits',
  ruler: 'ruler',
  strip: null,
};

/** Fixed lane heights, CSS px. */
export const LANE_PX: Readonly<Record<Exclude<LaneKey, 'logo' | 'hits' | 'strip'>, number>> = {
  consensus: 14,
  rf: 12,
  cs: 12,
  insertProb: 12,
  insertLength: 12,
  occupancy: 18,
  coverage: 26,
  ruler: 30,
};
/** Room above the tallest stack for the axis' top label. */
export const LOGO_TOP_PAD = 8;
export const LOGO_MIN_PX = 60;
export const LOGO_NATURAL_PX = 150;
/** One hit bar is this tall, whatever the room: a compact bar, never taller. */
export const HIT_BAR_PX = 4;
/** Clear space between two rows of bars. */
export const HIT_GAP_PX = 1;
/** Pitch of the packed rows (bar plus gap). */
export const HIT_ROW_PX = HIT_BAR_PX + HIT_GAP_PX;
/** Gap between the top of the bars lane and its first row. */
export const HITS_TOP_INSET = 2;
/** Padding around the packed bars (top inset included). */
const HITS_PAD = 4;
/** Share of the room left by the fixed rows (everything but the logo and the
 *  hits) that the whole hits block, coverage area and bars together, may take. */
export const HITS_MAX_SHARE = 0.28;
/** Share of the panel height the logo keeps at least, the hits yielding first. */
export const LOGO_MIN_SHARE = 0.55;
/** Rows of bars the tile asks for when it grows to its natural height. */
export const HITS_NATURAL_ROWS = 8;

export interface LaneLayout {
  lanes: Lane[];
  /** The expanded lanes by name (collapsed tracks are in `strips`). */
  byKey: Partial<Record<LaneKey, Lane>>;
  /** The strip of each collapsed track. */
  strips: Partial<Record<TrackKey, Lane>>;
  /** Every track on the panel with its extent, expanded or collapsed. */
  tracks: TrackSpan[];
  /** Top of the ruler (or of its strip), else the bottom of the last lane. */
  gridBottom: number;
  /** Pitch of the hit bar rows, the height of a bar within it, how many rows
   *  fit and how many the packing holds (0 and 0 when no bar fits). */
  hitRowPx: number;
  hitBarPx: number;
  hitRowsShown: number;
  hitRowsTotal: number;
  /** Height the content would like (lanes plus a comfortable logo). */
  natural: number;
}

const ORDER: readonly Exclude<LaneKey, 'strip'>[] = [
  'logo',
  'consensus',
  'rf',
  'cs',
  'insertProb',
  'insertLength',
  'occupancy',
  'coverage',
  'hits',
  'ruler',
];

/**
 * Lanes for a panel `height` px tall: the fixed rows the flags ask for, the
 * hits block, and the logo, which gets the rest.
 *
 * The hits block is the coverage area (a lane that is always kept) and the
 * packed hit bars. Bars are a fixed 4 px with a 1 px gap, so their count, not
 * their size, gives way: the whole block takes at most 28 % of what the fixed
 * rows leave, and never so much that the logo falls under 55 % of the panel
 * (or `LOGO_MIN_PX`). Rows that do not fit are not drawn; `hitRowsShown` of
 * `hitRowsTotal` is what the lane label summarises.
 *
 * Tracks (`tracks.ts`) may be hidden, which removes their lanes, or collapsed,
 * which swaps them for one `COLLAPSED_TRACK_PX` strip; the logo takes what they
 * free. The same stack answers drawing, hit testing, hover and `natural`.
 */
export function layoutLanes(height: number, flags: LaneFlags): LaneLayout {
  const hiddenTracks = new Set<TrackKey>(flags.hiddenTracks ?? []);
  const collapsedTracks = new Set<TrackKey>(flags.collapsedTracks ?? []);
  const on: Record<LaneKey, boolean> = {
    logo: true,
    consensus: flags.consensus,
    rf: flags.rf,
    cs: flags.cs,
    insertProb: flags.insertProb,
    insertLength: flags.insertLength,
    occupancy: flags.occupancy,
    coverage: flags.hits,
    hits: flags.hits && flags.hitRows > 0,
    ruler: true,
    strip: false,
  };
  // What a lane is drawn as: its own rows, a strip shared by its track, or nothing.
  const stateOf = (key: LaneKey) => trackState(TRACK_OF_LANE[key], hiddenTracks, collapsedTracks);
  const expanded = (key: LaneKey) => on[key] && stateOf(key) === 'shown';
  const stripTracks = new Set<TrackKey>();
  for (const key of ORDER) {
    const track = TRACK_OF_LANE[key];
    if (on[key] && track != null && stateOf(key) === 'collapsed') stripTracks.add(track);
  }
  let fixed = stripTracks.size * COLLAPSED_TRACK_PX;
  for (const key of ORDER) {
    if (key !== 'logo' && key !== 'hits' && key !== 'coverage' && expanded(key)) {
      fixed += LANE_PX[key];
    }
  }
  const coverageH = expanded('coverage') ? LANE_PX.coverage : 0;
  const rows = Math.max(0, Math.floor(flags.hitRows));
  const barsOn = expanded('hits');
  let hitRowsShown = 0;
  let hitsH = 0;
  if (barsOn) {
    const free = height - fixed;
    const logoMin = Math.max(LOGO_MIN_PX, LOGO_MIN_SHARE * height);
    const block = Math.min(free * HITS_MAX_SHARE, free - logoMin);
    const room = block - coverageH - HITS_PAD;
    hitRowsShown = Math.max(0, Math.min(rows, Math.floor(room / HIT_ROW_PX)));
    hitsH = hitRowsShown > 0 ? hitRowsShown * HIT_ROW_PX + HITS_PAD : 0;
  }
  const logoH = Math.max(20, height - fixed - coverageH - hitsH);
  // One vertical stack drives drawing, hit testing, hover and the natural height.
  const stack = stackTracks(
    ORDER.filter((key) => on[key]).map((key) => ({
      lane: key,
      track: TRACK_OF_LANE[key],
      h: key === 'logo' ? logoH : key === 'hits' ? hitsH : key === 'coverage' ? LANE_PX.coverage : LANE_PX[key],
    })),
    hiddenTracks,
    collapsedTracks,
  );
  const lanes: Lane[] = stack.slots.map((s) =>
    s.collapsed
      ? { key: 'strip', y: s.y, h: s.h, track: s.track as TrackKey }
      : { key: s.lane as LaneKey, y: s.y, h: s.h },
  );
  const strips: Partial<Record<TrackKey, Lane>> = {};
  for (const l of lanes) if (l.key === 'strip' && l.track) strips[l.track] = l;
  const byKey: Partial<Record<LaneKey, Lane>> = {};
  for (const l of lanes) if (l.key !== 'strip') byKey[l.key] = l;
  const tracks = trackSpans(stack.slots);
  const rulerSpan = tracks.find((t) => t.track === 'ruler');
  // The height at which the preferred rows are all drawn: a logo of its
  // natural height, and both shares of the block honoured.
  let natural = LOGO_NATURAL_PX + fixed;
  if (coverageH > 0) {
    const naturalRows = barsOn ? Math.min(rows, HITS_NATURAL_ROWS) : 0;
    const block = coverageH + (naturalRows > 0 ? naturalRows * HIT_ROW_PX + HITS_PAD : 0);
    natural = Math.max(
      LOGO_NATURAL_PX + fixed + block,
      fixed + block / HITS_MAX_SHARE,
      (fixed + block) / (1 - LOGO_MIN_SHARE),
    );
  }
  return {
    lanes,
    byKey,
    strips,
    tracks,
    gridBottom: rulerSpan ? rulerSpan.y : stack.total,
    hitRowPx: hitRowsShown > 0 ? HIT_ROW_PX : 0,
    hitBarPx: hitRowsShown > 0 ? HIT_BAR_PX : 0,
    hitRowsShown,
    hitRowsTotal: barsOn ? rows : 0,
    natural: Math.ceil(natural),
  };
}

/** Top of the bars of packed row `row` in the hits `lane`. */
export function hitBarTop(lane: Lane, row: number): number {
  return lane.y + HITS_TOP_INSET + row * HIT_ROW_PX;
}

/**
 * The packed row under a y coordinate of the hits lane (a bar and the gap
 * under it count as its row, so hit testing and drawing share one pitch), or
 * -1 outside the rows that are drawn. The inverse of `hitBarTop`.
 */
export function hitRowAt(layout: LaneLayout, y: number): number {
  const lane = layout.byKey.hits;
  if (!lane || layout.hitRowsShown <= 0 || y < lane.y) return -1;
  const row = Math.floor((y - lane.y - HITS_TOP_INSET) / layout.hitRowPx);
  return row >= 0 && row < layout.hitRowsShown ? row : -1;
}

/** The lane under a y coordinate, or null below the last one. */
export function laneAt(layout: LaneLayout, y: number): Lane | null {
  for (const lane of layout.lanes) if (y >= lane.y && y < lane.y + lane.h) return lane;
  return null;
}

export interface LogoAxis {
  /** Value at the top of the logo lane. */
  top: number;
  ticks: number[];
  /** Axis title (bits, or probability). */
  unit: string;
}

/**
 * The logo's y axis. Probability stacks to 1. Entropy modes scale to the
 * tallest stack of the model (not of the visible window, so scrolling does
 * not rescale), rounded up to a tick, at least 1 bit.
 */
export function logoAxis(maxInfo: number, mode: HeightMode, maxTicks = 5): LogoAxis {
  if (mode === 'probability') return { top: 1, ticks: [0, 0.5, 1], unit: 'prob' };
  const max = Number.isFinite(maxInfo) && maxInfo > 0 ? maxInfo : 1;
  const raw = max / Math.max(1, maxTicks);
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? 10 * pow;
  const top = Math.max(1, Math.ceil(max / step - 1e-9) * step);
  const ticks: number[] = [];
  for (let v = 0; v <= top + 1e-9; v += step) ticks.push(Number(v.toFixed(6)));
  return { top, ticks, unit: 'bits' };
}

/** Linear interpolation along colour stops, `t` in [0, 1]. */
export function rampColour(stops: readonly RGB[], t: number): RGB {
  if (!stops.length) return [128, 128, 128];
  if (stops.length === 1) return stops[0];
  const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const f = x - i;
  const [a, b] = [stops[i], stops[i + 1]];
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ];
}

/** Share of the largest expected insert length, on a log scale (lengths
 *  run from 1 to hundreds), for the insert-length strip. */
export function insertLengthShare(length: number | null, maxLength: number): number {
  if (length == null || !(length > 1) || !(maxLength > 1)) return 0;
  return Math.max(0, Math.min(1, Math.log(length) / Math.log(maxLength)));
}
