import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchUniqueValues } from './api';

const jsonResponse = (values: string[]) =>
  new Response(JSON.stringify({ values }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });

afterEach(() => vi.unstubAllGlobals());

describe('fetchUniqueValues', () => {
  it('sends one request for concurrent calls on the same column', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(['a', 'b']));
    vi.stubGlobal('fetch', fetchMock);

    const [first, second] = await Promise.all([
      fetchUniqueValues('dc1', 'locality'),
      fetchUniqueValues('dc1', 'locality'),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(first).toEqual(['a', 'b']);
    expect(second).toEqual(['a', 'b']);
  });

  it('hands each caller its own list', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(['b', 'a'])));

    const [first, second] = await Promise.all([
      fetchUniqueValues('dc1', 'season'),
      fetchUniqueValues('dc1', 'season'),
    ]);
    first.sort();

    expect(first).toEqual(['a', 'b']);
    expect(second).toEqual(['b', 'a']);
  });

  it('keeps different columns and scopes apart', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(['x']));
    vi.stubGlobal('fetch', fetchMock);

    await Promise.all([
      fetchUniqueValues('dc1', 'locality'),
      fetchUniqueValues('dc1', 'season'),
      fetchUniqueValues('dc1', 'locality', "col('a') == 1"),
      fetchUniqueValues('dc2', 'locality'),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('asks again once the first request has settled', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(['x']));
    vi.stubGlobal('fetch', fetchMock);

    await fetchUniqueValues('dc1', 'locality');
    await fetchUniqueValues('dc1', 'locality');

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not keep a failed request around', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response('nope', { status: 500 }))
      .mockResolvedValueOnce(jsonResponse(['ok']));
    vi.stubGlobal('fetch', fetchMock);

    await expect(fetchUniqueValues('dc1', 'locality')).rejects.toThrow();
    await expect(fetchUniqueValues('dc1', 'locality')).resolves.toEqual(['ok']);
  });
});
