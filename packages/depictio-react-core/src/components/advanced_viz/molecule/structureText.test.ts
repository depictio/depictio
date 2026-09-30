import { gzipSync } from 'node:zlib';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  clearStructureCache,
  decodeStructureBytes,
  isGzip,
  loadStructureText,
  loadStructureTextRenewing,
  parseResidues,
  sniffFormat,
  structureCacheKey,
  toOneLetter,
  tokenizeCifLine,
} from './structureText';

// Fixed-column PDB records (columns matter: the parser slices them).
function atom(
  serial: number,
  name: string,
  resn: string,
  chain: string,
  resi: number,
  b: number,
  record = 'ATOM  ',
  alt = ' ',
): string {
  return (
    record +
    String(serial).padStart(5) +
    ' ' +
    name.padEnd(4).slice(0, 4) +
    alt +
    resn.padStart(3) +
    ' ' +
    chain +
    String(resi).padStart(4) +
    ' ' +
    '   ' +
    '   1.000   2.000   3.000' +
    '  1.00' +
    b.toFixed(2).padStart(6) +
    '           C'
  );
}

const PDB = [
  'HEADER    TEST',
  atom(1, ' N  ', 'MET', 'A', 1, 91.2),
  atom(2, ' CA ', 'MET', 'A', 1, 91.2),
  atom(3, ' CA ', 'ARG', 'A', 2, 65.4),
  atom(4, ' CA ', 'ARG', 'A', 2, 65.4, 'ATOM  ', 'B'),
  atom(5, ' CA ', 'MSE', 'A', 3, 40.0, 'HETATM'),
  atom(6, 'CA  ', ' CA', 'A', 900, 10.0, 'HETATM'),
  atom(7, ' CA ', 'GLY', 'B', 1, 80.0),
  'ENDMDL',
  atom(8, ' CA ', 'LYS', 'A', 4, 50.0),
].join('\n');

const CIF = `data_test
#
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.B_iso_or_equiv
_atom_site.pdbx_PDB_model_num
ATOM 1 N MET A 10 ? 88.5 1
ATOM 2 CA MET A 10 ? 88.5 1
ATOM 3 CA TRP A 11 ? 72.0 1
HETATM 4 CA HOH A 500 ? 5.0 1
ATOM 5 CA ALA A 12 A 60.0 1
ATOM 6 CA ALA A 10 ? 1.0 2
#
`;

describe('format and encoding', () => {
  it('sniffs mmCIF from its data block and PDB otherwise', () => {
    expect(sniffFormat('data_1abc\n#')).toBe('mmcif');
    expect(sniffFormat('HEADER x\nATOM')).toBe('pdb');
    expect(sniffFormat('HEADER x', 'model.cif.gz')).toBe('mmcif');
    expect(sniffFormat('data_x', 'model.pdb')).toBe('pdb');
  });

  it('gunzips by magic number, whatever the name says', async () => {
    const gz = new Uint8Array(gzipSync(Buffer.from(PDB)));
    expect(isGzip(gz)).toBe(true);
    expect(await decodeStructureBytes(gz)).toBe(PDB);
    expect(await decodeStructureBytes(new TextEncoder().encode('ATOM'))).toBe('ATOM');
  });

  it('converts residue names to one-letter codes', () => {
    expect(toOneLetter('ARG')).toBe('R');
    expect(toOneLetter('mse')).toBe('M');
    expect(toOneLetter('r')).toBe('R');
    expect(toOneLetter('HOH')).toBe('X');
    expect(toOneLetter(null)).toBe('X');
  });
});

describe('parseResidues', () => {
  it('reads one residue per alpha carbon of the first PDB model', () => {
    const res = parseResidues(PDB, 'pdb');
    expect(res.map((r) => `${r.chain}${r.position}${r.aa}`)).toEqual(['A1M', 'A2R', 'A3M', 'B1G']);
    expect(res[0].bfactor).toBeCloseTo(91.2);
    // Calcium ions named CA and the second model are skipped.
    expect(res.some((r) => r.position === 900 || r.position === 4)).toBe(false);
  });

  it('reads the atom_site loop of an mmCIF with author numbering', () => {
    const res = parseResidues(CIF, 'mmcif');
    expect(res.map((r) => `${r.chain}${r.position}${r.insertion}${r.aa}`)).toEqual([
      'A10M',
      'A11W',
      'A12AA',
    ]);
    expect(res[1].bfactor).toBe(72);
  });

  it('tokenises quoted mmCIF values', () => {
    expect(tokenizeCifLine(`ATOM 1 "C1'" A 'x y'`)).toEqual(['ATOM', '1', "C1'", 'A', 'x y']);
  });
});

describe('loadStructureText', () => {
  beforeEach(() => clearStructureCache());

  it('keys the cache on the object path, not the presigned query', () => {
    expect(structureCacheKey('https://s3/b/k/P1.pdb?X-Amz-Signature=1')).toBe('https://s3/b/k/P1.pdb');
  });

  it('downloads an object once across presigned URLs and evicts failures', async () => {
    const fetcher = vi.fn(async () => new Response(PDB));
    const a = await loadStructureText('https://s3/k/P1.pdb?sig=1', { fetcher });
    const b = await loadStructureText('https://s3/k/P1.pdb?sig=2', { fetcher });
    expect(a).toBe(b);
    expect(a.format).toBe('pdb');
    expect(fetcher).toHaveBeenCalledTimes(1);

    const failing = vi.fn(async () => new Response('', { status: 403 }));
    await expect(loadStructureText('https://s3/k/P2.pdb', { fetcher: failing })).rejects.toThrow(
      '403',
    );
    const ok = vi.fn(async () => new Response(PDB));
    await loadStructureText('https://s3/k/P2.pdb', { fetcher: ok });
    expect(ok).toHaveBeenCalledTimes(1);
  });
});

describe('loadStructureTextRenewing', () => {
  beforeEach(() => clearStructureCache());

  const refused = (status: number) => async () => new Response('', { status });

  it('asks once for a fresh URL after a 403 and loads from it', async () => {
    const fetcher = vi.fn(async (u: string) =>
      u.includes('sig=old') ? new Response('', { status: 403 }) : new Response(PDB),
    );
    const renew = vi.fn(async () => 'https://s3/k/P1.pdb?sig=new');
    const out = await loadStructureTextRenewing('https://s3/k/P1.pdb?sig=old', { fetcher, renew });
    expect(out.format).toBe('pdb');
    expect(renew).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls.map(([u]) => u)).toEqual([
      'https://s3/k/P1.pdb?sig=old',
      'https://s3/k/P1.pdb?sig=new',
    ]);
  });

  it('gives up after one renewal, on the same URL, or on another status', async () => {
    const renew = vi.fn(async () => 'https://s3/k/P2.pdb?sig=new');
    await expect(
      loadStructureTextRenewing('https://s3/k/P2.pdb?sig=old', { fetcher: refused(403), renew }),
    ).rejects.toThrow('403');
    expect(renew).toHaveBeenCalledTimes(1);

    const same = vi.fn(async () => 'https://s3/k/P3.pdb?sig=1');
    await expect(
      loadStructureTextRenewing('https://s3/k/P3.pdb?sig=1', { fetcher: refused(403), renew: same }),
    ).rejects.toThrow('403');

    const notExpired = vi.fn(async () => 'https://s3/k/P4.pdb?sig=new');
    await expect(
      loadStructureTextRenewing('https://s3/k/P4.pdb', { fetcher: refused(404), renew: notExpired }),
    ).rejects.toThrow('404');
    expect(notExpired).not.toHaveBeenCalled();
  });
});
