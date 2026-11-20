/**
 * Fetch an nf-core module's meta.yml client-side and extract identity fields.
 * raw.githubusercontent.com sends permissive CORS headers, so a browser fetch
 * works with no backend. We parse the YAML with js-yaml.
 *
 * Accepts either a tree URL
 *   https://github.com/nf-core/modules/tree/master/modules/nf-core/<tool>[/subtool]
 * or a direct meta.yml URL. Returns a small metadata bag; missing fields are ''.
 */
import yaml from 'js-yaml';
import type { ExtractedMeta, OutputChannel } from '../types';
import { githubRawUrl } from './githubRaw';

/**
 * Canonicalise a pasted nf-core module URL to the module-*directory* form the
 * catalog uses (and that `dev catalog validate` checks against the vendored
 * index): `https://github.com/nf-core/modules/tree/master/modules/nf-core/<module>`.
 * Strips a trailing `/meta.yml` or `/main.nf` and rewrites `/blob/` → `/tree/`,
 * so pasting the meta.yml page (what the module docs link to) still yields a
 * valid `nf_core_url`. Non-nf-core URLs are returned unchanged.
 */
export function canonicalNfCoreUrl(url: string): string {
  const trimmed = url.trim();
  if (!trimmed.includes('/modules/nf-core/')) return trimmed;
  return trimmed
    .replace('/blob/', '/tree/')
    .replace(/\/(meta\.yml|main\.nf)$/, '')
    .replace(/\/+$/, '');
}

/** Turn a module tree URL (or a direct meta.yml page) into the raw meta.yml URL. */
export function metaYmlUrl(moduleUrl: string): string {
  // .../tree/<ref>/modules/nf-core/<tool>  →  raw .../<ref>/modules/nf-core/<tool>/meta.yml
  const raw = githubRawUrl(moduleUrl).replace(/\/+$/, '');
  return raw.endsWith('meta.yml') ? raw : `${raw}/meta.yml`;
}

interface MetaYml {
  name?: string;
  description?: string;
  homepage?: string;
  tools?: Array<
    Record<
      string,
      {
        description?: string;
        homepage?: string;
        tool_dev_url?: string;
        documentation?: string;
        identifier?: string;
      }
    >
  >;
  /** Either a map { channel: … } (modern) or a list of single-key maps (older). */
  output?: unknown;
}

/**
 * The fnmatch globs an nf-core `pattern` stands for. The catalog's `find` uses
 * Python fnmatch, which has no brace expansion, so:
 *   "*.{summary.txt}"      → ["*.summary.txt"]           (single option, unwrapped)
 *   "*.{bam,cram}"         → ["*.bam", "*.cram"]          (one glob per option)
 *   "*.gappedPeak,*.narrowPeak}" → ["*.gappedPeak", "*.narrowPeak"]
 * The last one is a real meta.yml (macs3/callpeak) with its opening brace
 * missing: stray braces are dropped and top-level commas still split, so a
 * typo upstream does not become an invalid glob in the entry.
 */
export function expandPattern(p: string): string[] {
  const trimmed = p.trim();
  if (!trimmed) return [''];
  const m = trimmed.match(/^([^{}]*)\{([^{}]*)\}([^{}]*)$/);
  if (m) {
    const [, pre, body, post] = m;
    return body.split(',').map((o) => `${pre}${o.trim()}${post}`).filter((g) => g !== pre + post);
  }
  // Unbalanced or nested braces: drop them, then split on commas.
  return trimmed
    .replace(/[{}]/g, '')
    .split(',')
    .map((g) => g.trim())
    .filter(Boolean);
}

/** Depth-first: find the first descriptor node with `type: file` + a string
 *  `pattern` anywhere inside a channel's (arbitrarily nested) value. */
function findFileDescriptor(node: unknown): { pattern: string; description: string } | null {
  if (Array.isArray(node)) {
    for (const item of node) {
      const found = findFileDescriptor(item);
      if (found) return found;
    }
    return null;
  }
  if (node && typeof node === 'object') {
    const obj = node as Record<string, unknown>;
    if (obj.type === 'file' && typeof obj.pattern === 'string') {
      return {
        pattern: obj.pattern,
        description: typeof obj.description === 'string' ? obj.description : '',
      };
    }
    for (const v of Object.values(obj)) {
      const found = findFileDescriptor(v);
      if (found) return found;
    }
  }
  return null;
}

/** Parse the `output:` section into the file channels we can auto-fill from.
 *  Tolerates both the modern map form (`output: { channel: … }`) and the older
 *  list form (`output: [ { channel: … } ]`). Non-file channels are skipped. */
export function parseOutputChannels(output: unknown): OutputChannel[] {
  const outs: OutputChannel[] = [];
  const channel = (name: string, d: { pattern: string; description: string }): OutputChannel => {
    const [pattern = '', ...alts] = expandPattern(d.pattern);
    return { name, pattern, ...(alts.length ? { altPatterns: alts } : {}), description: d.description.trim(), type: 'file' };
  };
  const push = (name: string, value: unknown) => {
    const d = findFileDescriptor(value);
    if (d) outs.push(channel(name, d));
  };
  if (Array.isArray(output)) {
    for (const item of output) {
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        const entries = Object.entries(item as Record<string, unknown>);
        if (entries.length === 1) push(entries[0][0], entries[0][1]);
        else {
          const d = findFileDescriptor(item);
          if (d) outs.push(channel(expandPattern(d.pattern)[0] ?? d.pattern, d));
        }
      }
    }
  } else if (output && typeof output === 'object') {
    for (const [name, value] of Object.entries(output as Record<string, unknown>)) push(name, value);
  }
  return outs;
}

export async function fetchNfCoreMeta(moduleUrl: string): Promise<ExtractedMeta> {
  const url = metaYmlUrl(moduleUrl.trim());
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  const text = await res.text();
  const doc = (yaml.load(text) ?? {}) as MetaYml;

  // meta.yml `tools` is a list of single-key maps: [{ tool: {description,...} }]
  // A catalog entry describes the TOOL (macs2, samtools), not the nf-core
  // module (macs2_callpeak, samtools_flagstat): its id, name and card text come
  // from `tools[0]`, and the module only from its URL. The module's own name
  // and description are the fallback when the tool block is missing.
  let toolName = '';
  let description = '';
  let homepage = doc.homepage ?? '';
  let biotools = '';
  const first = doc.tools?.[0];
  if (first) {
    const [key, info] = Object.entries(first)[0] ?? [];
    toolName = key ?? '';
    if (info) {
      description = (info.description ?? '').trim();
      // Many meta.yml leave `homepage` empty; the catalog card still needs a
      // link, so fall back to the source repository, then the docs.
      homepage = homepage || info.homepage || info.tool_dev_url || info.documentation || '';
      const id = info.identifier || '';
      if (id.startsWith('biotools:')) biotools = `https://bio.tools/${id.slice('biotools:'.length)}`;
    }
  }
  return {
    name: toolName || doc.name || '',
    description: description || (doc.description ?? '').replace(/\s+/g, ' ').trim(),
    homepage,
    biotools_url: biotools,
    source_url: canonicalNfCoreUrl(moduleUrl.trim()),
    outputs: parseOutputChannels(doc.output),
  };
}
