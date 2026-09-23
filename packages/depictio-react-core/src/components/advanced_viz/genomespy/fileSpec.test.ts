import { describe, expect, it } from 'vitest';

import {
  DEFAULT_TABIX_COLUMNS,
  DEFAULT_WINDOW_SIZE,
  buildFileGenomeSpec,
  fetchIndexedFileManifest,
  fileTrackOptions,
  infoFieldTransforms,
  laneSpecFor,
  lazyDataFor,
  needsIndexUrl,
} from './fileSpec';
import type { IndexedFileEntry, IndexedFileManifest } from './fileSpec';
import type { GenomeSpyThemeColors } from './genomeSpySpec';

const colors: GenomeSpyThemeColors = {
  textColor: '#222',
  gridColor: '#ccc',
  ruleColor: '#f00',
  palette: ['#1f77b4', '#ff7f0e', '#2ca02c'],
};

function entry(overrides: Partial<IndexedFileEntry> = {}): IndexedFileEntry {
  return {
    sample: 'NA12878',
    name: 'NA12878.vcf.gz',
    size_bytes: 1234,
    url: 'https://minio/bucket/indexed_files/dc/NA12878/NA12878.vcf.gz?sig=a',
    index_url: 'https://minio/bucket/indexed_files/dc/NA12878/NA12878.vcf.gz.tbi?sig=b',
    ...overrides,
  };
}

function manifest(overrides: Partial<IndexedFileManifest> = {}): IndexedFileManifest {
  return {
    data_collection_id: '646b0f3c1e4a2d7f8e5b8d00',
    format: 'vcf',
    index_suffix: '.tbi',
    assembly: 'hg38',
    sample_col: 'sample',
    expires_in: 900,
    files: [entry()],
    ...overrides,
  };
}

describe('lazyDataFor', () => {
  it('declares the vcf source with an explicit index url', () => {
    const { lazy } = lazyDataFor('vcf', entry());
    expect(lazy.type).toBe('vcf');
    expect(lazy.url).toBe(entry().url);
    // Presigned: the index signature cannot be derived from the file's, so it
    // must be passed rather than left to the library's `url + ".tbi"`.
    expect(lazy.indexUrl).toBe(entry().index_url);
    expect(lazy.windowSize).toBe(DEFAULT_WINDOW_SIZE.vcf);
  });

  it('maps fasta onto the indexedFasta source', () => {
    const { lazy } = lazyDataFor('fasta', entry({ name: 'ref.fa', index_url: 'x.fai' }));
    expect(lazy.type).toBe('indexedFasta');
  });

  it('gives bigwig pixelsPerBin and no index or window', () => {
    const { lazy } = lazyDataFor('bigwig', entry({ index_url: null }));
    expect(lazy.pixelsPerBin).toBe(1);
    expect(lazy.indexUrl).toBeUndefined();
    expect(lazy.windowSize).toBeUndefined();
  });

  it('uses the gff3 window size from the reference spec', () => {
    expect(lazyDataFor('gff3', entry()).lazy.windowSize).toBe(2_000_000);
  });

  it('honours an explicit window size override', () => {
    expect(lazyDataFor('vcf', entry(), { windowSize: 250_000 }).lazy.windowSize).toBe(250_000);
  });

  it('declares tabix columns, defaulting to BED order', () => {
    expect(lazyDataFor('tabix', entry()).lazy.columns).toEqual([...DEFAULT_TABIX_COLUMNS]);
    expect(lazyDataFor('tabix', entry(), { tabixColumns: ['c', 's', 'e'] }).lazy.columns).toEqual([
      'c',
      's',
      'e',
    ]);
  });

  it('only sets addChrPrefix on the tabix-backed formats, and only when asked', () => {
    expect(lazyDataFor('vcf', entry(), { addChrPrefix: true }).lazy.addChrPrefix).toBe(true);
    expect(lazyDataFor('vcf', entry()).lazy.addChrPrefix).toBeUndefined();
    expect(lazyDataFor('bigwig', entry({ index_url: null }), { addChrPrefix: true }).lazy
      .addChrPrefix).toBeUndefined();
  });

  it('refuses a format that needs an index when the manifest has none', () => {
    expect(() => lazyDataFor('vcf', entry({ index_url: null }))).toThrow(/index sidecar/);
    expect(needsIndexUrl('bigwig')).toBe(false);
    expect(needsIndexUrl('bam')).toBe(true);
  });
});

describe('infoFieldTransforms', () => {
  it('promotes INFO keys through formula transforms, guarding a missing INFO', () => {
    const [t] = infoFieldTransforms(['CLNSIG']) as Array<Record<string, string>>;
    expect(t.type).toBe('formula');
    expect(t.as).toBe('CLNSIG');
    expect(t.expr).toContain('datum.INFO == null');
    expect(t.expr).toContain('"CLNSIG"');
  });

  it('unwraps the single-element arrays @gmod/vcf returns for INFO values', () => {
    // Verified against the public ClinVar VCF: CLNSIG arrives as
    // ["Pathogenic"], and an array never matches an ordinal domain, so the
    // lane silently draws nothing without this.
    const [t] = infoFieldTransforms(['CLNSIG']) as Array<Record<string, string>>;
    expect(t.expr).toContain('isArray(');
    expect(t.expr).toContain('[0]');
  });

  it('is empty when no fields are declared', () => {
    expect(infoFieldTransforms(null)).toEqual([]);
    expect(infoFieldTransforms([])).toEqual([]);
  });
});

describe('laneSpecFor', () => {
  it('draws a vcf as sticks and balls on a locus axis', () => {
    const lane = laneSpecFor('vcf', entry(), {}, colors) as any;
    expect(lane.encoding.x).toMatchObject({ chrom: 'CHROM', pos: 'POS', type: 'locus' });
    expect(lane.layer.map((l: any) => l.name)).toEqual(['sticks', 'balls']);
    expect(lane.layer[0].mark.type).toBe('rule');
    expect(lane.layer[1].mark.type).toBe('point');
  });

  it('ranks and colours a vcf by the declared INFO category', () => {
    const lane = laneSpecFor(
      'vcf',
      entry(),
      { infoFields: ['CLNSIG'], categoryField: 'CLNSIG', categories: ['Pathogenic', 'Benign'] },
      colors,
    ) as any;
    expect(lane.transform).toHaveLength(1);
    expect(lane.encoding.y).toMatchObject({ field: 'CLNSIG', type: 'ordinal' });
    expect(lane.encoding.color.scale.range).toEqual([colors.palette[0], colors.palette[1]]);
  });

  it('draws bigwig coverage as rect bars from the score field', () => {
    const lane = laneSpecFor('bigwig', entry({ index_url: null }), {}, colors) as any;
    expect(lane.mark.type).toBe('rect');
    expect(lane.encoding.y.field).toBe('score');
    expect(lane.encoding.x2).toMatchObject({ chrom: 'chrom', pos: 'end' });
    expect(lane.data.lazy.pixelsPerBin).toBe(1);
  });

  it('packs gff3 transcripts into lanes with a pileup transform', () => {
    const lane = laneSpecFor('gff3', entry(), {}, colors) as any;
    const kinds = lane.transform.map((t: any) => t.type);
    expect(kinds).toContain('flatten');
    expect(kinds).toContain('pileup');
    expect(lane.encoding.x.chrom).toBe('seq_id');
  });

  it('packs tabix and bigbed intervals with the declared column names', () => {
    const lane = laneSpecFor('tabix', entry(), { tabixColumns: ['c', 's', 'e'] }, colors) as any;
    expect(lane.encoding.x).toMatchObject({ chrom: 'c', pos: 's' });
    expect(lane.encoding.x2).toMatchObject({ chrom: 'c', pos: 'e' });
    const bb = laneSpecFor('bigbed', entry({ index_url: null }), {}, colors) as any;
    expect(bb.encoding.x.pos).toBe('chromStart');
  });

  it('switches a bam between a coverage transform and a pileup', () => {
    const cov = laneSpecFor('bam', entry(), { bamView: 'coverage' }, colors) as any;
    expect(cov.transform.map((t: any) => t.type)).toContain('coverage');
    expect(cov.encoding.y.field).toBe('coverage');
    const pile = laneSpecFor('bam', entry(), { bamView: 'pileup' }, colors) as any;
    expect(pile.transform.map((t: any) => t.type)).toContain('pileup');
    expect(pile.encoding.y.field).toBe('_lane');
  });
});

describe('buildFileGenomeSpec', () => {
  const contigs = [
    { name: 'chr1', size: 248_956_422 },
    { name: 'chr2', size: 242_193_529 },
  ];

  it('stacks one lane per sample on a shared genome axis', () => {
    const built = buildFileGenomeSpec({
      manifest: manifest({
        files: [entry(), entry({ sample: 'NA12891', name: 'NA12891.vcf.gz' })],
      }),
      colors,
      assemblyContigs: contigs,
    });
    expect(built.lanes).toEqual(['NA12878', 'NA12891']);
    expect(built.droppedLanes).toBe(0);
    const spec = built.spec as any;
    expect(spec.vconcat).toHaveLength(2);
    expect(spec.assembly).toBe('hg38');
    expect(spec.resolve.scale.x).toBe('shared');
    // No materialised dataset: every lane reads its own lazy source.
    expect(spec.datasets).toBeUndefined();
    expect(spec.vconcat[0].data.lazy.type).toBe('vcf');
  });

  it('caps the lanes and reports how many it dropped', () => {
    const files = ['a', 'b', 'c'].map((s) => entry({ sample: s, name: `${s}.vcf.gz` }));
    const built = buildFileGenomeSpec({
      manifest: manifest({ files }),
      options: { maxLanes: 2 },
      colors,
      assemblyContigs: contigs,
    });
    expect(built.lanes).toEqual(['a', 'b']);
    expect(built.droppedLanes).toBe(1);
  });

  it('skips a sample whose index is missing rather than throwing', () => {
    const built = buildFileGenomeSpec({
      manifest: manifest({
        files: [entry(), entry({ sample: 'broken', index_url: null })],
      }),
      colors,
      assemblyContigs: contigs,
    });
    expect(built.lanes).toEqual(['NA12878']);
  });

  it('declares the region brush on the root, once, when asked', () => {
    const withBrush = buildFileGenomeSpec({
      manifest: manifest(),
      colors,
      assemblyContigs: contigs,
      regionBrushEnabled: true,
    }).spec as any;
    expect(withBrush.params).toHaveLength(1);
    expect(withBrush.params[0].select.type).toBe('interval');
    const without = buildFileGenomeSpec({ manifest: manifest(), colors, assemblyContigs: contigs })
      .spec as any;
    expect(without.params).toBeUndefined();
  });

  it('lets the tile override the assembly the collection declares', () => {
    const built = buildFileGenomeSpec({
      manifest: manifest({ assembly: null }),
      assembly: 'mm10',
      colors,
      assemblyContigs: contigs,
    });
    expect((built.spec as any).assembly).toBe('mm10');
  });

  it('refuses to build without an assembly', () => {
    expect(() =>
      buildFileGenomeSpec({ manifest: manifest({ assembly: null }), colors, assemblyContigs: contigs }),
    ).toThrow(/assembly/);
  });

  it('refuses a non built-in assembly with no contig sizes', () => {
    expect(() =>
      buildFileGenomeSpec({ manifest: manifest({ assembly: 'MN908947.3' }), colors }),
    ).toThrow(/contig sizes/);
  });
});

describe('fileTrackOptions', () => {
  it('reads only the file_* config keys, plus the two cosmetic ones', () => {
    const opts = fileTrackOptions({
      opacity: 0.5,
      point_size: 7,
      file_info_fields: ['CLNSIG'],
      file_category_field: 'CLNSIG',
      file_add_chr_prefix: true,
      file_window_size: 500_000,
      file_max_lanes: 3,
      file_bam_view: 'pileup',
    });
    expect(opts).toMatchObject({
      addChrPrefix: true,
      windowSize: 500_000,
      infoFields: ['CLNSIG'],
      categoryField: 'CLNSIG',
      maxLanes: 3,
      bamView: 'pileup',
      opacity: 0.5,
      pointSize: 7,
    });
  });

  it('defaults an empty config to the model defaults', () => {
    const opts = fileTrackOptions({});
    expect(opts.maxLanes).toBe(8);
    expect(opts.bamView).toBe('coverage');
    expect(opts.addChrPrefix).toBeUndefined();
  });
});

describe('fetchIndexedFileManifest', () => {
  it('hits the files route and returns the payload', async () => {
    const payload = manifest();
    const seen: string[] = [];
    const res = await fetchIndexedFileManifest('dc1', async (url) => {
      seen.push(url);
      return { ok: true, status: 200, json: async () => payload } as Response;
    });
    expect(seen[0]).toBe('/depictio/api/v1/files/indexed/dc1');
    expect(res.format).toBe('vcf');
  });

  it('turns a non-ok response into an error the tile can show', async () => {
    await expect(
      fetchIndexedFileManifest('dc1', async () => ({ ok: false, status: 404 }) as Response),
    ).rejects.toThrow(/404/);
  });
});
