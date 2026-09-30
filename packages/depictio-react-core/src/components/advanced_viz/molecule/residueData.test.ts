import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../../api';
import { residueRangeFilters } from '../../../selection';
import {
  buildColouring,
  checkVariants,
  chooseEntity,
  clickRange,
  columnsToFetch,
  distinctEntities,
  filtersForMoleculeFetch,
  markRadius,
  markRows,
  parseResidueRows,
  proteinChange,
  resolverQuery,
  rowsForEntity,
  selectedValuesByColumn,
  spectrumColour,
} from './residueData';
import type { StructureResidue } from './structureText';

const residue = (
  chain: string,
  position: number,
  aa: string,
  bfactor: number | null = 80,
): StructureResidue => ({ chain, position, insertion: '', resn: aa, aa, bfactor });

const STRUCTURE = [
  residue('A', 1, 'M', 95),
  residue('A', 2, 'R', 75),
  residue('A', 3, 'H', 55),
  residue('A', 4, 'K', 20),
];

const COLS = {
  entity: 'entity',
  position: 'position',
  refAa: 'ref',
  altAa: 'alt',
  category: 'consequence',
  value: 'vaf',
  label: 'label',
  uniprot: 'uniprot',
};

const FRAME = {
  entity: ['P1', 'P1', 'P1', 'P2', 'P1'],
  position: [2, 3, 9, 1, '4'],
  ref: ['R', 'Arg', 'A', 'M', null],
  alt: ['H', 'W', 'T', 'V', null],
  consequence: ['missense', 'missense', 'stop_gained', 'missense', null],
  vaf: [0.5, 0.1, 0.2, 0.9, null],
  label: [null, null, null, null, null],
  uniprot: ['P04637', null, null, 'P38398', null],
};

describe('rows and entities', () => {
  const rows = parseResidueRows(FRAME, COLS);

  it('types the frame and lists the fetched columns once', () => {
    expect(rows).toHaveLength(5);
    expect(rows[4].position).toBe(4);
    expect(rows[0].value).toBe(0.5);
    expect(columnsToFetch({ ...COLS, chain: null, gene: 'entity' })).toEqual([
      'entity',
      'position',
      'ref',
      'alt',
      'consequence',
      'vaf',
      'label',
      'uniprot',
    ]);
  });

  it('chooses the filtered entity, then the pick, then the first with a structure', () => {
    const available = ['P2', 'P1'];
    const rowEntities = distinctEntities(rows);
    expect(rowEntities).toEqual(['P1', 'P2']);
    expect(chooseEntity({ fromFilters: 'P2', picked: 'P1', rowEntities, available })).toBe('P2');
    expect(chooseEntity({ fromFilters: 'X', picked: 'P2', rowEntities, available })).toBe('P2');
    expect(chooseEntity({ fromFilters: null, picked: null, rowEntities, available })).toBe('P1');
    expect(chooseEntity({ fromFilters: null, picked: null, rowEntities: [], available })).toBe('P2');
    expect(chooseEntity({ fromFilters: null, picked: null, rowEntities, available: [] })).toBeNull();
  });

  it('keeps the rows of one entity and builds the resolver question from them', () => {
    const p1 = rowsForEntity(rows, 'P1', true);
    expect(p1).toHaveLength(4);
    expect(resolverQuery(p1)).toEqual({ uniprot: 'P04637', gene: null, sequence: null });
    expect(resolverQuery(rowsForEntity(rows, 'P1', true).slice(1))).toBeNull();
    expect(rowsForEntity(rows, 'P1', false)).toHaveLength(5);
  });
});

describe('variant marks', () => {
  const rows = rowsForEntity(parseResidueRows(FRAME, COLS), 'P1', true);

  it('draws matching variants, lists numbering mismatches and uncovered positions', () => {
    const marks = markRows(rows, { hasAltColumn: true, colourMode: 'plddt', residueCount: 4 });
    const check = checkVariants(marks, STRUCTURE);
    expect(check.drawn.map((m) => m.label)).toEqual(['p.R2H']);
    // `Arg` at 3, but the model has H there: a numbering problem, not drawn.
    expect(check.mismatched.map((m) => [m.label, m.structureAa])).toEqual([['p.R3W', 'H']]);
    expect(check.outside.map((m) => m.position)).toEqual([9]);
  });

  it('reads category-only rows as marks unless they colour most of the chain', () => {
    const sparse = parseResidueRows(
      { position: [1, 2], site: ['active', null] },
      { position: 'position', category: 'site' },
    );
    expect(markRows(sparse, { hasAltColumn: false, colourMode: 'plddt', residueCount: 4 })).toHaveLength(1);
    expect(markRows(sparse, { hasAltColumn: false, colourMode: 'category', residueCount: 4 })).toHaveLength(0);
    const dense = parseResidueRows(
      { position: [1, 2, 3], ss: ['H', 'H', 'E'] },
      { position: 'position', category: 'ss' },
    );
    expect(markRows(dense, { hasAltColumn: false, colourMode: 'plddt', residueCount: 4 })).toHaveLength(0);
  });

  it('formats protein changes and sizes marks by value', () => {
    expect(proteinChange('R', 175, 'H')).toBe('p.R175H');
    expect(proteinChange(null, 12, null)).toBe('p.12');
    expect(markRadius(null, 0, 1)).toBe(1.4);
    expect(markRadius(1, 0, 1)).toBeGreaterThan(markRadius(0, 0, 1));
  });
});

describe('filters', () => {
  const own = residueRangeFilters('mol', {
    entityColumn: 'entity',
    positionColumn: 'position',
    entity: 'P1',
    start: 2,
    end: 5,
  });
  const other = residueRangeFilters('msa', {
    entityColumn: 'entity',
    positionColumn: 'position',
    entity: 'P2',
    start: 10,
    end: 20,
  });
  const tableSel: InteractiveFilter = {
    index: 'table',
    value: ['p.R2H'],
    source: 'table_selection',
    column_name: 'label',
  };
  const sidebar: InteractiveFilter = { index: 'side', value: ['missense'], column_name: 'consequence' };

  it('drops its own pick, other picks position halves and emphasised row selections', () => {
    const kept = filtersForMoleculeFetch([...own, ...other, tableSel, sidebar], 'mol', [
      'position',
      'label',
    ]);
    expect(kept.map((f) => f.index)).toEqual(['msa', 'side']);
    expect(kept[0].column_name).toBe('entity');
  });

  it('collects values selected elsewhere on the emphasis columns', () => {
    const sel = selectedValuesByColumn([tableSel, sidebar], 'mol', ['label']);
    expect([...(sel.get('label') ?? [])]).toEqual(['p.R2H']);
  });

  it('extends a click range from the anchor with shift', () => {
    expect(clickRange(null, 7, true)).toEqual({ start: 7, end: 7 });
    expect(clickRange(10, 7, true)).toEqual({ start: 7, end: 10 });
    expect(clickRange(10, 7, false)).toEqual({ start: 7, end: 7 });
  });
});

describe('colouring', () => {
  const rows = rowsForEntity(parseResidueRows(FRAME, COLS), 'P1', true);
  const args = {
    residues: STRUCTURE,
    rows,
    palette: ['#111111', '#222222', '#333333'],
    neutral: '#999999',
    uniform: '#123456',
  };

  it('colours pLDDT in AlphaFold bands, on either scale', () => {
    const c = buildColouring('plddt', args);
    expect(c.colourOf('A', 1, 95)).not.toBe(c.colourOf('A', 4, 20));
    expect(c.legend?.kind).toBe('swatches');
    const fractional = buildColouring('plddt', {
      ...args,
      residues: STRUCTURE.map((r) => ({ ...r, bfactor: (r.bfactor ?? 0) / 100 })),
    });
    expect(fractional.colourOf('A', 1, 0.95)).toBe(c.colourOf('A', 1, 95));
    expect(c.colourOf('A', 1, null)).toBe('#999999');
  });

  it('colours by table value and category, neutral where the table is silent', () => {
    const v = buildColouring('value', args);
    expect(v.colourOf('A', 2, null)).toMatch(/^rgb\(/);
    expect(v.colourOf('A', 1, null)).toBe('#999999');
    expect(v.legend).toMatchObject({ kind: 'gradient', min: '0.1', max: '0.5' });
    const cat = buildColouring('category', args);
    expect(cat.colourOf('A', 2, null)).toBe(cat.colourOf('A', 3, null));
    expect(cat.colourOf('A', 1, null)).toBe('#999999');
  });

  it('paints value mode on the configured colour scale, Viridis by default', () => {
    const viridis = buildColouring('value', args);
    expect(buildColouring('value', { ...args, valueScale: null }).colourOf('A', 2, null)).toBe(
      viridis.colourOf('A', 2, null),
    );
    const magma = buildColouring('value', { ...args, valueScale: 'Magma' });
    expect(magma.colourOf('A', 2, null)).not.toBe(viridis.colourOf('A', 2, null));
    expect(magma.legend).toMatchObject({ kind: 'gradient', min: '0.1', max: '0.5' });
  });

  it('draws the spectrum in hex from blue to red, and uniform in one colour', () => {
    expect(spectrumColour(0)).toMatch(/^#[0-9a-f]{6}$/);
    expect(spectrumColour(0)).not.toBe(spectrumColour(1));
    expect(buildColouring('uniform', args).colourOf('A', 1, 10)).toBe('#123456');
    expect(buildColouring('chain', args).legend).toBeNull();
  });

  it('colours secondary structure from the model, helix, strand and coil', () => {
    const ss = buildColouring('secondary_structure', args);
    const helix = ss.colourOf('A', 1, null, 'h');
    const strand = ss.colourOf('A', 1, null, 's');
    expect(helix).not.toBe(strand);
    expect(ss.colourOf('A', 1, null, null)).toBe('#999999');
    expect(ss.colourOf('A', 1, null)).toBe('#999999');
    expect(ss.legend).toMatchObject({
      kind: 'swatches',
      items: [
        { label: 'Helix', colour: helix },
        { label: 'Strand', colour: strand },
        { label: 'Coil', colour: '#999999' },
      ],
    });
    expect(ss.scheme).toBeUndefined();
  });

  it('hands residue type to the 3Dmol amino scheme, without a legend', () => {
    const rt = buildColouring('residue_type', args);
    expect(rt.scheme).toBe('amino');
    expect(rt.legend).toBeNull();
  });

  it('colours hydrophobicity per residue on the Kyte-Doolittle ramp', () => {
    const h = buildColouring('hydrophobicity', {
      ...args,
      residues: [residue('A', 1, 'I'), residue('A', 2, 'R'), residue('A', 3, 'X')],
    });
    // Isoleucine is the hydrophobic end, arginine the hydrophilic one.
    expect(h.colourOf('A', 1, null)).toBe('rgb(255,0,0)');
    expect(h.colourOf('A', 2, null)).toBe('rgb(0,0,255)');
    expect(h.colourOf('A', 3, null)).toBe('#999999');
    expect(h.colourOf('B', 1, null)).toBe('#999999');
    expect(h.legend).toEqual({
      kind: 'gradient',
      title: 'Hydrophobicity (Kyte-Doolittle)',
      min: '-4.5',
      max: '4.5',
      stops: ['rgb(0,0,255)', 'rgb(255,0,0)'],
    });
  });
});

describe('distinctEntities', () => {
  it('puts the entity with the most rows first and keeps ties in appearance order', () => {
    const row = (entity: string) => ({ entity }) as unknown as Parameters<typeof distinctEntities>[0][number];
    const rows = ['B', 'A', 'C', 'C', 'A', 'C'].map(row);
    expect(distinctEntities(rows)).toEqual(['C', 'A', 'B']);
  });
});
