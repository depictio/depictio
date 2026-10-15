/**
 * Browser client of `POST /advanced_viz/structure/resolve` (molecule_3d,
 * `structure_source: resolve`).
 *
 * The server turns a UniProt accession, a gene symbol or a sequence into a
 * presigned PDB URL (AlphaFold DB first, ESMFold as the fallback) and caches
 * the model in the bucket. This module adds a per-session memo on top so a
 * dashboard re-render, a second tile on the same protein or a filter round
 * trip does not ask again, and turns the two expected refusals (resolver
 * disabled, nothing found) into messages a reader can act on.
 */

import { authFetch } from '../../../api';

const RESOLVE_URL = '/depictio/api/v1/advanced_viz/structure/resolve';

export interface ResolveRequest {
  uniprot?: string | null;
  gene?: string | null;
  taxon?: number;
  sequence?: string | null;
}

export type ResolveOrigin = 'afdb' | 'esmfold';

/** The public service that produced a model: scheme and host only. */
export interface ResolveUpstream {
  host: string;
  url: string;
}

export interface ResolvedStructure {
  /** Presigned URL of the PDB model. */
  url: string;
  /** Where this answer came from: an upstream call or the bucket cache. */
  source: ResolveOrigin | 'cache';
  /** Where the model itself came from, also on a cache hit. */
  origin: ResolveOrigin | null;
  /** The external service behind `origin`; null when the server does not know it. */
  upstream?: ResolveUpstream | null;
  accession: string | null;
  /** One-letter sequence of the model. */
  sequence: string;
  format: 'pdb';
}

/** Why a resolve did not give a structure; `kind` picks the message tone. */
export class ResolveError extends Error {
  constructor(
    readonly kind: 'disabled' | 'signin' | 'not_found' | 'invalid' | 'upstream',
    message: string,
  ) {
    super(message);
    this.name = 'ResolveError';
  }
}

/** One key per distinct question, so equal requests share one answer. */
export function resolveKey(req: ResolveRequest): string {
  return JSON.stringify([
    req.uniprot?.trim().toUpperCase() || null,
    req.gene?.trim().toUpperCase() || null,
    req.taxon ?? 9606,
    req.sequence?.replace(/\s+/g, '').toUpperCase() || null,
  ]);
}

/** The credit line a resolved model carries. AlphaFold DB models are CC-BY 4.0. */
export function modelCredit(origin: ResolveOrigin | null | undefined): string | null {
  if (origin === 'afdb') return 'Model: AlphaFold DB, CC-BY 4.0';
  if (origin === 'esmfold') return 'Model: ESMFold';
  return null;
}

/** What the colours of the 3D structure say, in words, for the explanation text. */
function colourWording(mode: string | null | undefined, categoryLabel?: string | null): string {
  switch (mode) {
    case 'plddt':
      return 'pLDDT confidence (how sure the model is of each residue)';
    case 'category':
      return categoryLabel || 'category';
    case 'value':
      return 'the measured value';
    case 'chain':
      return 'chain';
    case 'spectrum':
      return 'position along the chain';
    case 'secondary_structure':
      return 'secondary structure';
    case 'residue_type':
      return 'residue type';
    case 'hydrophobicity':
      return 'hydrophobicity';
    case 'uniform':
      return 'a single colour';
    default:
      return 'the selected colour mode';
  }
}

/** A link shown under the explanation note. */
export interface ExplanationLink {
  label: string;
  href: string;
}

/** The info note of a 3D tile: a paragraph and the links that back it up. */
export interface ModelExplanationNote {
  text: string;
  links: ExplanationLink[];
}

/**
 * The plain-language note behind a 3D tile's info button: where the structure
 * comes from, whether the protein left the server to get it, and how to read
 * it. `origin` is the resolved model's origin, or `'file'` for a structure file
 * written by the run; null when not known. `upstream` is the server's name of
 * the external service (its host is quoted in the sentence about the call).
 */
export function modelExplanation(
  origin: ResolveOrigin | 'file' | null | undefined,
  opts: {
    colorMode?: string | null;
    accession?: string | null;
    categoryLabel?: string | null;
    upstream?: ResolveUpstream | null;
  } = {},
): ModelExplanationNote | null {
  const colours = colourWording(opts.colorMode, opts.categoryLabel);
  const host = opts.upstream?.host || null;
  if (origin === 'esmfold') {
    return {
      text:
        'Predicted from the protein sequence alone by ESMFold (a protein language model; no ' +
        'alignment or database is searched). External call: the protein sequence is sent to ' +
        `the public ESM Atlas service (${host ? `${host}, ` : ''}run by Meta) to be folded; ` +
        'nothing else leaves the server. The result is cached on this server, so the same ' +
        'sequence is not sent twice. A prediction, not an experimental structure. ' +
        `Colours show ${colours}.`,
      links: [
        { label: 'ESM Atlas', href: 'https://esmatlas.com' },
        { label: 'ESMFold paper', href: 'https://doi.org/10.1126/science.ade2574' },
      ],
    };
  }
  if (origin === 'afdb') {
    const subject = opts.accession ? `AlphaFold DB prediction for ${opts.accession}` : 'AlphaFold DB prediction';
    return {
      text:
        `${subject}, looked up from the UniProt accession (CC-BY 4.0). External call: the ` +
        `UniProt accession is sent to AlphaFold DB (${host ? `${host}, ` : ''}EMBL-EBI) to fetch ` +
        'the model. The result is cached on this server. ' +
        `A prediction, not an experimental structure. Colours show ${colours}.`,
      links: [
        opts.accession
          ? {
              label: `AlphaFold DB entry ${opts.accession}`,
              href: `https://alphafold.ebi.ac.uk/entry/${encodeURIComponent(opts.accession)}`,
            }
          : { label: 'AlphaFold DB', href: 'https://alphafold.ebi.ac.uk' },
      ],
    };
  }
  if (origin === 'file') {
    return {
      text:
        `Structure file written by the run; coloured by ${colours}. ` +
        "Read from the run's output files; nothing is sent anywhere.",
      links: [],
    };
  }
  return null;
}

function asOrigin(value: unknown): ResolveOrigin | null {
  return value === 'afdb' || value === 'esmfold' ? value : null;
}

function asUpstream(value: unknown): ResolveUpstream | null {
  const v = value as { host?: unknown; url?: unknown } | null | undefined;
  return v && typeof v.host === 'string' && typeof v.url === 'string'
    ? { host: v.host, url: v.url }
    : null;
}

async function detailOf(res: Response): Promise<string | null> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    return typeof body?.detail === 'string' ? body.detail : null;
  } catch {
    return null;
  }
}

/** Detail of the server's 403 to an anonymous visitor (`ANONYMOUS_REFUSAL` in
 *  structure_resolver.py); any other 403 is the resolver being switched off. */
export const SIGN_IN_REFUSAL = 'Sign in to look up protein structures on this server.';

/** Map a failed response to the error the tile shows. */
async function resolveErrorFrom(res: Response): Promise<ResolveError> {
  const detail = await detailOf(res);
  switch (res.status) {
    case 403:
      if (detail === SIGN_IN_REFUSAL) {
        return new ResolveError(
          'signin',
          'Sign in to see this structure: looking up protein structures is open to ' +
            'signed-in users only on this server.',
        );
      }
      return new ResolveError(
        'disabled',
        'Structure lookup is disabled on this server. An administrator can enable it ' +
          'with DEPICTIO_STRUCTURE_RESOLVER_ENABLED=true.',
      );
    case 404:
      return new ResolveError('not_found', detail || 'No predicted structure found for this protein.');
    case 400:
    case 422:
      return new ResolveError('invalid', detail || 'The protein identifier could not be read.');
    default:
      return new ResolveError(
        'upstream',
        detail || `Structure lookup failed (${res.status}). Try again later.`,
      );
  }
}

// Session memo. Presigned URLs expire, so an entry is kept for a bounded time
// (under the server's presign TTL) and a failed lookup is not kept at all:
// the server does not cache negative answers either.
const MEMO_TTL_MS = 10 * 60 * 1000;
const memo = new Map<string, { at: number; pending: Promise<ResolvedStructure> }>();

export function resolveStructure(
  req: ResolveRequest,
  opts: { fetcher?: typeof authFetch; now?: () => number } = {},
): Promise<ResolvedStructure> {
  const now = opts.now ?? Date.now;
  if (!req.uniprot && !req.gene && !req.sequence) {
    return Promise.reject(
      new ResolveError('invalid', 'This row names no UniProt accession, gene or sequence.'),
    );
  }
  const key = resolveKey(req);
  const hit = memo.get(key);
  if (hit && now() - hit.at < MEMO_TTL_MS) return hit.pending;

  const fetcher = opts.fetcher ?? authFetch;
  const pending = (async () => {
    const res = await fetcher(RESOLVE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        uniprot: req.uniprot || null,
        gene: req.gene || null,
        taxon: req.taxon ?? 9606,
        sequence: req.sequence || null,
      }),
    });
    if (!res.ok) throw await resolveErrorFrom(res);
    const body = (await res.json()) as Partial<ResolvedStructure>;
    if (!body?.url) throw new ResolveError('upstream', 'The structure lookup returned no model.');
    return {
      url: body.url,
      source: body.source ?? 'cache',
      // An upstream answer names the model's origin in `source` only.
      origin: asOrigin(body.origin) ?? asOrigin(body.source),
      upstream: asUpstream(body.upstream),
      accession: body.accession ?? null,
      sequence: body.sequence ?? '',
      format: 'pdb' as const,
    };
  })();
  memo.set(key, { at: now(), pending });
  pending.catch(() => {
    if (memo.get(key)?.pending === pending) memo.delete(key);
  });
  return pending;
}

/** Test hook: forget every memoised lookup. */
export function clearResolveMemo(): void {
  memo.clear();
}
