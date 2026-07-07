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

export interface NfCoreMeta {
  name: string;
  description: string;
  homepage: string;
  biotools_url: string;
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
  };
}
