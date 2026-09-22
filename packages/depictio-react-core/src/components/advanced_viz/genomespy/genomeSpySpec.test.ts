import { describe, expect, it } from 'vitest';

import {
  BRUSH_PARAM,
  DATASET_NAME,
  DATA_ASSEMBLY,
  PICK_PARAM,
  buildGenomeSpySpec,
  contigsFromRows,
  effectiveMark,
  requiredColumns,
  rowsToObjects,
  sortChromosomes,
} from './genomeSpySpec';

const colors = {
  textColor: 'text',
  gridColor: 'grid',
  ruleColor: 'rule',
  palette: ['c0', 'c1', 'c2'],
};

const rows = {
  chr: ['chr2', 'chr1', 'chrX', 'chr1', null, 'chr10'],
  pos: [100, 50, 7, 900, 1, 5],
  score: [1.5, 2.5, 8.1, 0.2, 3, 4],
  feature: ['a', 'b', 'c', 'd', 'e', 'f'],
};

const base = { chr_col: 'chr', pos_col: 'pos', score_col: 'score' };

describe('sortChromosomes', () => {
  it('orders numerically, then X/Y/MT, then the rest', () => {
    expect(sortChromosomes(['chrX', 'chr10', 'chr2', 'chrMT', 'scaffold_1', 'chr1', 'chrY'])).toEqual([
      'chr1',
      'chr2',
      'chr10',
      'chrX',
      'chrY',
      'chrMT',
      'scaffold_1',
    ]);
  });
});

describe('rowsToObjects', () => {
  it('drops rows without a chromosome or position and keeps only the asked columns', () => {
    const out = rowsToObjects(rows, ['chr', 'pos', 'score'], 'chr', 'pos');
    expect(out).toHaveLength(5);
    expect(out[0]).toEqual({ chr: 'chr2', pos: 100, score: 1.5 });
    expect(out.every((r) => !('feature' in r))).toBe(true);
  });
});

describe('contigsFromRows', () => {
  it('sizes each contig past its last position, in natural order', () => {
    const data = rowsToObjects(rows, ['chr', 'pos'], 'chr', 'pos');
    const contigs = contigsFromRows(data, 'chr', 'pos');
    expect(contigs.map((c) => c.name)).toEqual(['chr1', 'chr2', 'chr10', 'chrX']);
    const chr1 = contigs.find((c) => c.name === 'chr1')!;
    expect(chr1.size).toBeGreaterThan(900);
  });

  it('uses the interval end when one is bound', () => {
    const data = [{ chr: 'chr1', start: 10, end: 500 }];
    expect(contigsFromRows(data, 'chr', 'start', 'end')[0].size).toBeGreaterThan(500);
  });
});

describe('requiredColumns / effectiveMark', () => {
  it('adds optional columns once and never duplicates', () => {
    expect(requiredColumns({ ...base, feature_col: 'feature', end_col: 'end' }, 'feature')).toEqual([
      'chr',
      'pos',
      'score',
      'end',
      'feature',
    ]);
  });

  it('degrades rect to point without an end column', () => {
    expect(effectiveMark({ ...base, mark: 'rect' })).toBe('point');
    expect(effectiveMark({ ...base, mark: 'rect', end_col: 'end' })).toBe('rect');
  });
});

describe('buildGenomeSpySpec', () => {
  it('builds a locus-scaled point track over a data-derived assembly', () => {
    const spec = buildGenomeSpySpec({ rows, config: base, colors }) as any;
    expect(spec.assembly).toBe(DATA_ASSEMBLY);
    expect(spec.genomes[DATA_ASSEMBLY].contigs.map((c: any) => c.name)).toEqual([
      'chr1',
      'chr2',
      'chr10',
      'chrX',
    ]);
    expect(spec.data).toEqual({ name: DATASET_NAME });
    expect(spec.datasets[DATASET_NAME]).toHaveLength(5);
    const track = spec.layer[0];
    expect(track.mark.type).toBe('point');
    expect(track.encoding.x).toMatchObject({ chrom: 'chr', pos: 'pos', type: 'locus' });
    expect(track.encoding.x2).toBeUndefined();
    expect(track.params.map((p: any) => p.name)).toEqual([PICK_PARAM, BRUSH_PARAM]);
    // One palette hue per chromosome, cycling, no literal colours of its own.
    expect(track.encoding.color.scale.range).toEqual(['c0', 'c1', 'c2', 'c0']);
    expect(spec.layer).toHaveLength(1);
  });

  it('uses a built-in assembly when named and skips the contig list', () => {
    const spec = buildGenomeSpySpec({ rows, config: { ...base, assembly: 'hg38' }, colors }) as any;
    expect(spec.assembly).toBe('hg38');
    expect(spec.genomes).toBeUndefined();
  });

  it('falls back to the data assembly for an unknown assembly name', () => {
    const spec = buildGenomeSpySpec({ rows, config: { ...base, assembly: 'MN908947.3' }, colors }) as any;
    expect(spec.assembly).toBe(DATA_ASSEMBLY);
  });

  it('draws intervals when rect and an end column are set', () => {
    const r = { chrom: ['chr1', 'chr1'], start: [10, 60], end: [50, 90], cov: [3, 9] };
    const spec = buildGenomeSpySpec({
      rows: r,
      config: { chr_col: 'chrom', pos_col: 'start', score_col: 'cov', end_col: 'end', mark: 'rect' },
      colors,
    }) as any;
    const track = spec.layer[0];
    expect(track.mark.type).toBe('rect');
    expect(track.encoding.x2).toEqual({ chrom: 'chrom', pos: 'end' });
  });

  it('adds the threshold rule only when a threshold is set', () => {
    const withRule = buildGenomeSpySpec({ rows, config: { ...base, score_threshold: 5 }, colors }) as any;
    expect(withRule.layer).toHaveLength(2);
    expect(withRule.layer[1].mark).toMatchObject({ type: 'rule', color: 'rule' });
    expect(withRule.layer[1].encoding.y.datum).toBe(5);
    const without = buildGenomeSpySpec({ rows, config: { ...base, score_threshold: null }, colors }) as any;
    expect(without.layer).toHaveLength(1);
  });

  it('carries the selection column into the dataset when selection is on', () => {
    const spec = buildGenomeSpySpec({
      rows,
      config: { ...base, selection_enabled: true, selection_column: 'feature' },
      colors,
    }) as any;
    expect(spec.datasets[DATASET_NAME][0]).toHaveProperty('feature', 'a');
  });
});
