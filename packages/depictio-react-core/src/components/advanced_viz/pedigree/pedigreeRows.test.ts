import { describe, expect, it } from 'vitest';

import { buildPedigree } from './pedigreeLayout';
import { packFamilies, type PackOptions } from './pedigreeRows';
import { fitScale } from './probands';

const columns = { individual: 'id', father: 'fa', mother: 'mo', sex: 'sex', status: 'st', family: 'fam' };
const limits = { maxIndividuals: 100, maxFamilies: 20 };

/** `n` identical trios, one per family. */
function trios(n: number) {
  const rows: Record<string, unknown[]> = { fam: [], id: [], fa: [], mo: [], sex: [], st: [] };
  for (let i = 0; i < n; i += 1) {
    const f = `F${i}`;
    for (const [id, fa, mo, sex, st] of [
      [`${f}_d`, '0', '0', 1, 1],
      [`${f}_m`, '0', '0', 2, 1],
      [`${f}_c`, `${f}_d`, `${f}_m`, 1, 2],
    ] as const) {
      rows.fam.push(f);
      rows.id.push(id);
      rows.fa.push(fa);
      rows.mo.push(mo);
      rows.sex.push(sex);
      rows.st.push(st);
    }
  }
  return buildPedigree(rows, columns, limits).families;
}

const base: Omit<PackOptions, 'availW' | 'availH'> = {
  gutter: 34,
  padX: 14,
  padBottom: 40,
  labelSpace: 18,
};

describe('packFamilies', () => {
  it('draws one family in one row at the scale that fits it', () => {
    const families = trios(1);
    const p = packFamilies(families, { ...base, availW: 480, availH: 420 });
    expect(p.rows).toHaveLength(1);
    expect(p.rows[0].y).toBe(0);
    expect(p.scale).toBeCloseTo(
      fitScale({ contentW: p.contentW, contentH: p.contentH, availW: 480, availH: 420 }),
      9,
    );
  });

  it('wraps families into rows when the tile is narrow and tall', () => {
    const families = trios(3);
    const wide = packFamilies(families, { ...base, availW: 2000, availH: 300 });
    const tall = packFamilies(families, { ...base, availW: 470, availH: 700 });
    expect(wide.rows).toHaveLength(1);
    expect(tall.rows.length).toBeGreaterThan(1);
    // and earns a larger scale than the strip would have
    const strip = packFamilies(families.slice(0, 3), { ...base, availW: 470, availH: 700 });
    const stripScale = fitScale({
      contentW: wide.contentW,
      contentH: wide.contentH,
      availW: 470,
      availH: 700,
    });
    expect(strip.scale).toBeGreaterThan(stripScale);
  });

  it('keeps the families in order, row after row', () => {
    const families = trios(4);
    const p = packFamilies(families, { ...base, availW: 420, availH: 900 });
    expect(p.rows.flatMap((r) => r.families.map((f) => f.id))).toEqual(families.map((f) => f.id));
  });

  it('stacks the rows without overlap', () => {
    const p = packFamilies(trios(3), { ...base, availW: 300, availH: 1200 });
    for (let i = 1; i < p.rows.length; i += 1) {
      expect(p.rows[i].y).toBeGreaterThanOrEqual(p.rows[i - 1].y + p.rows[i - 1].layout.height);
    }
    const last = p.rows[p.rows.length - 1];
    expect(p.contentH).toBeGreaterThanOrEqual(last.y + last.layout.height);
  });

  it('keeps one row on a tie (an unmeasured tile)', () => {
    const p = packFamilies(trios(3), { ...base, availW: 0, availH: 0 });
    expect(p.rows).toHaveLength(1);
    expect(p.scale).toBe(1);
  });

  it('is empty without families, and copes with many', () => {
    expect(packFamilies([], { ...base, availW: 400, availH: 400 }).rows).toEqual([]);
    const many = packFamilies(trios(14), { ...base, availW: 500, availH: 900 });
    expect(many.rows.flatMap((r) => r.families)).toHaveLength(14);
  });
});
