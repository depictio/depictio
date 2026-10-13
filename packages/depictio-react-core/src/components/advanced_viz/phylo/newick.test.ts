import { describe, expect, it } from 'vitest';

import { ladderise, parseNewick, toNewick } from './newick';
import { descendants } from './layout';

// Shape: ((A,B)AB, (C,(D,E)DE)CDE)root — two clades of different sizes so
// ladderise has something to reorder.
const NWK = '((A:1,B:2)AB:0.5,(C:1,(D:1,E:1)DE:0.3)CDE:0.7)root;';

describe('parseNewick / toNewick', () => {
  it('round-trips a tree with names and branch lengths', () => {
    const tree = parseNewick(NWK);
    expect(toNewick(tree.root)).toBe(NWK);
  });

  it('collects leaves and assigns leaf counts', () => {
    const tree = parseNewick(NWK);
    expect(tree.leaves.map((l) => l.name)).toEqual(['A', 'B', 'C', 'D', 'E']);
    expect(tree.root.leafCount).toBe(5);
    expect(tree.nodes.find((n) => n.name === 'CDE')?.leafCount).toBe(3);
  });

  it('assigns the same ids on every parse of the same text', () => {
    const a = parseNewick(NWK);
    const b = parseNewick(NWK);
    expect(a.nodes.map((n) => [n.id, n.name])).toEqual(b.nodes.map((n) => [n.id, n.name]));
  });
});

describe('descendants', () => {
  it('includes the root itself and every node below it', () => {
    const tree = parseNewick(NWK);
    const cde = tree.nodes.find((n) => n.name === 'CDE')!;
    const names = descendants(cde)
      .map((n) => n.name)
      .sort();
    expect(names).toEqual(['C', 'CDE', 'D', 'DE', 'E']);
  });
});

describe('ladderise', () => {
  it('reorders leaves without renumbering node ids', () => {
    const tree = parseNewick(NWK);
    const idByName = new Map(tree.nodes.map((n) => [n.name, n.id]));
    ladderise(tree, false);
    // Descending: the 3-leaf clade (CDE) moves before the 2-leaf AB, and
    // within CDE the 2-leaf DE moves before the single leaf C.
    expect(tree.leaves.map((l) => l.name)).toEqual(['D', 'E', 'C', 'A', 'B']);
    for (const n of tree.nodes) {
      expect(n.id).toBe(idByName.get(n.name));
    }
  });
});
