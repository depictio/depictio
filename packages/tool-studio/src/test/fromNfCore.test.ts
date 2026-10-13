import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  canonicalNfCoreUrl,
  metaYmlUrl,
  parseOutputChannels,
  fetchNfCoreMeta,
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

  it('unwraps a single-option brace but keeps a multi-option one for the author', () => {
    const single = parseOutputChannels({ c: { type: 'file', pattern: '*.{summary.txt}' } });
    expect(single[0].pattern).toBe('*.summary.txt');
    const multi = parseOutputChannels({ c: { type: 'file', pattern: '*.{bam,cram}' } });
    expect(multi[0].pattern).toBe('*.{bam,cram}');
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
    expect(meta.name).toBe('MOSDEPTH');
    expect(meta.description).toBe('Fast BAM/CRAM depth calculation');
    expect(meta.homepage).toBe('https://github.com/brentp/mosdepth');
    expect(meta.biotools_url).toBe('https://bio.tools/mosdepth');
    // The pasted meta.yml URL is normalised before it reaches module.yaml.
    expect(meta.source_url).toBe(MODULE);
    expect(meta.outputs[0].pattern).toBe('*.summary.txt');
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
