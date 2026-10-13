import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  canonicalSnakemakeUrl,
  metaYamlUrl,
  parseSnakemakeOutputs,
  fetchSnakemakeMeta,
} from '../catalog/fromSnakemake';

describe('canonicalSnakemakeUrl', () => {
  it('rewrites /blob/ → /tree/ and strips a trailing /meta.yaml', () => {
    expect(
      canonicalSnakemakeUrl(
        'https://github.com/snakemake/snakemake-wrappers/blob/master/bio/samtools/sort/meta.yaml',
      ),
    ).toBe('https://github.com/snakemake/snakemake-wrappers/tree/master/bio/samtools/sort');
  });

  it('maps a readthedocs wrapper page onto the GitHub wrapper dir', () => {
    expect(
      canonicalSnakemakeUrl(
        'https://snakemake-wrappers.readthedocs.io/en/stable/wrappers/bio/samtools/sort.html',
      ),
    ).toBe('https://github.com/snakemake/snakemake-wrappers/tree/master/bio/samtools/sort');
  });

  it('leaves an unrecognised URL trimmed-only', () => {
    expect(canonicalSnakemakeUrl('  https://example.com/x  ')).toBe('https://example.com/x');
  });
});

describe('metaYamlUrl', () => {
  it('derives the raw meta.yaml URL from a wrapper dir', () => {
    expect(
      metaYamlUrl('https://github.com/snakemake/snakemake-wrappers/tree/master/bio/samtools/sort'),
    ).toBe(
      'https://raw.githubusercontent.com/snakemake/snakemake-wrappers/master/bio/samtools/sort/meta.yaml',
    );
  });

  it('works straight from a readthedocs page too', () => {
    expect(
      metaYamlUrl('https://snakemake-wrappers.readthedocs.io/en/stable/wrappers/bio/samtools/sort.html'),
    ).toBe(
      'https://raw.githubusercontent.com/snakemake/snakemake-wrappers/master/bio/samtools/sort/meta.yaml',
    );
  });
});

describe('parseSnakemakeOutputs', () => {
  it('turns a list of description strings into channels with empty patterns and unique names', () => {
    const outs = parseSnakemakeOutputs(['SAM/BAM/CRAM file', 'SAM/BAM/CRAM index file (optional)']);
    expect(outs).toEqual([
      { name: 'sam_bam_cram', pattern: '', description: 'SAM/BAM/CRAM file', type: 'file' },
      {
        name: 'sam_bam_cram_2',
        pattern: '',
        description: 'SAM/BAM/CRAM index file (optional)',
        type: 'file',
      },
    ]);
  });

  it('ignores a non-list output', () => {
    expect(parseSnakemakeOutputs(undefined)).toEqual([]);
    expect(parseSnakemakeOutputs('a string')).toEqual([]);
  });
});

const SAMPLE = `name: samtools sort
description: Sort a bam file with samtools.
url: http://www.htslib.org/
authors:
  - Johannes Köster
input:
  - SAM/BAM/CRAM file
output:
  - SAM/BAM/CRAM file
  - SAM/BAM/CRAM index file (optional)
`;

describe('fetchSnakemakeMeta', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('fetches, parses and maps identity + outputs', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(SAMPLE, { status: 200 })),
    );
    const meta = await fetchSnakemakeMeta(
      'https://github.com/snakemake/snakemake-wrappers/tree/master/bio/samtools/sort',
    );
    expect(meta.name).toBe('samtools sort');
    expect(meta.description).toBe('Sort a bam file with samtools.');
    expect(meta.homepage).toBe('http://www.htslib.org/');
    expect(meta.biotools_url).toBe('');
    expect(meta.source_url).toBe(
      'https://github.com/snakemake/snakemake-wrappers/tree/master/bio/samtools/sort',
    );
    expect(meta.outputs).toHaveLength(2);
  });

  it('raises on a non-OK response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('', { status: 404 })),
    );
    await expect(
      fetchSnakemakeMeta('https://github.com/snakemake/snakemake-wrappers/tree/master/bio/x'),
    ).rejects.toThrow(/HTTP 404/);
  });
});
