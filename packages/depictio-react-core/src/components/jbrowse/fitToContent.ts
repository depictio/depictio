/**
 * "Fit every track to what is in view": the height each open track needs for
 * the content it lays out in the rendered region, one click for the whole tile.
 *
 * It is the per-track double click on a resize handle (`useFitTrackOnDoubleClick`)
 * applied to every display of every linear view, with the content read off the
 * model rather than the DOM. Everything here is pure; `JBrowseRenderer.tsx`
 * owns the button.
 *
 * Properties used, all read from the 4.3.0 sources (`esm/` of each plugin):
 *  - `layoutFeatures` (plugin-linear-genome-view `BaseLinearDisplay/model.js`):
 *    a composite map over the rendered blocks' `layout.getRectangles()`, whose
 *    values are `[left, top, right, bottom, data]` (`GranularRectLayout`
 *    in @jbrowse/core `util/layouts`). The lowest `bottom` is the stack's
 *    height. Feature tracks (`LinearBasicDisplay`, `LinearFeatureDisplay`,
 *    `LinearVariantDisplay`) and the pileup (`SharedLinearPileupDisplayMixin`
 *    composes `BaseLinearDisplay`) both have it. Only the blocks that are
 *    rendered contribute, so a pan to a sparser region shrinks the fit.
 *  - `height` / `setHeight(px)` (`BaseLinearDisplay/models/TrackHeightMixin.js`,
 *    minimum 20): the display's own height. On `LinearAlignmentsDisplay`
 *    (`LinearAlignmentsDisplay/model.js`) `height` is the whole track, and an
 *    autorun gives `PileupDisplay` the part below `SNPCoverageDisplay.height`
 *    (default 45): so the track needs coverage height + the pileup's content.
 *  - `PileupDisplay` / `SNPCoverageDisplay`: the two panels of
 *    `LinearAlignmentsDisplay`. `LinearReadCloudDisplay` (a lower panel) holds
 *    the stack height in `layoutHeight` (`setLayoutHeight`, set by
 *    `afterAttachRPC.js`); `LinearReadArcsDisplay` has no layout: left alone.
 *  - `sources`, `rowHeightMode` (`'auto'` or a pixel number), `lineZoneHeight`
 *    (`variants/shared/MultiVariantBaseModel.js`): the multi-sample variant
 *    displays (`MultiLinearVariantDisplay`, `LinearVariantMatrixDisplay`) draw
 *    one row per sample. Their `rowHeight` follows the display height under
 *    `'auto'` (`(height - lineZoneHeight) / nrow`), so the fit gives every row
 *    `MULTI_ROW_PX` (10, what `setAutoHeight(false)` falls back to) or the
 *    fixed row height set.
 *  - Signal displays (`LinearWiggleDisplay`, `MultiLinearWiggleDisplay`) have
 *    no layout; their height is a design choice, so it is left as it is. The
 *    y axis is what "fit" means for them (`autoscale.ts`).
 */
import { LABEL_PX, layoutBottom } from './useFitTrackOnDoubleClick';

/** No track is fitted below this: a signal reads poorly under it, pixels. */
export const FIT_MIN_PX = 40;
/** No track is fitted above this, so a dense BAM cannot take over the tile. */
export const FIT_MAX_PX = 600;
/** The tile is never treated as shorter than this, pixels. */
const FIT_TILE_FLOOR_PX = 160;
/** Default `SNPCoverageDisplay` height, used when the panel does not say. */
export const COVERAGE_DEFAULT_PX = 45;
/** Per-sample row height of a multi-sample variant track, pixels. */
export const MULTI_ROW_PX = 10;
/** Under the lowest read row, pixels. */
const PILEUP_TAIL_PX = 4;

/** Any display model; its views are read defensively (a view may throw). */
export type DisplayLike = Record<string, unknown>;

const get = (model: unknown, name: string): unknown => {
  if (!model || typeof model !== 'object') return undefined;
  try {
    return (model as DisplayLike)[name];
  } catch {
    return undefined;
  }
};

const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

/** `px` held to `[FIT_MIN_PX, maxPx]`, rounded up to a whole pixel. */
export function clampFit(px: number, maxPx: number = FIT_MAX_PX): number {
  return Math.min(Math.max(Math.ceil(px), FIT_MIN_PX), Math.max(maxPx, FIT_MIN_PX));
}

/** The tallest a fitted track gets: the tile's height, between 160 and 600. */
export function maxFitPx(tilePx: number): number {
  const tile = Number.isFinite(tilePx) && tilePx > 0 ? tilePx : FIT_MAX_PX;
  return Math.min(Math.max(Math.floor(tile), FIT_TILE_FLOOR_PX), FIT_MAX_PX);
}

/** The layout rectangles of the rendered blocks of a display (see the header). */
function layoutRecords(display: unknown): Iterable<unknown> {
  const layout = get(display, 'layoutFeatures') as { values?: () => Iterable<unknown> } | undefined;
  try {
    return typeof layout?.values === 'function' ? layout.values() : [];
  } catch {
    return [];
  }
}

/** The bottom (px) of the lowest laid-out rectangle of a display, or 0. */
function layoutExtent(display: unknown): number {
  const padded = layoutBottom(layoutRecords(display));
  // `layoutBottom` adds room for a name label; reads have none.
  return padded > 0 ? padded - LABEL_PX : 0;
}

/** The height of a read pileup's stack, or null while nothing is laid out. */
function pileupContent(pileup: unknown): number | null {
  const type = get(pileup, 'type');
  if (type === 'LinearReadCloudDisplay') {
    const cloud = num(get(pileup, 'layoutHeight'));
    return cloud && cloud > 0 ? cloud : null;
  }
  const rows = layoutExtent(pileup);
  return rows > 0 ? rows + PILEUP_TAIL_PX : null;
}

/** Rows of a multi-sample variant display, or null when it is not one. */
function multiRowContent(display: unknown): number | null {
  const sources = get(display, 'sources');
  const mode = get(display, 'rowHeightMode');
  if (!Array.isArray(sources) || mode === undefined) return null;
  const rowPx = typeof mode === 'number' && mode > 0 ? mode : MULTI_ROW_PX;
  const zone = num(get(display, 'lineZoneHeight')) ?? 0;
  return zone + Math.max(sources.length, 1) * rowPx;
}

/**
 * The height `display` needs for what it shows, or null when it has nothing
 * to measure (a signal track, a layout still empty, an unknown type): such a
 * track keeps its height.
 */
export function contentHeight(display: unknown): number | null {
  const type = get(display, 'type');
  if (typeof type !== 'string') return null;

  if (type === 'LinearAlignmentsDisplay') {
    const content = pileupContent(get(display, 'PileupDisplay'));
    if (content == null) return null;
    const coverage = num(get(get(display, 'SNPCoverageDisplay'), 'height')) ?? COVERAGE_DEFAULT_PX;
    return coverage + content;
  }
  if (type === 'LinearPileupDisplay' || type === 'LinearReadCloudDisplay') {
    return pileupContent(display);
  }
  // Signal and coverage: a design height, not a content one.
  if (type.includes('Wiggle') || type === 'LinearSNPCoverageDisplay') return null;

  const rows = multiRowContent(display);
  if (rows != null) return rows;

  // Feature tracks (genes, variants, bed...): the stack plus its name labels.
  const laidOut = layoutBottom(layoutRecords(display));
  return laidOut > 0 ? laidOut : null;
}

/** The height to set on `display`, or null to leave it: nothing to measure, or
 *  already within a pixel of the fit. */
export function fitTarget(display: unknown, maxPx: number = FIT_MAX_PX): number | null {
  const content = contentHeight(display);
  if (content == null) return null;
  const target = clampFit(content, maxPx);
  const current = num(get(display, 'height'));
  return current != null && Math.abs(target - current) <= 1 ? null : target;
}

/** The tracks of a view, and of the linear views nested in it (a split view). */
export function collectViewTracks(view: unknown, seen: Set<unknown> = new Set()): unknown[] {
  if (!view || typeof view !== 'object' || seen.has(view)) return [];
  seen.add(view);
  const out: unknown[] = [];
  const tracks = get(view, 'tracks');
  if (Array.isArray(tracks)) out.push(...tracks);
  const nested = get(view, 'views');
  if (Array.isArray(nested)) for (const v of nested) out.push(...collectViewTracks(v, seen));
  return out;
}

/** The top-level displays of a track list (one per track). */
export function collectTrackDisplays(tracks: readonly unknown[]): DisplayLike[] {
  const out: DisplayLike[] = [];
  for (const track of tracks) {
    const displays = get(track, 'displays');
    const display = Array.isArray(displays) ? displays[0] : undefined;
    if (display && typeof display === 'object') out.push(display as DisplayLike);
  }
  return out;
}

/** Calls `display.setHeight(px)`; false when it is missing or throws. */
function setHeight(display: DisplayLike, px: number): boolean {
  const fn = display.setHeight;
  if (typeof fn !== 'function') return false;
  try {
    (fn as (v: number) => unknown).call(display, px);
    return true;
  } catch {
    // A display torn down mid-flight.
    return false;
  }
}

/** Fit each of `displays` to its content; returns how many changed height. */
export function fitDisplaysToContent(
  displays: readonly DisplayLike[],
  maxPx: number = FIT_MAX_PX,
): number {
  let changed = 0;
  for (const display of displays) {
    const target = fitTarget(display, maxPx);
    if (target != null && setHeight(display, target)) changed += 1;
  }
  return changed;
}

export const FIT_TO_CONTENT_LABEL = 'Fit every track to what is in view';
