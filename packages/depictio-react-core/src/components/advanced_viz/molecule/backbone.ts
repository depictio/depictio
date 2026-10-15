/**
 * Protein backbone from a structure file: the N, CA, C and O atoms of every
 * residue of the first model, and the torsion angles they define.
 *
 * This is the sibling of the CA-only reader in `structureText.ts` and follows
 * its conventions so the two agree residue for residue: author numbering and
 * chain ids (the label columns of an mmCIF only where the author ones are
 * absent), insertion codes kept apart, HETATM records kept only for amino
 * acids (selenomethionine is a residue, a calcium ion is not), residue names
 * turned into one-letter codes by the same table, the first model only.
 * Alternate locations: the first one met in a residue wins, so every atom of a
 * residue comes from one conformer.
 *
 * Distances are in angstroms, angles in degrees.
 */

import {
  isAminoAcidName,
  parseNumber,
  tokenizeCifLine,
  toOneLetter,
  type StructureFormat,
} from './structureText';

export type Vec3 = readonly [number, number, number];

/** The backbone atoms read, by PDB atom name. */
export type BackboneAtom = 'N' | 'CA' | 'C' | 'O';

const BACKBONE_ATOMS: readonly BackboneAtom[] = ['N', 'CA', 'C', 'O'];

/** One residue of a chain with the backbone atoms the file gives it. */
export interface BackboneResidue {
  chain: string;
  /** Author residue number. */
  position: number;
  /** Insertion code, '' when none. */
  insertionCode: string;
  /** Residue name as written in the file. */
  resName: string;
  /** One-letter code, 'X' for anything non-standard. */
  oneLetter: string;
  /** B-factor of the alpha carbon (pLDDT in predicted models), null when absent. */
  bfactor: number | null;
  N?: Vec3;
  CA?: Vec3;
  C?: Vec3;
  O?: Vec3;
}

/** Residues of each chain in file order, chains in order of first appearance. */
export type BackboneChains = Map<string, BackboneResidue[]>;

interface AtomRecord {
  chain: string;
  position: number;
  insertionCode: string;
  resName: string;
  atom: BackboneAtom;
  /** Alternate-location label, '' for none. */
  alt: string;
  xyz: Vec3;
  bfactor: number | null;
}

/** Gathers backbone atoms into residues, applying the one-conformer rule. */
class BackboneCollector {
  private readonly chains: BackboneChains = new Map();

  /** Per residue: the first alternate-location label met, if any. */
  private readonly conformer = new Map<BackboneResidue, string>();

  private readonly byKey = new Map<string, BackboneResidue>();

  add(rec: AtomRecord): void {
    const key = `${rec.chain}:${rec.position}:${rec.insertionCode}`;
    let res = this.byKey.get(key);
    if (!res) {
      res = {
        chain: rec.chain,
        position: rec.position,
        insertionCode: rec.insertionCode,
        resName: rec.resName,
        oneLetter: toOneLetter(rec.resName),
        bfactor: null,
      };
      this.byKey.set(key, res);
      let list = this.chains.get(rec.chain);
      if (!list) {
        list = [];
        this.chains.set(rec.chain, list);
      }
      list.push(res);
    }
    if (rec.alt) {
      const first = this.conformer.get(res);
      if (first === undefined) this.conformer.set(res, rec.alt);
      else if (first !== rec.alt) return;
    }
    if (res[rec.atom]) return;
    res[rec.atom] = rec.xyz;
    if (rec.atom === 'CA') res.bfactor = rec.bfactor;
  }

  result(): BackboneChains {
    return this.chains;
  }
}

function isBackboneAtom(name: string): name is BackboneAtom {
  return (BACKBONE_ATOMS as readonly string[]).includes(name);
}

function coords(x: number | null, y: number | null, z: number | null): Vec3 | null {
  return x === null || y === null || z === null ? null : [x, y, z];
}

/** Backbone of the first model of a PDB file (fixed columns). */
function parsePdbBackbone(text: string): BackboneChains {
  const out = new BackboneCollector();
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith('ENDMDL')) break;
    const record = line.slice(0, 6);
    if (record !== 'ATOM  ' && record !== 'HETATM') continue;
    const atom = line.slice(12, 16).trim();
    if (!isBackboneAtom(atom)) continue;
    const resName = line.slice(17, 20).trim();
    if (record === 'HETATM' && !isAminoAcidName(resName)) continue;
    const position = parseNumber(line.slice(22, 26));
    if (position === null) continue;
    const xyz = coords(
      parseNumber(line.slice(30, 38)),
      parseNumber(line.slice(38, 46)),
      parseNumber(line.slice(46, 54)),
    );
    if (!xyz) continue;
    out.add({
      chain: line.slice(21, 22).trim(),
      position,
      insertionCode: line.slice(26, 27).trim(),
      resName,
      atom,
      alt: line.slice(16, 17).trim(),
      xyz,
      bfactor: line.length >= 66 ? parseNumber(line.slice(60, 66)) : null,
    });
  }
  return out.result();
}

/** Backbone of the first model of an mmCIF file, from its `_atom_site` loop. */
function parseCifBackbone(text: string): BackboneChains {
  const out = new BackboneCollector();
  const lines = text.split(/\r?\n/);
  let i = 0;
  while (i < lines.length) {
    if (lines[i].trim() === 'loop_' && lines[i + 1]?.trim().startsWith('_atom_site.')) break;
    i += 1;
  }
  if (i >= lines.length) return out.result();
  i += 1;
  const headers: string[] = [];
  while (i < lines.length && lines[i].trim().startsWith('_atom_site.')) {
    headers.push(lines[i].trim().split(/\s+/)[0].slice('_atom_site.'.length));
    i += 1;
  }
  const col = (name: string) => headers.indexOf(name);
  // The author column when the file has it, else the label one.
  const authOrLabel = (item: string) =>
    col(`auth_${item}`) >= 0 ? col(`auth_${item}`) : col(`label_${item}`);
  const cGroup = col('group_PDB');
  const cAtom = authOrLabel('atom_id');
  const cResn = authOrLabel('comp_id');
  const cChain = authOrLabel('asym_id');
  const cSeq = authOrLabel('seq_id');
  const cIns = col('pdbx_PDB_ins_code');
  const cAlt = col('label_alt_id');
  const cB = col('B_iso_or_equiv');
  const cModel = col('pdbx_PDB_model_num');
  const cX = col('Cartn_x');
  const cY = col('Cartn_y');
  const cZ = col('Cartn_z');
  if (cAtom < 0 || cResn < 0 || cSeq < 0 || cX < 0 || cY < 0 || cZ < 0) return out.result();

  const blank = (v: string) => (v === '?' || v === '.' ? '' : v);
  let firstModel: string | null = null;
  let buffer: string[] = [];
  for (; i < lines.length; i += 1) {
    const raw = lines[i];
    const trimmed = raw.trim();
    if (!trimmed) continue;
    if (
      trimmed === '#' ||
      trimmed === 'loop_' ||
      trimmed.startsWith('_') ||
      trimmed.startsWith('data_')
    ) {
      break;
    }
    buffer = buffer.concat(tokenizeCifLine(raw));
    if (buffer.length < headers.length) continue;
    const t = buffer.slice(0, headers.length);
    buffer = buffer.slice(headers.length);
    if (cModel >= 0) {
      if (firstModel === null) firstModel = t[cModel];
      else if (t[cModel] !== firstModel) break;
    }
    const atom = t[cAtom].replace(/"/g, '');
    if (!isBackboneAtom(atom)) continue;
    const resName = t[cResn];
    if (cGroup >= 0 && t[cGroup] === 'HETATM' && !isAminoAcidName(resName)) continue;
    const position = parseNumber(t[cSeq]);
    if (position === null) continue;
    const xyz = coords(parseNumber(t[cX]), parseNumber(t[cY]), parseNumber(t[cZ]));
    if (!xyz) continue;
    out.add({
      chain: cChain >= 0 ? t[cChain] : '',
      position,
      insertionCode: cIns >= 0 ? blank(t[cIns]) : '',
      resName,
      atom,
      alt: cAlt >= 0 ? blank(t[cAlt]) : '',
      xyz,
      bfactor: cB >= 0 ? parseNumber(t[cB]) : null,
    });
  }
  return out.result();
}

/**
 * The backbone atoms of a structure's first model, per chain.
 *
 * A residue is listed once it has any of N, CA, C or O; the atoms a file
 * leaves out are simply absent. Chains keep their file order, and so do the
 * residues within them, whatever their numbers.
 */
export function parseBackbone(text: string, format: StructureFormat): BackboneChains {
  return format === 'mmcif' ? parseCifBackbone(text) : parsePdbBackbone(text);
}

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

const RAD_TO_DEG = 180 / Math.PI;

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];

/** Smallest squared length, in squared angstroms, still read as a direction. */
const MIN_LENGTH_SQ = 1e-12;

/**
 * The torsion angle of four points, in degrees in (-180, 180].
 *
 * IUPAC sign: looking from `b` to `c`, a positive angle turns the bond `a-b`
 * clockwise onto the bond `c-d`. A right-handed alpha helix has phi about -57
 * and psi about -47. `NaN` when the points do not define one: a zero-length
 * bond, or `a` or `d` on the line through `b` and `c`.
 */
export function dihedral(a: Vec3, b: Vec3, c: Vec3, d: Vec3): number {
  const b0 = sub(a, b);
  const axis = sub(c, b);
  const b2 = sub(d, c);
  const axisLenSq = dot(axis, axis);
  if (!(axisLenSq > MIN_LENGTH_SQ)) return NaN;
  // The parts of the two outer bonds that are perpendicular to the axis.
  const k0 = dot(b0, axis) / axisLenSq;
  const k2 = dot(b2, axis) / axisLenSq;
  const v: Vec3 = [b0[0] - k0 * axis[0], b0[1] - k0 * axis[1], b0[2] - k0 * axis[2]];
  const w: Vec3 = [b2[0] - k2 * axis[0], b2[1] - k2 * axis[1], b2[2] - k2 * axis[2]];
  if (!(dot(v, v) > MIN_LENGTH_SQ) || !(dot(w, w) > MIN_LENGTH_SQ)) return NaN;
  const x = dot(v, w);
  // cross(axis, v) . w, with the axis unit length folded into the scale of atan2.
  const y = dot(cross(axis, v), w) / Math.sqrt(axisLenSq);
  const deg = Math.atan2(y, x) * RAD_TO_DEG;
  // atan2 of a negative zero returns -pi: the interval is open at -180.
  return deg <= -180 ? deg + 360 : deg;
}

/** Longest C(i-1)-N(i) distance, in angstroms, still read as a peptide bond
 *  (the bond is 1.33; a gap in the chain is several times that). */
export const PEPTIDE_BOND_MAX = 2.0;

/** Whether `next` follows `prev` through a peptide bond: both atoms exist and
 *  are within `PEPTIDE_BOND_MAX`. A numbering gap with intact geometry is bonded;
 *  a missing atom or a gap in the chain is not. */
export function isPeptideBonded(
  prev: Pick<BackboneResidue, 'C'>,
  next: Pick<BackboneResidue, 'N'>,
): boolean {
  if (!prev.C || !next.N) return false;
  const d = sub(prev.C, next.N);
  return Math.sqrt(dot(d, d)) <= PEPTIDE_BOND_MAX;
}

/** The backbone torsions of one residue, null where undefined. */
export interface BackboneTorsions {
  /** C(i-1), N(i), CA(i), C(i). */
  phi: number | null;
  /** N(i), CA(i), C(i), N(i+1). */
  psi: number | null;
  /** CA(i-1), C(i-1), N(i), CA(i): about 180 for a trans peptide, about 0 for cis. */
  omega: number | null;
}

function torsion(
  a: Vec3 | undefined,
  b: Vec3 | undefined,
  c: Vec3 | undefined,
  d: Vec3 | undefined,
): number | null {
  if (!a || !b || !c || !d) return null;
  const t = dihedral(a, b, c, d);
  return Number.isFinite(t) ? t : null;
}

/**
 * Phi, psi and omega of every residue of one chain, in the order given.
 *
 * `residues` is one chain in order (a value of `parseBackbone`). The angles of
 * a residue that would span a missing atom or a chain break (see
 * `isPeptideBonded`) are null, and so are phi and omega of the first residue
 * and psi of the last.
 */
export function phiPsi(residues: readonly BackboneResidue[]): BackboneTorsions[] {
  return residues.map((res, i) => {
    const prev = i > 0 && isPeptideBonded(residues[i - 1], res) ? residues[i - 1] : undefined;
    const next =
      i + 1 < residues.length && isPeptideBonded(res, residues[i + 1])
        ? residues[i + 1]
        : undefined;
    return {
      phi: torsion(prev?.C, res.N, res.CA, res.C),
      psi: torsion(res.N, res.CA, res.C, next?.N),
      omega: torsion(prev?.CA, prev?.C, res.N, res.CA),
    };
  });
}

/** The classes of the Ramachandran distributions (MolProbity's four). */
export type ResidueClass = 'general' | 'glycine' | 'proline' | 'pre_proline';

/**
 * The Ramachandran class of a residue: glycine, proline, a residue that
 * precedes a proline, or general. Glycine and proline come first, as in
 * MolProbity, so a glycine before a proline is a glycine. Pass `next` as
 * null where the following residue is not bonded to this one (a chain break).
 */
export function residueClass(
  res: Pick<BackboneResidue, 'oneLetter'>,
  next?: Pick<BackboneResidue, 'oneLetter'> | null,
): ResidueClass {
  if (res.oneLetter === 'G') return 'glycine';
  if (res.oneLetter === 'P') return 'proline';
  if (next?.oneLetter === 'P') return 'pre_proline';
  return 'general';
}
