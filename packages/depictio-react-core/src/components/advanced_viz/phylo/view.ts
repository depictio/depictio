/**
 * Full tree or summary: which of the two the phylogenetic component draws.
 *
 * `collapse_rank` is the switch. Unset, the component is the full interactive
 * tree; set (to Phylum, say), it is the one-tip-per-lineage summary of
 * `PhyloSummaryRenderer`. The two are separate renderers that share no state,
 * so the choice cannot live inside either of them: the router in
 * `PhylogeneticRenderer` owns it and hands both the same `PhyloView`, which is
 * what lets either one's settings flip to the other on the spot.
 *
 * Pure functions over the config; the React side is `PhyloViewSwitch.tsx`.
 */

import type { PhylogeneticConfig } from './config';

/** The view switch as the router hands it down. */
export interface PhyloView {
  /** The rank the tree is collapsed to; null draws the full tree. */
  rank: string | null;
  /** Columns of the tip metadata the summary can collapse to. */
  choices: string[];
  /** Why the summary cannot be drawn from this config, or null when it can. */
  blocker: string | null;
  /** The rank the switch to "Summary" lands on. */
  summaryRank: string | null;
  /** Collapse the tree to a rank, or null for the full tree. */
  setRank: (rank: string | null) => void;
}

/**
 * The tip-metadata columns the summary can collapse to.
 *
 * Only columns the config already names, because they are the ones the tree
 * fetches and offers as "Colour by": the rank columns listed in
 * `extra_color_cols` (in the order the author listed them, which for ranks is
 * root to leaf), then `color_col`, then whatever `collapse_rank` already holds,
 * so a rank set in YAML is never missing from its own picker. `taxon_col` is
 * the tip id, one value per tip, and collapsing to it would redraw the tree.
 * `label_col` is left out for the same reason: a label is per tip, not a group.
 */
export function rankChoices(
  config: Partial<PhylogeneticConfig>,
  current?: string | null,
): string[] {
  const taxon = config.taxon_col || 'taxon';
  const out: string[] = [];
  for (const c of [
    ...(config.extra_color_cols ?? []),
    config.color_col,
    config.collapse_rank,
    current,
  ]) {
    if (c && c !== taxon && !out.includes(c)) out.push(c);
  }
  return out;
}

/** Why the summary cannot be drawn from this config, said as the fix; null
 *  when it can. The summary reads every rank from the tip metadata, so a tree
 *  without that table, or a table the config names no rank column of, has
 *  nothing to collapse to. */
export function summaryBlocker(
  config: Partial<PhylogeneticConfig>,
  choices: string[],
): string | null {
  if (!config.metadata_dc_id && !config.metadata_dc_tag) {
    return 'The summary reads its ranks from a tip-metadata table, and this tree has none.';
  }
  if (choices.length === 0) {
    return 'Name a rank column of the tip metadata (extra_color_cols, or the colour column) to collapse to.';
  }
  return null;
}

/**
 * The rank "Summary" switches to: the one last collapsed to, while it is still
 * offered, so flipping to the full tree and back returns the same view. With
 * nothing remembered, Phylum when there is one, the rank a microbial community
 * is usually summarised at on a landing page, else the first rank listed.
 */
export function nextSummaryRank(choices: string[], remembered: string | null): string | null {
  if (remembered && choices.includes(remembered)) return remembered;
  return choices.find((c) => c.toLowerCase() === 'phylum') ?? choices[0] ?? null;
}
