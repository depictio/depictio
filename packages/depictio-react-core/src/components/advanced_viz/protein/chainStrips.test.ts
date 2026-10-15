import { describe, expect, it } from 'vitest';

import { chainsOfEntity, chainsShown, onChain, residuesByChain } from './chainStrips';

const frame = {
  entity: ['P1', 'P1', 'P1', 'P1', 'P1', 'P2'],
  chain: ['A', 'A', 'B', 'B', 'B', 'Z'],
  position: [1, 2, 1, 2, 3, 1],
  residue: ['M', 'K', 'G', 'S', 'T', 'W'],
  value: [90, 80, 70, 60, 50, 10],
};
const columns = { entityCol: 'entity', positionCol: 'position', chainCol: 'chain', residueCol: 'residue', valueCol: 'value' };

describe('chainsOfEntity', () => {
  it('lists the chains of one entity in table order', () => {
    expect(chainsOfEntity(frame, 'entity', 'chain', 'P1')).toEqual(['A', 'B']);
    expect(chainsOfEntity(frame, 'entity', 'chain', 'P2')).toEqual(['Z']);
  });
  it('is empty without a chain column or a frame', () => {
    expect(chainsOfEntity({ position: [1] }, 'entity', 'chain', 'P1')).toEqual([]);
    expect(chainsOfEntity(null, 'entity', 'chain', 'P1')).toEqual([]);
  });
});

describe('chainsShown', () => {
  it('shows every chain unless a chain of the entity was picked', () => {
    expect(chainsShown(['A', 'B'], null)).toEqual(['A', 'B']);
    expect(chainsShown(['A', 'B'], 'B')).toEqual(['B']);
    expect(chainsShown(['A', 'B'], 'Q')).toEqual(['A', 'B']);
  });
  it('keeps a single chain as the one strip', () => {
    expect(chainsShown(['A'], 'A')).toEqual(['A']);
    expect(chainsShown([], null)).toEqual([]);
  });
});

describe('residuesByChain', () => {
  it('splits the entity rows into one strip per chain, each on its own numbering', () => {
    const strips = residuesByChain(frame, columns, 'P1', ['A', 'B'], null);
    expect(strips.map((s) => s.chain)).toEqual(['A', 'B']);
    expect(strips[0].residues.map((r) => r.position)).toEqual([1, 2]);
    expect(strips[1].residues.map((r) => r.position)).toEqual([1, 2, 3]);
    expect(strips[1].residues[2]).toMatchObject({ letter: 'T', value: 50 });
  });
  it('returns only the picked chain', () => {
    const strips = residuesByChain(frame, columns, 'P1', ['A', 'B'], 'A');
    expect(strips).toHaveLength(1);
    expect(strips[0].chain).toBe('A');
    expect(strips[0].residues).toHaveLength(2);
  });
  it('does not split a single-chain entity, nor one with no chain column', () => {
    const one = residuesByChain(frame, columns, 'P2', ['Z'], null);
    expect(one).toEqual([{ chain: 'Z', residues: [{ position: 1, letter: 'W', value: 10, category: null }] }]);
    const bare = { position: [1, 2], residue: ['M', 'K'] };
    const none = residuesByChain(bare, { ...columns, entityCol: null, valueCol: null }, null, [], null);
    expect(none).toHaveLength(1);
    expect(none[0].chain).toBeNull();
    expect(none[0].residues).toHaveLength(2);
  });
});

describe('onChain', () => {
  it('keeps every event on a single chain', () => {
    expect(onChain(false, 'B', 'A')).toBe(true);
  });
  it('sends a complex event to the chain it names, or to all when it names none', () => {
    expect(onChain(true, 'B', 'B')).toBe(true);
    expect(onChain(true, 'B', 'A')).toBe(false);
    expect(onChain(true, null, 'A')).toBe(true);
  });
});
