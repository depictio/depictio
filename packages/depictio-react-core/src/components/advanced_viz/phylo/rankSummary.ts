/**
 * The tree collapsed to one tip per lineage: the summary view.
 *
 * A tree of thousands of ASVs answers "how are these sequences related" and
 * nothing a landing page asks. What a reader wants there is which lineages
 * make up the community and how those lineages sit relative to each other.
 * This module turns the full tree plus a rank column of the tip metadata
 * (Phylum, say) into exactly that: one leaf per rank value, joined by the
 * topology the tree itself gives them.
 *
 * Placing a lineage is the part that needs a rule. A phylum is rarely a single
 * clade of an amplicon tree — misassigned tips, short reads, and here 16S and
 * 18S aligned together all break monophyly — so "the MRCA of its tips" is
 * often the root. Each lineage is placed instead at its **core clade**: the
 * largest clade whose classified tips all carry that value. Unclassified tips
 * are neutral, so they neither break a clade nor count towards it. Core clades
 * of different lineages are disjoint by construction (a node pure for one
 * value cannot hold a tip of another), so the induced tree over them is always
 * well defined. The size a lineage is drawn at is its whole share, not its
 * core clade's; how much of it the core clade holds is reported alongside, so
 * a scattered lineage says so rather than looking tidy.
 *
 * Pure functions over `PhyloTree`; the React side lives in
 * `PhyloSummaryRenderer.tsx`.
 */

import { ladderise, type PhyloNode, type PhyloTree } from './newick';

/** One lineage of the summary. */
export interface RankGroup {
  /** The rank value, e.g. `Metazoa`. Also the summary leaf's `name`. */
  group: string;
  /** Tips of the (in-scope) tree carrying this value. */
  tips: number;
  /** Tips inside the clade the lineage is drawn at (see the module note). */
  coreTips: number;
  /** Node id, in the source tree, of that clade. */
  coreNodeId: number;
  /** The commonest value of the colour column among the lineage's tips. */
  colourValue: string | null;
  /** What the lineage is sized and ranked by, as a fraction (0..1). */
  share: number;
  /** `share` per value of the split column (abundance mode only). */
  splitShares: Record<string, number> | null;
}

export interface RankSummary {
  /** One leaf per shown lineage (`leaf.name` = the group), ids fresh. */
  tree: PhyloTree;
  /** Shown lineages, in leaf order (top to bottom). */
  shown: RankGroup[];
  /** Everything ranked below the top N, plus what has no place in the tree. */
  other: {
    /** Lineages not drawn: ranked out, or absent from the tree. */
    groups: number;
    share: number;
  };
  /** In-scope tips the summary was computed over. */
  totalTips: number;
}

/** Per-lineage figures from an abundance table (see `aggregateAbundance`). */
export interface AbundanceSummary {
  /** Mean share of a sample's reads, per lineage. */
  share: Map<string, number>;
  /** Mean share per lineage, within each value of the split column. */
  split: Map<string, Map<string, number>> | null;
  /** Split values with at least one sample in view, sorted. */
  splitValues: string[];
  /** Distinct samples the means are taken over (0 when there is no sample column). */
  samples: number;
}

/** The value a tip or a row carries, or null when it carries none. ampliseq
 *  writes unassigned ranks as empty strings, the recipes as nulls. */
export function rankValue(v: unknown): string | null {
  if (v == null) return null;
  const s = String(v).trim();
  return s === '' ? null : s;
}

/**
 * The core clade of every lineage: the largest clade whose classified tips all
 * carry it. Returns `group → { nodeId, coreTips }`.
 *
 * One post-order pass. A node is pure for `g` when every child is either pure
 * for `g` or carries no classified tip at all; its count of `g` is the sum of
 * its children's. Among nodes pure for the same value the one with the most
 * tips wins, ties going to the higher node (the walk is post-order, so a parent
 * is seen after its children and a `>=` keeps it).
 */
export function coreClades(
  tree: PhyloTree,
  groupOf: (tip: string) => string | null,
): Map<string, { nodeId: number; coreTips: number }> {
  // Per node: the single value it is pure for, `null` for "no classified tip",
  // or MIXED; and how many tips of that value it holds.
  const MIXED = '\u0000mixed';
  const best = new Map<string, { nodeId: number; coreTips: number }>();

  function visit(n: PhyloNode): { value: string | null; count: number } {
    let value: string | null;
    let count = 0;
    if (n.children.length === 0) {
      value = groupOf(n.name ?? '');
      count = value == null ? 0 : 1;
    } else {
      value = null;
      for (const c of n.children) {
        const r = visit(c);
        if (r.value == null) continue;
        if (r.value === MIXED || (value != null && value !== r.value)) value = MIXED;
        else value = r.value;
        count += r.count;
      }
    }
    if (value != null && value !== MIXED) {
      const prev = best.get(value);
      if (!prev || count >= prev.coreTips) best.set(value, { nodeId: n.id, coreTips: count });
    }
    return { value, count };
  }
  visit(tree.root);
  return best;
}

/** Branch lengths are optional in Newick; a known length plus an unknown one
 *  is the known one (same rule as `prune.ts`). */
function addLength(a: number, b: number): number {
  const aOk = Number.isFinite(a);
  const bOk = Number.isFinite(b);
  if (aOk && bOk) return a + b;
  if (aOk) return a;
  if (bOk) return b;
  return NaN;
}

/**
 * The tree induced by a set of disjoint clades, each turned into one leaf
 * named after it. Internal nodes left with a single child are folded away
 * (their branch added to the child's), and the root carries no stem, exactly
 * as `pruneToTips` does for tips. Ids are fresh: the result shares no node
 * with the source tree.
 */
export function inducedOverClades(tree: PhyloTree, leafFor: Map<number, string>): PhyloTree | null {
  let nextId = 0;
  function rec(n: PhyloNode): PhyloNode | null {
    const label = leafFor.get(n.id);
    if (label != null) {
      return { id: nextId++, name: label, branchLength: n.branchLength, parent: null, children: [] };
    }
    if (n.children.length === 0) return null;
    const kids: PhyloNode[] = [];
    for (const c of n.children) {
      const kid = rec(c);
      if (kid) kids.push(kid);
    }
    if (kids.length === 0) return null;
    if (kids.length === 1) {
      kids[0].branchLength = addLength(n.branchLength, kids[0].branchLength);
      return kids[0];
    }
    const copy: PhyloNode = {
      id: nextId++,
      name: null,
      branchLength: n.branchLength,
      parent: null,
      children: kids,
    };
    for (const k of kids) k.parent = copy;
    return copy;
  }

  const root = rec(tree.root);
  if (!root) return null;
  root.parent = null;
  root.branchLength = NaN;
  const leaves: PhyloNode[] = [];
  const nodes: PhyloNode[] = [];
  function walk(n: PhyloNode): number {
    nodes.push(n);
    if (n.children.length === 0) {
      n.leafCount = 1;
      leaves.push(n);
      return 1;
    }
    let count = 0;
    for (const c of n.children) count += walk(c);
    n.leafCount = count;
    return count;
  }
  walk(root);
  return { root, leaves, nodes };
}

export interface SummariseOptions {
  /** How many lineages get a tip; the rest are counted under `other`. */
  topN: number;
  /** The colour column's value of a tip (the lineage takes the commonest). */
  colourOf?: (tip: string) => string | null;
  /** Read shares from an abundance table. Without it lineages are sized and
   *  ranked by their number of tips. */
  abundance?: AbundanceSummary | null;
  /** Order children small clade first, as the full tree's `ladderize` does. */
  ladderize?: boolean;
}

/**
 * Collapse `tree` to its top `topN` lineages by `groupOf`.
 *
 * Ranking is by share: of the reads when `abundance` is given, of the tips
 * otherwise. Only a lineage with at least one tip can be placed; with an
 * abundance table, one with no reads in view is not shown either. Returns null
 * when nothing is left to draw.
 */
export function summariseByRank(
  tree: PhyloTree,
  groupOf: (tip: string) => string | null,
  opts: SummariseOptions,
): RankSummary | null {
  const totalTips = tree.leaves.length;
  if (totalTips === 0) return null;

  const tipCount = new Map<string, number>();
  const colourVotes = new Map<string, Map<string, number>>();
  for (const leaf of tree.leaves) {
    const name = leaf.name ?? '';
    const g = groupOf(name);
    if (g == null) continue;
    tipCount.set(g, (tipCount.get(g) ?? 0) + 1);
    const cv = opts.colourOf ? opts.colourOf(name) : null;
    if (cv != null) {
      const votes = colourVotes.get(g) ?? new Map<string, number>();
      votes.set(cv, (votes.get(cv) ?? 0) + 1);
      colourVotes.set(g, votes);
    }
  }

  const abundance = opts.abundance ?? null;
  const shareOf = (g: string): number =>
    abundance ? (abundance.share.get(g) ?? 0) : (tipCount.get(g) ?? 0) / totalTips;

  const placeable = [...tipCount.keys()].filter((g) => !abundance || shareOf(g) > 0);
  placeable.sort(
    (a, b) =>
      shareOf(b) - shareOf(a) ||
      (tipCount.get(b) ?? 0) - (tipCount.get(a) ?? 0) ||
      a.localeCompare(b),
  );
  const top = placeable.slice(0, Math.max(1, Math.floor(opts.topN)));
  if (top.length === 0) return null;

  const cores = coreClades(tree, groupOf);
  const leafFor = new Map<number, string>();
  for (const g of top) {
    const core = cores.get(g);
    if (core) leafFor.set(core.nodeId, g);
  }
  const summaryTree = inducedOverClades(tree, leafFor);
  if (!summaryTree) return null;
  if (opts.ladderize) ladderise(summaryTree, true);

  const majority = (g: string): string | null => {
    const votes = colourVotes.get(g);
    if (!votes) return null;
    let bestValue: string | null = null;
    let bestN = -1;
    for (const [v, n] of votes) {
      if (n > bestN || (n === bestN && bestValue != null && v.localeCompare(bestValue) < 0)) {
        bestValue = v;
        bestN = n;
      }
    }
    return bestValue;
  };

  const split = abundance?.split ?? null;
  const shown: RankGroup[] = summaryTree.leaves.map((leaf) => {
    const g = leaf.name as string;
    const core = cores.get(g)!;
    const perSplit = split?.get(g);
    return {
      group: g,
      tips: tipCount.get(g) ?? 0,
      coreTips: core.coreTips,
      coreNodeId: core.nodeId,
      colourValue: majority(g),
      share: shareOf(g),
      splitShares: split
        ? Object.fromEntries(abundance!.splitValues.map((s) => [s, perSplit?.get(s) ?? 0]))
        : null,
    };
  });

  // Everything that is not a tip: lineages ranked out, lineages the tree has no
  // tip for (abundance only), and what carries no value at all.
  const shownSet = new Set(top);
  let otherShare = 0;
  let otherGroups = 0;
  if (abundance) {
    for (const [g, s] of abundance.share) {
      if (shownSet.has(g) || s <= 0) continue;
      otherShare += s;
      otherGroups += 1;
    }
  } else {
    for (const [g, n] of tipCount) {
      if (shownSet.has(g)) continue;
      otherShare += n / totalTips;
      otherGroups += 1;
    }
    let unclassified = totalTips;
    for (const n of tipCount.values()) unclassified -= n;
    otherShare += unclassified / totalTips;
  }

  return {
    tree: summaryTree,
    shown,
    other: { groups: otherGroups, share: otherShare },
    totalTips,
  };
}

/**
 * Per-lineage read shares from a long abundance table (one row per sample and
 * lineage, as `taxonomy_rel_abundance`).
 *
 * With a sample column the share is the **mean over samples** of each
 * sample's share — the sum of the lineage's relative abundance divided by the
 * number of samples in view — which is what "share of the reads" means on a
 * per-sample table and what stays put when a taxon filter narrows the rows.
 * Without one, it is the lineage's fraction of the column's total.
 *
 * The split column (a site, say) gives the same mean within each of its
 * values, over that value's own samples.
 */
export function aggregateAbundance(
  rows: Record<string, unknown[]>,
  cols: { rank: string; value: string; sample?: string | null; split?: string | null },
): AbundanceSummary {
  const groups = (rows[cols.rank] ?? []) as unknown[];
  const values = (rows[cols.value] ?? []) as unknown[];
  const samples = cols.sample ? ((rows[cols.sample] ?? null) as unknown[] | null) : null;
  const splits = cols.split ? ((rows[cols.split] ?? null) as unknown[] | null) : null;

  const sum = new Map<string, number>();
  const splitSum = splits ? new Map<string, Map<string, number>>() : null;
  const sampleSet = new Set<string>();
  const samplesBySplit = new Map<string, Set<string>>();
  let total = 0;

  for (let i = 0; i < groups.length; i++) {
    const v = Number(values[i]);
    if (!Number.isFinite(v) || v <= 0) continue;
    total += v;
    const sample = samples ? rankValue(samples[i]) : null;
    if (sample != null) sampleSet.add(sample);
    const s = splits ? rankValue(splits[i]) : null;
    if (s != null && sample != null) {
      const set = samplesBySplit.get(s) ?? new Set<string>();
      set.add(sample);
      samplesBySplit.set(s, set);
    }
    const g = rankValue(groups[i]);
    if (g == null) continue;
    sum.set(g, (sum.get(g) ?? 0) + v);
    if (splitSum && s != null) {
      const per = splitSum.get(g) ?? new Map<string, number>();
      per.set(s, (per.get(s) ?? 0) + v);
      splitSum.set(g, per);
    }
  }

  const perSample = samples != null && sampleSet.size > 0;
  const denom = perSample ? sampleSet.size : total;
  const share = new Map<string, number>();
  if (denom > 0) for (const [g, v] of sum) share.set(g, v / denom);

  let split: Map<string, Map<string, number>> | null = null;
  const splitValues = [...samplesBySplit.keys()].sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }),
  );
  if (splitSum && perSample) {
    split = new Map();
    for (const [g, per] of splitSum) {
      const out = new Map<string, number>();
      for (const [s, v] of per) {
        const n = samplesBySplit.get(s)?.size ?? 0;
        if (n > 0) out.set(s, v / n);
      }
      split.set(g, out);
    }
  }

  return { share, split, splitValues: split ? splitValues : [], samples: perSample ? sampleSet.size : 0 };
}

/** A node of the cladogram, in layout units: `x` in levels from the root,
 *  `y` in rows (leaf i at y = i). */
export interface CladogramPoint {
  x: number;
  y: number;
}

/**
 * Cladogram coordinates: topology only, every leaf on the same column. A node
 * sits one level left of its deepest child, so the tree is as shallow as its
 * branching allows, and its row is midway between its outermost children.
 *
 * Branch lengths are deliberately ignored. On a summary they would mostly
 * measure how far apart the deep splits are, which on an amplicon tree (and
 * one aligning 16S with 18S in particular) is the least trustworthy part.
 */
export function cladogram(tree: PhyloTree): {
  points: Map<number, CladogramPoint>;
  depth: number;
} {
  const points = new Map<number, CladogramPoint>();
  const height = new Map<number, number>();
  function h(n: PhyloNode): number {
    let v = 0;
    for (const c of n.children) v = Math.max(v, h(c) + 1);
    height.set(n.id, v);
    return v;
  }
  const depth = h(tree.root);
  tree.leaves.forEach((leaf, i) => points.set(leaf.id, { x: depth, y: i }));
  function place(n: PhyloNode): number {
    if (n.children.length === 0) return points.get(n.id)!.y;
    const ys = n.children.map(place);
    const y = (Math.min(...ys) + Math.max(...ys)) / 2;
    points.set(n.id, { x: depth - (height.get(n.id) ?? 0), y });
    return y;
  }
  place(tree.root);
  return { points, depth };
}

/** A share as a reader says it: whole percent from 10 % up, one decimal
 *  below, and "<0.1%" rather than a zero for a lineage that is there. */
export function formatShare(share: number): string {
  if (!Number.isFinite(share) || share <= 0) return '0%';
  const pct = share * 100;
  if (pct < 0.1) return '<0.1%';
  // 9.96 % would round to "10.0%": the whole-percent rule takes it from 9.95.
  if (pct < 9.95) return `${pct.toFixed(1)}%`;
  return `${Math.round(pct)}%`;
}
