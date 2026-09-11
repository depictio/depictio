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

/** Badge text for a figure whose grouping was requested. `colored` is the
 *  server's answer to "did the figure actually repaint", which is a different
 *  question from "could the groups reach the frame" — a visu type can decline
 *  the override with every group resolved. */
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
  if (summary && summary.applied === 0) return 'not grouped';
  return null;
}
