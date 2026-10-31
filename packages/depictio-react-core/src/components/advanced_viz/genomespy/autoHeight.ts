/**
 * How tall a `genome_view` tile wants to be when its height follows its
 * content (`auto_height`): the stacked lanes at a comfortable pitch, the genome
 * axis and the gene lane. Pure arithmetic over counts, never over the tile's
 * own size, so the grid answering with a taller tile cannot ask for more.
 *
 * The numbers were read off a GenomeSpy embed: a lane takes its own height plus
 * a title above it and the gap to the next lane, and the stack is wrapped in
 * the embed's padding with the sticky axis under it.
 */

/** Height of one stacked lane when nothing fixes it (`lane_height` unset). */
export const AUTO_LANE_PX = 56;
/** Height of the lone track of an unfaceted tile. */
export const AUTO_SINGLE_TRACK_PX = 180;
/** What a lane costs besides its own height: its title and the gap below. */
export const LANE_OVERHEAD_PX = 21;
/** The embed's padding and the sticky genome axis under the lanes. */
export const AXIS_PX = 41;
/** The gene lane under the data lanes, with its gap. */
export const ANNOTATION_PX = 49;
/** The gap between file-backed lanes. */
const FILE_LANE_GAP_PX = 8;

export interface GenomeContent {
  /** Data lanes drawn: one is an unfaceted track. */
  lanes: number;
  /** Fixed height of each stacked lane (`lane_height`), else the auto pitch. */
  laneHeight?: number | null;
  /** The gene annotation lane is drawn. */
  annotation?: boolean;
  /** File-backed tile: the least height each lane takes (see `fileLaneMinPx`). */
  fileLaneMinPx?: number;
}

/** The height the content of a genome view needs inside its embed, in px. */
export function genomeContentPx({
  lanes,
  laneHeight,
  annotation = false,
  fileLaneMinPx,
}: GenomeContent): number {
  const n = Math.max(1, Math.floor(lanes));
  if (fileLaneMinPx !== undefined) {
    return n * (fileLaneMinPx + FILE_LANE_GAP_PX) - FILE_LANE_GAP_PX + AXIS_PX;
  }
  const gene = annotation ? ANNOTATION_PX : 0;
  if (n === 1) return AUTO_SINGLE_TRACK_PX + AXIS_PX + gene;
  return n * ((laneHeight || AUTO_LANE_PX) + LANE_OVERHEAD_PX) + AXIS_PX + gene;
}

/** The height the tile has to offer: the content plus what the tile spends
 *  around the box the embed sits in (header, controls strip, padding). Null
 *  until that is measured, which is "no demand yet". */
export function tileFitPx(contentPx: number, chromePx: number | null): number | null {
  if (chromePx === null || !Number.isFinite(contentPx) || contentPx <= 0) return null;
  return Math.ceil(contentPx + Math.max(0, chromePx));
}
