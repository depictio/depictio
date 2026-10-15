import { gzipSync } from 'node:zlib';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  clearObjectCache,
  decodeObjectBytes,
  loadObjectText,
  loadObjectTextRenewing,
  MAX_CACHED_OBJECTS,
  objectCacheKey,
  ObjectFileError,
} from './objectText';

const body = (text: string) => async () => new Response(text);
const refused = (status: number) => async () => new Response('', { status });
const url = (n: number | string, ns = 'a') => `https://s3/bucket/${ns}/obj-${n}.txt`;

beforeEach(() => clearObjectCache());

describe('objectCacheKey', () => {
  it('drops the query string and keeps the path', () => {
    expect(objectCacheKey('https://s3/b/k/P1.pdb?X-Amz-Signature=1&X-Amz-Expires=900')).toBe(
      'https://s3/b/k/P1.pdb',
    );
    expect(objectCacheKey('https://s3/b/k/P1.pdb')).toBe('https://s3/b/k/P1.pdb');
  });
});

describe('decodeObjectBytes', () => {
  it('gunzips by magic number, whatever the name says, and passes plain bytes through', async () => {
    const gz = new Uint8Array(gzipSync(Buffer.from('1\t2\n3\t4\n')));
    expect(await decodeObjectBytes(gz)).toBe('1\t2\n3\t4\n');
    expect(await decodeObjectBytes(new TextEncoder().encode('plain'))).toBe('plain');
  });

  it('loads a gzipped object under a plain name', async () => {
    const gz = gzipSync(Buffer.from('hello'));
    const text = await loadObjectText(url('gz'), {
      cacheNamespace: 'a',
      fetcher: async () => new Response(gz),
    });
    expect(text).toBe('hello');
  });
});

describe('the cache key', () => {
  it('downloads an object once across presigned URLs', async () => {
    const fetcher = vi.fn(body('payload'));
    const first = await loadObjectText('https://s3/k/P1.tsv?sig=1', {
      cacheNamespace: 'a',
      fetcher,
    });
    const second = await loadObjectText('https://s3/k/P1.tsv?sig=2&exp=9', {
      cacheNamespace: 'a',
      fetcher,
    });
    expect(first).toBe('payload');
    expect(second).toBe('payload');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('keeps different paths apart', async () => {
    const fetcher = vi.fn(body('x'));
    await loadObjectText('https://s3/k/P1.tsv?sig=1', { cacheNamespace: 'a', fetcher });
    await loadObjectText('https://s3/k/P2.tsv?sig=1', { cacheNamespace: 'a', fetcher });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

describe('the shared promise', () => {
  it('gives two tiles asking at once one download and one promise', async () => {
    let release: (r: Response) => void = () => {};
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const fetcher = vi.fn(() => gate);
    const one = loadObjectText(url('shared'), { cacheNamespace: 'a', fetcher });
    const two = loadObjectText(url('shared') + '?sig=other', { cacheNamespace: 'a', fetcher });
    expect(two).toBe(one);
    release(new Response('late'));
    expect(await one).toBe('late');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('runs the parser once and shares its value', async () => {
    const parse = vi.fn((text: string) => ({ n: text.length }));
    const fetcher = vi.fn(body('abcd'));
    const [x, y] = await Promise.all([
      loadObjectText(url('parsed'), { cacheNamespace: 'a', fetcher, parse }),
      loadObjectText(url('parsed'), { cacheNamespace: 'a', fetcher, parse }),
    ]);
    expect(x).toBe(y);
    expect(x).toEqual({ n: 4 });
    expect(parse).toHaveBeenCalledTimes(1);
  });

  it('hands the parser the cache key and the name hint', async () => {
    const parse = vi.fn((_text: string, ctx: { key: string; nameHint: string | null }) => ctx);
    const out = await loadObjectText('https://s3/k/m.json.gz?sig=1', {
      cacheNamespace: 'a',
      nameHint: 'm.json.gz',
      fetcher: body('{}'),
      parse,
    });
    expect(out).toEqual({ key: 'https://s3/k/m.json.gz', nameHint: 'm.json.gz' });
    const bare = await loadObjectText(url('nohint'), {
      cacheNamespace: 'a',
      fetcher: body('{}'),
      parse,
    });
    expect(bare.nameHint).toBeNull();
  });
});

describe('failures', () => {
  it('evicts a refused download so the next ask fetches again', async () => {
    await expect(
      loadObjectText(url('flaky'), { cacheNamespace: 'pae', fetcher: refused(500) }),
    ).rejects.toMatchObject({ status: 500, message: 'Pae file unavailable (500)' });
    const ok = vi.fn(body('now fine'));
    expect(await loadObjectText(url('flaky'), { cacheNamespace: 'pae', fetcher: ok })).toBe(
      'now fine',
    );
    expect(ok).toHaveBeenCalledTimes(1);
  });

  it('names the file in its messages, and takes its own error type', async () => {
    await expect(
      loadObjectText(url('named'), { cacheNamespace: 'a', noun: 'PAE', fetcher: refused(404) }),
    ).rejects.toThrow('PAE file unavailable (404)');
    await expect(
      loadObjectText(url('empty'), { cacheNamespace: 'a', noun: 'PAE', fetcher: body('  \n') }),
    ).rejects.toThrow('Empty PAE file');

    class MineError extends ObjectFileError {}
    const err = await loadObjectText(url('mine'), {
      cacheNamespace: 'a',
      fetcher: refused(403),
      errorFor: (status) => new MineError(status, 'mine'),
    }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(MineError);
    expect(err).toBeInstanceOf(ObjectFileError);
  });

  it('evicts an object its parser rejects', async () => {
    const fetcher = vi.fn(body('x'));
    const parse = vi
      .fn<(text: string) => string>()
      .mockImplementationOnce(() => {
        throw new Error('not a matrix');
      })
      .mockImplementation((t) => t.toUpperCase());
    await expect(
      loadObjectText(url('bad'), { cacheNamespace: 'a', fetcher, parse }),
    ).rejects.toThrow('not a matrix');
    expect(await loadObjectText(url('bad'), { cacheNamespace: 'a', fetcher, parse })).toBe('X');
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

describe('namespaces', () => {
  it('keep the same path apart', async () => {
    const structure = vi.fn(body('structure text'));
    const pae = vi.fn(body('pae text'));
    const u = 'https://s3/k/P1';
    expect(await loadObjectText(u, { cacheNamespace: 'structure', fetcher: structure })).toBe(
      'structure text',
    );
    expect(await loadObjectText(u, { cacheNamespace: 'pae', fetcher: pae })).toBe('pae text');
    // Both are cached now.
    expect(await loadObjectText(u, { cacheNamespace: 'structure', fetcher: structure })).toBe(
      'structure text',
    );
    expect(await loadObjectText(u, { cacheNamespace: 'pae', fetcher: pae })).toBe('pae text');
    expect(structure).toHaveBeenCalledTimes(1);
    expect(pae).toHaveBeenCalledTimes(1);
  });

  it('do not evict each other: a full namespace leaves the other one alone', async () => {
    const paeFetch = vi.fn(body('pae'));
    await loadObjectText(url('only', 'pae'), { cacheNamespace: 'pae', fetcher: paeFetch });
    const structureFetch = vi.fn(body('s'));
    for (let i = 0; i < MAX_CACHED_OBJECTS * 2; i += 1) {
      await loadObjectText(url(i, 'structure'), {
        cacheNamespace: 'structure',
        fetcher: structureFetch,
      });
    }
    expect(structureFetch).toHaveBeenCalledTimes(MAX_CACHED_OBJECTS * 2);
    await loadObjectText(url('only', 'pae'), { cacheNamespace: 'pae', fetcher: paeFetch });
    expect(paeFetch).toHaveBeenCalledTimes(1);
  });

  it('are cleared one at a time, or all together', async () => {
    const a = vi.fn(body('a'));
    const b = vi.fn(body('b'));
    const ask = () =>
      Promise.all([
        loadObjectText(url(1), { cacheNamespace: 'a', fetcher: a }),
        loadObjectText(url(1), { cacheNamespace: 'b', fetcher: b }),
      ]);
    await ask();
    clearObjectCache('a');
    await ask();
    expect([a.mock.calls.length, b.mock.calls.length]).toEqual([2, 1]);
    clearObjectCache();
    await ask();
    expect([a.mock.calls.length, b.mock.calls.length]).toEqual([3, 2]);
  });
});

describe('the LRU cap', () => {
  const fill = async (fetcher: () => Promise<Response>, count: number) => {
    for (let i = 0; i < count; i += 1) {
      await loadObjectText(url(i), { cacheNamespace: 'a', fetcher });
    }
  };

  it('keeps MAX_CACHED_OBJECTS objects per namespace', async () => {
    const fetcher = vi.fn(body('x'));
    await fill(fetcher, MAX_CACHED_OBJECTS);
    await fill(fetcher, MAX_CACHED_OBJECTS);
    expect(fetcher).toHaveBeenCalledTimes(MAX_CACHED_OBJECTS);
  });

  it('drops the oldest object when one more arrives', async () => {
    const fetcher = vi.fn(body('x'));
    await fill(fetcher, MAX_CACHED_OBJECTS + 1);
    expect(fetcher).toHaveBeenCalledTimes(MAX_CACHED_OBJECTS + 1);
    // The newest is still cached, the first is gone.
    await loadObjectText(url(MAX_CACHED_OBJECTS), { cacheNamespace: 'a', fetcher });
    expect(fetcher).toHaveBeenCalledTimes(MAX_CACHED_OBJECTS + 1);
    await loadObjectText(url(0), { cacheNamespace: 'a', fetcher });
    expect(fetcher).toHaveBeenCalledTimes(MAX_CACHED_OBJECTS + 2);
  });

  it('counts a hit as a use: the object asked for again outlives its elders', async () => {
    const fetcher = vi.fn(body('x'));
    await fill(fetcher, MAX_CACHED_OBJECTS);
    // Touch the oldest; the second-oldest is now the one to go.
    await loadObjectText(url(0), { cacheNamespace: 'a', fetcher });
    await loadObjectText(url('extra'), { cacheNamespace: 'a', fetcher });
    expect(fetcher).toHaveBeenCalledTimes(MAX_CACHED_OBJECTS + 1);
    await loadObjectText(url(0), { cacheNamespace: 'a', fetcher });
    expect(fetcher).toHaveBeenCalledTimes(MAX_CACHED_OBJECTS + 1);
    await loadObjectText(url(1), { cacheNamespace: 'a', fetcher });
    expect(fetcher).toHaveBeenCalledTimes(MAX_CACHED_OBJECTS + 2);
  });
});

describe('a namespace with its own cap', () => {
  const ask = (n: number | string, ns: string, fetcher: () => Promise<Response>, cap?: number) =>
    loadObjectText(url(n, ns), { cacheNamespace: ns, fetcher, maxCachedObjects: cap });

  it('keeps that many objects and drops the oldest past it', async () => {
    const fetcher = vi.fn(body('x'));
    for (let i = 0; i < 3; i += 1) await ask(i, 'small', fetcher, 3);
    for (let i = 0; i < 3; i += 1) await ask(i, 'small', fetcher, 3);
    expect(fetcher).toHaveBeenCalledTimes(3);
    await ask(3, 'small', fetcher, 3);
    expect(fetcher).toHaveBeenCalledTimes(4);
    // The first is gone, the newest is still held.
    await ask(3, 'small', fetcher, 3);
    expect(fetcher).toHaveBeenCalledTimes(4);
    await ask(0, 'small', fetcher, 3);
    expect(fetcher).toHaveBeenCalledTimes(5);
  });

  it('still counts a hit as a use', async () => {
    const fetcher = vi.fn(body('x'));
    for (let i = 0; i < 3; i += 1) await ask(i, 'small', fetcher, 3);
    await ask(0, 'small', fetcher, 3);
    await ask('extra', 'small', fetcher, 3);
    expect(fetcher).toHaveBeenCalledTimes(4);
    await ask(0, 'small', fetcher, 3);
    expect(fetcher).toHaveBeenCalledTimes(4);
    await ask(1, 'small', fetcher, 3);
    expect(fetcher).toHaveBeenCalledTimes(5);
  });

  it('leaves the default namespace at MAX_CACHED_OBJECTS', async () => {
    const small = vi.fn(body('s'));
    for (let i = 0; i < 10; i += 1) await ask(i, 'small', small, 2);
    const structure = vi.fn(body('t'));
    for (let i = 0; i < MAX_CACHED_OBJECTS; i += 1) await ask(i, 'structure', structure);
    for (let i = 0; i < MAX_CACHED_OBJECTS; i += 1) await ask(i, 'structure', structure);
    expect(structure).toHaveBeenCalledTimes(MAX_CACHED_OBJECTS);
    await ask(MAX_CACHED_OBJECTS, 'structure', structure);
    await ask(0, 'structure', structure);
    expect(structure).toHaveBeenCalledTimes(MAX_CACHED_OBJECTS + 2);
  });

  it('is at least one object, and a nonsense cap falls back to the default', async () => {
    const one = vi.fn(body('x'));
    await ask('a', 'one', one, 0);
    await ask('a', 'one', one, 0);
    expect(one).toHaveBeenCalledTimes(1);
    await ask('b', 'one', one, 0);
    await ask('a', 'one', one, 0);
    expect(one).toHaveBeenCalledTimes(3);

    const odd = vi.fn(body('x'));
    for (let i = 0; i < MAX_CACHED_OBJECTS; i += 1) await ask(i, 'odd', odd, Number.NaN);
    for (let i = 0; i < MAX_CACHED_OBJECTS; i += 1) await ask(i, 'odd', odd, Number.NaN);
    expect(odd).toHaveBeenCalledTimes(MAX_CACHED_OBJECTS);
  });

  it('applies through the renewing loader too', async () => {
    const fetcher = vi.fn(body('x'));
    const load = (n: number) =>
      loadObjectTextRenewing(url(n, 'renew'), {
        cacheNamespace: 'renew',
        maxCachedObjects: 2,
        fetcher,
      });
    await load(0);
    await load(1);
    await load(2);
    await load(0);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });
});

describe('loadObjectTextRenewing', () => {
  it('asks once for a fresh URL after a 403 and loads from it', async () => {
    const fetcher = vi.fn(async (u: string) =>
      u.includes('sig=old') ? new Response('', { status: 403 }) : new Response('fresh'),
    );
    const renew = vi.fn(async () => 'https://s3/k/P1.tsv?sig=new');
    const out = await loadObjectTextRenewing('https://s3/k/P1.tsv?sig=old', {
      cacheNamespace: 'a',
      fetcher,
      renew,
    });
    expect(out).toBe('fresh');
    expect(renew).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls.map(([u]) => u)).toEqual([
      'https://s3/k/P1.tsv?sig=old',
      'https://s3/k/P1.tsv?sig=new',
    ]);
  });

  it('gives up after one renewal, on the same URL, on a null, or on another status', async () => {
    const renew = vi.fn(async () => 'https://s3/k/P2.tsv?sig=new');
    await expect(
      loadObjectTextRenewing('https://s3/k/P2.tsv?sig=old', {
        cacheNamespace: 'a',
        fetcher: refused(403),
        renew,
      }),
    ).rejects.toThrow('403');
    expect(renew).toHaveBeenCalledTimes(1);

    const same = vi.fn(async () => 'https://s3/k/P3.tsv?sig=1');
    const sameFetch = vi.fn(refused(403));
    await expect(
      loadObjectTextRenewing('https://s3/k/P3.tsv?sig=1', {
        cacheNamespace: 'a',
        fetcher: sameFetch,
        renew: same,
      }),
    ).rejects.toThrow('403');
    // The renewal gave the URL that was just refused: no second download.
    expect(sameFetch).toHaveBeenCalledTimes(1);

    const nothing = vi.fn(async () => null);
    await expect(
      loadObjectTextRenewing('https://s3/k/P5.tsv', {
        cacheNamespace: 'a',
        fetcher: refused(403),
        renew: nothing,
      }),
    ).rejects.toThrow('403');
    expect(nothing).toHaveBeenCalledTimes(1);

    const notExpired = vi.fn(async () => 'https://s3/k/P4.tsv?sig=new');
    await expect(
      loadObjectTextRenewing('https://s3/k/P4.tsv', {
        cacheNamespace: 'a',
        fetcher: refused(404),
        renew: notExpired,
      }),
    ).rejects.toThrow('404');
    expect(notExpired).not.toHaveBeenCalled();
  });

  it('throws the refusal as is when there is no renewal', async () => {
    await expect(
      loadObjectTextRenewing(url('norenew'), { cacheNamespace: 'a', fetcher: refused(403) }),
    ).rejects.toBeInstanceOf(ObjectFileError);
  });
});
