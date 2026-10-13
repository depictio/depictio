/**
 * Fetch a Snakemake wrapper's `meta.yaml` client-side and extract identity
 * fields — the Snakemake counterpart of `fromNfCore.ts`. raw.githubusercontent.com
 * sends permissive CORS headers, so a browser fetch works with no backend; we
 * parse the YAML with js-yaml.
 *
 * Accepts a GitHub URL to the wrapper directory
 *   https://github.com/snakemake/snakemake-wrappers/tree/master/bio/<tool>[/<sub>]
 * or the readthedocs docs page for the wrapper
 *   https://snakemake-wrappers.readthedocs.io/en/stable/wrappers/bio/<tool>/<sub>.html
 * (mapped best-effort onto the GitHub repo). Returns a small metadata bag;
 * missing fields are ''.
 */
import yaml from 'js-yaml';
import type { ExtractedMeta, OutputChannel } from '../types';
import { githubRawUrl } from './githubRaw';

const REPO = 'https://github.com/snakemake/snakemake-wrappers';

/**
 * Canonicalise a pasted Snakemake wrapper URL to the wrapper-*directory* form on
 * GitHub: `https://github.com/snakemake/snakemake-wrappers/tree/master/<path>`.
 * Rewrites `/blob/` → `/tree/`, strips a trailing `/meta.yaml`, and maps a
 * `snakemake-wrappers.readthedocs.io/.../wrappers/<path>.html` docs URL onto the
 * GitHub wrapper dir. Unrecognised URLs are returned trimmed-only.
 */
export function canonicalSnakemakeUrl(url: string): string {
  const trimmed = url.trim();

  // readthedocs docs page → GitHub wrapper dir.
  const rtdMatch = trimmed.match(/readthedocs\.io\/.*\/wrappers\/(.+?)(?:\.html)?(?:[?#].*)?$/);
  if (rtdMatch) {
    const path = rtdMatch[1].replace(/\/+$/, '');
    return `${REPO}/tree/master/${path}`;
  }

  if (trimmed.includes('github.com/snakemake/snakemake-wrappers')) {
    return trimmed
      .replace('/blob/', '/tree/')
      .replace(/\/meta\.yaml$/, '')
      .replace(/\/+$/, '');
  }
  return trimmed;
}

/** Turn a wrapper-directory URL into the raw meta.yaml URL. */
export function metaYamlUrl(dirUrl: string): string {
  // .../tree/<ref>/<path>  →  raw .../<ref>/<path>/meta.yaml
  const raw = githubRawUrl(canonicalSnakemakeUrl(dirUrl)).replace(/\/+$/, '');
  return `${raw}/meta.yaml`;
}

interface SnakemakeMetaYaml {
  name?: string;
  description?: string;
  url?: string;
  /** Snakemake wrapper `output:` is a list of prose descriptions (no globs). */
  output?: unknown;
}

const slugify = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');

/** Parse the `output:` section — a list of description strings — into channels.
 *  There is no glob in a wrapper's meta.yaml, so `pattern` is '' (the author
 *  still writes the path glob); we surface the description for auto-fill and
 *  derive a slug-friendly, unique name from it. */
export function parseSnakemakeOutputs(output: unknown): OutputChannel[] {
  if (!Array.isArray(output)) return [];
  const outs: OutputChannel[] = [];
  const seen = new Map<string, number>();
  for (const item of output) {
    if (typeof item !== 'string') continue;
    const description = item.trim();
    if (!description) continue;
    // A short name from the leading words of the description (e.g.
    // "SAM/BAM/CRAM index file (optional)" → "sam_bam_cram"), disambiguated with
    // a numeric suffix when two descriptions collapse to the same base — the
    // channel `name` is the picker's unique value.
    const base = slugify(description.split(/[(,]/)[0]).split('_').slice(0, 3).join('_') || 'output';
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    outs.push({ name: n === 1 ? base : `${base}_${n}`, pattern: '', description, type: 'file' });
  }
  return outs;
}

export async function fetchSnakemakeMeta(wrapperUrl: string): Promise<ExtractedMeta> {
  const url = metaYamlUrl(wrapperUrl);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  const text = await res.text();
  const doc = (yaml.load(text) ?? {}) as SnakemakeMetaYaml;

  return {
    name: doc.name ?? '',
    description: doc.description ?? '',
    homepage: doc.url ?? '',
    biotools_url: '',
    source_url: canonicalSnakemakeUrl(wrapperUrl),
    outputs: parseSnakemakeOutputs(doc.output),
  };
}
