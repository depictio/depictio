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
import type { NfCoreOutput } from '../types';

export interface NfCoreMeta {
  name: string;
  description: string;
  homepage: string;
  biotools_url: string;
  /** File output channels parsed from the `output:` section (for auto-fill). */
  outputs: NfCoreOutput[];
}

/** Turn a module tree URL into the raw meta.yml URL. */
export function metaYmlUrl(moduleUrl: string): string {
  if (moduleUrl.endsWith('meta.yml')) {
    return moduleUrl.replace('github.com', 'raw.githubusercontent.com').replace('/tree/', '/').replace('/blob/', '/');
  }
  // .../tree/<ref>/modules/nf-core/<tool>  →  raw .../<ref>/modules/nf-core/<tool>/meta.yml
  const raw = moduleUrl
    .replace('github.com', 'raw.githubusercontent.com')
    .replace('/tree/', '/')
    .replace(/\/+$/, '');
  return `${raw}/meta.yml`;
}

interface MetaYml {
  name?: string;
  description?: string;
  homepage?: string;
  tools?: Array<Record<string, { description?: string; homepage?: string; identifier?: string }>>;
  /** Either a map { channel: … } (modern) or a list of single-key maps (older). */
  output?: unknown;
}

/** nf-core wraps the extension in braces, e.g. "*.{summary.txt}". With a single
 *  option (no comma) that's just literal text, but the catalog `find` uses
 *  Python glob/fnmatch, which doesn't do brace expansion — so unwrap it. Leave
 *  multi-option braces ("*.{bam,cram}") for the author to resolve by hand. */
function cleanPattern(p: string): string {
  return p.replace(/\{([^{},]*)\}/g, '$1');
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
export function parseNfCoreOutputs(output: unknown): NfCoreOutput[] {
  const outs: NfCoreOutput[] = [];
  const push = (name: string, value: unknown) => {
    const d = findFileDescriptor(value);
    if (d) {
      outs.push({ name, pattern: cleanPattern(d.pattern), description: d.description.trim(), type: 'file' });
    }
  };
  if (Array.isArray(output)) {
    for (const item of output) {
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        const entries = Object.entries(item as Record<string, unknown>);
        if (entries.length === 1) push(entries[0][0], entries[0][1]);
        else {
          const d = findFileDescriptor(item);
          if (d) outs.push({ name: cleanPattern(d.pattern), pattern: cleanPattern(d.pattern), description: d.description.trim(), type: 'file' });
        }
      }
    }
  } else if (output && typeof output === 'object') {
    for (const [name, value] of Object.entries(output as Record<string, unknown>)) push(name, value);
  }
  return outs;
}

export async function fetchNfCoreMeta(moduleUrl: string): Promise<NfCoreMeta> {
  const url = metaYmlUrl(moduleUrl.trim());
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  const text = await res.text();
  const doc = (yaml.load(text) ?? {}) as MetaYml;

  // meta.yml `tools` is a list of single-key maps: [{ tool: {description,...} }]
  let description = doc.description ?? '';
  let homepage = doc.homepage ?? '';
  let biotools = '';
  const first = doc.tools?.[0];
  if (first) {
    const [, info] = Object.entries(first)[0] ?? [];
    if (info) {
      description = description || info.description || '';
      homepage = homepage || info.homepage || '';
      const id = info.identifier || '';
      if (id.startsWith('biotools:')) biotools = `https://bio.tools/${id.slice('biotools:'.length)}`;
    }
  }
  return {
    name: doc.name ?? '',
    description,
    homepage,
    biotools_url: biotools,
    outputs: parseNfCoreOutputs(doc.output),
  };
}
