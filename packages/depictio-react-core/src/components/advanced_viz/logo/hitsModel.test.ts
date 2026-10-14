import { describe, expect, it } from 'vitest';

import {
  compareHits,
  coverageDepth,
  evalueScale,
  formatEvalue,
  hitAt,
  hitsFromFrame,
  packHits,
  partialEdges,
  selectHits,
  type HitColumns,
  type LogoHit,
} from './hitsModel';

const COLS: HitColumns = {
  model: 'label',
  entity: 'entity',
  from: 'hmm_from',
  to: 'hmm_to',
  length: 'hmm_length',
  evalue: 'i_evalue',
  score: 'dom_score',
  aliFrom: 'ali_from',
  aliTo: 'ali_to',
};

function hit(partial: Partial<LogoHit> & { from: number; to: number }): LogoHit {
  return {
    key: `${partial.entity ?? 'p'}:${partial.from}`,
    entity: 'p',
    modelLength: null,
    evalue: null,
    score: null,
    aliFrom: null,
    aliTo: null,
    ...partial,
  };
}

describe('hitsFromFrame', () => {
  const frame = {
    label: ['PF1', 'PF1', 'PF2', 'PF1', 'PF1'],
    entity: ['P1', 'P2', 'P3', null, 'P4'],
    hmm_from: [1, 30, 1, 5, 40],
    hmm_to: [50, 10, 20, 9, null],
    hmm_length: [50, 50, 20, 50, 50],
    i_evalue: [1e-20, 0.5, 1e-3, 1e-5, 1e-5],
    dom_score: [80, 2, 20, 30, 30],
    ali_from: [3, 120, 1, 1, 1],
    ali_to: [52, 101, 20, 5, 5],
  };

  it('reads the model\'s hits, putting reversed spans in order and skipping incomplete rows', () => {
    const hits = hitsFromFrame(frame, COLS, 'PF1');
    expect(hits.map((h) => h.entity)).toEqual(['P1', 'P2']);
    expect(hits[1]).toMatchObject({ from: 10, to: 30, aliFrom: 101, aliTo: 120, modelLength: 50 });
    expect(hits[0]).toMatchObject({ evalue: 1e-20, score: 80, key: '0' });
  });

  it('reads every row without a model column, and tolerates missing optional columns', () => {
    const hits = hitsFromFrame(frame, { entity: 'entity', from: 'hmm_from', to: 'hmm_to' }, 'ignored');
    expect(hits).toHaveLength(3);
    expect(hits[0]).toMatchObject({ evalue: null, score: null, aliFrom: null, modelLength: null });
  });

  it('is empty for no frame', () => {
    expect(hitsFromFrame(null, COLS, 'PF1')).toEqual([]);
  });
});

describe('selectHits', () => {
  const hits = [
    hit({ entity: 'weak', from: 1, to: 5, evalue: 0.5, score: 3 }),
    hit({ entity: 'best', from: 1, to: 5, evalue: 1e-30, score: 100 }),
    hit({ entity: 'mid', from: 1, to: 5, evalue: 1e-5, score: 40 }),
    hit({ entity: 'nan', from: 1, to: 5 }),
  ];

  it('drops hits above the threshold, keeps unknown E-values, best score first', () => {
    const sel = selectHits(hits, { evalueMax: 0.01, maxHits: 10 });
    expect(sel.passing.map((h) => h.entity)).toEqual(['best', 'mid', 'nan']);
    expect(sel.total).toBe(4);
  });

  it('caps what is drawn, not what passes', () => {
    const sel = selectHits(hits, { evalueMax: null, maxHits: 2 });
    expect(sel.passing).toHaveLength(4);
    expect(sel.drawn.map((h) => h.entity)).toEqual(['best', 'mid']);
  });

  it('breaks score ties on the E-value, then the name', () => {
    const a = hit({ entity: 'b', from: 1, to: 2, score: 10, evalue: 1e-3 });
    const b = hit({ entity: 'a', from: 1, to: 2, score: 10, evalue: 1e-9 });
    const c = hit({ entity: 'a', from: 3, to: 4, score: 10, evalue: 1e-9 });
    expect([a, c, b].sort(compareHits)).toEqual([b, c, a]);
  });
});

describe('coverageDepth', () => {
  it('counts the hits spanning each state, clamped to the model', () => {
    const depth = coverageDepth(
      [hit({ from: 1, to: 3 }), hit({ from: 2, to: 5 }), hit({ from: 4, to: 99 }), hit({ from: 9, to: 12 })],
      6,
    );
    expect(Array.from(depth)).toEqual([1, 2, 2, 2, 2, 1]);
  });

  it('is all zero without hits and empty for no model', () => {
    expect(Array.from(coverageDepth([], 3))).toEqual([0, 0, 0]);
    expect(coverageDepth([hit({ from: 1, to: 2 })], 0)).toHaveLength(0);
  });
});

describe('packHits', () => {
  const hits = [
    hit({ entity: 'a', from: 1, to: 10 }),
    hit({ entity: 'b', from: 5, to: 20 }),
    hit({ entity: 'c', from: 12, to: 30 }),
    hit({ entity: 'd', from: 11, to: 11 }),
    hit({ entity: 'e', from: 22, to: 40 }),
  ];

  it('first-fits in the given order, leaving a state clear between bars', () => {
    const pack = packHits(hits);
    expect(Array.from(pack.rowOf)).toEqual([0, 1, 0, 2, 1]);
    expect(pack.rows).toBe(3);
    expect(pack.byRow[0]).toEqual([0, 2]);
  });

  it('packs touching bars side by side with no gap', () => {
    expect(Array.from(packHits(hits, 0).rowOf)).toEqual([0, 1, 0, 0, 1]);
  });

  it('finds the hit under a state', () => {
    const pack = packHits(hits);
    expect(hitAt(hits, pack, 0, 15)?.entity).toBe('c');
    expect(hitAt(hits, pack, 0, 11)).toBeNull();
    expect(hitAt(hits, pack, 2, 11)?.entity).toBe('d');
    expect(hitAt(hits, pack, 7, 1)).toBeNull();
  });
});

describe('partialEdges', () => {
  it('flags a hit that misses either end of the model', () => {
    expect(partialEdges(hit({ from: 1, to: 50, modelLength: 50 }), 99)).toEqual({ left: false, right: false });
    expect(partialEdges(hit({ from: 3, to: 40, modelLength: 50 }), 99)).toEqual({ left: true, right: true });
    // No hmm_length: the profile's own length decides.
    expect(partialEdges(hit({ from: 1, to: 40 }), 40)).toEqual({ left: false, right: false });
    expect(partialEdges(hit({ from: 1, to: 40 }), null)).toEqual({ left: false, right: false });
  });
});

describe('E-values', () => {
  it('scales -log10 E between the weakest and the strongest hit', () => {
    const scale = evalueScale([hit({ from: 1, to: 2, evalue: 1e-2 }), hit({ from: 1, to: 2, evalue: 1e-12 })]);
    expect(scale(1e-2)).toBe(0);
    expect(scale(1e-12)).toBe(1);
    expect(scale(1e-7)).toBeCloseTo(0.5);
    expect(scale(null)).toBe(0);
    expect(scale(0)).toBe(1);
    expect(evalueScale([hit({ from: 1, to: 2, evalue: 3e-4 })])(3e-4)).toBe(1);
    expect(evalueScale([])(1)).toBe(0.5);
  });

  it('prints E-values the hmmsearch way', () => {
    expect(formatEvalue(2.3e-12)).toBe('2.3e-12');
    expect(formatEvalue(0.0123)).toBe('0.012');
    expect(formatEvalue(0)).toBe('0');
    expect(formatEvalue(null)).toBe('-');
  });
});
