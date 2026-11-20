import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  canonicalNfCoreUrl,
  metaYmlUrl,
  parseOutputChannels,
  fetchNfCoreMeta,
  expandPattern,
} from '../catalog/fromNfCore';

afterEach(() => vi.unstubAllGlobals());

const MODULE = 'https://github.com/nf-core/modules/tree/master/modules/nf-core/mosdepth';

describe('canonicalNfCoreUrl', () => {
  // `dev catalog validate` checks nf_core_url against the vendored module index
  // in its DIRECTORY form; the docs link to meta.yml, so the two disagreed and
  // real modules were rejected (the failure PR #904 hit).
  it('strips /meta.yml and /main.nf', () => {
    expect(canonicalNfCoreUrl(`${MODULE}/meta.yml`)).toBe(MODULE);
    expect(canonicalNfCoreUrl(`${MODULE}/main.nf`)).toBe(MODULE);
  });

  it('rewrites /blob/ to /tree/', () => {
    expect(
      canonicalNfCoreUrl(
        'https://github.com/nf-core/modules/blob/master/modules/nf-core/mosdepth/meta.yml',
      ),
    ).toBe(MODULE);
  });

  it('drops trailing slashes and surrounding whitespace', () => {
    expect(canonicalNfCoreUrl(`  ${MODULE}///  `)).toBe(MODULE);
  });

  it('leaves a non-nf-core URL alone', () => {
    expect(canonicalNfCoreUrl('https://example.org/tool')).toBe('https://example.org/tool');
  });
});

describe('metaYmlUrl', () => {
  it('appends meta.yml to a module directory, on the raw host', () => {
    expect(metaYmlUrl(MODULE)).toBe(
      'https://raw.githubusercontent.com/nf-core/modules/master/modules/nf-core/mosdepth/meta.yml',
    );
  });

  it('does not double up when the URL already points at meta.yml', () => {
    expect(metaYmlUrl(`${MODULE}/meta.yml`)).toMatch(/mosdepth\/meta\.yml$/);
    expect(metaYmlUrl(`${MODULE}/meta.yml`)).not.toMatch(/meta\.yml\/meta\.yml/);
  });
});

describe('parseOutputChannels', () => {
  it('reads the modern map form', () => {
    const out = parseOutputChannels({
      summary_txt: [{ 'meta,txt': [{ type: 'file', pattern: '*.summary.txt', description: 'Summary' }] }],
    });
    expect(out).toEqual([
      { name: 'summary_txt', pattern: '*.summary.txt', description: 'Summary', type: 'file' },
    ]);
  });

  it('reads the older list-of-single-key-maps form', () => {
    const out = parseOutputChannels([
      { regions_bed: { type: 'file', pattern: '*.regions.bed.gz', description: 'Regions' } },
    ]);
    expect(out).toEqual([
      { name: 'regions_bed', pattern: '*.regions.bed.gz', description: 'Regions', type: 'file' },
    ]);
  });

  it('unwraps a single-option brace and splits a multi-option one into alternatives', () => {
    const single = parseOutputChannels({ c: { type: 'file', pattern: '*.{summary.txt}' } });
    expect(single[0].pattern).toBe('*.summary.txt');
    expect(single[0].altPatterns).toBeUndefined();
    // fnmatch has no brace expansion: one glob per option.
    const multi = parseOutputChannels({ c: { type: 'file', pattern: '*.{bam,cram}' } });
    expect(multi[0].pattern).toBe('*.bam');
    expect(multi[0].altPatterns).toEqual(['*.cram']);
  });

  it('repairs an unbalanced brace (macs3/callpeak meta.yml)', () => {
    expect(expandPattern('*.gappedPeak,*.narrowPeak}')).toEqual(['*.gappedPeak', '*.narrowPeak']);
    expect(expandPattern('{*.bed')).toEqual(['*.bed']);
    expect(expandPattern('*.xls')).toEqual(['*.xls']);
  });

  it('skips channels with no file descriptor', () => {
    expect(parseOutputChannels({ versions: { type: 'string' } })).toEqual([]);
    expect(parseOutputChannels(undefined)).toEqual([]);
    expect(parseOutputChannels('nonsense')).toEqual([]);
  });
});

describe('fetchNfCoreMeta', () => {
  const META = `
name: MOSDEPTH
tools:
  - mosdepth:
      description: "Fast BAM/CRAM depth calculation"
      homepage: https://github.com/brentp/mosdepth
      identifier: biotools:mosdepth
output:
  summary_txt:
    - meta:
        type: file
        pattern: "*.{summary.txt}"
        description: Summary metrics
`;

  it('extracts identity, bio.tools id and outputs', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(META, { status: 200 })));
    const meta = await fetchNfCoreMeta(`${MODULE}/meta.yml`);
    // The tool (tools[0] key), not the module's own `name`.
    expect(meta.name).toBe('mosdepth');
    expect(meta.description).toBe('Fast BAM/CRAM depth calculation');
    expect(meta.homepage).toBe('https://github.com/brentp/mosdepth');
    expect(meta.biotools_url).toBe('https://bio.tools/mosdepth');
    // The pasted meta.yml URL is normalised before it reaches module.yaml.
    expect(meta.source_url).toBe(MODULE);
    expect(meta.outputs[0].pattern).toBe('*.summary.txt');
  });

  it('takes the id and description from the tool, not the module', async () => {
    const macs3 = `
name: "macs3_callpeak"
description: Peak calling of enriched genomic regions of ChIP-seq and ATAC-seq
  experiments
tools:
  - macs3:
      description: "Model Based Analysis for ChIP-Seq data"
      homepage: "https://macs3-project.github.io/MACS/"
      identifier: ""
`;
    vi.stubGlobal('fetch', vi.fn(async () => new Response(macs3, { status: 200 })));
    const meta = await fetchNfCoreMeta('https://github.com/nf-core/modules/tree/master/modules/nf-core/macs3/callpeak');
    expect(meta.name).toBe('macs3');
    expect(meta.description).toBe('Model Based Analysis for ChIP-Seq data');
    expect(meta.biotools_url).toBe('');
  });

  it('falls back to the module name and description without a tools block', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('name: foo_bar\ndescription: Does  things\n', { status: 200 })));
    const meta = await fetchNfCoreMeta(MODULE);
    expect(meta.name).toBe('foo_bar');
    expect(meta.description).toBe('Does things');
  });

  it('ignores a non-biotools identifier', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('tools:\n  - t:\n      identifier: doi:10.1234\n', { status: 200 })),
    );
    expect((await fetchNfCoreMeta(MODULE)).biotools_url).toBe('');
  });

  it('surfaces the status on an HTTP error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('Not Found', { status: 404 })));
    await expect(fetchNfCoreMeta(MODULE)).rejects.toThrow(/404/);
  });

  it('returns empty fields rather than throwing on an empty document', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 200 })));
    const meta = await fetchNfCoreMeta(MODULE);
    expect(meta.name).toBe('');
    expect(meta.outputs).toEqual([]);
  });
});
