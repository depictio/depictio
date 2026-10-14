import { describe, expect, it } from 'vitest';

import {
  agreementOf,
  agreementRuns,
  alphaRuns,
  buildSsModel,
  compositionOf,
  compositionSummary,
  confidenceAlpha,
  confidenceScale,
  DEFAULT_SOURCE,
  denseByPosition,
  formatPercent,
  meanFinite,
  MIN_ALPHA,
  q3Of,
  quantiseAlpha,
  resolveConfidence,
  runsOfSource,
  segmentLabel,
  segmentsOf,
  spanOf,
  tooltipLines,
  UNKNOWN_SOURCE,
  type SsColumns,
  type SsFrame,
} from './ssModel';

const COLS: SsColumns = {
  entity: 'entity',
  position: 'position',
  residue: 'residue',
  state: 'ss_code',
  source: null,
  pHelix: 'p_helix',
  pStrand: 'p_strand',
  pCoil: 'p_coil',
  confidence: null,
};

/** A frame from row objects (the columns are those of the first row). */
function frameOf(rows: Record<string, unknown>[]): SsFrame {
  const out: SsFrame = {};
  for (const key of Object.keys(rows[0])) out[key] = rows.map((r) => r[key]);
  return out;
}

/** S4PRED-style rows for one protein: `states` one code per residue from 1. */
function s4pred(states: string, extra: Record<string, unknown> = {}): Record<string, unknown>[] {
  return states.split('').map((code, i) => ({
    entity: 'P1',
    position: i + 1,
    residue: 'ACDEFGHIKLMNPQRSTVWY'[i % 20],
    ss_code: code,
    p_helix: code === 'H' ? 0.9 : 0.05,
    p_strand: code === 'E' ? 0.9 : 0.05,
    p_coil: code === 'C' ? 0.9 : 0.05,
    ...extra,
  }));
}

describe('buildSsModel', () => {
  it('maps DSSP letters, S4PRED codes and words onto the four classes', () => {
    const codes = ['H', 'G', 'I', 'P', 'E', 'B', 'T', 'S', 'C', 'L', '-', 'Helix', 'strand', 'Coil', 'X'];
    const frame = frameOf(
      codes.map((c, i) => ({ entity: 'P1', position: i + 1, residue: 'A', ss_code: c })),
    );
    const model = buildSsModel(frame, COLS, 'P1');
    expect(model.sources).toHaveLength(1);
    expect(model.sources[0].name).toBe(DEFAULT_SOURCE);
    expect(model.sources[0].states).toEqual([
      'helix', 'helix', 'helix', 'helix',
      'strand', 'strand',
      'turn', 'turn',
      'coil', 'coil', 'coil',
      'helix', 'strand', 'coil',
      null,
    ]);
    // The unrecognised code is kept as written for the tooltip.
    expect(model.sources[0].codes[14]).toBe('X');
    expect(model.hasStates).toBe(true);
  });

  it('keeps only the entity asked for, sorted by position, the first row of a duplicate', () => {
    const frame = frameOf([
      { entity: 'P1', position: 3, residue: 'C', ss_code: 'E' },
      { entity: 'P2', position: 1, residue: 'X', ss_code: 'H' },
      { entity: 'P1', position: 1, residue: 'A', ss_code: 'H' },
      { entity: 'P1', position: 3, residue: 'Z', ss_code: 'C' },
    ]);
    const model = buildSsModel(frame, COLS, 'P1');
    expect(model.positions).toEqual([1, 3]);
    expect(model.letters).toEqual(['A', 'C']);
    expect(model.sources[0].states).toEqual(['helix', 'strand']);
    expect(buildSsModel(frame, COLS, null).positions).toEqual([1, 3]);
  });

  it('is empty without rows, a position column or an entity match', () => {
    expect(buildSsModel(null, COLS, 'P1').positions).toEqual([]);
    expect(buildSsModel({}, COLS, 'P1').sources).toEqual([]);
    expect(buildSsModel(frameOf(s4pred('HH')), COLS, 'nobody').sources).toEqual([]);
  });

  it('has no states when the state column is missing or holds no class', () => {
    const noState = frameOf([{ entity: 'P1', position: 1, residue: 'A' }]);
    expect(buildSsModel(noState, COLS, 'P1').hasStates).toBe(false);
    const junk = frameOf([{ entity: 'P1', position: 1, ss_code: 'zzz' }]);
    expect(buildSsModel(junk, COLS, 'P1').hasStates).toBe(false);
  });

  it('groups sources in order of appearance and puts the reference first', () => {
    const rows = [
      ...s4pred('HHC', { source: 'S4PRED' }),
      ...s4pred('HCC', { source: 'structure' }),
    ];
    const cols = { ...COLS, source: 'source' };
    const first = buildSsModel(frameOf(rows), cols, 'P1');
    expect(first.names).toEqual(['S4PRED', 'structure']);
    expect(first.sources.map((s) => s.name)).toEqual(['S4PRED', 'structure']);

    const ref = buildSsModel(frameOf(rows), cols, 'P1', 'structure');
    expect(ref.names).toEqual(['S4PRED', 'structure']);
    expect(ref.sources.map((s) => s.name)).toEqual(['structure', 'S4PRED']);

    // A reference the table does not have falls back to the first source; case is ignored.
    expect(buildSsModel(frameOf(rows), cols, 'P1', 'nope').sources[0].name).toBe('S4PRED');
    expect(buildSsModel(frameOf(rows), cols, 'P1', ' STRUCTURE ').sources[0].name).toBe('structure');
  });

  it('names rows whose source cell is empty', () => {
    const rows = [...s4pred('H', { source: null })];
    const model = buildSsModel(frameOf(rows), { ...COLS, source: 'source' }, 'P1');
    expect(model.sources[0].name).toBe(UNKNOWN_SOURCE);
  });

  it('reads one source when the source column is not in the frame', () => {
    const model = buildSsModel(frameOf(s4pred('HE')), { ...COLS, source: 'source' }, 'P1');
    expect(model.sources.map((s) => s.name)).toEqual([DEFAULT_SOURCE]);
  });

  it('spans the axis from residue 1', () => {
    const frame = frameOf([
      { entity: 'P1', position: 5, ss_code: 'H' },
      { entity: 'P1', position: 9, ss_code: 'E' },
    ]);
    expect(spanOf(buildSsModel(frame, COLS, 'P1'))).toEqual({ min: 1, max: 9 });
    expect(spanOf(buildSsModel(null, COLS, 'P1'))).toBeNull();
  });
});

describe('confidence', () => {
  it('uses the bound column when there is one', () => {
    const rows = s4pred('HC').map((r, i) => ({ ...r, conf: i === 0 ? 0.4 : 0.8 }));
    const model = buildSsModel(frameOf(rows), { ...COLS, confidence: 'conf' }, 'P1');
    expect(model.sources[0].confidence).toEqual([0.4, 0.8]);
    expect(model.sources[0].explicitConfidence).toBe(true);
  });

  it('falls back to the largest of the three probabilities', () => {
    const frame = frameOf([
      { entity: 'P1', position: 1, ss_code: 'H', p_helix: 0.7, p_strand: 0.2, p_coil: 0.1 },
      { entity: 'P1', position: 2, ss_code: 'C', p_helix: 0.1, p_strand: 0.3, p_coil: 0.6 },
    ]);
    const model = buildSsModel(frame, COLS, 'P1');
    expect(model.sources[0].confidence).toEqual([0.7, 0.6]);
    expect(model.sources[0].explicitConfidence).toBe(false);
    expect(model.sources[0].hasProbabilities).toBe(true);
  });

  it('works from the probabilities that are bound', () => {
    const frame = frameOf([{ entity: 'P1', position: 1, ss_code: 'H', p_helix: 0.8 }]);
    expect(buildSsModel(frame, COLS, 'P1').sources[0].confidence).toEqual([0.8]);
    // Only the helix column is bound: the other two are not read.
    const onlyHelix = { ...COLS, pStrand: null, pCoil: null };
    expect(buildSsModel(frame, onlyHelix, 'P1').sources[0].confidence).toEqual([0.8]);
  });

  it('is null (opaque) with neither a column nor probabilities', () => {
    const frame = frameOf([{ entity: 'P1', position: 1, ss_code: 'H' }]);
    const model = buildSsModel(frame, COLS, 'P1');
    expect(model.sources[0].confidence).toEqual([null]);
    expect(model.sources[0].hasProbabilities).toBe(false);
    expect(confidenceAlpha(null)).toBe(1);
  });

  it('prefers the bound column over the probabilities, per residue', () => {
    const frame = frameOf([
      { entity: 'P1', position: 1, ss_code: 'H', p_helix: 0.9, conf: 0.2 },
      { entity: 'P1', position: 2, ss_code: 'H', p_helix: 0.9, conf: null },
    ]);
    const model = buildSsModel(frame, { ...COLS, confidence: 'conf' }, 'P1');
    expect(model.sources[0].confidence).toEqual([0.2, 0.9]);
  });

  it('brings a 0 to 100 column (pLDDT-like) onto 0 to 1', () => {
    expect(confidenceScale([0.2, 0.9])).toBe(1);
    expect(confidenceScale([20, 95, null])).toBe(100);
    expect(confidenceScale([20, 195])).toBe(1);
    expect(confidenceScale([])).toBe(1);
    const frame = frameOf([
      { entity: 'P1', position: 1, ss_code: 'H', plddt: 50 },
      { entity: 'P1', position: 2, ss_code: 'H', plddt: 90 },
    ]);
    const model = buildSsModel(frame, { ...COLS, confidence: 'plddt' }, 'P1');
    expect(model.sources[0].confidence).toEqual([0.5, 0.9]);
  });

  it('resolves and clamps one residue', () => {
    expect(resolveConfidence(0.5, 0.9, null, null)).toBe(0.5);
    expect(resolveConfidence(null, 0.2, 0.6, 0.1)).toBe(0.6);
    expect(resolveConfidence(null, null, null, null)).toBeNull();
    expect(resolveConfidence(1.4, null, null, null)).toBe(1);
    expect(resolveConfidence(-1, null, null, null)).toBe(0);
  });

  it('maps confidence to an opacity that never vanishes', () => {
    expect(confidenceAlpha(1)).toBe(1);
    expect(confidenceAlpha(0)).toBe(MIN_ALPHA);
    expect(confidenceAlpha(0.5)).toBeCloseTo((1 + MIN_ALPHA) / 2);
    expect(confidenceAlpha(7)).toBe(1);
  });
});

describe('segments', () => {
  it('cuts runs of one class and ends a run at a gap in the numbering', () => {
    const frame = frameOf([
      ...s4pred('CCHHHHEEC'),
    ].filter((r) => r.position !== 5));
    const model = buildSsModel(frame, COLS, 'P1');
    expect(runsOfSource(model).map((r) => [r.value, r.start, r.end])).toEqual([
      ['coil', 1, 2],
      ['helix', 3, 4],
      ['helix', 6, 6],
      ['strand', 7, 8],
      ['coil', 9, 9],
    ]);
  });

  it('gives each segment its length and the mean P of its own state', () => {
    const rows = s4pred('CHHHE').map((r, i) => (i === 1 ? { ...r, p_helix: 0.6 } : r));
    const model = buildSsModel(frameOf(rows), COLS, 'P1');
    const segs = segmentsOf(model);
    expect(segs.map((s) => [s.state, s.start, s.end, s.length])).toEqual([
      ['coil', 1, 1, 1],
      ['helix', 2, 4, 3],
      ['strand', 5, 5, 1],
    ]);
    expect(segs[1].mean).toBeCloseTo((0.6 + 0.9 + 0.9) / 3);
    expect(segs[1].meanOf).toBe('probability');
    expect(segmentLabel(segs[1])).toBe('Helix 2–4 (3 aa, mean P 0.80)');
    expect(segmentLabel(segs[2])).toBe('Strand 5 (1 aa, mean P 0.90)');
  });

  it('means the confidence for a turn, which has no probability column', () => {
    const frame = frameOf([
      { entity: 'P1', position: 1, ss_code: 'T', conf: 0.5 },
      { entity: 'P1', position: 2, ss_code: 'T', conf: 0.7 },
    ]);
    const model = buildSsModel(frame, { ...COLS, confidence: 'conf' }, 'P1');
    const [seg] = segmentsOf(model);
    expect(seg.state).toBe('turn');
    expect(seg.meanOf).toBe('confidence');
    expect(segmentLabel(seg)).toBe('Turn 1–2 (2 aa, mean confidence 0.60)');
  });

  it('has no mean without probabilities or confidence', () => {
    const frame = frameOf([{ entity: 'P1', position: 1, ss_code: 'E' }]);
    const [seg] = segmentsOf(buildSsModel(frame, COLS, 'P1'));
    expect(seg.mean).toBeNull();
    expect(segmentLabel(seg)).toBe('Strand 1 (1 aa)');
  });

  it('lists the segments of the main source, the reference when set', () => {
    const rows = [
      ...s4pred('HHC', { source: 'S4PRED' }),
      ...s4pred('CEE', { source: 'structure' }),
    ];
    const cols = { ...COLS, source: 'source' };
    expect(segmentsOf(buildSsModel(frameOf(rows), cols, 'P1')).map((s) => s.state)).toEqual([
      'helix',
      'coil',
    ]);
    expect(segmentsOf(buildSsModel(frameOf(rows), cols, 'P1', 'structure')).map((s) => s.state)).toEqual([
      'coil',
      'strand',
    ]);
    expect(segmentsOf(buildSsModel(null, cols, 'P1'))).toEqual([]);
  });
});

describe('composition', () => {
  it('counts each class among the residues that have a state', () => {
    const rows = [...s4pred('HHHHEECCCT'), { entity: 'P1', position: 11, ss_code: 'zz' }];
    const model = buildSsModel(frameOf(rows), COLS, 'P1');
    const c = compositionOf(model);
    expect(c.counts).toEqual({ helix: 4, strand: 2, turn: 1, coil: 3 });
    expect(c.total).toBe(10);
    expect(c.fractions.helix).toBeCloseTo(0.4);
    expect(c.fractions.coil).toBeCloseTo(0.3);
    expect(formatPercent(c.fractions.helix)).toBe('40.0%');
    expect(compositionSummary(c)).toBe('H 40.0% · E 20.0% · T 10.0% · C 30.0%');
  });

  it('leaves the turn out of the summary when the source has none', () => {
    const model = buildSsModel(frameOf(s4pred('HHEC')), COLS, 'P1');
    expect(compositionSummary(compositionOf(model))).toBe('H 50.0% · E 25.0% · C 25.0%');
  });

  it('is per source and zero for a source with no states', () => {
    const rows = [
      ...s4pred('HHCC', { source: 'S4PRED' }),
      ...s4pred('EEEE', { source: 'structure' }),
    ];
    const model = buildSsModel(frameOf(rows), { ...COLS, source: 'source' }, 'P1');
    expect(compositionOf(model, 0).fractions.helix).toBeCloseTo(0.5);
    expect(compositionOf(model, 1).fractions.strand).toBe(1);
    const empty = compositionOf(buildSsModel(null, COLS, 'P1'));
    expect(empty.total).toBe(0);
    expect(empty.fractions.helix).toBe(0);
  });
});

describe('agreement', () => {
  const cols = { ...COLS, source: 'source' };

  it('is null with a single source', () => {
    expect(agreementOf(buildSsModel(frameOf(s4pred('HHC')), COLS, 'P1'))).toBeNull();
  });

  it('marks agree and disagree residue by residue against the main source', () => {
    const rows = [
      ...s4pred('HHEEC', { source: 'S4PRED' }),
      ...s4pred('HCEHC', { source: 'structure' }),
    ];
    const a = agreementOf(buildSsModel(frameOf(rows), cols, 'P1'));
    expect(a?.marks).toEqual(['agree', 'disagree', 'agree', 'disagree', 'agree']);
    expect(a?.agree).toBe(3);
    expect(a?.compared).toBe(5);
    expect(a?.fraction).toBeCloseTo(0.6);
    expect(a?.perSource).toEqual([{ name: 'structure', agree: 3, compared: 5, fraction: 0.6 }]);
  });

  it('compares only the positions both sources cover', () => {
    // The structure has no residue 2 and 5, and a state the tile cannot read at 4.
    const structure = s4pred('HHEEC', { source: 'structure' })
      .filter((r) => r.position !== 2 && r.position !== 5)
      .map((r) => (r.position === 4 ? { ...r, ss_code: 'zz' } : r));
    const rows = [...s4pred('HCEEC', { source: 'S4PRED' }), ...structure];
    const model = buildSsModel(frameOf(rows), cols, 'P1');
    const a = agreementOf(model);
    expect(a?.marks).toEqual(['agree', null, 'agree', null, null]);
    expect(a?.compared).toBe(2);
    expect(a?.fraction).toBe(1);
    expect(a?.perSource[0].compared).toBe(2);
  });

  it('counts a position only the other source has as not compared', () => {
    const rows = [
      ...s4pred('HH', { source: 'S4PRED' }),
      ...s4pred('HHE', { source: 'structure' }),
    ];
    const model = buildSsModel(frameOf(rows), cols, 'P1');
    expect(model.positions).toEqual([1, 2, 3]);
    const a = agreementOf(model);
    expect(a?.marks).toEqual(['agree', 'agree', null]);
    expect(a?.compared).toBe(2);
  });

  it('has no fraction when nothing could be compared', () => {
    const rows = [
      ...s4pred('H', { source: 'S4PRED' }),
      ...[{ entity: 'P1', position: 2, ss_code: 'H', source: 'structure' }],
    ];
    const a = agreementOf(buildSsModel(frameOf(rows), cols, 'P1'));
    expect(a?.compared).toBe(0);
    expect(a?.fraction).toBeNull();
    expect(a?.perSource[0].fraction).toBeNull();
  });

  it('compares H, E and C: a turn is coil, a 3-10 helix is helix', () => {
    expect(q3Of('turn')).toBe('coil');
    expect(q3Of('helix')).toBe('helix');
    expect(q3Of(null)).toBeNull();
    const rows = [
      ...s4pred('CCHE', { source: 'S4PRED' }),
      ...s4pred('TSGB', { source: 'DSSP' }),
    ];
    const a = agreementOf(buildSsModel(frameOf(rows), cols, 'P1'));
    expect(a?.marks).toEqual(['agree', 'agree', 'agree', 'agree']);
  });

  it('measures against the reference source and needs every other source to agree', () => {
    // A does not cover residue 1.
    const rows = [
      ...s4pred('HHHE', { source: 'A' }).filter((r) => r.position !== 1),
      ...s4pred('HHEE', { source: 'B' }),
      ...s4pred('HEHE', { source: 'C' }),
    ];
    const a = agreementOf(buildSsModel(frameOf(rows), cols, 'P1', 'A'));
    expect(a?.marks).toEqual([null, 'disagree', 'disagree', 'agree']);
    expect(a?.perSource.map((p) => [p.name, p.agree, p.compared])).toEqual([
      ['B', 2, 3],
      ['C', 2, 3],
    ]);
    // Measured against C, the main source changes: residue 1 is now compared (B with C).
    const vsC = agreementOf(buildSsModel(frameOf(rows), cols, 'P1', 'C'));
    expect(vsC?.marks).toEqual(['agree', 'disagree', 'disagree', 'agree']);
    expect(vsC?.perSource.map((p) => p.name)).toEqual(['A', 'B']);
  });

  it('turns the marks into runs', () => {
    const rows = [
      ...s4pred('HHEECC', { source: 'S4PRED' }),
      ...s4pred('HHCCEE', { source: 'structure' }),
    ];
    const model = buildSsModel(frameOf(rows), cols, 'P1');
    const runs = agreementRuns(model, agreementOf(model));
    expect(runs.map((r) => [r.value, r.start, r.end])).toEqual([
      ['agree', 1, 2],
      ['disagree', 3, 6],
    ]);
    expect(agreementRuns(model, null)).toEqual([]);
  });
});

describe('opacity runs', () => {
  const runs = [{ start: 1, end: 6, value: 'helix' as const }];

  it('quantises opacity between the floor and 1', () => {
    expect(quantiseAlpha(1)).toBe(1);
    expect(quantiseAlpha(0)).toBe(MIN_ALPHA);
    expect(quantiseAlpha(0.99, 5)).toBe(1);
    expect(quantiseAlpha(0.5, 1)).toBe(1);
  });

  it('splits a run where the quantised opacity changes', () => {
    const conf = [1, 1, 0, 0, 1, 1];
    const out = alphaRuns(runs, (p) => confidenceAlpha(conf[p - 1]), { perResidue: true });
    expect(out.map((r) => [r.start, r.end, r.alpha])).toEqual([
      [1, 2, 1],
      [3, 4, MIN_ALPHA],
      [5, 6, 1],
    ]);
    expect(out.every((r) => r.value === 'helix')).toBe(true);
  });

  it('keeps one piece at the mean opacity when the residues are too narrow', () => {
    const conf = [1, 1, 0, 0, 1, 1];
    const out = alphaRuns(runs, (p) => confidenceAlpha(conf[p - 1]), { perResidue: false });
    expect(out).toHaveLength(1);
    expect([out[0].start, out[0].end]).toEqual([1, 6]);
    expect(out[0].alpha).toBeGreaterThan(MIN_ALPHA);
    expect(out[0].alpha).toBeLessThan(1);
  });

  it('is a single opaque piece without confidence', () => {
    const out = alphaRuns(runs, () => 1, { perResidue: true });
    expect(out).toEqual([{ start: 1, end: 6, value: 'helix', alpha: 1 }]);
  });
});

describe('drawing helpers', () => {
  it('spreads values over the axis, NaN where there is no residue', () => {
    const frame = frameOf([
      { entity: 'P1', position: 2, ss_code: 'H', p_helix: 0.5 },
      { entity: 'P1', position: 4, ss_code: 'H', p_helix: 0.25 },
    ]);
    const model = buildSsModel(frame, COLS, 'P1');
    const dense = denseByPosition(model, model.sources[0].pHelix, 1, 5);
    expect(Array.from(dense).map((v) => (Number.isNaN(v) ? null : v))).toEqual([
      null,
      0.5,
      null,
      0.25,
      null,
    ]);
  });

  it('averages the finite entries of a window', () => {
    const v = new Float32Array([NaN, 0.5, 1, NaN]);
    expect(meanFinite(v, 0, 3)).toBeCloseTo(0.75);
    expect(meanFinite(v, 3, 3)).toBeNull();
    expect(meanFinite(v, -5, 99)).toBeCloseTo(0.75);
  });
});

describe('tooltip', () => {
  it('names the residue, the state, the probabilities and the agreement', () => {
    const rows = [
      ...s4pred('HC', { source: 'S4PRED' }),
      ...s4pred('EC', { source: 'structure' }).map((r) => ({
        ...r,
        p_helix: null,
        p_strand: null,
        p_coil: null,
      })),
    ];
    const model = buildSsModel(frameOf(rows), { ...COLS, source: 'source' }, 'P1');
    const agreement = agreementOf(model);
    expect(tooltipLines(model, 1, agreement)).toEqual([
      'A 1',
      'S4PRED: Helix',
      'P  H 0.90  E 0.05  C 0.05',
      'structure: Strand',
      'Differs from S4PRED',
    ]);
    expect(tooltipLines(model, 2, agreement)).toContain('Agrees with S4PRED');
  });

  it('reads simply with one source and says when a position has no row', () => {
    const model = buildSsModel(frameOf(s4pred('H')), COLS, 'P1');
    expect(tooltipLines(model, 1)).toEqual(['A 1', 'Helix', 'P  H 0.90  E 0.05  C 0.05']);
    expect(tooltipLines(model, 40)).toEqual(['40']);
  });

  it('shows the written state of a code it cannot classify', () => {
    const frame = frameOf([{ entity: 'P1', position: 1, ss_code: 'X' }]);
    const model = buildSsModel(frame, COLS, 'P1');
    expect(tooltipLines(model, 1)).toEqual(['1', 'X']);
  });
});
