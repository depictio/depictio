import { describe, expect, it } from 'vitest';

import { parseNewick, type PhyloTree } from './newick';
import {
  aggregateAbundance,
  cladogram,
  splitCandidates,
  coreClades,
  formatShare,
  inducedOverClades,
  rankValue,
  summariseByRank,
} from './rankSummary';

// Three lineages and one unclassified tip. A is split: two tips form a clade,
// the third sits with a B. C's clade holds the unclassified tip.
//
//   ((A1,A2),(A3,B1))  ((B2,B3),(C1,(C2,U1)))
const NWK = '(((A1:1,A2:1):1,(A3:1,B1:1):1):1,((B2:1,B3:1):1,(C1:1,(C2:1,U1:1):1):1):1);';
const groupOf = (tip: string) => (tip.startsWith('U') ? null : tip[0]);
const tree = () => parseNewick(NWK);

const nodeOf = (t: PhyloTree, id: number) => t.nodes.find((n) => n.id === id)!;
const tipsUnder = (t: PhyloTree, id: number): string[] => {
  const out: string[] = [];
  const walk = (n: PhyloTree['root']) =>
    n.children.length ? n.children.forEach(walk) : out.push(n.name ?? '');
  walk(nodeOf(t, id));
  return out.sort();
};
const names = (t: PhyloTree) => t.leaves.map((l) => l.name);

describe('rankValue', () => {
  it('reads blanks and nulls as no value', () => {
    expect(rankValue(null)).toBeNull();
    expect(rankValue(undefined)).toBeNull();
    expect(rankValue('  ')).toBeNull();
    expect(rankValue(' Metazoa ')).toBe('Metazoa');
    expect(rankValue(3)).toBe('3');
  });
});

describe('coreClades', () => {
  it('places a lineage at its largest clade with no other lineage in it', () => {
    const t = tree();
    const cores = coreClades(t, groupOf);
    expect(tipsUnder(t, cores.get('A')!.nodeId)).toEqual(['A1', 'A2']);
    expect(cores.get('A')!.coreTips).toBe(2);
    expect(tipsUnder(t, cores.get('B')!.nodeId)).toEqual(['B2', 'B3']);
  });

  it('lets an unclassified tip sit inside a clade without counting it', () => {
    const t = tree();
    const c = coreClades(t, groupOf).get('C')!;
    expect(tipsUnder(t, c.nodeId)).toEqual(['C1', 'C2', 'U1']);
    expect(c.coreTips).toBe(2);
  });

  it('gives a tie to the higher node', () => {
    // (C2,U1) and C2 both hold one C; the clade wins over the bare tip.
    const t = parseNewick('((C2,U1),(A1,A2));');
    const c = coreClades(t, groupOf).get('C')!;
    expect(tipsUnder(t, c.nodeId)).toEqual(['C2', 'U1']);
  });
});

describe('inducedOverClades', () => {
  it('keeps one leaf per clade and folds the nodes left with one child', () => {
    const t = tree();
    const cores = coreClades(t, groupOf);
    const leafFor = new Map([
      [cores.get('A')!.nodeId, 'A'],
      [cores.get('B')!.nodeId, 'B'],
      [cores.get('C')!.nodeId, 'C'],
    ]);
    const induced = inducedOverClades(t, leafFor)!;
    expect(names(induced)).toEqual(['A', 'B', 'C']);
    expect(induced.root.children.map((c) => c.leafCount)).toEqual([1, 2]);
    // A's stem absorbs the folded ((A1,A2),(A3,B1)) node above it.
    expect(induced.leaves[0].branchLength).toBe(2);
    expect(Number.isFinite(induced.root.branchLength)).toBe(false);
    // Fresh ids, no node shared with the source tree.
    expect(new Set(induced.nodes.map((n) => n.id)).size).toBe(induced.nodes.length);
    expect(induced.nodes.some((n) => t.nodes.includes(n))).toBe(false);
  });

  it('returns null when no clade is asked for', () => {
    expect(inducedOverClades(tree(), new Map())).toBeNull();
  });
});

describe('summariseByRank (by tips)', () => {
  it('draws the top N and counts the rest, unclassified included', () => {
    const s = summariseByRank(tree(), groupOf, { topN: 2 })!;
    // A and B tie on 3 tips each; the name breaks the tie.
    expect(s.shown.map((g) => g.group)).toEqual(['A', 'B']);
    expect(names(s.tree)).toEqual(['A', 'B']);
    expect(s.shown[0]).toMatchObject({ tips: 3, coreTips: 2, share: 3 / 9 });
    expect(s.other).toEqual({ groups: 1, share: 3 / 9 }); // C (2) + U1 (1)
    expect(s.totalTips).toBe(9);
  });

  it('gives each lineage the commonest colour of its tips', () => {
    const colourOf = (tip: string) => (tip === 'A3' ? 'Eukaryota' : tip === 'U1' ? null : 'Bacteria');
    const s = summariseByRank(tree(), groupOf, { topN: 3, colourOf })!;
    expect(Object.fromEntries(s.shown.map((g) => [g.group, g.colourValue]))).toEqual({
      A: 'Bacteria',
      B: 'Bacteria',
      C: 'Bacteria',
    });
  });

  it('ladderises small clade first when asked', () => {
    const t = parseNewick('(((B1,B2),C1),A1);');
    expect(names(summariseByRank(t, groupOf, { topN: 3 })!.tree)).toEqual(['B', 'C', 'A']);
    expect(names(summariseByRank(t, groupOf, { topN: 3, ladderize: true })!.tree)).toEqual([
      'A',
      'B',
      'C',
    ]);
  });

  it('returns null when nothing carries a value', () => {
    expect(summariseByRank(tree(), () => null, { topN: 5 })).toBeNull();
  });
});

// Three samples at two sites. D has reads but no tip in the tree.
const ROWS = {
  Phylum: ['A', 'B', 'D', 'A', 'B', 'C', 'C', 'B'],
  rel_abundance: [0.5, 0.3, 0.2, 0.1, 0.6, 0.3, 1.0, 0],
  sample: ['s1', 's1', 's1', 's2', 's2', 's2', 's3', 's3'],
  locality: ['X', 'X', 'X', 'Y', 'Y', 'Y', 'Y', 'Y'],
};
const COLS = { rank: 'Phylum', value: 'rel_abundance', sample: 'sample', split: 'locality' };

describe('aggregateAbundance', () => {
  it('takes the mean share over samples, overall and per split value', () => {
    const a = aggregateAbundance(ROWS, COLS);
    expect(a.samples).toBe(3);
    expect(a.share.get('A')).toBeCloseTo(0.6 / 3);
    expect(a.share.get('C')).toBeCloseTo(1.3 / 3);
    expect(a.splitValues).toEqual(['X', 'Y']);
    // Within Y, over Y's two samples.
    expect(a.split!.get('A')!.get('Y')).toBeCloseTo(0.1 / 2);
    expect(a.split!.get('C')!.get('Y')).toBeCloseTo(1.3 / 2);
    expect(a.split!.get('A')!.get('X')).toBeCloseTo(0.5);
  });

  it('falls back to a fraction of the total without a sample column', () => {
    const a = aggregateAbundance(ROWS, { rank: 'Phylum', value: 'rel_abundance' });
    expect(a.samples).toBe(0);
    expect(a.share.get('B')).toBeCloseTo(0.9 / 3.0);
    expect(a.split).toBeNull();
    expect(a.splitValues).toEqual([]);
  });

  it('skips blank ranks and non-positive values', () => {
    const a = aggregateAbundance(
      { Phylum: ['A', '', null, 'B'], rel_abundance: [1, 1, 1, -1], sample: ['s', 's', 's', 's'] },
      { rank: 'Phylum', value: 'rel_abundance', sample: 'sample' },
    );
    expect([...a.share.keys()]).toEqual(['A']);
  });
});

describe('summariseByRank (by reads)', () => {
  const abundance = aggregateAbundance(ROWS, COLS);

  it('ranks by reads, and counts reads the tree cannot place', () => {
    const s = summariseByRank(tree(), groupOf, { topN: 2, abundance })!;
    expect(s.shown.map((g) => g.group).sort()).toEqual(['B', 'C']);
    expect(s.shown.find((g) => g.group === 'C')!.share).toBeCloseTo(1.3 / 3);
    // A ranked out, D absent from the tree.
    expect(s.other.groups).toBe(2);
    expect(s.other.share).toBeCloseTo((0.6 + 0.2) / 3);
  });

  it('carries the per-site shares, zero where a lineage has none', () => {
    const s = summariseByRank(tree(), groupOf, { topN: 3, abundance })!;
    const c = s.shown.find((g) => g.group === 'C')!;
    expect(c.splitShares!.X).toBe(0);
    expect(c.splitShares!.Y).toBeCloseTo(0.65);
  });

  it('does not place a lineage with no reads in view', () => {
    const noA = aggregateAbundance(
      { ...ROWS, Phylum: ROWS.Phylum.map((p) => (p === 'A' ? 'Z' : p)) },
      COLS,
    );
    const s = summariseByRank(tree(), groupOf, { topN: 5, abundance: noA })!;
    expect(s.shown.map((g) => g.group)).not.toContain('A');
  });
});

describe('cladogram', () => {
  it('lines the leaves up on the deepest column, one row each', () => {
    const s = summariseByRank(tree(), groupOf, { topN: 3 })!;
    const { points, depth } = cladogram(s.tree);
    expect(depth).toBe(2);
    expect(s.tree.leaves.map((l) => points.get(l.id))).toEqual([
      { x: 2, y: 0 },
      { x: 2, y: 1 },
      { x: 2, y: 2 },
    ]);
    // The (B,C) node one level in, midway between its leaves; the root at 0.
    expect(points.get(s.tree.root.children[1].id)).toEqual({ x: 1, y: 1.5 });
    expect(points.get(s.tree.root.id)).toEqual({ x: 0, y: 0.75 });
  });
});

describe('formatShare', () => {
  it('says a share the way a reader would', () => {
    expect(formatShare(0.325)).toBe('33%');
    expect(formatShare(0.091)).toBe('9.1%');
    expect(formatShare(0.0996)).toBe('10%');
    expect(formatShare(0.0004)).toBe('<0.1%');
    expect(formatShare(0)).toBe('0%');
    expect(formatShare(Number.NaN)).toBe('0%');
  });
});

describe('splitCandidates', () => {
  const col = (name: string, type: string, nunique: number) => ({ name, type, specs: { nunique } });
  const specs = [
    col('sample', 'object', 85),
    col('rel_abundance', 'float64', 5000),
    col('Kingdom', 'object', 7),
    col('locality', 'object', 3),
    col('season', 'object', 2),
    col('platform', 'object', 1),
    col('station_name', 'object', 40),
    col('depth_min_m', 'int64', 4),
    col('depictio_run_id', 'object', 2),
  ];

  it('offers text columns of a few values, in table order', () => {
    expect(splitCandidates(specs, ['sample', 'rel_abundance'])).toEqual(['locality', 'season']);
  });

  it('leaves out excluded columns, ranks and anything not a list of specs', () => {
    expect(splitCandidates(specs, ['locality'])).toEqual(['season']);
    expect(splitCandidates({}, [])).toEqual([]);
    expect(splitCandidates(null, [])).toEqual([]);
  });
});
