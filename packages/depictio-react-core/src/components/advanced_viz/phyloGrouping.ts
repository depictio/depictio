/**
 * How the phylogenetic component answers the dashboard's Analysis "Split".
 *
 * The component is two views behind one kind (see phylo/view.ts), and they do
 * not answer alike:
 *
 *  - the **summary** (`collapse_rank` set) is one tip per lineage with a share
 *    beside it. A group is a set of samples, the shares are computed over
 *    samples, so the summary rebuilt from one group's samples is a real answer
 *    and side by side is how lineages are compared across groups;
 *  - the **full tree** is read against its topology. Cut per group, each copy
 *    would prune to a different set of tips and the shared shape the eye
 *    compares across is gone, so it is drawn whole and badged.
 *
 * Which one is on screen is a Tier-2 control (the viewer can flip it), but the
 * dispatch only sees the stored config, so the policy is read from the config's
 * `collapse_rank`, and a panel keeps the summary on while it is one (see
 * `PhylogeneticRenderer`, `PhyloView.fullTreeBlocker`).
 */

import type { InteractiveFilter } from '../../api';
import type { GroupingMode } from '../../splitPanels';
import { GROUP_FILTER_SOURCE } from '../../selectionGroups';
import type { PhylogeneticConfig } from './phylo/config';
import { rankChoices, summaryBlocker } from './phylo/view';

/** Whether the config draws the summary: a rank is set and the config can
 *  actually draw it (the same test the router applies before mounting it). */
export function phyloDrawsSummary(config: Partial<PhylogeneticConfig> | null | undefined): boolean {
  const c = config ?? {};
  if (!c.collapse_rank) return false;
  return summaryBlocker(c, rankChoices(c, c.collapse_rank)) == null;
}

/** The split policy of a phylogenetic tile: 'split' for the summary, 'none'
 *  for the full tree (never 'colour': neither view colours marks by group). */
export function phyloGroupingMode(
  config: Partial<PhylogeneticConfig> | null | undefined,
): GroupingMode {
  return phyloDrawsSummary(config) ? 'split' : 'none';
}

/** Hover line of the 'kind' badge on a full tree drawn whole. */
export { PHYLO_FULL_TREE_NOT_SPLIT_REASON } from '../../groupStatus';

/** Why a panel cannot flip back to the full tree (shown under the switch). */
export const PHYLO_PANEL_SUMMARY_ONLY_REASON =
  'Split by group keeps the summary: a full tree cut per group would lose the shared topology.';

/** Shown under "Size by" in a group panel, where ASVs cannot be told apart by sample. */
export const PHYLO_PANEL_READS_ONLY_REASON =
  'Split by group: sized by reads, the only measure that depends on the group’s samples.';

/** Whether `filters` carry a group's sample constraint (a split panel's cell,
 *  or an active group filter). */
export function hasGroupConstraint(filters: readonly InteractiveFilter[]): boolean {
  return filters.some((f) => f.source === GROUP_FILTER_SOURCE);
}
