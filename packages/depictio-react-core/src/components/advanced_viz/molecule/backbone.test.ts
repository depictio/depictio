import { describe, expect, it } from 'vitest';

import {
  dihedral,
  isPeptideBonded,
  parseBackbone,
  PEPTIDE_BOND_MAX,
  phiPsi,
  residueClass,
  type BackboneAtom,
  type BackboneResidue,
  type Vec3,
} from './backbone';
import { parseResidues } from './structureText';

// ---------------------------------------------------------------------------
// Coordinates from internal coordinates (NeRF), so a fixture has known torsions
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
  /** Peptide torsion into this residue; trans (180) by default. */
  omega?: number;
}

type Atoms = Partial<Record<BackboneAtom, V>>;

/** Backbone atoms of a chain whose residues have the torsions of `specs`.
 *  The phi of the first residue and the psi of the last cannot be placed. */
function buildChain(specs: Spec[], shift: V = [0, 0, 0]): Atoms[] {
  const N: V = [0, 0, 0];
  const CA: V = [LEN.NCA, 0, 0];
  const a = rad(ANG.NCAC);
  const C: V = [CA[0] - LEN.CAC * Math.cos(a), LEN.CAC * Math.sin(a), 0];
  const out: Required<Atoms>[] = [
    { N, CA, C, O: place(N, CA, C, LEN.CO, ANG.CACO, specs[0].psi + 180) },
  ];
  for (let i = 1; i < specs.length; i += 1) {
    const prev = out[i - 1];
    const n = place(prev.N, prev.CA, prev.C, LEN.CN, ANG.CACN, specs[i - 1].psi);
    const ca = place(prev.CA, prev.C, n, LEN.NCA, ANG.CNCA, specs[i].omega ?? 180);
    const c = place(prev.C, n, ca, LEN.CAC, ANG.NCAC, specs[i].phi);
    out.push({ N: n, CA: ca, C: c, O: place(n, ca, c, LEN.CO, ANG.CACO, specs[i].psi + 180) });
  }
  return out.map((r) => {
    const moved: Atoms = {};
    for (const k of ['N', 'CA', 'C', 'O'] as const) {
      moved[k] = [r[k][0] + shift[0], r[k][1] + shift[1], r[k][2] + shift[2]];
    }
    return moved;
  });
}

const spec = (resn: string, phi: number, psi: number, omega?: number): Spec => ({
  resn,
  phi,
  psi,
  omega,
});

// ---------------------------------------------------------------------------
// File writers
// ---------------------------------------------------------------------------

interface Res {
  resn: string;
  chain: string;
  resi: number;
  ins?: string;
  atoms: Atoms;
  /** Atoms of another alternate location: [label, atoms]. */
  alts?: Array<[string, Atoms]>;
  b?: number;
  hetatm?: boolean;
}

const ATOM_ORDER: BackboneAtom[] = ['N', 'CA', 'C', 'O'];
const NAME4: Record<BackboneAtom, string> = { N: ' N  ', CA: ' CA ', C: ' C  ', O: ' O  ' };
const f = (n: number, w: number, d: number) => n.toFixed(d).padStart(w);

function pdbLine(
  serial: number,
  name4: string,
  alt: string,
  r: Res,
  xyz: V,
  record: string,
  resn = r.resn,
): string {
  return (
    record +
    String(serial).padStart(5) +
    ' ' +
    name4 +
    alt +
    resn.padStart(3) +
    ' ' +
    r.chain +
    String(r.resi).padStart(4) +
    (r.ins ?? ' ') +
    '   ' +
    f(xyz[0], 8, 3) +
    f(xyz[1], 8, 3) +
    f(xyz[2], 8, 3) +
    '  1.00' +
    f(r.b ?? 50, 6, 2) +
    '           C'
  );
}

function pdbBlock(residues: Res[]): string[] {
  const lines: string[] = [];
  let serial = 1;
  for (const r of residues) {
    const record = r.hetatm ? 'HETATM' : 'ATOM  ';
    for (const k of ATOM_ORDER) {
      const xyz = r.atoms[k];
      if (xyz) lines.push(pdbLine(serial++, NAME4[k], ' ', r, xyz, record));
    }
    for (const [label, atoms] of r.alts ?? []) {
      for (const k of ATOM_ORDER) {
        const xyz = atoms[k];
        if (xyz) lines.push(pdbLine(serial++, NAME4[k], label, r, xyz, record));
      }
    }
  }
  return lines;
}

/** A PDB file, one MODEL block per element of `models`. */
function pdbText(...models: Res[][]): string {
  if (models.length === 1) return ['HEADER    TEST', ...pdbBlock(models[0]), 'END'].join('\n');
  const lines = ['HEADER    TEST'];
  models.forEach((m, i) => {
    lines.push(`MODEL     ${String(i + 1).padStart(4)}`, ...pdbBlock(m), 'ENDMDL');
  });
  return lines.join('\n');
}

/** An mmCIF file; `label` writes label_asym_id / label_seq_id instead of the author columns. */
function cifText(models: Res[][], opts: { label?: boolean } = {}): string {
  const chainCol = opts.label ? 'label_asym_id' : 'auth_asym_id';
  const seqCol = opts.label ? 'label_seq_id' : 'auth_seq_id';
  const rows: string[] = [];
  let id = 1;
  models.forEach((residues, mi) => {
    for (const r of residues) {
      const group = r.hetatm ? 'HETATM' : 'ATOM';
      const ins = r.ins && r.ins.trim() ? r.ins : '?';
      const emit = (k: BackboneAtom, xyz: V, alt: string) =>
        rows.push(
          [
            group,
            id++,
            k,
            alt,
            r.resn,
            r.chain,
            r.resi,
            ins,
            xyz[0].toFixed(3),
            xyz[1].toFixed(3),
            xyz[2].toFixed(3),
            (r.b ?? 50).toFixed(2),
            mi + 1,
          ].join(' '),
        );
      for (const k of ATOM_ORDER) if (r.atoms[k]) emit(k, r.atoms[k] as V, '.');
      for (const [label, atoms] of r.alts ?? []) {
        for (const k of ATOM_ORDER) if (atoms[k]) emit(k, atoms[k] as V, label);
      }
    }
  });
  return [
    'data_test',
    '#',
    'loop_',
    '_atom_site.group_PDB',
    '_atom_site.id',
    '_atom_site.label_atom_id',
    '_atom_site.label_alt_id',
    '_atom_site.label_comp_id',
    `_atom_site.${chainCol}`,
    `_atom_site.${seqCol}`,
    '_atom_site.pdbx_PDB_ins_code',
    '_atom_site.Cartn_x',
    '_atom_site.Cartn_y',
    '_atom_site.Cartn_z',
    '_atom_site.B_iso_or_equiv',
    '_atom_site.pdbx_PDB_model_num',
    ...rows,
    '#',
  ].join('\n');
}

/** Residues of chain `chain` numbered from `first`, on the atoms of `chain`. */
function residuesOf(specs: Spec[], atoms: Atoms[], chain = 'A', first = 1): Res[] {
  return specs.map((s, i) => ({
    resn: s.resn,
    chain,
    resi: first + i,
    atoms: atoms[i],
    b: 90 - i,
  }));
}

// ---------------------------------------------------------------------------
// Assertions
// ---------------------------------------------------------------------------

/** Difference of two angles in degrees, wrapped to [0, 180]. */
const angularGap = (a: number, b: number) => Math.abs(((((a - b + 540) % 360) + 360) % 360) - 180);

function expectAngle(actual: number | null, expected: number, tol = 0.5): void {
  expect(actual).not.toBeNull();
  expect(angularGap(actual as number, expected)).toBeLessThan(tol);
}

function expectNear(a: Vec3 | undefined, b: Vec3 | undefined): void {
  expect(a).toBeDefined();
  expect(b).toBeDefined();
  for (let k = 0; k < 3; k += 1) expect((a as Vec3)[k]).toBeCloseTo((b as Vec3)[k], 2);
}

const ALA = (n: number, phi: number, psi: number): Spec[] =>
  Array.from({ length: n }, () => spec('ALA', phi, psi));

// ---------------------------------------------------------------------------
// dihedral
// ---------------------------------------------------------------------------

describe('dihedral', () => {
  const b: V = [0, 0, 0];
  const c: V = [0, 0, 1];
  const a: V = [1, 0, 0];
  const around = (deg: number): V => [Math.cos(rad(deg)), Math.sin(rad(deg)), 1];

  it('follows the IUPAC sign: clockwise looking from b to c is positive', () => {
    expect(dihedral(a, b, c, around(90))).toBeCloseTo(90, 9);
    expect(dihedral(a, b, c, around(-90))).toBeCloseTo(-90, 9);
    expect(dihedral(a, b, c, around(0))).toBeCloseTo(0, 9);
    expect(dihedral(a, b, c, around(45))).toBeCloseTo(45, 9);
  });

  it('stays in (-180, 180], whichever way a planar trans arrangement rounds', () => {
    expect(dihedral(a, b, c, [-1, 0, 1])).toBe(180);
    // A hair on the negative side: atan2 answers -pi, which the interval excludes.
    expect(dihedral(a, b, c, [-1, -1e-17, 1])).toBe(180);
    expect(dihedral(a, b, c, around(-180))).toBe(180);
    for (let deg = -179; deg <= 180; deg += 7) {
      const t = dihedral(a, b, c, around(deg));
      expect(t).toBeGreaterThan(-180);
      expect(t).toBeLessThanOrEqual(180);
      expect(angularGap(t, deg)).toBeLessThan(1e-9);
    }
  });

  it('does not depend on where the four points are or how they are turned', () => {
    const points: V[] = [a, b, c, around(-123)];
    // A rotation of 70 degrees about (1, 2, 2) / 3, then a shift.
    const k: V = [1 / 3, 2 / 3, 2 / 3];
    const th = rad(70);
    const move = (p: V): V => {
      const kp = cross(k, p);
      const kd = k[0] * p[0] + k[1] * p[1] + k[2] * p[2];
      return [0, 1, 2].map(
        (i) => p[i] * Math.cos(th) + kp[i] * Math.sin(th) + k[i] * kd * (1 - Math.cos(th)) + 5 * i,
      ) as V;
    };
    const moved = points.map(move);
    expect(dihedral(moved[0], moved[1], moved[2], moved[3])).toBeCloseTo(-123, 9);
  });

  it('is NaN where the points define no torsion', () => {
    expect(dihedral(b, b, c, around(30))).toBeNaN();
    expect(dihedral(a, b, b, around(30))).toBeNaN();
    expect(dihedral([0, 0, -1], b, c, around(30))).toBeNaN();
    expect(dihedral(a, b, c, [0, 0, 2])).toBeNaN();
  });
});

// ---------------------------------------------------------------------------
// phiPsi
// ---------------------------------------------------------------------------

function chainOf(text: string, format: 'pdb' | 'mmcif', chain = 'A'): BackboneResidue[] {
  const chains = parseBackbone(text, format);
  const list = chains.get(chain);
  expect(list).toBeDefined();
  return list as BackboneResidue[];
}

describe('phiPsi', () => {
  it('recovers the torsions of an ideal alpha helix', () => {
    const specs = ALA(9, -57, -47);
    const text = pdbText(residuesOf(specs, buildChain(specs)));
    const t = phiPsi(chainOf(text, 'pdb'));
    expect(t).toHaveLength(9);
    for (let i = 1; i < 8; i += 1) {
      expectAngle(t[i].phi, -57);
      expectAngle(t[i].psi, -47);
      expectAngle(t[i].omega, 180);
    }
  });

  it('recovers the torsions of an extended beta strand', () => {
    const specs = ALA(7, -120, 130);
    const t = phiPsi(chainOf(pdbText(residuesOf(specs, buildChain(specs))), 'pdb'));
    for (let i = 1; i < 6; i += 1) {
      expectAngle(t[i].phi, -120);
      expectAngle(t[i].psi, 130);
    }
  });

  it("puts each residue's angles on that residue, across the +-180 wrap and cis peptides", () => {
    const specs = [
      spec('ALA', 0, 150),
      spec('GLY', 80, -170),
      spec('PRO', -63, -42, 0),
      spec('LEU', -100, 179),
      spec('LYS', 60, 40),
      spec('SER', -179, -179),
      spec('THR', -75, 145),
      spec('VAL', -90, 0),
    ];
    const t = phiPsi(chainOf(pdbText(residuesOf(specs, buildChain(specs))), 'pdb'));
    for (let i = 1; i < specs.length - 1; i += 1) {
      expectAngle(t[i].phi, specs[i].phi);
      expectAngle(t[i].psi, specs[i].psi);
      expectAngle(t[i].omega, specs[i].omega ?? 180);
    }
    expectAngle(t[2].omega, 0);
  });

  it('takes phi, psi and omega over the atoms that define them', () => {
    // Bonded but crooked residues, so that swapping any atom for a neighbour changes the angle.
    const at = (N: V, CA: V, C: V): BackboneResidue => ({
      chain: 'A',
      position: 0,
      insertionCode: '',
      resName: 'ALA',
      oneLetter: 'A',
      bfactor: null,
      N,
      CA,
      C,
    });
    const r = [
      at([0, 0, 0], [1.4, 0.2, 0.1], [2.1, 1.4, -0.3]),
      at([3.3, 1.3, -0.2], [4.2, 2.3, 0.5], [5.6, 1.8, 0.9]),
      at([6.5, 2.6, 1.6], [7.9, 2.3, 2.0], [8.6, 3.4, 2.9]),
    ];
    const [, mid] = phiPsi(r);
    expect(mid.phi).toBeCloseTo(dihedral(r[0].C!, r[1].N!, r[1].CA!, r[1].C!), 9);
    expect(mid.psi).toBeCloseTo(dihedral(r[1].N!, r[1].CA!, r[1].C!, r[2].N!), 9);
    expect(mid.omega).toBeCloseTo(dihedral(r[0].CA!, r[0].C!, r[1].N!, r[1].CA!), 9);
  });

  it('reads an mmCIF the same way as the PDB', () => {
    const specs = ALA(6, -57, -47);
    const res = residuesOf(specs, buildChain(specs));
    const fromPdb = phiPsi(chainOf(pdbText(res), 'pdb'));
    const fromCif = phiPsi(chainOf(cifText([res]), 'mmcif'));
    expect(fromCif).toHaveLength(fromPdb.length);
    fromCif.forEach((t, i) => {
      expect(t.phi === null).toBe(fromPdb[i].phi === null);
      if (t.phi !== null) expectAngle(t.phi, fromPdb[i].phi as number, 1e-6);
      if (t.psi !== null) expectAngle(t.psi, fromPdb[i].psi as number, 1e-6);
    });
  });

  it('leaves the ends of a chain without the angles that would leave it', () => {
    const specs = ALA(5, -57, -47);
    const t = phiPsi(chainOf(pdbText(residuesOf(specs, buildChain(specs))), 'pdb'));
    expect(t[0].phi).toBeNull();
    expect(t[0].omega).toBeNull();
    expect(t[0].psi).not.toBeNull();
    expect(t[4].psi).toBeNull();
    expect(t[4].phi).not.toBeNull();
    expect(t[4].omega).not.toBeNull();
    expect(phiPsi([])).toEqual([]);
  });

  it('breaks at a gap in the chain, whatever the numbering says', () => {
    const first = ALA(4, -57, -47);
    const second = ALA(4, -60, -40);
    // The second piece sits 10 A away but is numbered straight on.
    const res = [
      ...residuesOf(first, buildChain(first)),
      ...residuesOf(second, buildChain(second, [10, 0, 0]), 'A', 5),
    ];
    const t = phiPsi(chainOf(pdbText(res), 'pdb'));
    expect(t[3].psi).toBeNull();
    expect(t[4].phi).toBeNull();
    expect(t[4].omega).toBeNull();
    expect(t[4].psi).not.toBeNull();
    expect(t[3].phi).not.toBeNull();
    expectAngle(t[5].phi, -60);
    expectAngle(t[2].psi, -47);
  });

  it('does not break at a numbering gap with intact geometry', () => {
    const specs = ALA(5, -57, -47);
    const res = residuesOf(specs, buildChain(specs));
    res[3].resi = 40;
    res[4].resi = 41;
    const t = phiPsi(chainOf(pdbText(res), 'pdb'));
    expectAngle(t[3].phi, -57);
    expectAngle(t[2].psi, -47);
  });

  it('gives null for the angles that need an atom the file lacks, and only those', () => {
    const specs = ALA(7, -57, -47);
    const missing = (atom: BackboneAtom) => {
      const res = residuesOf(specs, buildChain(specs));
      delete res[3].atoms[atom];
      return phiPsi(chainOf(pdbText(res), 'pdb'));
    };

    const noC = missing('C');
    expect(noC[3].phi).toBeNull();
    expect(noC[3].psi).toBeNull();
    expect(noC[3].omega).not.toBeNull();
    expect(noC[4].phi).toBeNull();
    expect(noC[4].omega).toBeNull();
    expect(noC[4].psi).not.toBeNull();
    expectAngle(noC[2].psi, -47);

    const noN = missing('N');
    expect(noN[3].phi).toBeNull();
    expect(noN[3].psi).toBeNull();
    expect(noN[3].omega).toBeNull();
    expect(noN[2].psi).toBeNull();
    expectAngle(noN[4].phi, -57);
    expectAngle(noN[4].omega, 180);

    const noCA = missing('CA');
    expect(noCA[3].phi).toBeNull();
    expect(noCA[3].psi).toBeNull();
    expect(noCA[3].omega).toBeNull();
    expect(noCA[4].omega).toBeNull();
    expectAngle(noCA[4].phi, -57);

    // The carbonyl oxygen takes part in no angle.
    const noO = missing('O');
    for (let i = 1; i < 6; i += 1) {
      expectAngle(noO[i].phi, -57);
      expectAngle(noO[i].psi, -47);
    }
  });
});

describe('isPeptideBonded', () => {
  const prev = { C: [0, 0, 0] as Vec3 };
  it('holds up to the peptide-bond limit and not beyond', () => {
    expect(PEPTIDE_BOND_MAX).toBe(2);
    expect(isPeptideBonded(prev, { N: [1.329, 0, 0] })).toBe(true);
    expect(isPeptideBonded(prev, { N: [2, 0, 0] })).toBe(true);
    expect(isPeptideBonded(prev, { N: [2.01, 0, 0] })).toBe(false);
  });

  it('needs both atoms', () => {
    expect(isPeptideBonded({}, { N: [1.3, 0, 0] })).toBe(false);
    expect(isPeptideBonded(prev, {})).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// residueClass
// ---------------------------------------------------------------------------

describe('residueClass', () => {
  const r = (oneLetter: string) => ({ oneLetter });

  it('names glycine, proline, the residue before a proline, and the rest', () => {
    expect(residueClass(r('G'), r('A'))).toBe('glycine');
    expect(residueClass(r('P'), r('A'))).toBe('proline');
    expect(residueClass(r('A'), r('P'))).toBe('pre_proline');
    expect(residueClass(r('A'), r('A'))).toBe('general');
    expect(residueClass(r('X'), r('G'))).toBe('general');
  });

  it('puts glycine and proline ahead of pre-proline, as MolProbity does', () => {
    expect(residueClass(r('G'), r('P'))).toBe('glycine');
    expect(residueClass(r('P'), r('P'))).toBe('proline');
  });

  it('is general at the end of a chain or across a break', () => {
    expect(residueClass(r('A'))).toBe('general');
    expect(residueClass(r('A'), null)).toBe('general');
    expect(residueClass(r('G'), null)).toBe('glycine');
  });
});

// ---------------------------------------------------------------------------
// parseBackbone
// ---------------------------------------------------------------------------

describe('parseBackbone: PDB', () => {
  it('reads the four backbone atoms, the names and the CA B-factor of each residue', () => {
    const specs = [spec('MET', 0, -40), spec('ARG', -60, -40), spec('GLY', -70, -30)];
    const atoms = buildChain(specs);
    const chains = parseBackbone(pdbText(residuesOf(specs, atoms)), 'pdb');
    expect(Array.from(chains.keys())).toEqual(['A']);
    const res = chains.get('A') as BackboneResidue[];
    expect(res.map((r) => `${r.position}${r.oneLetter}`)).toEqual(['1M', '2R', '3G']);
    expect(res.map((r) => r.resName)).toEqual(['MET', 'ARG', 'GLY']);
    expect(res.map((r) => r.bfactor)).toEqual([90, 89, 88]);
    expect(res.every((r) => r.insertionCode === '' && r.chain === 'A')).toBe(true);
    res.forEach((r, i) => {
      for (const k of ATOM_ORDER) expectNear(r[k], atoms[i][k]);
    });
  });

  it('keeps two chains apart, in order of appearance', () => {
    const specs = ALA(3, -57, -47);
    const a = residuesOf(specs, buildChain(specs), 'B');
    const b = residuesOf(specs, buildChain(specs, [20, 0, 0]), 'A');
    const chains = parseBackbone(pdbText([...a, ...b]), 'pdb');
    expect(Array.from(chains.keys())).toEqual(['B', 'A']);
    expect(chains.get('A')).toHaveLength(3);
    expectNear(chains.get('A')?.[0].N, [20, 0, 0]);
    expectNear(chains.get('B')?.[0].N, [0, 0, 0]);
  });

  it('reads a blank chain id as an empty one', () => {
    const specs = ALA(2, -57, -47);
    const chains = parseBackbone(pdbText(residuesOf(specs, buildChain(specs), ' ')), 'pdb');
    expect(Array.from(chains.keys())).toEqual(['']);
  });

  it('keeps the first alternate location and every atom of the residue from it', () => {
    const specs = ALA(3, -57, -47);
    const res = residuesOf(specs, buildChain(specs));
    const { N, CA, C, O } = res[1].atoms as Required<Atoms>;
    const moved = (p: V): V => [p[0] + 0.5, p[1], p[2]];
    // Residue 2: N plain; CA and C in conformer A, then B; O in B only.
    const mid = { ...res[1], atoms: {} };
    const at = (name4: string, alt: string, xyz: V, serial: number) =>
      pdbLine(serial, name4, alt, mid, xyz, 'ATOM  ');
    const lines = [
      ...pdbBlock([res[0]]),
      at(NAME4.N, ' ', N, 101),
      at(NAME4.CA, 'A', CA, 102),
      at(NAME4.CA, 'B', moved(CA), 103),
      at(NAME4.C, 'A', C, 104),
      at(NAME4.C, 'B', moved(C), 105),
      at(NAME4.O, 'B', O, 106),
      ...pdbBlock([res[2]]),
    ];
    const parsed = parseBackbone(lines.join('\n'), 'pdb').get('A') as BackboneResidue[];
    expect(parsed).toHaveLength(3);
    expectNear(parsed[1].N, N);
    expectNear(parsed[1].CA, CA);
    expectNear(parsed[1].C, C);
    // O is only in the second conformer, which is not the one kept.
    expect(parsed[1].O).toBeUndefined();
  });

  it('keeps the first conformer even when it is not labelled A', () => {
    const specs = ALA(1, -57, -47);
    const [atoms] = buildChain(specs);
    const r: Res = { resn: 'ALA', chain: 'A', resi: 1, atoms: {} };
    const lines = [
      pdbLine(1, NAME4.CA, 'B', r, atoms.CA!, 'ATOM  '),
      pdbLine(2, NAME4.CA, 'C', r, [9, 9, 9], 'ATOM  '),
    ];
    expectNear(parseBackbone(lines.join('\n'), 'pdb').get('A')?.[0].CA, atoms.CA);
  });

  it('tells an insertion code from the residue it follows, and keeps file order', () => {
    const specs = ALA(4, -57, -47);
    const res = residuesOf(specs, buildChain(specs));
    res[0].resi = 51;
    res[1].resi = 52;
    res[2].resi = 52;
    res[2].ins = 'A';
    res[3].resi = 53;
    const parsed = parseBackbone(pdbText(res), 'pdb').get('A') as BackboneResidue[];
    expect(parsed.map((r) => `${r.position}${r.insertionCode}`)).toEqual(['51', '52', '52A', '53']);
    // Phi/psi run through the insertion: the geometry is intact.
    expectAngle(phiPsi(parsed)[2].phi, -57);
  });

  it('keeps selenomethionine and skips waters, ions and ligands', () => {
    const specs = ALA(3, -57, -47);
    const res = residuesOf(specs, buildChain(specs));
    res[1].resn = 'MSE';
    res[1].hetatm = true;
    const extra: Res[] = [
      { resn: 'HOH', chain: 'A', resi: 301, atoms: { O: [30, 30, 30] }, hetatm: true },
      { resn: 'CA', chain: 'A', resi: 302, atoms: { CA: [31, 31, 31] }, hetatm: true },
      {
        resn: 'GOL',
        chain: 'A',
        resi: 303,
        atoms: { C: [32, 32, 32], O: [33, 33, 33] },
        hetatm: true,
      },
    ];
    // The calcium ion's atom is called CA, in the columns of an element name.
    const ion = pdbLine(900, 'CA  ', ' ', extra[1], [31, 31, 31], 'HETATM', ' CA');
    const text = [...pdbBlock([res[0], res[1], res[2], extra[0], extra[2]]), ion].join('\n');
    const parsed = parseBackbone(text, 'pdb').get('A') as BackboneResidue[];
    expect(parsed.map((r) => `${r.position}${r.oneLetter}`)).toEqual(['1A', '2M', '3A']);
    expect(parsed[1].resName).toBe('MSE');
  });

  it('reads the first model only', () => {
    const specs = ALA(3, -57, -47);
    const one = residuesOf(specs, buildChain(specs));
    const two = residuesOf(specs, buildChain(specs, [50, 0, 0]));
    const extra = residuesOf(specs, buildChain(specs), 'Z');
    const chains = parseBackbone(pdbText(one, [...two, ...extra]), 'pdb');
    expect(Array.from(chains.keys())).toEqual(['A']);
    expectNear(chains.get('A')?.[0].N, [0, 0, 0]);
  });

  it('lists the same residues as the CA-only reader', () => {
    const specs = [
      spec('MET', 0, -40),
      spec('ARG', -60, -40),
      spec('MSE', -70, -30),
      spec('GLY', -80, 0),
    ];
    const res = residuesOf(specs, buildChain(specs));
    res[2].hetatm = true;
    res[3].ins = 'B';
    const text = pdbText(res);
    const bb = Array.from(parseBackbone(text, 'pdb').values())
      .flat()
      .filter((r) => r.CA);
    const ca = parseResidues(text, 'pdb');
    expect(
      bb.map((r) => [r.chain, r.position, r.insertionCode, r.resName, r.oneLetter, r.bfactor]),
    ).toEqual(ca.map((r) => [r.chain, r.position, r.insertion, r.resn, r.aa, r.bfactor]));
  });

  it('is empty for text with no atoms', () => {
    expect(parseBackbone('HEADER    NOTHING\nEND', 'pdb').size).toBe(0);
    expect(parseBackbone('', 'pdb').size).toBe(0);
  });
});

describe('parseBackbone: mmCIF', () => {
  it('reads the same coordinates and names as the PDB of the same model', () => {
    const specs = [spec('MET', 0, -40), spec('ARG', -60, -40), spec('GLY', -70, -30)];
    const res = residuesOf(specs, buildChain(specs));
    const pdb = parseBackbone(pdbText(res), 'pdb').get('A') as BackboneResidue[];
    const cif = parseBackbone(cifText([res]), 'mmcif').get('A') as BackboneResidue[];
    expect(cif).toHaveLength(pdb.length);
    cif.forEach((r, i) => {
      expect([r.chain, r.position, r.insertionCode, r.resName, r.oneLetter, r.bfactor]).toEqual([
        pdb[i].chain,
        pdb[i].position,
        pdb[i].insertionCode,
        pdb[i].resName,
        pdb[i].oneLetter,
        pdb[i].bfactor,
      ]);
      for (const k of ATOM_ORDER) expectNear(r[k], pdb[i][k]);
    });
  });

  it('uses the label columns where the file has no author ones', () => {
    const specs = ALA(3, -57, -47);
    const res = residuesOf(specs, buildChain(specs), 'C', 7);
    const chains = parseBackbone(cifText([res], { label: true }), 'mmcif');
    expect(Array.from(chains.keys())).toEqual(['C']);
    expect(chains.get('C')?.map((r) => r.position)).toEqual([7, 8, 9]);
  });

  it('keeps two chains, insertion codes and the first alternate location', () => {
    const specs = ALA(3, -57, -47);
    const a = residuesOf(specs, buildChain(specs), 'A', 51);
    a[2].ins = 'A';
    a[2].resi = 52;
    a[1].resi = 52;
    const original = a[1].atoms.CA as V;
    a[1].alts = [
      ['A', { CA: original }],
      ['B', { CA: [original[0] + 1, original[1], original[2]] }],
    ];
    delete a[1].atoms.CA;
    const b = residuesOf(specs, buildChain(specs, [30, 0, 0]), 'B');
    const chains = parseBackbone(cifText([[...a, ...b]]), 'mmcif');
    expect(Array.from(chains.keys())).toEqual(['A', 'B']);
    const first = chains.get('A') as BackboneResidue[];
    expect(first.map((r) => `${r.position}${r.insertionCode}`)).toEqual(['51', '52', '52A']);
    expectNear(first[1].CA, original);
    expectNear(chains.get('B')?.[0].N, [30, 0, 0]);
  });

  it('reads the first model only', () => {
    const specs = ALA(3, -57, -47);
    const one = residuesOf(specs, buildChain(specs));
    const two = residuesOf(specs, buildChain(specs, [50, 0, 0]));
    const extra = residuesOf(specs, buildChain(specs), 'Z');
    const chains = parseBackbone(cifText([one, [...two, ...extra]]), 'mmcif');
    expect(Array.from(chains.keys())).toEqual(['A']);
    expect(chains.get('A')).toHaveLength(3);
    expectNear(chains.get('A')?.[0].N, [0, 0, 0]);
  });

  it('keeps selenomethionine and skips waters and ligands', () => {
    const specs = ALA(3, -57, -47);
    const res = residuesOf(specs, buildChain(specs));
    res[1].resn = 'MSE';
    res[1].hetatm = true;
    const extra: Res[] = [
      { resn: 'HOH', chain: 'A', resi: 301, atoms: { O: [30, 30, 30] }, hetatm: true },
      { resn: 'GOL', chain: 'A', resi: 302, atoms: { C: [32, 32, 32] }, hetatm: true },
    ];
    const parsed = parseBackbone(cifText([[...res, ...extra]]), 'mmcif').get(
      'A',
    ) as BackboneResidue[];
    expect(parsed.map((r) => `${r.position}${r.oneLetter}`)).toEqual(['1A', '2M', '3A']);
  });

  it('lists the same residues as the CA-only reader', () => {
    const specs = [spec('MET', 0, -40), spec('ARG', -60, -40), spec('GLY', -70, -30)];
    const res = residuesOf(specs, buildChain(specs));
    res[2].ins = 'A';
    const text = cifText([res]);
    const bb = Array.from(parseBackbone(text, 'mmcif').values()).flat();
    const ca = parseResidues(text, 'mmcif');
    expect(bb.map((r) => [r.chain, r.position, r.insertionCode, r.oneLetter, r.bfactor])).toEqual(
      ca.map((r) => [r.chain, r.position, r.insertion, r.aa, r.bfactor]),
    );
  });

  it('is empty without an atom_site loop or without coordinates', () => {
    expect(parseBackbone('data_x\n#\n', 'mmcif').size).toBe(0);
    const noXyz = [
      'data_x',
      'loop_',
      '_atom_site.group_PDB',
      '_atom_site.label_atom_id',
      '_atom_site.label_comp_id',
      '_atom_site.auth_asym_id',
      '_atom_site.auth_seq_id',
      'ATOM CA ALA A 1',
    ].join('\n');
    expect(parseBackbone(noXyz, 'mmcif').size).toBe(0);
  });
});
