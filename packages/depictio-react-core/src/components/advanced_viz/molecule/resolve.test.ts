import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  clearResolveMemo,
  modelCredit,
  resolveKey,
  ResolveError,
  resolveStructure,
  SIGN_IN_REFUSAL,
} from './resolve';

const OK_BODY = {
  url: 'https://s3/structures/abc.pdb?sig=1',
  source: 'cache',
  origin: 'afdb',
  accession: 'P04637',
  sequence: 'MEEP',
  format: 'pdb',
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('resolveStructure', () => {
  beforeEach(() => clearResolveMemo());

  it('posts the question and keeps the model origin apart from the answer source', async () => {
    const fetcher = vi.fn(async () => json(200, OK_BODY));
    const res = await resolveStructure({ uniprot: 'P04637' }, { fetcher });
    expect(res).toMatchObject({ source: 'cache', origin: 'afdb', accession: 'P04637' });
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/depictio/api/v1/advanced_viz/structure/resolve');
    expect(JSON.parse(String(init.body))).toEqual({
      uniprot: 'P04637',
      gene: null,
      taxon: 9606,
      sequence: null,
    });
  });

  it('asks once per question within the memo window', async () => {
    const fetcher = vi.fn(async () => json(200, OK_BODY));
    await resolveStructure({ uniprot: 'p04637 ' }, { fetcher });
    await resolveStructure({ uniprot: 'P04637' }, { fetcher });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(resolveKey({ gene: 'tp53' })).toBe(resolveKey({ gene: 'TP53', taxon: 9606 }));
  });

  it('turns 403 and 404 into readable refusals, and does not memoise them', async () => {
    const disabled = vi.fn(async () => json(403, { detail: 'disabled' }));
    await expect(resolveStructure({ gene: 'TP53' }, { fetcher: disabled })).rejects.toMatchObject({
      kind: 'disabled',
    });
    const missing = vi.fn(async () => json(404, { detail: 'No structure found: afdb miss' }));
    const err = await resolveStructure({ gene: 'TP53' }, { fetcher: missing }).catch((e) => e);
    expect(err).toBeInstanceOf(ResolveError);
    expect(err.kind).toBe('not_found');
    expect(err.message).toContain('No structure found');
    expect(missing).toHaveBeenCalledTimes(1);
  });

  it('tells an anonymous visitor to sign in rather than that the lookup is off', async () => {
    const anonymous = vi.fn(async () => json(403, { detail: SIGN_IN_REFUSAL }));
    const err = await resolveStructure({ gene: 'TP53' }, { fetcher: anonymous }).catch((e) => e);
    expect(err).toBeInstanceOf(ResolveError);
    expect(err.kind).toBe('signin');
    expect(err.message).toMatch(/^Sign in/);
  });

  it('refuses a question with no identifier without calling the server', async () => {
    const fetcher = vi.fn();
    await expect(resolveStructure({}, { fetcher: fetcher as never })).rejects.toMatchObject({
      kind: 'invalid',
    });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('credits AlphaFold DB models under CC-BY 4.0', () => {
    expect(modelCredit('afdb')).toBe('Model: AlphaFold DB, CC-BY 4.0');
    expect(modelCredit('esmfold')).toBe('Model: ESMFold');
    expect(modelCredit(null)).toBeNull();
  });
});
