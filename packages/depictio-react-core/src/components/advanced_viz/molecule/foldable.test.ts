import { describe, expect, it } from 'vitest';

import {
  chooseDefaultEntity,
  foldLength,
  renderableEntities,
  unfoldableEntities,
} from './foldable';
import { chooseEntity, distinctEntities, parseResidueRows } from './residueData';
import { ESMFOLD_MAX_RESIDUES } from './resolve';

const COLS = { entity: 'entity', position: 'position', sequence: 'sequence', uniprot: 'uniprot', gene: 'gene' };

interface Protein {
  entity: string;
  /** Residue rows the table holds (the protein's length on a residue table). */
  residues: number;
  /** Length of the `sequence` column's value, or null for no sequence. */
  sequence: number | null;
  uniprot?: string;
  gene?: string;
}

/** A residue table: one row per residue, the sequence repeated on each. */
function table(proteins: Protein[]) {
  const frame: Record<string, unknown[]> = {
    entity: [],
    position: [],
    sequence: [],
    uniprot: [],
    gene: [],
  };
  for (const p of proteins) {
    for (let i = 1; i <= p.residues; i += 1) {
      frame.entity.push(p.entity);
      frame.position.push(i);
      frame.sequence.push(p.sequence === null ? null : 'A'.repeat(p.sequence));
      frame.uniprot.push(p.uniprot ?? null);
      frame.gene.push(p.gene ?? null);
    }
  }
  return parseResidueRows(frame, COLS);
}

describe('ESMFOLD_MAX_RESIDUES', () => {
  it('is the 400 residues the public ESM Atlas service folds', () => {
    expect(ESMFOLD_MAX_RESIDUES).toBe(400);
  });
});

describe('foldLength', () => {
  it('counts residues the way the server does', () => {
    expect(foldLength('MKT')).toBe(3);
    expect(foldLength(' MK T\n')).toBe(3);
    expect(foldLength('MKT*')).toBe(3);
    expect(foldLength('*')).toBe(0);
    expect(foldLength(null)).toBe(0);
    expect(foldLength(undefined)).toBe(0);
  });
});

describe('unfoldableEntities', () => {
  it('lists a sequence-only protein longer than the limit, and keeps the limit itself', () => {
    const rows = table([
      { entity: 'at-limit', residues: 3, sequence: ESMFOLD_MAX_RESIDUES },
      { entity: 'over', residues: 3, sequence: ESMFOLD_MAX_RESIDUES + 1 },
      { entity: 'short', residues: 3, sequence: 120 },
    ]);
    expect([...unfoldableEntities(rows)]).toEqual(['over']);
  });

  it('never lists a protein with an accession or a gene, whatever its length', () => {
    const rows = table([
      { entity: 'acc', residues: 2, sequence: 900, uniprot: 'P04637' },
      { entity: 'gene', residues: 2, sequence: 900, gene: 'TP53' },
      { entity: 'bare', residues: 2, sequence: 900 },
    ]);
    expect([...unfoldableEntities(rows)]).toEqual(['bare']);
  });

  it('lists a protein with nothing the resolver can ask', () => {
    const rows = [
      ...table([
        { entity: 'empty', residues: 2, sequence: null },
        { entity: 'ok', residues: 2, sequence: 50 },
      ]),
      // A lone stop symbol leaves no residue to fold.
      ...parseResidueRows({ entity: ['stop-only'], position: [1], sequence: ['*'] }, COLS),
    ];
    expect([...unfoldableEntities(rows)].sort()).toEqual(['empty', 'stop-only']);
  });

  it('reads the first value of each identifier across a protein, as the resolver query does', () => {
    const rows = parseResidueRows(
      {
        entity: ['P', 'P', 'P'],
        position: [1, 2, 3],
        sequence: [null, 'A'.repeat(300), 'A'.repeat(900)],
        uniprot: [null, null, null],
        gene: [null, null, null],
      },
      COLS,
    );
    expect(unfoldableEntities(rows).size).toBe(0);
  });

  it('takes the limit as an argument and skips rows with no entity', () => {
    const rows = table([{ entity: 'mid', residues: 2, sequence: 150 }]);
    expect([...unfoldableEntities(rows, 100)]).toEqual(['mid']);
    expect(unfoldableEntities(rows, 150).size).toBe(0);
    const anonymous = parseResidueRows(
      { entity: [null], position: [1], sequence: ['A'.repeat(900)] },
      COLS,
    );
    expect(unfoldableEntities(anonymous).size).toBe(0);
  });
});

describe('chooseDefaultEntity', () => {
  // The proteinannotator shape: the default order is the protein with the most
  // rows, which on a residue table is the longest one.
  const proteins: Protein[] = [
    { entity: 'short', residues: 120, sequence: 120 },
    { entity: 'longest', residues: 612, sequence: 612 },
    { entity: 'long', residues: 455, sequence: 455 },
    { entity: 'mid', residues: 380, sequence: 380 },
  ];
  const rows = table(proteins);
  const rowEntities = distinctEntities(rows);
  const available = rowEntities;
  const unrenderable = unfoldableEntities(rows);

  it('starts from the longest protein in the plain default order', () => {
    expect(rowEntities).toEqual(['longest', 'long', 'mid', 'short']);
    expect(chooseEntity({ fromFilters: null, picked: null, rowEntities, available })).toBe('longest');
  });

  it('opens on the first protein in that order that can be folded', () => {
    expect(chooseDefaultEntity({ rowEntities, available, unrenderable })).toEqual({
      entity: 'mid',
      steered: true,
    });
  });

  it('keeps the plain default when nothing is over the limit', () => {
    expect(
      chooseDefaultEntity({ rowEntities, available, unrenderable: new Set() }),
    ).toEqual({ entity: 'longest', steered: false });
  });

  it('keeps today\'s pick when no protein can be folded', () => {
    const tooLong = table([
      { entity: 'a', residues: 700, sequence: 700 },
      { entity: 'b', residues: 500, sequence: 500 },
    ]);
    const entities = distinctEntities(tooLong);
    expect(
      chooseDefaultEntity({
        rowEntities: entities,
        available: entities,
        unrenderable: unfoldableEntities(tooLong),
      }),
    ).toEqual({ entity: 'a', steered: false });
  });

  it('falls back to the first folded entity of `available` when no row entity qualifies', () => {
    expect(
      chooseDefaultEntity({
        rowEntities: ['long'],
        available: ['long', 'other'],
        unrenderable: new Set(['long']),
      }),
    ).toEqual({ entity: 'other', steered: true });
  });

  it('never returns an entity outside `available`', () => {
    expect(
      chooseDefaultEntity({ rowEntities: ['ghost', 'mid'], available: ['mid'], unrenderable: new Set(['x']) })
        .entity,
    ).toBe('mid');
    expect(
      chooseDefaultEntity({ rowEntities: [], available: [], unrenderable: new Set() }),
    ).toEqual({ entity: null, steered: false });
  });
});

describe('an explicit choice is never overridden', () => {
  const rowEntities = ['longest', 'mid'];
  const available = ['longest', 'mid'];
  const unrenderable = new Set(['longest']);

  it('honours a dashboard filter, a table pick and the agreed opening that name an unfoldable protein', () => {
    expect(
      chooseEntity({ fromFilters: 'longest', picked: 'mid', rowEntities, available, unrenderable }),
    ).toBe('longest');
    expect(
      chooseEntity({ fromFilters: null, picked: 'longest', rowEntities, available, unrenderable }),
    ).toBe('longest');
    expect(
      chooseEntity({
        fromFilters: null,
        picked: null,
        rowEntities,
        available,
        opening: 'longest',
        unrenderable,
      }),
    ).toBe('longest');
  });

  it('steers only the automatic steps', () => {
    expect(
      chooseEntity({ fromFilters: null, picked: null, rowEntities, available, unrenderable }),
    ).toBe('mid');
  });
});

describe('renderableEntities', () => {
  it('drops what the source cannot draw, so the tile adopts no opening it cannot show', () => {
    expect(renderableEntities(['a', 'b', 'c'], new Set(['a']))).toEqual(['b', 'c']);
  });

  it('keeps every entity when none can be drawn, or when nothing is refused', () => {
    expect(renderableEntities(['a', 'b'], new Set(['a', 'b']))).toEqual(['a', 'b']);
    expect(renderableEntities(['a', 'b'], new Set())).toEqual(['a', 'b']);
  });
});
