import { describe, expect, it } from 'vitest';

import type { BackboneAtom, BackboneChains, BackboneResidue } from '../molecule/backbone';
import { toOneLetter } from '../molecule/structureText';
import {
  annotatePoints,
  CLASS_LABELS,
  filterByClass,
  pointsFrame,
  positionLabel,
  RESIDUE_CLASSES,
  torsionPoints,
  type TorsionPoint,
} from './torsions';

// ---------------------------------------------------------------------------
// A backbone with known torsions, placed from internal coordinates (NeRF)
// ---------------------------------------------------------------------------

type V = [number, number, number];
const rad = (deg: number) => (deg * Math.PI) / 180;
const sub = (a: V, b: V): V => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a: V, b: V): V => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const unit = (a: V): V => {
  const n = Math.hypot(a[0], a[1], a[2]);
  return [a[0] / n, a[1] / n, a[2] / n];
};

/** The point D with |CD| = r, angle B-C-D = theta and torsion A-B-C-D = tau (degrees). */
function place(a: V, b: V, c: V, r: number, theta: number, tau: number): V {
  const bc = unit(sub(c, b));
  const n = unit(cross(sub(b, a), bc));
  const m = cross(n, bc);
  const t = rad(theta);
  const p = rad(tau);
  const d: V = [-r * Math.cos(t), r * Math.sin(t) * Math.cos(p), r * Math.sin(t) * Math.sin(p)];
  return [
    c[0] + d[0] * bc[0] + d[1] * m[0] + d[2] * n[0],
    c[1] + d[0] * bc[1] + d[1] * m[1] + d[2] * n[1],
    c[2] + d[0] * bc[2] + d[1] * m[2] + d[2] * n[2],
  ];
}

// Engh and Huber backbone geometry.
const LEN = { NCA: 1.458, CAC: 1.525, CN: 1.329, CO: 1.231 };
const ANG = { NCAC: 111.0, CACN: 116.2, CNCA: 121.7, CACO: 120.8 };

interface Spec {
  resn: string;
  phi: number;
  psi: number;
}

type Atoms = Record<BackboneAtom, V>;

/** Backbone atoms of a chain whose residues have the torsions of `specs`. */
function buildAtoms(specs: Spec[], shift: V = [0, 0, 0]): Atoms[] {
  const N: V = [0, 0, 0];
  const CA: V = [LEN.NCA, 0, 0];
  const a = rad(ANG.NCAC);
  const C: V = [CA[0] - LEN.CAC * Math.cos(a), LEN.CAC * Math.sin(a), 0];
  const out: Atoms[] = [{ N, CA, C, O: place(N, CA, C, LEN.CO, ANG.CACO, specs[0].psi + 180) }];
  for (let i = 1; i < specs.length; i += 1) {
    const prev = out[i - 1];
    const n = place(prev.N, prev.CA, prev.C, LEN.CN, ANG.CACN, specs[i - 1].psi);
    const ca = place(prev.CA, prev.C, n, LEN.NCA, ANG.CNCA, 180);
    const c = place(prev.C, n, ca, LEN.CAC, ANG.NCAC, specs[i].phi);
    out.push({ N: n, CA: ca, C: c, O: place(n, ca, c, LEN.CO, ANG.CACO, specs[i].psi + 180) });
  }
  return out.map((r) => {
    const move = (v: V): V => [v[0] + shift[0], v[1] + shift[1], v[2] + shift[2]];
    return { N: move(r.N), CA: move(r.CA), C: move(r.C), O: move(r.O) };
  });
}

const spec = (resn: string, phi: number, psi: number): Spec => ({ resn, phi, psi });

/** One chain of residues numbered from `first`, as `parseBackbone` would give it. */
function chainOf(
  id: string,
  specs: Spec[],
  opts: { first?: number; shift?: V } = {},
): BackboneResidue[] {
  const atoms = buildAtoms(specs, opts.shift);
  return specs.map((s, i) => ({
    chain: id,
    position: (opts.first ?? 1) + i,
    insertionCode: '',
    resName: s.resn,
    oneLetter: toOneLetter(s.resn),
    bfactor: 90 - i,
    ...atoms[i],
  }));
}

const asChains = (...chains: BackboneResidue[][]): BackboneChains =>
  new Map(chains.map((residues) => [residues[0].chain, residues]));

// ---------------------------------------------------------------------------

describe('torsionPoints', () => {
  const helix = (resn: string) => spec(resn, -57, -47);
  const strand = (resn: string) => spec(resn, -120, 130);

  it('keeps the residues with both torsions and drops the chain ends', () => {
    const chains = asChains(
      chainOf('A', [helix('ALA'), helix('LEU'), strand('VAL'), strand('SER'), helix('GLU')], {
        first: 10,
      }),
    );
    const out = torsionPoints(chains);
    expect(out.residues).toBe(5);
    expect(out.withoutTorsions).toBe(2);
    expect(out.chains).toEqual(['A']);
    expect(out.points.map((p) => p.position)).toEqual([11, 12, 13]);
  });

  it('reads back the torsions the chain was built with', () => {
    const chains = asChains(
      chainOf('A', [helix('ALA'), spec('LEU', -63, -41), spec('VAL', -119, 113), helix('SER')]),
    );
    const { points } = torsionPoints(chains);
    expect(points).toHaveLength(2);
    expect(points[0].phi).toBeCloseTo(-63, 1);
    expect(points[0].psi).toBeCloseTo(-41, 1);
    expect(points[1].phi).toBeCloseTo(-119, 1);
    expect(points[1].psi).toBeCloseTo(113, 1);
  });

  it('carries the residue, its B-factor and its chain', () => {
    const chains = asChains(chainOf('B', [helix('ALA'), helix('TRP'), helix('GLY')]));
    const [p] = torsionPoints(chains).points;
    expect(p).toMatchObject({
      chain: 'B',
      position: 2,
      resName: 'TRP',
      oneLetter: 'W',
      bfactor: 89,
      cls: 'general',
    });
  });

  it('assigns glycine, proline, pre-proline and general', () => {
    // Interior residues 2..7; the ends are dropped for want of a torsion.
    const chains = asChains(
      chainOf('A', [
        helix('ALA'),
        helix('VAL'), // before a proline
        helix('PRO'),
        helix('GLY'),
        helix('SER'),
        helix('GLY'), // a glycine before a proline stays a glycine
        helix('PRO'),
        helix('ALA'),
      ]),
    );
    const { points } = torsionPoints(chains);
    expect(points.map((p) => [p.resName, p.cls])).toEqual([
      ['VAL', 'pre_proline'],
      ['PRO', 'proline'],
      ['GLY', 'glycine'],
      ['SER', 'general'],
      ['GLY', 'glycine'],
      ['PRO', 'proline'],
    ]);
  });

  it('does not call the residue before a chain break a pre-proline', () => {
    // The proline starts a second segment far away: no peptide bond, so no
    // phi for it and no psi for the residue before it.
    const first = chainOf('A', [helix('ALA'), helix('VAL'), helix('LEU')]);
    const second = chainOf('A', [helix('PRO'), helix('ALA'), helix('SER')], {
      first: 4,
      shift: [60, 0, 0],
    });
    const out = torsionPoints(asChains([...first, ...second]));
    expect(out.residues).toBe(6);
    expect(out.points.map((p) => [p.position, p.cls])).toEqual([
      [2, 'general'],
      [5, 'general'],
    ]);
  });

  it('drops a residue whose atoms are missing, and its neighbour across the gap', () => {
    const residues = chainOf('A', [
      helix('ALA'),
      helix('LEU'),
      helix('VAL'),
      helix('SER'),
      helix('GLU'),
      helix('ALA'),
    ]);
    // No amide nitrogen for residue 4: its own phi and psi, and residue 3's psi.
    delete residues[3].N;
    const { points, withoutTorsions } = torsionPoints(asChains(residues));
    expect(points.map((p) => p.position)).toEqual([2, 5]);
    expect(withoutTorsions).toBe(4);
  });

  it('yields no points for a chain with no peptide geometry', () => {
    const lone: BackboneResidue = {
      chain: 'A',
      position: 1,
      insertionCode: '',
      resName: 'ALA',
      oneLetter: 'A',
      bfactor: 50,
      CA: [0, 0, 0],
    };
    const calphaOnly: BackboneResidue[] = [1, 2, 3].map((i) => ({
      ...lone,
      position: i,
      CA: [3.8 * i, 0, 0],
    }));
    const out = torsionPoints(asChains(calphaOnly));
    expect(out.points).toEqual([]);
    expect(out.residues).toBe(3);
    expect(out.withoutTorsions).toBe(3);
  });

  it('yields nothing for an empty backbone', () => {
    expect(torsionPoints(new Map())).toEqual({
      points: [],
      residues: 0,
      withoutTorsions: 0,
      chains: [],
    });
  });

  it('keeps chains apart and in file order', () => {
    const out = torsionPoints(
      asChains(
        chainOf('B', [helix('ALA'), helix('LEU'), helix('VAL')]),
        chainOf('A', [strand('ALA'), strand('LEU'), strand('VAL')]),
      ),
    );
    expect(out.chains).toEqual(['B', 'A']);
    expect(out.points.map((p) => p.chain)).toEqual(['B', 'A']);
  });
});

describe('filterByClass', () => {
  const pts = (['general', 'glycine', 'proline', 'pre_proline', 'glycine'] as const).map(
    (cls, i) => ({ cls, position: i }),
  );

  it('keeps everything for no filter', () => {
    expect(filterByClass(pts, null)).toBe(pts);
    expect(filterByClass(pts, undefined)).toBe(pts);
    expect(filterByClass(pts, [])).toBe(pts);
  });

  it('keeps everything when all four classes are named', () => {
    expect(filterByClass(pts, RESIDUE_CLASSES)).toBe(pts);
  });

  it('keeps only the named classes, in their original order', () => {
    expect(filterByClass(pts, ['glycine']).map((p) => p.position)).toEqual([1, 4]);
    expect(filterByClass(pts, ['proline', 'pre_proline']).map((p) => p.position)).toEqual([2, 3]);
    expect(filterByClass(pts, ['glycine', 'general']).map((p) => p.position)).toEqual([0, 1, 4]);
  });

  it('can filter down to nothing', () => {
    expect(filterByClass(pts.filter((p) => p.cls === 'general'), ['proline'])).toEqual([]);
  });
});

describe('annotatePoints', () => {
  const base = (chain: string, position: number): TorsionPoint => ({
    chain,
    position,
    insertionCode: '',
    resName: 'ALA',
    oneLetter: 'A',
    phi: -60,
    psi: -40,
    bfactor: 80,
    cls: 'general',
  });
  const row = (
    chain: string | null,
    position: number | null,
    value: number | null,
    category: string | null,
  ) => ({ chain, position, value, category });

  it('joins on position when the rows name no chain', () => {
    const out = annotatePoints([base('A', 5), base('B', 5)], [row(null, 5, 0.7, 'kinase')]);
    expect(out.map((p) => [p.value, p.category])).toEqual([
      [0.7, 'kinase'],
      [0.7, 'kinase'],
    ]);
  });

  it('joins on chain and position when the rows name a chain', () => {
    const out = annotatePoints(
      [base('A', 5), base('B', 5)],
      [row('A', 5, 1, 'helix'), row('B', 5, 2, 'strand')],
    );
    expect(out.map((p) => [p.value, p.category])).toEqual([
      [1, 'helix'],
      [2, 'strand'],
    ]);
  });

  it('keeps the largest value and the first category of a shared residue', () => {
    const out = annotatePoints(
      [base('A', 5)],
      [row(null, 5, 3, 'first'), row(null, 5, 9, 'second'), row(null, 5, 4, null)],
    );
    expect(out[0].value).toBe(9);
    expect(out[0].category).toBe('first');
  });

  it('gives nulls to a residue no row covers and ignores rows without a position', () => {
    const out = annotatePoints([base('A', 7)], [row(null, 5, 3, 'x'), row(null, null, 8, 'y')]);
    expect(out[0].value).toBeNull();
    expect(out[0].category).toBeNull();
  });

  it('does not touch the points it is given', () => {
    const input = [base('A', 5)];
    annotatePoints(input, [row(null, 5, 1, 'x')]);
    expect(input[0]).not.toHaveProperty('value');
  });
});

describe('labels and frames', () => {
  it('writes a position with its insertion code', () => {
    expect(positionLabel({ position: 45, insertionCode: '' })).toBe('45');
    expect(positionLabel({ position: 45, insertionCode: 'A' })).toBe('45A');
  });

  it('names every class', () => {
    for (const c of RESIDUE_CLASSES) expect(CLASS_LABELS[c]).toBeTruthy();
  });

  it('lays the plotted residues out as columns', () => {
    const chains = asChains(chainOf('A', [spec('ALA', -57, -47), spec('GLY', -63.04, -41.96), spec('SER', -57, -47)]));
    const frame = pointsFrame(torsionPoints(chains).points);
    expect(frame.chain).toEqual(['A']);
    expect(frame.position).toEqual([2]);
    expect(frame.residue).toEqual(['GLY']);
    expect(frame.class).toEqual(['Glycine']);
    expect(frame.phi).toEqual([-63]);
    expect(frame.psi).toEqual([-42]);
  });
});
