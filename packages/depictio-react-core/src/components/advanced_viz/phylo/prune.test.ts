import { describe, expect, it } from 'vitest';
import { parseNewick } from './newick';
import { pruneToTips } from './prune';

function depth(tree: any, name: string): number {
  const leaf = tree.leaves.find((l: any) => l.name === name);
  let d = 0;
  let cur = leaf;
  while (cur) {
    if (Number.isFinite(cur.branchLength)) d += cur.branchLength;
    cur = cur.parent;
  }
  return d;
}

describe('pruneToTips', () => {
  const nwk = '(((A:0.1,B:0.2):0.3,(C:0.4,D:0.5):0.6):0.7,E:0.8);';

  it('keeps root-to-tip distances through collapsed nodes', () => {
    const full = parseNewick(nwk);
    const dA_full = depth(full, 'A');
    const pruned = pruneToTips(parseNewick(nwk), new Set(['A', 'C']))!;
    expect(pruned).not.toBeNull();
    // A's stem now absorbs the collapsed (A,B) and the (…):0.7 above it.
    expect(depth(pruned, 'A')).toBeCloseTo(dA_full - 0.7, 10);
    expect(pruned.leaves.map((l: any) => l.name).sort()).toEqual(['A', 'C']);
  });

  it('re-roots at the MRCA with no incoming branch', () => {
    const pruned = pruneToTips(parseNewick(nwk), new Set(['A', 'C']))!;
    expect(pruned.root.parent).toBeNull();
    expect(Number.isFinite(pruned.root.branchLength)).toBe(false);
    expect(pruned.root.children.length).toBe(2);
  });

  it('preserves node ids so the highlight still maps', () => {
    const full = parseNewick(nwk);
    const pruned = pruneToTips(parseNewick(nwk), new Set(['A', 'B', 'C']))!;
    const idOf = (t: any, n: string) => t.leaves.find((l: any) => l.name === n).id;
    expect(idOf(pruned, 'A')).toBe(idOf(full, 'A'));
    expect(idOf(pruned, 'C')).toBe(idOf(full, 'C'));
  });

  it('returns null when there is nothing to prune', () => {
    expect(pruneToTips(parseNewick(nwk), new Set())).toBeNull();
    expect(pruneToTips(parseNewick(nwk), new Set(['nope']))).toBeNull();
    expect(pruneToTips(parseNewick(nwk), new Set(['A','B','C','D','E']))).toBeNull();
  });

  it('recomputes leafCount and handles a single surviving tip', () => {
    const pruned = pruneToTips(parseNewick(nwk), new Set(['A']))!;
    expect(pruned.leaves.length).toBe(1);
    expect(pruned.root.leafCount).toBe(1);
  });
});
