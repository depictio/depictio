/**
 * Why a saved analysis group did, or did not, reach a component's frame.
 *
 * The server decides this per group and per data collection (it may translate
 * the group's column onto this collection through a declared project link), and
 * reports it alongside the render. Before this existed a group that could not
 * reach a frame simply did nothing: the tile rendered ungrouped, with no error
 * and no hint, which is indistinguishable from a tile that ignores grouping
 * altogether. Turning that silence into a sentence is what makes the whole
 * feature verifiable.
 */

/** One group's fate on one data collection, as the render endpoints report it. */
export interface GroupStatusEntry {
  name: string;
  /** See `GROUP_STATUS_REASONS` for the vocabulary. */
  status: string;
  /** Mirrors membership of the "reached the frame" statuses. */
  applied: boolean;
  /** Column used (or that would have been used) on this data collection. */
  column_name?: string | null;
  /** Where the group was captured. */
  source_dc_id?: string | null;
  source_column?: string | null;
  matched_values?: number | null;
}

/** Plain-language reason per status, written for a dashboard reader rather
 *  than an implementer. `applied` / `linked` / `unknown` reached the frame and
 *  need no explanation, so they are absent here. */
const GROUP_STATUS_REASONS: Record<string, string> = {
  column_absent: 'the column it was drawn on is not in this dataset',
  no_link: 'no declared link joins this dataset to the one it was drawn on',
  link_no_match: 'the link resolved, but nothing in this dataset matches it',
  link_failed: 'the link between the two datasets could not be resolved',
};

export interface GroupStatusSummary {
  /** How many groups reached this frame. */
  applied: number;
  /** How many were submitted. */
  total: number;
  /** Groups that did not reach it, already phrased. Empty when all applied. */
  unapplied: Array<{ name: string; reason: string }>;
  /** True when a group was refused for a reason that is a fault rather than an
   *  honest mismatch — worth a different treatment in the UI. */
  faulted: boolean;
}

export function summarizeGroupStatus(
  entries: GroupStatusEntry[] | undefined | null,
): GroupStatusSummary | null {
  if (!Array.isArray(entries) || entries.length === 0) return null;
  const unapplied = entries
    .filter((e) => e && e.applied === false)
    .map((e) => ({
      name: e.name,
      // An unrecognised status still says *which* group missed, which is more
      // useful than dropping the row: this vocabulary can grow server-side.
      reason: GROUP_STATUS_REASONS[e.status] ?? `it could not be applied (${e.status})`,
    }));
  return {
    applied: entries.length - unapplied.length,
    total: entries.length,
    unapplied,
    faulted: entries.some((e) => e?.status === 'link_failed'),
  };
}

/** Why a figure drew none of the groups that did reach its frame. The server
 *  never rewrites a code figure (its author has to spread
 *  `depictio_group_kwargs`), and it declines the override on visu types whose
 *  columns it cannot reason about. */
export const GROUP_DECLINED_REASONS = {
  code: "this figure's code does not use analysis groups",
  ui: 'this chart type cannot be coloured by analysis groups',
} as const;

/** Why a component built per group came back identical in every panel: the
 *  group's values name nothing this component's dataset can be narrowed on. */
export const GROUP_UNREACHABLE_REASON =
  'the groups were drawn on another dataset and no declared link reaches this one';

/** Why a component was drawn whole when the dashboard asked for a split, when
 *  the cause is its chart type rather than its data (see `groupingModeForKind`).
 *  Worded apart from the unreachable reason: a link would not change this. */
export const GROUP_KIND_NOT_SPLIT_REASON =
  'this chart type is not split or coloured by analysis groups';

/** Why a component drawn whole with the groups came back exactly as it was
 *  drawn without them: it recolours by matching each point's own identity
 *  against the groups' values, and not one point matched. Worded apart from
 *  the unreachable reason: the groups may come from this very dataset. */
export const GROUP_UNMATCHED_REASON =
  "none of this figure's points belong to a group: its rows carry no value the groups were drawn on";

/** Badge text for a figure whose grouping was requested. `colored` is the
 *  server's answer to "did the figure actually repaint", which is a different
 *  question from "could the groups reach the frame": a visu type, or a code
 *  figure that ignores the groups, can decline the override with every group
 *  resolved. Either way the tile is drawn ungrouped, and says so. */
export function groupBadgeLabel(
  colored: boolean,
  summary: GroupStatusSummary | null,
): string | null {
  if (colored) {
    if (summary && summary.unapplied.length > 0) {
      return `grouped (${summary.applied} of ${summary.total})`;
    }
    return 'grouped';
  }
  if (summary) return 'not grouped';
  return null;
}

function sentence(reason: string): string {
  return `${reason.charAt(0).toUpperCase()}${reason.slice(1)}.`;
}

/** Hover lines for the badge: one per group that missed, then, when groups
 *  reached the frame but the figure still did not repaint, the reason it
 *  declined. Empty means the badge needs no explanation. */
export function groupBadgeReasons(
  colored: boolean,
  summary: GroupStatusSummary | null,
  declinedReason: string,
): string[] {
  const lines = (summary?.unapplied ?? []).map((u) => `${u.name}: ${u.reason}`);
  if (!colored && summary && summary.applied > 0) lines.push(sentence(declinedReason));
  return lines;
}

/** The single hover line for a component that could not be split by groups. */
export function groupUnreachableReasons(): string[] {
  return [sentence(GROUP_UNREACHABLE_REASON)];
}

/** The single hover line for a component whose chart type is never split. */
export function groupKindNotSplitReasons(): string[] {
  return [sentence(GROUP_KIND_NOT_SPLIT_REASON)];
}

/** The single hover line for a component whose points matched no group. */
export function groupUnmatchedReasons(): string[] {
  return [sentence(GROUP_UNMATCHED_REASON)];
}

/** Which of the reasons above an advanced viz wears on its "not grouped" badge. */
export type AdvancedVizGroupBadge = 'kind' | 'unreachable' | 'unmatched';

/** What the advanced viz dispatch knows about one tile's grouping. */
export interface AdvancedVizGroupInputs {
  /** The dashboard colours by groups, and has some. */
  groupsActive: boolean;
  /** Drawn as one panel per group. */
  split: boolean;
  /** A Split display, on a kind that takes the groups neither way. */
  declinedByKind: boolean;
  /** A split was drawn and every panel came back identical. */
  splitIneffective: boolean;
  /** What the renderer drawn whole reported after recolouring: whether any
   *  point belonged to a group. `null` when it reported nothing. */
  coloured: boolean | null;
  /** A group was drawn on this tile's own dataset. */
  drawnHere: boolean;
}

export interface AdvancedVizGroupOutcome {
  /** The "not grouped" reason to show, or none. */
  badge: AdvancedVizGroupBadge | null;
  /** What the tile adds to the Analysis panel's pool; `null` stays uncounted. */
  reach: boolean | null;
}

/**
 * The badge and the reach of one advanced viz, decided together so they
 * cannot disagree.
 *
 * A drawing split counts as reached until it proves ineffective, and a kind
 * that is never split never counts. A whole render goes by what its recolour
 * reported, and a match wins even after an ineffective split: the tile is
 * coloured, and a badge saying otherwise would contradict it. Only a renderer
 * that reports nothing (one that does not recolour client-side) falls back to
 * vouching for groups drawn on its own dataset.
 */
export function advancedVizGroupOutcome(inputs: AdvancedVizGroupInputs): AdvancedVizGroupOutcome {
  const { groupsActive, split, declinedByKind, splitIneffective, coloured, drawnHere } = inputs;
  if (!groupsActive) return { badge: null, reach: null };
  if (declinedByKind) return { badge: 'kind', reach: false };
  if (split || coloured === true) return { badge: null, reach: true };
  if (splitIneffective) return { badge: 'unreachable', reach: false };
  if (coloured === false) return { badge: 'unmatched', reach: false };
  return { badge: null, reach: drawnHere ? true : null };
}
