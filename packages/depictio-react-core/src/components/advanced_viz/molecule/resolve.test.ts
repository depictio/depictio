import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  clearResolveMemo,
  modelCredit,
  modelExplanation,
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

  describe('modelExplanation', () => {
    const ESM_UPSTREAM = { host: 'api.esmatlas.com', url: 'https://api.esmatlas.com' };

    it('explains an ESMFold prediction and the colour mode in use', () => {
      const note = modelExplanation('esmfold', { colorMode: 'plddt' });
      expect(note?.text).toContain('Predicted from the protein sequence alone by ESMFold');
      expect(note?.text).toContain('not an experimental structure');
      expect(note?.text).toContain('Colours show pLDDT confidence');
      expect(
        modelExplanation('esmfold', { colorMode: 'category', categoryLabel: 'domain' })?.text,
      ).toContain('Colours show domain.');
    });

    it('says plainly that the sequence leaves the server for ESM Atlas, with the host', () => {
      const note = modelExplanation('esmfold', { upstream: ESM_UPSTREAM });
      expect(note?.text).toContain(
        'the protein sequence is sent to the public ESM Atlas service ' +
          '(api.esmatlas.com, run by Meta) to be folded; nothing else leaves the server. ' +
          'The result is cached on this server, so the same sequence is not sent twice.',
      );
      expect(note?.links).toEqual([
        { label: 'ESM Atlas', href: 'https://esmatlas.com' },
        { label: 'ESMFold paper', href: 'https://doi.org/10.1126/science.ade2574' },
      ]);
    });

    it('still names the external call when the server sent no upstream', () => {
      expect(modelExplanation('esmfold')?.text).toContain('ESM Atlas service (run by Meta)');
    });

    it('names the accession and the external call of an AlphaFold DB model', () => {
      const note = modelExplanation('afdb', {
        accession: 'P04637',
        colorMode: 'plddt',
        upstream: { host: 'alphafold.ebi.ac.uk', url: 'https://alphafold.ebi.ac.uk' },
      });
      expect(note?.text).toContain('AlphaFold DB prediction for P04637');
      expect(note?.text).toContain('CC-BY 4.0');
      expect(note?.text).toContain(
        'the UniProt accession is sent to AlphaFold DB (alphafold.ebi.ac.uk, EMBL-EBI)',
      );
      expect(note?.links).toEqual([
        {
          label: 'AlphaFold DB entry P04637',
          href: 'https://alphafold.ebi.ac.uk/entry/P04637',
        },
      ]);
      const bare = modelExplanation('afdb');
      expect(bare?.text).toContain('AlphaFold DB prediction,');
      expect(bare?.links).toEqual([{ label: 'AlphaFold DB', href: 'https://alphafold.ebi.ac.uk' }]);
    });

    it('lists the technical details of an ESMFold call, with the endpoint', () => {
      const note = modelExplanation('esmfold', {
        upstream: { ...ESM_UPSTREAM, endpoint: 'https://api.esmatlas.com/foldSequence/v1/pdb/' },
      });
      expect(note?.details).toEqual([
        { label: 'Service', value: 'api.esmatlas.com' },
        { label: 'Endpoint', value: 'https://api.esmatlas.com/foldSequence/v1/pdb/', code: true },
        { label: 'Method and body', value: 'POST, the protein sequence as plain text' },
        { label: 'What comes back', value: 'A PDB file' },
        {
          label: 'What is stored',
          value:
            "The model is cached in this deployment's bucket under a hash of the request, so a repeat is not sent again",
        },
        { label: 'Server switch', value: 'DEPICTIO_STRUCTURE_RESOLVER_ENABLED, off by default' },
      ]);
    });

    it('lists the technical details of an AlphaFold DB call', () => {
      const note = modelExplanation('afdb', {
        accession: 'P04637',
        upstream: {
          host: 'alphafold.ebi.ac.uk',
          url: 'https://alphafold.ebi.ac.uk',
          endpoint: 'https://alphafold.ebi.ac.uk/api/prediction/{accession}',
        },
      });
      const byLabel = Object.fromEntries((note?.details ?? []).map((d) => [d.label, d]));
      expect(byLabel['Service'].value).toBe('alphafold.ebi.ac.uk');
      expect(byLabel['Endpoint']).toEqual({
        label: 'Endpoint',
        value: 'https://alphafold.ebi.ac.uk/api/prediction/{accession}',
        code: true,
      });
      expect(byLabel['Method and body'].value).toBe('GET, the UniProt accession');
    });

    it('omits the Endpoint row when the server sent none, and Service with no upstream', () => {
      const noEndpoint = modelExplanation('esmfold', { upstream: ESM_UPSTREAM });
      expect(noEndpoint?.details.map((d) => d.label)).toEqual([
        'Service',
        'Method and body',
        'What comes back',
        'What is stored',
        'Server switch',
      ]);
      expect(modelExplanation('esmfold')?.details.map((d) => d.label)).not.toContain('Endpoint');
      expect(modelExplanation('afdb')?.details.map((d) => d.label)).not.toContain('Service');
    });

    it('returns no details for a file, and no note for an unknown origin', () => {
      expect(modelExplanation('file')?.details).toEqual([]);
      expect(modelExplanation(null)).toBeNull();
    });

    it('keeps the file mode text short, generic and free of any external call', () => {
      const note = modelExplanation('file', { colorMode: 'chain' });
      expect(note?.text).toBe(
        'Structure file written by the run; coloured by chain. ' +
          "Read from the run's output files; nothing is sent anywhere.",
      );
      expect(note?.links).toEqual([]);
      expect(note?.text).not.toContain('External call');
    });

    it('gives nothing for an unknown origin', () => {
      expect(modelExplanation(null)).toBeNull();
      expect(modelExplanation(undefined, { colorMode: 'plddt' })).toBeNull();
    });
  });

  it('keeps the upstream host and endpoint the server names, and null when it names none', async () => {
    const upstream = {
      host: 'api.esmatlas.com',
      url: 'https://api.esmatlas.com',
      endpoint: 'https://api.esmatlas.com/foldSequence/v1/pdb/',
    };
    const withUpstream = vi.fn(async () => json(200, { ...OK_BODY, origin: 'esmfold', upstream }));
    expect((await resolveStructure({ uniprot: 'P04637' }, { fetcher: withUpstream })).upstream).toEqual(
      upstream,
    );
    clearResolveMemo();
    const without = vi.fn(async () => json(200, OK_BODY));
    expect((await resolveStructure({ uniprot: 'P04637' }, { fetcher: without })).upstream).toBeNull();
  });
});
