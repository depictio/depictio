/**
 * Structure files as text: format detection, the structure flavour of the
 * shared per-object loader (`objectText`: gzip, a memory cache keyed on the
 * object path, URL renewal), and a light CA-only parser for PDB and mmCIF.
 *
 * The parser is not a second structure reader beside 3Dmol. It reads one line
 * per residue (the alpha carbon) so the renderer knows the structure's own
 * sequence and numbering before, and without, a WebGL context: the numbering
 * check of the variant marks, the tooltip, the embedded sequence strip and the
 * N-to-C spectrum all need it, and a tile that lost its GL slot still shows
 * them.
 */

import {
  clearObjectCache,
  decodeObjectBytes,
  loadObjectText,
  loadObjectTextRenewing,
  objectCacheKey,
  ObjectFileError,
  type ObjectLoadOptions,
} from './objectText';

export type StructureFormat = 'pdb' | 'mmcif';

/** One residue of the structure, read from its alpha carbon. */
export interface StructureResidue {
  chain: string;
  /** Author residue number (what 3Dmol calls `resi`). */
  position: number;
  /** Insertion code, '' when none. */
  insertion: string;
  /** Three-letter residue name as written in the file. */
  resn: string;
  /** One-letter code, 'X' for anything non-standard. */
  aa: string;
  /** B-factor column (pLDDT in AlphaFold and ESMFold models), null when absent. */
  bfactor: number | null;
}

const THREE_TO_ONE: Record<string, string> = {
  ALA: 'A',
  ARG: 'R',
  ASN: 'N',
  ASP: 'D',
  CYS: 'C',
  GLN: 'Q',
  GLU: 'E',
  GLY: 'G',
  HIS: 'H',
  ILE: 'I',
  LEU: 'L',
  LYS: 'K',
  MET: 'M',
  PHE: 'F',
  PRO: 'P',
  SER: 'S',
  THR: 'T',
  TRP: 'W',
  TYR: 'Y',
  VAL: 'V',
  // Modified or protonation-state names a model file commonly carries.
  MSE: 'M',
  SEC: 'U',
  PYL: 'O',
  HID: 'H',
  HIE: 'H',
  HIP: 'H',
  HSD: 'H',
  HSE: 'H',
  CYX: 'C',
  ASX: 'B',
  GLX: 'Z',
};

/** One-letter code for a residue name: three-letter names are converted,
 *  one-letter codes pass through upper-cased, anything else is 'X'. */
export function toOneLetter(name: string | null | undefined): string {
  if (!name) return 'X';
  const n = String(name).trim().toUpperCase();
  if (n.length === 1) return n;
  return THREE_TO_ONE[n] ?? 'X';
}

/** Whether a residue name is an amino acid the parsers know (standard, modified
 *  or a protonation-state name). HETATM records are kept only for these, never
 *  for ligands, waters or ions. */
export function isAminoAcidName(name: string | null | undefined): boolean {
  return Boolean(name && THREE_TO_ONE[String(name).trim().toUpperCase()]);
}

/** mmCIF opens with a `data_` block (or a bare `_category.item`); anything
 *  else is read as PDB. A file name, when known, wins over sniffing. */
export function sniffFormat(text: string, nameHint?: string | null): StructureFormat {
  const name = (nameHint ?? '').toLowerCase().replace(/\.gz$/, '');
  if (name.endsWith('.cif') || name.endsWith('.mmcif')) return 'mmcif';
  if (name.endsWith('.pdb') || name.endsWith('.ent')) return 'pdb';
  const head = text.slice(0, 2000).trimStart();
  return head.startsWith('data_') || head.startsWith('_') || head.startsWith('loop_')
    ? 'mmcif'
    : 'pdb';
}

export { isGzip } from './objectText';

/** The `objectText` cache namespace of structure files. */
export const STRUCTURE_CACHE_NAMESPACE = 'structure';

/** What error messages call a structure file. */
const STRUCTURE_NOUN = 'structure';

/** Raw bytes to text, gunzipping when the bytes say so (whatever the name says). */
export function decodeStructureBytes(bytes: Uint8Array): Promise<string> {
  return decodeObjectBytes(bytes, STRUCTURE_NOUN);
}

/**
 * The cache key of a URL: the URL without its query string (see
 * `objectCacheKey`).
 */
export const structureCacheKey = objectCacheKey;

export interface LoadedStructure {
  text: string;
  format: StructureFormat;
}

/** A structure download the object store refused, with its HTTP status. */
export class StructureFileError extends ObjectFileError {
  constructor(status: number) {
    super(status, STRUCTURE_NOUN);
    this.name = 'StructureFileError';
  }
}

function structureLoadOptions(opts: {
  nameHint?: string | null;
  fetcher?: (url: string) => Promise<Response>;
}): ObjectLoadOptions<LoadedStructure> {
  return {
    cacheNamespace: STRUCTURE_CACHE_NAMESPACE,
    noun: STRUCTURE_NOUN,
    nameHint: opts.nameHint,
    fetcher: opts.fetcher,
    errorFor: (status) => new StructureFileError(status),
    parse: (text, { key, nameHint }) => ({ text, format: sniffFormat(text, nameHint ?? key) }),
  };
}

/**
 * Fetch a structure once per object and keep it in memory (the shared
 * per-object cache of `objectText`, namespace `"structure"`): two tiles asking
 * for the same model share one download, a failed load is evicted so a retry
 * fetches again.
 */
export function loadStructureText(
  url: string,
  opts: { nameHint?: string | null; fetcher?: (url: string) => Promise<Response> } = {},
): Promise<LoadedStructure> {
  return loadObjectText(url, structureLoadOptions(opts));
}

/**
 * `loadStructureText`, asking once for a new URL when the object store answers
 * 403: a presigned URL past its expiry (15 minutes) is refused that way, and
 * the manifest it came from signs a fresh one. Any other failure, a renewal
 * that gives nothing or the same URL, or a second refusal is thrown as is.
 */
export function loadStructureTextRenewing(
  url: string,
  opts: {
    nameHint?: string | null;
    fetcher?: (url: string) => Promise<Response>;
    renew?: (() => Promise<string | null>) | null;
  } = {},
): Promise<LoadedStructure> {
  return loadObjectTextRenewing(url, { ...structureLoadOptions(opts), renew: opts.renew });
}

/** Test hook: forget every cached structure (other namespaces are left alone). */
export function clearStructureCache(): void {
  clearObjectCache(STRUCTURE_CACHE_NAMESPACE);
}

/** A numeric field, null when blank, `.`/`?` (mmCIF's unknown) or not a number. */
export function parseNumber(s: string): number | null {
  const t = s.trim();
  if (!t || t === '.' || t === '?') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** Residues of the first model of a PDB file, one per alpha carbon. */
function parsePdbResidues(text: string): StructureResidue[] {
  const out: StructureResidue[] = [];
  const seen = new Set<string>();
  for (const line of text.split(/\r?\n/)) {
    if (line.startsWith('ENDMDL')) break;
    const record = line.slice(0, 6);
    if (record !== 'ATOM  ' && record !== 'HETATM') continue;
    if (line.slice(12, 16).trim() !== 'CA') continue;
    const resn = line.slice(17, 20).trim();
    // HETATM alpha carbons are kept only for residues that are amino acids
    // (selenomethionine), never for ligands or ions named CA (calcium).
    if (record === 'HETATM' && !isAminoAcidName(resn)) continue;
    const position = parseNumber(line.slice(22, 26));
    if (position === null) continue;
    const chain = line.slice(21, 22).trim();
    const insertion = line.slice(26, 27).trim();
    const key = `${chain}:${position}:${insertion}`;
    // Alternate locations repeat the CA: the first one wins.
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      chain,
      position,
      insertion,
      resn,
      aa: toOneLetter(resn),
      bfactor: line.length >= 66 ? parseNumber(line.slice(60, 66)) : null,
    });
  }
  return out;
}

/** Split one mmCIF data line into tokens, honouring single and double quotes. */
export function tokenizeCifLine(line: string): string[] {
  const out: string[] = [];
  let i = 0;
  const n = line.length;
  while (i < n) {
    while (i < n && (line[i] === ' ' || line[i] === '\t')) i += 1;
    if (i >= n) break;
    const c = line[i];
    if (c === "'" || c === '"') {
      // A quote closes only when followed by whitespace or the end of line.
      let j = i + 1;
      while (j < n && !(line[j] === c && (j + 1 === n || /\s/.test(line[j + 1])))) j += 1;
      out.push(line.slice(i + 1, j));
      i = j + 1;
    } else {
      let j = i;
      while (j < n && line[j] !== ' ' && line[j] !== '\t') j += 1;
      out.push(line.slice(i, j));
      i = j;
    }
  }
  return out;
}

/** Residues of the first model of an mmCIF file, from its `_atom_site` loop.
 *  Author numbering and chain ids first, like 3Dmol's own CIF reader. */
function parseCifResidues(text: string): StructureResidue[] {
  const lines = text.split(/\r?\n/);
  let i = 0;
  // Find the loop whose first header is _atom_site.*
  while (i < lines.length) {
    if (lines[i].trim() === 'loop_' && lines[i + 1]?.trim().startsWith('_atom_site.')) break;
    i += 1;
  }
  if (i >= lines.length) return [];
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
  const cB = col('B_iso_or_equiv');
  const cModel = col('pdbx_PDB_model_num');
  if (cAtom < 0 || cResn < 0 || cSeq < 0) return [];

  const out: StructureResidue[] = [];
  const seen = new Set<string>();
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
    if (t[cAtom].replace(/"/g, '') !== 'CA') continue;
    const resn = t[cResn];
    if (cGroup >= 0 && t[cGroup] === 'HETATM' && !isAminoAcidName(resn)) continue;
    const position = parseNumber(t[cSeq]);
    if (position === null) continue;
    const chain = cChain >= 0 ? t[cChain] : '';
    const insRaw = cIns >= 0 ? t[cIns] : '';
    const insertion = insRaw === '?' || insRaw === '.' ? '' : insRaw;
    const key = `${chain}:${position}:${insertion}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      chain,
      position,
      insertion,
      resn,
      aa: toOneLetter(resn),
      bfactor: cB >= 0 ? parseNumber(t[cB]) : null,
    });
  }
  return out;
}

/** The residues of a structure's first model, in file order. */
export function parseResidues(text: string, format: StructureFormat): StructureResidue[] {
  return format === 'mmcif' ? parseCifResidues(text) : parsePdbResidues(text);
}

/** Residue lookup key; chain may be '' for single-chain files. */
export function residueKey(chain: string | null | undefined, position: number): string {
  return `${chain ?? ''}:${position}`;
}
