import { describe, expect, it } from 'vitest';

import {
  BRUSH_PARAM,
  DATASET_NAME,
  DATA_ASSEMBLY,
  GENES_DATASET_NAME,
  GENOME_SCALE_NAME,
  PICK_PARAM,
  buildGenomeSpySpec,
  contigsFromRows,
  effectiveMark,
  facetValues,
  facetingEnabled,
  latchSeedRows,
  regionFromInterval,
  requiredColumns,
  rowsToObjects,
  sortChromosomes,
} from './genomeSpySpec';
import type { GenomeViewConfig } from './genomeSpySpec';

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

const base: GenomeViewConfig = { chr_col: 'chr', pos_col: 'pos', score_col: 'score' };

/** The one data lane of a non-faceted spec. */
const lane = (spec: any) => spec.vconcat[0];
const marks = (spec: any) => lane(spec).layer[0];

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

describe('latchSeedRows', () => {
  const empty = { chr: [], pos: [], score: [] };
  const unusable = { chr: [null, ''], pos: [1, 2], score: [1, 2] };

  it('empty first rows do not seed contigs', () => {
    expect(latchSeedRows(null, null, 'chr', 'pos')).toBeNull();
    expect(latchSeedRows(null, empty, 'chr', 'pos')).toBeNull();
    // Rows that fail the chromosome / position guard count as no rows.
    expect(latchSeedRows(null, unusable, 'chr', 'pos')).toBeNull();
    // What a seed built from them would have fixed into the spec: no contigs.
    const { spec, contigs } = buildGenomeSpySpec({ rows: empty, config: base, colors });
    expect(contigs).toEqual([]);
    expect((spec as any).genomes[DATA_ASSEMBLY].contigs).toEqual([]);
  });

  it('latches the first non-empty rows and keeps them through a later empty fetch', () => {
    const seed = latchSeedRows(null, rows, 'chr', 'pos');
    expect(seed).toBe(rows);
    const later = { ...rows, chr: ['chr5'], pos: [1], score: [1], feature: ['z'] };
    expect(latchSeedRows(seed, later, 'chr', 'pos')).toBe(rows);
    expect(latchSeedRows(seed, empty, 'chr', 'pos')).toBe(rows);
    expect(latchSeedRows(seed, null, 'chr', 'pos')).toBe(rows);
  });
});

describe('requiredColumns / effectiveMark', () => {
  it('adds every optional column once and never duplicates', () => {
    expect(
      requiredColumns(
        {
          ...base,
          feature_col: 'feature',
          end_col: 'end',
          sample_col: 'sample',
          category_col: 'region',
        },
        'feature',
      ),
    ).toEqual(['chr', 'pos', 'score', 'end', 'feature', 'sample', 'region']);
  });

  it('degrades rect to point without an end column, but keeps bar', () => {
    expect(effectiveMark({ ...base, mark: 'rect' })).toBe('point');
    expect(effectiveMark({ ...base, mark: 'rect', end_col: 'end' })).toBe('rect');
    // A bar is a height from a baseline, which needs no interval to exist.
    expect(effectiveMark({ ...base, mark: 'bar' })).toBe('bar');
  });
});

describe('facetValues / facetingEnabled', () => {
  it('needs both the switch and a bound sample column', () => {
    expect(facetingEnabled({ ...base, facet_by_sample: true })).toBe(false);
    expect(facetingEnabled({ ...base, facet_by_sample: true, sample_col: 's' })).toBe(true);
    expect(facetingEnabled({ ...base, sample_col: 's' })).toBe(false);
  });

  it('sorts samples naturally and reports what max_facets left out', () => {
    const data = [
      { s: 'S10' },
      { s: 'S2' },
      { s: 'S1' },
      { s: 'S2' },
      { s: '' },
      { s: null as unknown as string },
    ];
    expect(facetValues(data, 's', 10)).toEqual({ kept: ['S1', 'S2', 'S10'], dropped: 0 });
    expect(facetValues(data, 's', 2)).toEqual({ kept: ['S1', 'S2'], dropped: 1 });
  });
});

describe('regionFromInterval', () => {
  const contigs = [
    { name: 'chr1', size: 1000 },
    { name: 'chr2', size: 500 },
    { name: 'chr3', size: 200 },
  ];

  it('maps a single-contig interval to a chromosome and a position range', () => {
    expect(regionFromInterval(contigs, [1100, 1300])).toEqual({
      chroms: ['chr2'],
      range: [100, 300],
    });
  });

  it('normalises a backwards drag', () => {
    expect(regionFromInterval(contigs, [1300, 1100])).toEqual({
      chroms: ['chr2'],
      range: [100, 300],
    });
  });

  it('drops the range when the brush spans several contigs', () => {
    expect(regionFromInterval(contigs, [900, 1600])).toEqual({
      chroms: ['chr1', 'chr2', 'chr3'],
      range: null,
    });
  });

  it('returns null for an absent, empty or inverted-to-zero interval', () => {
    expect(regionFromInterval(contigs, null)).toBeNull();
    expect(regionFromInterval(contigs, [5])).toBeNull();
    expect(regionFromInterval(contigs, [100, 100])).toBeNull();
    expect(regionFromInterval(contigs, [9000, 9500])).toBeNull();
  });
});

describe('buildGenomeSpySpec', () => {
  it('builds a locus-scaled point track over a data-derived assembly', () => {
    const { spec, contigs, rowCount } = buildGenomeSpySpec({ rows, config: base, colors });
    const s = spec as any;
    expect(s.assembly).toBe(DATA_ASSEMBLY);
    expect(s.genomes[DATA_ASSEMBLY].contigs.map((c: any) => c.name)).toEqual([
      'chr1',
      'chr2',
      'chr10',
      'chrX',
    ]);
    expect(contigs.map((c) => c.name)).toEqual(['chr1', 'chr2', 'chr10', 'chrX']);
    expect(s.data).toEqual({ name: DATASET_NAME });
    expect(s.datasets[DATASET_NAME]).toHaveLength(5);
    expect(rowCount).toBe(5);
    expect(s.vconcat).toHaveLength(1);
    const track = marks(s);
    expect(track.mark.type).toBe('point');
    expect(track.encoding.x).toMatchObject({ chrom: 'chr', pos: 'pos', type: 'locus' });
    expect(track.encoding.x.scale).toEqual({ name: GENOME_SCALE_NAME });
    expect(track.encoding.x2).toBeUndefined();
    expect(track.encoding.y2).toBeUndefined();
    // The pick param sits on the marks unit view, not on the layer above:
    // GenomeSpy allocates the selection texture from the mark's own view.
    expect(lane(s).params).toBeUndefined();
    expect(track.params.map((p: any) => p.name)).toEqual([PICK_PARAM]);
    // One palette hue per chromosome, cycling, no literal colours of its own.
    expect(track.encoding.color.scale.range).toEqual(['c0', 'c1', 'c2', 'c0']);
  });

  it('declares the region brush once, on the vconcat root', () => {
    const { spec } = buildGenomeSpySpec({ rows, config: base, colors });
    expect((spec as any).params.map((p: any) => p.name)).toEqual([BRUSH_PARAM]);
    expect((spec as any).params[0].select).toEqual({ type: 'interval', encodings: ['x'] });
  });

  it('omits the brush param when the region filter is off', () => {
    const { spec } = buildGenomeSpySpec({
      rows,
      config: { ...base, region_filter_enabled: false },
      colors,
    });
    expect((spec as any).params).toBeUndefined();
  });

  it('uses a built-in assembly when named and its contigs are supplied', () => {
    const assemblyContigs = [
      { name: 'chr1', size: 248956422 },
      { name: 'chr2', size: 242193529 },
    ];
    const { spec, contigs } = buildGenomeSpySpec({
      rows,
      config: { ...base, assembly: 'hg38' },
      colors,
      assemblyContigs,
    });
    expect((spec as any).assembly).toBe('hg38');
    expect((spec as any).genomes).toBeUndefined();
    expect(contigs).toEqual(assemblyContigs);
  });

  it('derives contigs when a built-in assembly is named but not yet loaded', () => {
    const { spec, contigs } = buildGenomeSpySpec({
      rows,
      config: { ...base, assembly: 'hg38' },
      colors,
    });
    expect((spec as any).assembly).toBe('hg38');
    // The spec still needs a contig list, and the rows are the only source.
    expect((spec as any).genomes[DATA_ASSEMBLY].contigs).toHaveLength(4);
    expect(contigs).toHaveLength(4);
  });

  it('falls back to the data assembly for an unknown assembly name', () => {
    const { spec } = buildGenomeSpySpec({
      rows,
      config: { ...base, assembly: 'MN908947.3' },
      colors,
    });
    expect((spec as any).assembly).toBe(DATA_ASSEMBLY);
  });

  it('draws intervals when rect and an end column are set', () => {
    const r = { chrom: ['chr1', 'chr1'], start: [10, 60], end: [50, 90], cov: [3, 9] };
    const { spec } = buildGenomeSpySpec({
      rows: r,
      config: { chr_col: 'chrom', pos_col: 'start', score_col: 'cov', end_col: 'end', mark: 'rect' },
      colors,
    });
    const track = marks(spec);
    expect(track.mark.type).toBe('rect');
    expect(track.encoding.x2).toEqual({ chrom: 'chrom', pos: 'end' });
    expect(track.encoding.y2).toBeUndefined();
  });

  it('anchors a bar at the baseline, because GenomeSpy has no area mark', () => {
    const r = { chrom: ['chr1', 'chr1'], start: [10, 60], end: [50, 90], cov: [3, 9] };
    const { spec } = buildGenomeSpySpec({
      rows: r,
      config: { chr_col: 'chrom', pos_col: 'start', score_col: 'cov', end_col: 'end', mark: 'bar' },
      colors,
    });
    const track = marks(spec);
    expect(track.mark.type).toBe('rect');
    expect(track.encoding.x2).toEqual({ chrom: 'chrom', pos: 'end' });
    expect(track.encoding.y2).toEqual({ datum: 0 });
  });

  it('colours by the category column when one is bound', () => {
    const r = {
      chr: ['chr1', 'chr1', 'chr2'],
      pos: [1, 2, 3],
      score: [1, 2, 3],
      region: ['S', 'N', 'S'],
    };
    const { spec } = buildGenomeSpySpec({
      rows: r,
      config: { ...base, category_col: 'region' },
      colors,
    });
    const color = marks(spec).encoding.color;
    expect(color.field).toBe('region');
    expect(color.scale.domain).toEqual(['N', 'S']);
  });

  it('adds the threshold rule only when a threshold is set', () => {
    const withRule = buildGenomeSpySpec({ rows, config: { ...base, score_threshold: 5 }, colors });
    const layers = lane(withRule.spec).layer;
    expect(layers).toHaveLength(2);
    expect(layers[1].mark).toMatchObject({ type: 'rule', color: 'rule' });
    expect(layers[1].encoding.y.datum).toBe(5);
    const without = buildGenomeSpySpec({ rows, config: { ...base, score_threshold: null }, colors });
    expect(lane(without.spec).layer).toHaveLength(1);
  });

  it('carries the selection column into the dataset when selection is on', () => {
    const { spec } = buildGenomeSpySpec({
      rows,
      config: { ...base, selection_enabled: true, selection_column: 'feature' },
      colors,
    });
    expect((spec as any).datasets[DATASET_NAME][0]).toHaveProperty('feature', 'a');
  });

  describe('per-sample lanes', () => {
    const r = {
      chr: ['chr1', 'chr1', 'chr1', 'chr1'],
      pos: [1, 2, 1, 2],
      score: [5, 6, 7, 8],
      s: ['S1', 'S1', 'S2', 'S2'],
    };
    const faceted: GenomeViewConfig = { ...base, sample_col: 's', facet_by_sample: true };

    it('stacks one filtered lane per sample over one shared dataset', () => {
      const { spec, facets, droppedFacets } = buildGenomeSpySpec({ rows: r, config: faceted, colors });
      const s = spec as any;
      expect(facets).toEqual(['S1', 'S2']);
      expect(droppedFacets).toBe(0);
      expect(s.vconcat).toHaveLength(2);
      expect(s.vconcat[0].transform).toEqual([{ type: 'filter', expr: 'datum["s"] === "S1"' }]);
      expect(s.vconcat[1].transform).toEqual([{ type: 'filter', expr: 'datum["s"] === "S2"' }]);
      expect(s.vconcat[0].title.text).toBe('S1');
      // One dataset, N lanes: the rows are not copied per lane.
      expect(Object.keys(s.datasets)).toEqual([DATASET_NAME]);
      expect(s.datasets[DATASET_NAME]).toHaveLength(4);
      // The x scale is shared so every lane pans and zooms together.
      expect(s.resolve).toMatchObject({ scale: { x: 'shared' }, axis: { x: 'shared' } });
    });

    it('gives every lane its own pick param, because names must be unique', () => {
      const { spec } = buildGenomeSpySpec({ rows: r, config: faceted, colors });
      const names = (spec as any).vconcat.map((v: any) => v.layer[0].params[0].name);
      expect(names).toEqual([`${PICK_PARAM}_0`, `${PICK_PARAM}_1`]);
      expect(new Set(names).size).toBe(names.length);
    });

    it('caps the lanes at max_facets and reports the remainder', () => {
      const { spec, facets, droppedFacets } = buildGenomeSpySpec({
        rows: r,
        config: { ...faceted, max_facets: 1 },
        colors,
      });
      expect(facets).toEqual(['S1']);
      expect(droppedFacets).toBe(1);
      expect((spec as any).vconcat).toHaveLength(1);
    });

    it('stays a single lane when the sample column is not bound', () => {
      const { spec, facets } = buildGenomeSpySpec({
        rows: r,
        config: { ...base, facet_by_sample: true },
        colors,
      });
      expect(facets).toEqual([]);
      expect((spec as any).vconcat).toHaveLength(1);
    });
  });

  describe('gene annotation lane', () => {
    const genes = [
      { name: 'AAA', chrom: 'chr1', start: 10, end: 200, strand: '+' },
      { name: 'BBB', chrom: 'chr2', start: 5, end: 40, strand: '-' },
      { name: 'CCC', chrom: 'chr99', start: 5, end: 40, strand: '+' },
    ];

    it('appends a lane with its own dataset and a semantic-zoom label layer', () => {
      const { spec, geneCount } = buildGenomeSpySpec({ rows, config: base, colors, genes });
      const s = spec as any;
      // chr99 is not a contig in view, so its gene is dropped.
      expect(geneCount).toBe(2);
      expect(s.vconcat).toHaveLength(2);
      const annotation = s.vconcat[1];
      expect(annotation.name).toBe('annotation');
      expect(annotation.data).toEqual({ name: GENES_DATASET_NAME });
      expect(s.datasets[GENES_DATASET_NAME]).toHaveLength(2);
      const [rect, labels] = annotation.layer;
      expect(rect.mark.type).toBe('rect');
      expect(rect.encoding.x).toMatchObject({ chrom: 'chrom', pos: 'start', type: 'locus' });
      expect(rect.encoding.x2).toEqual({ chrom: 'chrom', pos: 'end' });
      // Constant positional values are normalised within the lane, so the lane
      // resolves no y scale against the data tracks' score axis.
      expect(rect.encoding.y).toEqual({ value: 0.3 });
      expect(labels.mark.type).toBe('text');
      expect(labels.opacity).toMatchObject({ values: [0, 1] });
    });

    it('draws no lane without genes', () => {
      const { spec, geneCount } = buildGenomeSpySpec({ rows, config: base, colors, genes: [] });
      expect(geneCount).toBe(0);
      expect((spec as any).vconcat).toHaveLength(1);
      expect((spec as any).datasets[GENES_DATASET_NAME]).toBeUndefined();
    });

    it('sits under every sample lane, not inside one', () => {
      const r = { chr: ['chr1', 'chr1'], pos: [1, 2], score: [5, 6], s: ['S1', 'S2'] };
      const { spec } = buildGenomeSpySpec({
        rows: r,
        config: { ...base, sample_col: 's', facet_by_sample: true },
        colors,
        genes,
      });
      const names = (spec as any).vconcat.map((v: any) => v.name);
      expect(names).toEqual(['track_0', 'track_1', 'annotation']);
    });
  });
});
