import { describe, expect, it } from 'vitest';

import {
  alleleFrequencies,
  barValuePlacement,
  clampResolution,
  fitRowPx,
  fontsForRow,
  formatBarValue,
  maxAlleleFields,
  MAX_ROW_PX,
  MIN_ROW_PX,
  NATURAL_ROW_PX,
  resolutionOptions,
  alleleGroup,
  assignAlleleShades,
  buildAlleleGrid,
  cellKey,
  cellSummary,
  cellZygosity,
  clusterByGroup,
  colourUniverse,
  fitAlleleLabel,
  formatAllele,
  gridGeometry,
  groupKeyOf,
  locusClasses,
  inkFor,
  locusGroups,
  MAX_CELL_PX,
  MIN_CELL_PX,
  naturalCompare,
  normaliseLocus,
  orderLoci,
  pairHaplotypes,
  parseAllele,
  parseAlleleRows,
  parseHaplotype,
  rankInGroup,
  rawValuesForLabel,
  rowPositions,
  shadeForRank,
  shadeOffset,
  zygosityCounts,
  type AlleleRow,
  type AlleleCall,
} from './alleleGridLayout';

const COLS = { sample: 'sample', locus: 'locus', allele: 'allele' };

function rowsOf(
  table: Array<[string, string, string | null, (number | string)?]>,
  extra: Partial<Record<'category' | 'value' | 'reads', unknown[]>> = {},
): AlleleRow[] {
  const columns: Record<string, unknown[]> = {
    sample: table.map((r) => r[0]),
    locus: table.map((r) => r[1]),
    allele: table.map((r) => r[2]),
    haplotype: table.map((r) => r[3] ?? null),
    ...extra,
  };
  return parseAlleleRows(columns, {
    ...COLS,
    haplotype: 'haplotype',
    category: extra.category ? 'category' : null,
    value: extra.value ? 'value' : null,
    reads: extra.reads ? 'reads' : null,
  });
}

describe('parseAllele', () => {
  it('reads the full WHO name and strips the HLA- prefix', () => {
    expect(parseAllele('HLA-A*02:01:01:01')).toEqual({
      raw: 'HLA-A*02:01:01:01',
      gene: 'A',
      fields: ['02', '01', '01', '01'],
      suffix: '',
    });
    expect(parseAllele('HLA-DRB1*15:01:01')?.gene).toBe('DRB1');
  });

  it('reads the short forms typing tools write', () => {
    expect(parseAllele('A*02:01')).toMatchObject({ gene: 'A', fields: ['02', '01'] });
    // OptiType-style without the star, and lower case.
    expect(parseAllele('A02:01')).toMatchObject({ gene: 'A', fields: ['02', '01'] });
    expect(parseAllele('dqb1*06:02')).toMatchObject({ gene: 'DQB1', fields: ['06', '02'] });
    expect(parseAllele('DRB115:01')).toMatchObject({ gene: 'DRB1', fields: ['15', '01'] });
    // Pre-2010 names, digits in pairs.
    expect(parseAllele('A*0201')).toMatchObject({ gene: 'A', fields: ['02', '01'] });
    expect(parseAllele('B*270502')).toMatchObject({ gene: 'B', fields: ['27', '05', '02'] });
    // No gene at all: the locus column names it later.
    expect(parseAllele('02:01')).toMatchObject({ gene: null, fields: ['02', '01'] });
    expect(parseAllele(' HLA_C*07:02 ')).toMatchObject({ gene: 'C', fields: ['07', '02'] });
  });

  it('keeps expression suffixes and group designations apart from the fields', () => {
    expect(parseAllele('A*24:09N')).toMatchObject({ fields: ['24', '09'], suffix: 'N' });
    expect(parseAllele('DQB1*06:02:01G')).toMatchObject({ fields: ['06', '02', '01'], suffix: 'G' });
    expect(parseAllele('B*39:01:01:02L')).toMatchObject({ suffix: 'L' });
  });

  it('treats an empty cell or a no-call marker as no call', () => {
    for (const v of [null, undefined, '', '  ', '-', 'NA', 'nan', 'None', 'no_call', '.']) {
      expect(parseAllele(v), String(v)).toBeNull();
    }
    expect(parseAllele(Number.NaN)).toBeNull();
  });

  it('keeps text that is not nomenclature as written rather than dropping the call', () => {
    expect(parseAllele('unresolved')).toEqual({ raw: 'unresolved', gene: null, fields: [], suffix: '' });
    expect(formatAllele(parseAllele('unresolved')!, 2)).toBe('unresolved');
    expect(parseAllele('A*')?.fields).toEqual([]);
  });
});

describe('formatAllele and alleleGroup', () => {
  const full = parseAllele('HLA-A*02:01:01:01')!;
  it('truncates to the resolution', () => {
    expect(formatAllele(full, 1)).toBe('A*02');
    expect(formatAllele(full, 2)).toBe('A*02:01');
    expect(formatAllele(full, 3)).toBe('A*02:01:01');
    expect(formatAllele(full, 4)).toBe('A*02:01:01:01');
    expect(formatAllele(full, 2, false)).toBe('02:01');
  });

  it('never pads a short call up to the resolution', () => {
    expect(formatAllele(parseAllele('A*02:01')!, 4)).toBe('A*02:01');
  });

  it('keeps a suffix only while no field is cut', () => {
    const nul = parseAllele('A*24:09N')!;
    expect(formatAllele(nul, 2)).toBe('A*24:09N');
    expect(formatAllele(nul, 4)).toBe('A*24:09N');
    expect(formatAllele(nul, 1)).toBe('A*24');
  });

  it('names the group by the first field, borrowing the locus when the call has no gene', () => {
    expect(alleleGroup(full)).toBe('A*02');
    expect(alleleGroup(parseAllele('02:01')!, 'HLA-B')).toBe('B*02');
  });
});

describe('small readers', () => {
  it('normalises locus names', () => {
    expect(normaliseLocus('HLA-A')).toBe('A');
    expect(normaliseLocus(' hla-drb1 ')).toBe('DRB1');
    expect(normaliseLocus('DQB1')).toBe('DQB1');
    expect(normaliseLocus(null)).toBe('');
  });

  it('reads a haplotype from a number or a trailing digit', () => {
    expect(parseHaplotype(1)).toBe(1);
    expect(parseHaplotype(2)).toBe(2);
    expect(parseHaplotype('A1')).toBe(1);
    expect(parseHaplotype('hap2')).toBe(2);
    expect(parseHaplotype('2')).toBe(2);
    expect(parseHaplotype(3)).toBeNull();
    expect(parseHaplotype('maternal')).toBeNull();
    expect(parseHaplotype(null)).toBeNull();
  });

  it('orders names naturally', () => {
    expect(['S10', 'S2', 'S1'].sort(naturalCompare)).toEqual(['S1', 'S2', 'S10']);
    expect(['A*11:01', 'A*02:01'].sort(naturalCompare)).toEqual(['A*02:01', 'A*11:01']);
  });
});

describe('parseAlleleRows', () => {
  it('drops rows with no sample, and takes the locus from the allele when the column is empty', () => {
    const rows = parseAlleleRows(
      {
        sample: ['S1', null, 'S2', 'S3'],
        locus: ['HLA-A', 'HLA-A', '', null],
        allele: ['A*02:01', 'A*01:01', 'B*07:02', 'unknown'],
      },
      COLS,
    );
    expect(rows.map((r) => [r.sample, r.locus])).toEqual([
      ['S1', 'A'],
      ['S2', 'B'],
    ]);
    expect(rows[1].row).toBe(2);
  });

  it('reads numeric side columns and ignores non-finite values', () => {
    const rows = parseAlleleRows(
      { sample: ['S1', 'S1'], locus: ['A', 'A'], allele: ['A*02:01', 'A*03:01'], v: ['0.9', 'x'] },
      { ...COLS, value: 'v' },
    );
    expect(rows.map((r) => r.value)).toEqual([0.9, null]);
  });
});

describe('pairHaplotypes', () => {
  it('pairs by row order when no haplotype is bound', () => {
    const rows = rowsOf([
      ['S1', 'A', 'A*24:02'],
      ['S1', 'A', 'A*02:01'],
    ]);
    const { haplotypes } = pairHaplotypes(rows, 2);
    expect(haplotypes.map((h) => h?.label)).toEqual(['A*24:02', 'A*02:01']);
  });

  it('honours the haplotype column whatever the row order', () => {
    const rows = rowsOf([
      ['S1', 'A', 'A*24:02', 2],
      ['S1', 'A', 'A*02:01', 1],
    ]);
    expect(pairHaplotypes(rows, 2).haplotypes.map((h) => h?.label)).toEqual(['A*02:01', 'A*24:02']);
  });

  it('lets an unlabelled call fill the half a labelled one left free', () => {
    const rows = rowsOf([
      ['S1', 'A', 'A*24:02'],
      ['S1', 'A', 'A*02:01', 1],
    ]);
    expect(pairHaplotypes(rows, 2).haplotypes.map((h) => h?.label)).toEqual(['A*02:01', 'A*24:02']);
  });

  it('keeps an explicit no-call in its half', () => {
    const rows = rowsOf([
      ['S1', 'A', 'A*02:01', 1],
      ['S1', 'A', '-', 2],
      ['S1', 'A', 'A*03:01'],
    ]);
    const { haplotypes, extra } = pairHaplotypes(rows, 2);
    expect(haplotypes[0]?.label).toBe('A*02:01');
    expect(haplotypes[1]).toBeNull();
    expect(extra).toBe(1);
  });

  it('counts calls past the second instead of drawing them', () => {
    const rows = rowsOf([
      ['S1', 'A', 'A*02:01'],
      ['S1', 'A', 'A*03:01'],
      ['S1', 'A', 'A*11:01'],
    ]);
    expect(pairHaplotypes(rows, 2).extra).toBe(1);
  });

  it('gives a gene-less call the locus as its gene', () => {
    const rows = rowsOf([['S1', 'HLA-B', '07:02']]);
    const [h1, h2] = pairHaplotypes(rows, 2).haplotypes;
    expect(h1?.label).toBe('B*07:02');
    expect(h1?.group).toBe('B*07');
    expect(h2).toBeNull();
  });
});

describe('buildAlleleGrid', () => {
  const table: Array<[string, string, string | null, (number | string)?]> = [
    ['S10', 'HLA-A', 'A*02:01:01'],
    ['S10', 'HLA-A', 'A*02:01:02'],
    ['S10', 'HLA-DRB1', 'DRB1*15:01'],
    ['S10', 'HLA-DRB1', 'DRB1*03:01'],
    ['S2', 'HLA-A', 'A*01:01'],
    ['S2', 'HLA-A', 'A*02:01'],
    ['S2', 'HLA-B', 'B*08:01'],
    ['S2', 'HLA-B', 'B*07:02'],
    ['S1', 'HLA-B', 'B*07:02'],
    ['S1', 'HLA-B', 'B*07:02'],
    ['S1', 'HLA-A', 'A*03:01'],
    ['S1', 'HLA-A', 'A*02:01'],
  ];
  const categories = table.map((r) => (r[1] === 'HLA-DRB1' ? 'Class II' : 'Class I'));
  const values = table.map((r) => ({ S1: 0.5, S2: 0.9, S10: 0.7 })[r[0]]);
  const rows = rowsOf(table, { category: categories, value: values });

  it('decides homozygosity at the display resolution', () => {
    const at2 = buildAlleleGrid(rows, { resolution: 2 });
    expect(at2.cells.get(cellKey('S10', 'A'))?.homozygous).toBe(true);
    expect(at2.cells.get(cellKey('S1', 'B'))?.homozygous).toBe(true);
    expect(at2.cells.get(cellKey('S2', 'A'))?.homozygous).toBe(false);
    const at3 = buildAlleleGrid(rows, { resolution: 3 });
    expect(at3.cells.get(cellKey('S10', 'A'))?.homozygous).toBe(false);
    // At one field A*01 and A*02 still differ, but DRB1*15 / DRB1*03 too.
    const at1 = buildAlleleGrid(rows, { resolution: 1 });
    expect(at1.cells.get(cellKey('S2', 'A'))?.homozygous).toBe(false);
  });

  it('orders loci conventionally inside their class, and groups the header by class', () => {
    const grid = buildAlleleGrid(rows, { resolution: 2 });
    expect(grid.loci.map((l) => l.locus)).toEqual(['A', 'B', 'DRB1']);
    expect(grid.groups).toEqual([
      { category: 'Class I', start: 0, end: 2 },
      { category: 'Class II', start: 2, end: 3 },
    ]);
  });

  it('puts the authored loci first', () => {
    const grid = buildAlleleGrid(rows, { resolution: 2, locusOrder: ['HLA-DRB1', 'B'] });
    expect(grid.loci.map((l) => l.locus)).toEqual(['DRB1', 'B', 'A']);
  });

  it('orders samples by name, by value, or by their alleles at one locus', () => {
    const names = (mode: 'alphabetical' | 'value' | 'allele', orderLocus?: string) =>
      buildAlleleGrid(rows, { resolution: 2, sampleOrder: mode, orderLocus }).samples.map(
        (s) => s.sample,
      );
    expect(names('alphabetical')).toEqual(['S1', 'S2', 'S10']);
    expect(names('value')).toEqual(['S2', 'S10', 'S1']);
    // At A, A*02:01 is the commonest (4 copies) and every sample carries it,
    // so the second allele's rank decides: S10 is homozygous for it, then
    // A*01:01 before A*03:01 (one copy each, natural order).
    expect(names('allele', 'HLA-A')).toEqual(['S10', 'S2', 'S1']);
    // B: S1 is B*07:02 homozygous, S2 carries one B*07:02, S10 has no B call.
    expect(names('allele', 'B')).toEqual(['S1', 'S2', 'S10']);
  });

  it('guards samples and loci after ordering, and counts what it left out', () => {
    const grid = buildAlleleGrid(rows, { resolution: 2, maxSamples: 2, maxLoci: 1 });
    expect(grid.samples.map((s) => s.sample)).toEqual(['S1', 'S2']);
    expect(grid.loci.map((l) => l.locus)).toEqual(['A']);
    expect(grid.droppedSamples).toBe(1);
    expect(grid.droppedLoci).toBe(2);
  });

  it('keeps the largest per-sample value', () => {
    const grid = buildAlleleGrid(rows, { resolution: 2 });
    expect(grid.samples.find((s) => s.sample === 'S2')?.value).toBe(0.9);
  });

  it('builds a legend of allele frequencies over every typed sample', () => {
    const grid = buildAlleleGrid(rows, { resolution: 2 });
    const a = grid.legend.filter((e) => e.locus === 'A');
    expect(a[0]).toMatchObject({ label: 'A*02:01', copies: 4, carriers: 3 });
    expect(a[0].frequency).toBeCloseTo(4 / 6);
    const b = grid.legend.find((e) => e.label === 'B*07:02');
    // Two samples typed at B, three copies.
    expect(b).toMatchObject({ copies: 3, carriers: 2 });
    expect(b?.frequency).toBeCloseTo(3 / 4);
    // Ordered by locus, then by copies.
    expect(grid.legend.map((e) => e.locus)).toEqual(['A', 'A', 'A', 'B', 'B', 'DRB1', 'DRB1']);
  });

  it('flags a cell with a third call', () => {
    const grid = buildAlleleGrid(rowsOf([...table, ['S1', 'HLA-A', 'A*11:01']]), { resolution: 2 });
    expect(grid.overfull).toBe(1);
    expect(grid.cells.get(cellKey('S1', 'A'))?.extra).toBe(1);
  });

  it('maps a 2-field pick back onto every raw value that truncates to it', () => {
    const grid = buildAlleleGrid(rows, { resolution: 2 });
    expect(rawValuesForLabel(grid.cells.values(), 'A*02:01')).toEqual([
      'A*02:01',
      'A*02:01:01',
      'A*02:01:02',
    ]);
  });

  it('summarises a cell for the hover', () => {
    const grid = buildAlleleGrid(rows, { resolution: 2 });
    expect(cellSummary(grid.cells.get(cellKey('S2', 'A'))!)).toBe('S2 · A · A*01:01 / A*02:01');
    expect(cellSummary(grid.cells.get(cellKey('S1', 'B'))!)).toBe('S1 · B · B*07:02 (homozygous)');
  });

  it('draws nothing for an empty frame', () => {
    const grid = buildAlleleGrid([], { resolution: 2 });
    expect(grid.samples).toEqual([]);
    expect(grid.loci).toEqual([]);
    expect(grid.legend).toEqual([]);
  });
});

describe('orderLoci and locusGroups', () => {
  it('falls back to the name past the conventional list', () => {
    const loci = orderLoci([
      { locus: 'KIR2DL1', category: null },
      { locus: 'C', category: null },
      { locus: 'A', category: null },
      { locus: 'DPB1', category: null },
    ]);
    expect(loci.map((l) => l.locus)).toEqual(['A', 'C', 'DPB1', 'KIR2DL1']);
    expect(locusGroups(loci)).toEqual([]);
  });
});

describe('colours', () => {
  const call = (raw: string, locus = ''): AlleleCall => {
    const rows = rowsOf([['S', locus || raw.split('*')[0], raw]]);
    return pairHaplotypes(rows, 2).haplotypes[0]!;
  };

  it('walks a shade ladder from the base shade of each scheme', () => {
    expect(shadeForRank(0, false)).toBe(6);
    expect(shadeForRank(0, true)).toBe(4);
    expect(new Set([0, 1, 2, 3, 4, 5, 6, 7].map((r) => shadeForRank(r, false))).size).toBe(8);
    expect(shadeForRank(8, false)).toBe(shadeForRank(0, false));
  });

  it('gives one hue to a group and a different shade to each of its alleles', () => {
    const universe = colourUniverse(
      ['A*02:01', 'A*02:06', 'A*24:02', 'B*07:02', 'B*08:01'],
      [],
      2,
    );
    const shades = assignAlleleShades(universe, 12, false);
    const a0201 = shades.get('A*02:01')!;
    const a0206 = shades.get('A*02:06')!;
    const a2402 = shades.get('A*24:02')!;
    expect(a0201.hue).toBe(a0206.hue);
    expect(a0201.shade).not.toBe(a0206.shade);
    expect(a2402.hue).not.toBe(a0201.hue);
    expect(shades.get('B*07:02')!.hue).not.toBe(shades.get('B*08:01')!.hue);
  });

  it('does not repaint an allele when a filter removes its neighbours', () => {
    const all = assignAlleleShades(
      colourUniverse(['A*01:01', 'A*02:01', 'A*03:01'], [], 2),
      12,
      false,
    );
    const filtered = assignAlleleShades(
      colourUniverse(['A*01:01', 'A*02:01', 'A*03:01'], [call('A*03:01')], 2),
      12,
      false,
    );
    expect(filtered.get('A*03:01')).toEqual(all.get('A*03:01'));
  });

  it('collapses the universe to the display resolution', () => {
    const u = colourUniverse(['A*02:01:01', 'A*02:01:02', 'HLA-A*02:01'], [], 2);
    expect(u.map((e) => e.label)).toEqual(['A*02:01']);
    expect(u[0]).toMatchObject({ gene: 'A', group: 'A*02' });
  });

  it('places a gene-less value once a row names its locus', () => {
    const u = colourUniverse(['07:02'], [call('07:02', 'B')], 2);
    expect(u.map((e) => e.label)).toEqual(['B*07:02']);
  });

  it('picks the readable ink for a background', () => {
    expect(inkFor('#ffffff')).toBe('dark');
    expect(inkFor('#fff')).toBe('dark');
    expect(inkFor('#000000')).toBe('light');
    expect(inkFor('#1864ab')).toBe('light');
    expect(inkFor('#ffd43b')).toBe('dark');
    expect(inkFor('rgb(20, 20, 20)')).toBe('light');
    expect(inkFor('var(--mantine-color-blue-6)')).toBe('dark');
  });
});

describe('geometry and labels', () => {
  const c = (raw: string) => pairHaplotypes(rowsOf([['S', raw.split('*')[0], raw]]), 2).haplotypes[0]!;

  it('writes the full allele when it fits, the bare fields when only they do, else nothing', () => {
    expect(fitAlleleLabel(c('A*02:01'), 60, 10, 2)).toBe('A*02:01');
    expect(fitAlleleLabel(c('A*02:01'), 40, 10, 2)).toBe('02:01');
    expect(fitAlleleLabel(c('A*02:01'), 20, 10, 2)).toBeNull();
    expect(fitAlleleLabel(c('DRB1*15:01'), 60, 10, 2)).toBe('15:01');
  });

  it('shares the free width between the loci inside the clamps', () => {
    const g = gridGeometry({ width: 700, nLoci: 5, sampleLabelChars: 8, sideBars: 2 });
    expect(g.labelWidth).toBeGreaterThanOrEqual(48);
    expect(g.cellWidth).toBe(Math.floor((700 - g.labelWidth - 2 * (g.barWidth + 6)) / 5));
    expect(g.totalWidth).toBeLessThanOrEqual(700);
    expect(gridGeometry({ width: 5000, nLoci: 2, sampleLabelChars: 8, sideBars: 0 }).cellWidth).toBe(
      MAX_CELL_PX,
    );
    const narrow = gridGeometry({ width: 200, nLoci: 12, sampleLabelChars: 40, sideBars: 1 });
    expect(narrow.cellWidth).toBe(MIN_CELL_PX);
    expect(narrow.labelWidth).toBe(180);
    expect(narrow.totalWidth).toBeGreaterThan(200);
  });

  it('frequencies of an empty set are empty', () => {
    expect(alleleFrequencies([], [])).toEqual([]);
  });
});

describe('colour modes', () => {
  const rows = rowsOf([
    ['S1', 'A', 'A*02:01', 1],
    ['S1', 'A', 'A*11:01', 2],
    ['S2', 'A', 'A*02:01', 1],
    ['S2', 'A', 'A*02:01', 2],
    ['S3', 'A', 'A*03:01', 1],
    ['S3', 'A', null, 2],
  ]);

  it('classes a cell as homozygous, heterozygous or one allele typed', () => {
    const grid = buildAlleleGrid(rows, { resolution: 2 });
    const z = (s: string) => cellZygosity(grid.cells.get(cellKey(s, 'A'))!);
    expect(z('S1')).toBe('Heterozygous');
    expect(z('S2')).toBe('Homozygous');
    expect(z('S3')).toBe('One allele typed');
    expect(Object.fromEntries(zygosityCounts(grid))).toEqual({
      Heterozygous: 1,
      Homozygous: 1,
      'One allele typed': 1,
    });
  });

  it('decides zygosity at the display resolution', () => {
    const fine = rowsOf([
      ['S1', 'A', 'A*02:01', 1],
      ['S1', 'A', 'A*02:05', 2],
    ]);
    const at2 = buildAlleleGrid(fine, { resolution: 2 }).cells.get(cellKey('S1', 'A'))!;
    const at1 = buildAlleleGrid(fine, { resolution: 1 }).cells.get(cellKey('S1', 'A'))!;
    expect(cellZygosity(at2)).toBe('Heterozygous');
    expect(cellZygosity(at1)).toBe('Homozygous');
  });

  it('lists the locus classes once each, in column order', () => {
    expect(locusClasses([])).toEqual([]);
    expect(
      locusClasses([
        { locus: 'A', category: 'Class I' },
        { locus: 'B', category: 'Class I' },
        { locus: 'DRB1', category: 'Class II' },
        { locus: 'X', category: null },
      ]),
    ).toEqual(['Class I', 'Class II']);
  });

  it('finds the family of a pinned allele-group value', () => {
    expect(groupKeyOf('HLA-A*02')).toBe('A*02');
    expect(groupKeyOf('A*02')).toBe('A*02');
    expect(groupKeyOf(null)).toBeNull();
    const calls = buildAlleleGrid(rows, { resolution: 2 }).cells.get(cellKey('S1', 'A'))!.haplotypes;
    expect(calls[0]!.group).toBe(groupKeyOf('HLA-A*02'));
  });

  it('shades alleles of a group lighter and darker around its base', () => {
    const universe = colourUniverse(['HLA-A*02:01', 'HLA-A*02:05', 'HLA-A*11:01'], [], 2);
    const ranks = rankInGroup(universe);
    expect(ranks.get('A*02:01')).toBe(0);
    expect(ranks.get('A*02:05')).toBe(1);
    expect(ranks.get('A*11:01')).toBe(0);
    expect(shadeOffset(0)).toBe(0);
    expect(shadeOffset(1)).toBeGreaterThan(0);
    expect(shadeOffset(2)).toBeLessThan(0);
    const offsets = [1, 2, 3, 4, 5, 6].map(shadeOffset);
    expect(new Set(offsets).size).toBe(offsets.length);
    expect(Math.max(...offsets.map(Math.abs))).toBeLessThanOrEqual(0.7);
  });
});

describe('grouping the rows', () => {
  const cols = { ...COLS, haplotype: 'haplotype', group: 'grp' };
  const table: Record<string, unknown[]> = {
    sample: ['S1', 'S1', 'S2', 'S2', 'S3', 'S3', 'S4', 'S4'],
    locus: Array(8).fill('A'),
    allele: ['A*02:01', 'A*11:01', 'A*02:01', 'A*02:01', 'A*03:01', 'A*24:02', 'A*01:01', 'A*01:01'],
    haplotype: [1, 2, 1, 2, 1, 2, 1, 2],
    grp: ['RNA', 'RNA', 'DNA', 'DNA', 'RNA', 'RNA', null, null],
  };

  it('keeps the order untouched when not grouping', () => {
    const grid = buildAlleleGrid(parseAlleleRows(table, cols), { resolution: 2 });
    expect(grid.samples.map((s) => s.sample)).toEqual(['S1', 'S2', 'S3', 'S4']);
    expect(grid.sampleRuns).toEqual([]);
  });

  it('clusters by group, no group last, and keeps the order inside a group', () => {
    const grid = buildAlleleGrid(parseAlleleRows(table, cols), { resolution: 2, groupSamples: true });
    expect(grid.samples.map((s) => s.sample)).toEqual(['S2', 'S1', 'S3', 'S4']);
    expect(grid.sampleRuns).toEqual([
      { group: 'DNA', start: 0, end: 1 },
      { group: 'RNA', start: 1, end: 3 },
      { group: null, start: 3, end: 4 },
    ]);
    expect(
      clusterByGroup([
        { sample: 'b', value: null, reads: null, group: 'x' },
        { sample: 'a', value: null, reads: null, group: 'x' },
      ]).map((s) => s.sample),
    ).toEqual(['b', 'a']);
  });

  it('applies the sample guard after grouping and counts what it drops', () => {
    const grid = buildAlleleGrid(parseAlleleRows(table, cols), {
      resolution: 2,
      groupSamples: true,
      maxSamples: 2,
    });
    expect(grid.samples.map((s) => s.sample)).toEqual(['S2', 'S1']);
    expect(grid.droppedSamples).toBe(2);
  });

  it('lays a header band before every run', () => {
    const packed = rowPositions(3, [], 22, 18, 40);
    expect(packed).toEqual({ ys: [40, 62, 84], bands: [], height: 66 });
    const runs = [
      { group: 'DNA', start: 0, end: 1 },
      { group: 'RNA', start: 1, end: 3 },
    ];
    const laid = rowPositions(3, runs, 22, 18, 40);
    expect(laid.bands).toEqual([40, 80]);
    expect(laid.ys).toEqual([58, 98, 120]);
    expect(laid.height).toBe(2 * 18 + 3 * 22);
  });
});

describe('resolution on offer', () => {
  it('counts the fields the data carries: OptiType alleles have two', () => {
    const two = rowsOf([
      ['S1', 'A', 'A*01:01', 1],
      ['S1', 'A', 'A*02:01', 2],
    ]);
    expect(maxAlleleFields(two)).toBe(2);
    expect(resolutionOptions(maxAlleleFields(two))).toEqual([1, 2]);
  });

  it('ignores an expression suffix and takes the finest allele', () => {
    const rows = rowsOf([
      ['S1', 'A', 'A*24:09N', 1],
      ['S1', 'A', 'A*02:01:01:01', 2],
    ]);
    expect(maxAlleleFields(rows)).toBe(4);
    expect(maxAlleleFields(rowsOf([['S1', 'A', 'A*24:09N', 1]]))).toBe(2);
  });

  it('is 4 when nothing parses, and offers nothing for one field', () => {
    expect(maxAlleleFields([])).toBe(4);
    expect(maxAlleleFields(rowsOf([['S1', 'A', 'A*02', 1]]))).toBe(1);
    expect(resolutionOptions(1)).toEqual([]);
    expect(resolutionOptions(4)).toEqual([1, 2, 3, 4]);
  });

  it('clamps a configured or persisted resolution down to the maximum', () => {
    expect(clampResolution(4, 2)).toBe(2);
    expect(clampResolution(3, 3)).toBe(3);
    expect(clampResolution(0, 3)).toBe(1);
    expect(clampResolution(Number.NaN, 4)).toBe(2);
  });
});

describe('fitRowPx', () => {
  it('fills the available height with the rows', () => {
    // 12 rows under a 22 px header and 4 px pad in 400 px: (400 - 26) / 12 = 31.
    expect(fitRowPx(400, 12, 22)).toBe(31);
  });

  it('counts the group bands', () => {
    expect(fitRowPx(400, 10, 40, 2, 18)).toBe(Math.floor((400 - 40 - 36 - 4) / 10));
  });

  it('stays within the bounds', () => {
    expect(fitRowPx(2000, 3, 22)).toBe(MAX_ROW_PX);
    expect(fitRowPx(120, 40, 22)).toBe(MIN_ROW_PX);
  });

  it('falls back to the natural height before the tile is measured', () => {
    expect(fitRowPx(0, 5, 22)).toBe(NATURAL_ROW_PX);
    expect(fitRowPx(300, 0, 22)).toBe(NATURAL_ROW_PX);
    expect(fitRowPx(Number.NaN, 5, 22)).toBe(NATURAL_ROW_PX);
  });
});

describe('fontsForRow', () => {
  it('grows with the row and never drops under the readable minimum', () => {
    const small = fontsForRow(MIN_ROW_PX);
    const big = fontsForRow(MAX_ROW_PX);
    expect(small.label).toBeGreaterThanOrEqual(10);
    expect(small.axis).toBeGreaterThanOrEqual(11);
    expect(big.label).toBeGreaterThan(small.label);
    expect(big.axis).toBeGreaterThanOrEqual(small.axis);
  });
});

describe('side bar values', () => {
  it('writes a value short enough for a bar end', () => {
    expect(formatBarValue(950)).toBe('950');
    expect(formatBarValue(12345)).toBe('12k');
    expect(formatBarValue(4_100_000)).toBe('4.1M');
    expect(formatBarValue(0.4567)).toBe('0.46');
    expect(formatBarValue(0)).toBe('0');
  });

  it('puts it inside a long bar, past a short one, and nowhere without room', () => {
    expect(barValuePlacement(50, 56, '950', 10)).toBe('inside');
    expect(barValuePlacement(8, 56, '950', 10)).toBe('outside');
    expect(barValuePlacement(28, 56, '4.1M', 12)).toBeNull();
    expect(barValuePlacement(0, 56, '0', 10)).toBe('outside');
  });
});
