import { describe, it, expect, vi, afterEach } from 'vitest';
import { fetchFixtureText, fileNameFromUrl, TABULAR_EXT_RE } from '../catalog/fetchFixture';

const MQC =
  'https://github.com/MultiQC/test-data/blob/main/data/modules/abricate/abricate_summary.txt';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('fileNameFromUrl', () => {
  it('takes the last path segment', () => {
    expect(fileNameFromUrl(MQC)).toBe('abricate_summary.txt');
  });
  it('ignores query and fragment', () => {
    expect(fileNameFromUrl('https://x.test/a/b/report.tsv?raw=1#L2')).toBe('report.tsv');
  });
  it('is empty for a URL with no file', () => {
    expect(fileNameFromUrl('https://x.test/')).toBe('');
  });
});

describe('TABULAR_EXT_RE', () => {
  it('accepts the extensions real outputs use', () => {
    for (const n of ['a.csv', 'a.tsv', 'a.txt', 'a.tab', 'A.TSV']) expect(TABULAR_EXT_RE.test(n)).toBe(true);
  });
  it('rejects anything else', () => {
    for (const n of ['a.bam', 'a.html', 'a.json', 'a']) expect(TABULAR_EXT_RE.test(n)).toBe(false);
  });
});

describe('fetchFixtureText', () => {
  it('rewrites a github blob URL to raw and returns the file', async () => {
    const fetchMock = vi.fn(async (_url: string) => new Response('a\tb\n1\t2\n', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const got = await fetchFixtureText(MQC);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'https://raw.githubusercontent.com/MultiQC/test-data/main/data/modules/abricate/abricate_summary.txt',
    );
    expect(got.fileName).toBe('abricate_summary.txt');
    expect(got.text).toBe('a\tb\n1\t2\n');
    expect(got.bytes).toBe(8);
  });

  it('rejects a non-http URL before touching the network', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(fetchFixtureText('data/modules/x.tsv')).rejects.toThrow('full http(s) URL');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects an extension it cannot parse', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(fetchFixtureText('https://x.test/report.bam')).rejects.toThrow('not a .csv');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('explains a CORS failure instead of surfacing "Failed to fetch"', async () => {
    // The browser gives a bare TypeError with no detail for a blocked request,
    // so the message has to supply the cause and the way out.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    await expect(fetchFixtureText('https://example.test/report.tsv')).rejects.toThrow(
      /cross-origin/,
    );
  });

  it('reports an HTTP error with its status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 404, statusText: 'Not Found' })));
    await expect(fetchFixtureText('https://x.test/missing.tsv')).rejects.toThrow('404');
  });
});
