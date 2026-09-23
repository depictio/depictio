import { describe, expect, it } from 'vitest';

import { BRUSH_PARAM, GENES_DATASET_NAME, GENOME_SCALE_NAME } from '../genomespy/genomeSpySpec';
import { parseCnvRows } from './cnvLayout';
import { buildCnvLocusSpec, MAX_LOCUS_LANES, toLocusData } from './cnvLocusSpec';
import type { CnvLocusColors, CnvLocusInput } from './cnvLocusSpec';

const COLORS: CnvLocusColors = {
  textColor: 'text',
  gridColor: 'grid',
  bin: 'bin',
  baf: 'baf',
  segment: { gain: 'g', neutral: 'n', loss: 'l' },
  major: 'maj',
  minor: 'min',
  gene: 'gene',
};

const COLS = {
  sample: 'sample',
  chrom: 'chrom',
  start: 'start',
  end: 'end',
  log2: 'log2',
  baf: 'baf',
  copyNumber: 'cn',
  minorCopyNumber: 'minor',
  segment: 'kind',
  label: 'label',
};

function rows(withMinor = true) {
  const raw: Record<string, unknown[]> = {
    sample: ['A', 'A', 'A', 'B', 'B'],
    chrom: ['chr1', 'chr1', 'chr1', 'chr2', 'chr2'],
    start: [0, 1000, 0, 0, 0],
    end: [1000, 2000, 2000, 1000, 1000],
    log2: [0.6, 0.5, 0.58, -1, -1],
    baf: [0.33, 0.66, 0.33, 0.02, 0.02],
    cn: [3, 3, 3, 1, 1],
    minor: withMinor ? [1, 1, 1, 0, 0] : [null, null, null, null, null],
    kind: ['bin', 'bin', 'segment', 'bin', 'segment'],
    label: [null, null, 'CN 3 gain', null, 'CN 1 loss'],
  };
  return parseCnvRows(raw, withMinor ? COLS : { ...COLS, minorCopyNumber: null });
}

function input(overrides: Partial<CnvLocusInput> = {}): CnvLocusInput {
  return {
    data: toLocusData(rows(), { samples: ['A'], gain: 0.3, loss: -0.3, maxBins: 1000 }),
    lanes: ['A'],
    faceted: false,
    showBaf: true,
    yRange: 3,
    pointSize: 3,
    gainThreshold: 0.3,
    lossThreshold: -0.3,
    colors: COLORS,
    brush: true,
    ...overrides,
  };
}

function trackNames(spec: Record<string, unknown>): string[] {
  return (spec.vconcat as Array<{ name: string }>).map((v) => v.name);
}

describe('toLocusData', () => {
  it('narrows to the requested sample and derives nMajor, the mirror and the class', () => {
    const data = toLocusData(rows(), { samples: ['A'], gain: 0.3, loss: -0.3, maxBins: 1000 });
    expect(data.every((d) => d.sample === 'A')).toBe(true);
    const segment = data.find((d) => d.kind === 'segment');
    expect(segment).toMatchObject({ cn: 3, minor: 1, major: 2, cls: 'gain', mid: 1000 });
    expect(segment?.baf_mirror).toBeCloseTo(0.67);
    // Bins carry no mirror: only a segment's BAF is drawn as a pair of bands.
    expect(data.filter((d) => d.kind === 'bin').every((d) => d.baf_mirror === null)).toBe(true);
  });

  it('keeps every segment while averaging bins down to the guard', () => {
    const data = toLocusData(rows(), { samples: null, gain: 0.3, loss: -0.3, maxBins: 2 });
    expect(data.filter((d) => d.kind === 'segment')).toHaveLength(2);
    expect(data.filter((d) => d.kind === 'bin').length).toBeLessThanOrEqual(2);
  });

  it('leaves the allele split null when no minor column is bound', () => {
    const data = toLocusData(rows(false), { samples: null, gain: 0.3, loss: -0.3, maxBins: 100 });
    expect(data.every((d) => d.minor === null && d.major === null)).toBe(true);
  });
});

describe('buildCnvLocusSpec', () => {
  it('stacks the ASCAT tracks: allelic copy number, log2, BAF', () => {
    const built = buildCnvLocusSpec(input());
    expect(trackNames(built.spec)).toEqual(['cn', 'log2', 'baf']);
    expect(built.tracks).toEqual({ copyNumber: 'allelic', baf: true });
    const cn = (built.spec.vconcat as Array<{ layer: Array<{ name: string }> }>)[0];
    expect(cn.layer.map((l) => l.name)).toEqual(['cn-minor', 'cn-major']);
  });

  it('falls back to one total copy-number rule without the minor allele', () => {
    const data = toLocusData(rows(false), { samples: ['A'], gain: 0.3, loss: -0.3, maxBins: 100 });
    const built = buildCnvLocusSpec(input({ data }));
    expect(built.tracks.copyNumber).toBe('total');
  });

  it('drops the BAF track when switched off', () => {
    expect(trackNames(buildCnvLocusSpec(input({ showBaf: false })).spec)).toEqual(['cn', 'log2']);
  });

  it('gives each sample its own tracks when faceted, capped', () => {
    const data = toLocusData(rows(), { samples: null, gain: 0.3, loss: -0.3, maxBins: 100 });
    const built = buildCnvLocusSpec(input({ data, lanes: ['A', 'B'], faceted: true }));
    expect(trackNames(built.spec)).toEqual(['cn_0', 'log2_0', 'baf_0', 'cn_1', 'log2_1', 'baf_1']);
    const many = Array.from({ length: MAX_LOCUS_LANES + 2 }, (_, i) => `S${i}`);
    const capped = buildCnvLocusSpec(input({ data, lanes: many, faceted: true }));
    expect(trackNames(capped.spec).filter((n) => n.startsWith('log2'))).toHaveLength(MAX_LOCUS_LANES);
  });

  it('declares the region brush on the root and names the genome scale', () => {
    const built = buildCnvLocusSpec(input());
    expect(built.spec.params).toEqual([
      { name: BRUSH_PARAM, select: { type: 'interval', encodings: ['x'] } },
    ]);
    expect(JSON.stringify(built.spec)).toContain(`"name":"${GENOME_SCALE_NAME}"`);
    expect(buildCnvLocusSpec(input({ brush: false })).spec.params).toBeUndefined();
  });

  it('lays the genome out from the rows and keeps genes on known contigs only', () => {
    const built = buildCnvLocusSpec(
      input({
        genes: [
          { name: 'G1', chrom: 'chr1', start: 100, end: 500, strand: '+' },
          { name: 'G2', chrom: 'chr9', start: 100, end: 500, strand: '+' },
          { name: 'G3', chrom: 'chr1', start: 9e9, end: 9e9 + 10, strand: '+' },
        ],
      }),
    );
    expect(built.contigs.map((c) => c.name)).toEqual(['chr1']);
    expect(built.geneCount).toBe(1);
    const names = trackNames(built.spec);
    expect(names[names.length - 1]).toBe('annotation');
    expect((built.spec.datasets as Record<string, unknown[]>)[GENES_DATASET_NAME]).toHaveLength(1);
  });
});
