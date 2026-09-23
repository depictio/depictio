import type { InteractiveFilter } from '../../api';

/**
 * Where a framed advanced-viz renderer's controls are drawn, and the rules
 * that decide it.
 *
 * Pure logic, kept out of `AdvancedVizInlineControls.tsx` for the same reason
 * as `kneeThinning` or `upsetHover`: the vitest suite runs in a node
 * environment with no DOM, so anything it covers must be importable without
 * React or Mantine.
 *
 * `popover` is what every tile did before this existed: both tiers behind the
 * Settings ActionIcon in the chrome row. The two inline placements put the
 * controls next to what they drive.
 *
 *  - `header`: the encoding tier (`primaryControls`) as a compact strip under
 *    the title; the cosmetic tier stays in the popover. A renderer with no
 *    encoding tier has its cosmetic controls promoted into the strip instead
 *    (see `frameTiers.ts`), so the pin always changes something visible.
 *  - `rail`: both tiers in a column beside the plot when the tile is wide
 *    enough for one, under the plot when it is not.
 */
export type ControlsPlacement = 'popover' | 'rail' | 'header';

/** Cycle order of the chrome toggle, and the values the config accepts. */
export const CONTROLS_PLACEMENTS: readonly ControlsPlacement[] = ['popover', 'header', 'rail'];

export function isControlsPlacement(value: unknown): value is ControlsPlacement {
  return typeof value === 'string' && (CONTROLS_PLACEMENTS as readonly string[]).includes(value);
}

/**
 * The placement a tile ends up with: its own config wins, the dashboard-level
 * default applies when the tile says nothing, and `popover` is the floor.
 */
export function resolveControlsPlacement(
  config: unknown,
  dashboardDefault?: unknown,
): ControlsPlacement {
  const own = (config as Record<string, unknown> | undefined)?.controls_placement;
  if (isControlsPlacement(own)) return own;
  if (isControlsPlacement(dashboardDefault)) return dashboardDefault;
  return 'popover';
}

/** The next placement in the toggle's cycle. */
export function nextPlacement(current: ControlsPlacement): ControlsPlacement {
  const i = CONTROLS_PLACEMENTS.indexOf(current);
  return CONTROLS_PLACEMENTS[(i + 1) % CONTROLS_PLACEMENTS.length];
}

/** Width of the side rail, and the frame width below which it moves under the
 *  plot. ~480px is a 4-column tile on the standard 8-column grid: narrower
 *  than that, a 220px rail leaves the figure too little to be worth reading. */
export const RAIL_WIDTH_PX = 220;
export const RAIL_MIN_FRAME_WIDTH_PX = 480;

export type InlineLayout = 'none' | 'header' | 'rail-side' | 'rail-below';

/**
 * Which inline area the frame draws, from the placement and the measured frame
 * width. `null` width means "not measured yet": a rail starts below the plot
 * and moves beside it once the observer reports, which never hides controls.
 */
export function inlineLayoutFor(
  placement: ControlsPlacement,
  frameWidth: number | null,
  hasInlineControls: boolean,
): InlineLayout {
  if (!hasInlineControls) return 'none';
  if (placement === 'header') return 'header';
  if (placement === 'rail') {
    return (frameWidth ?? 0) >= RAIL_MIN_FRAME_WIDTH_PX ? 'rail-side' : 'rail-below';
  }
  return 'none';
}

/** `55000000` -> `55,000,000`, and an open-ended contig as the bare chromosome. */
export function formatRegion(chrom: string, start: number, end: number): string {
  if (!Number.isFinite(start) || !Number.isFinite(end)) return chrom;
  return `${chrom}:${Math.round(start).toLocaleString()}-${Math.round(end).toLocaleString()}`;
}

/**
 * The region a `genome_selection` filter carries, as a string for the echo.
 *
 * Column-agnostic on purpose: the echo says what the reader selected, and a
 * tile that follows a region it did not emit should say the same thing. Two
 * chromosomes are not somewhere to zoom, so they read as a count instead.
 */
export function genomeRegionEcho(filters: readonly InteractiveFilter[] | undefined): string | null {
  if (!filters?.length) return null;
  let chroms: string[] = [];
  let range: [number, number] | null = null;
  for (const f of filters) {
    if (f.source !== 'genome_selection') continue;
    const value = f.value;
    if (
      f.interactive_component_type === 'RangeSlider' &&
      Array.isArray(value) &&
      value.length === 2
    ) {
      const lo = Number(value[0]);
      const hi = Number(value[1]);
      if (Number.isFinite(lo) && Number.isFinite(hi) && hi > lo) range = [lo, hi];
    } else if (Array.isArray(value) && value.length) {
      chroms = value.map((v) => String(v));
    }
  }
  if (!chroms.length) return null;
  if (chroms.length > 1) return `${chroms.length} chromosomes`;
  return range ? formatRegion(chroms[0], range[0], range[1]) : chroms[0];
}

export interface EchoInputs {
  /** What the renderer wants said, when it knows better than the frame (the
   *  group summary of a group_compare, for instance). */
  echo?: string;
  /** Server-side downsampling state, the frame's own default source. */
  reduction?: { displayed: number; total: number; full: boolean } | null;
  /** Rows the renderer actually has in hand, used when nothing was sampled:
   *  most tiles never reduce, and a count that only appears once the server
   *  had to downsample is a count nobody learns to read. */
  rows?: number | null;
  /** Region carried by a `genome_selection` filter that reached this tile. */
  region?: string | null;
}

/**
 * The one dim line under the title: what this tile is currently showing.
 *
 * `343 / 343 rows` is deliberately said even when nothing is filtered, the
 * reference portals echo the full count too, and a number that only appears
 * once something is selected is a number nobody trusts.
 */
export function selectionEcho({ echo, reduction, region, rows }: EchoInputs): string | null {
  const parts: string[] = [];
  if (echo) parts.push(echo);
  else if (reduction && Number.isFinite(reduction.total) && reduction.total > 0) {
    parts.push(
      reduction.full || reduction.displayed >= reduction.total
        ? `${reduction.total.toLocaleString()} rows`
        : `${reduction.displayed.toLocaleString()} / ${reduction.total.toLocaleString()} rows`,
    );
  } else if (rows && rows > 0) {
    parts.push(`${rows.toLocaleString()} rows`);
  }
  if (region) parts.push(region);
  return parts.length ? parts.join(' · ') : null;
}
