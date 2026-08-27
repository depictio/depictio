/**
 * Fetch a Galaxy tool's XML wrapper client-side and extract identity fields —
 * the Galaxy counterpart of `fromNfCore.ts`. raw.githubusercontent.com sends
 * permissive CORS headers, so a browser fetch works with no backend; we parse
 * the XML with the browser-native `DOMParser` (no extra dependency).
 *
 * Accepts a GitHub URL to the tool's `.xml` wrapper, e.g.
 *   https://github.com/galaxyproject/tools-iuc/blob/main/tools/<tool>/<tool>.xml
 * Toolshed / doc URLs don't map cleanly to a raw file, so they are returned
 * unchanged and the fetch fails with a clear HTTP error (surfaced in the UI).
 *
 * Extraction is best-effort: Galaxy wrappers frequently pull `name`/`version`
 * and the bio.tools xref from a sibling `macros.xml` via `<expand macro="…"/>`,
 * which this single-file parse does not resolve. Fields left behind by macros
 * come back '' for the author to fill.
 */
import type { ExtractedMeta, OutputChannel } from '../types';
import { githubRawUrl } from './githubRaw';

/**
 * Canonicalise a pasted Galaxy tool URL. A Galaxy wrapper is a single `.xml`
 * file, so (unlike nf-core) there is no directory form to normalise to — we
 * keep the `/blob/` path that maps to a raw file and only trim whitespace and
 * trailing slashes. Non-GitHub URLs are returned as-is.
 */
export function canonicalGalaxyUrl(url: string): string {
  return url.trim().replace(/\/+$/, '');
}

/** Turn a GitHub `.xml` blob/tree URL into the raw.githubusercontent.com URL. */
export function toolXmlUrl(xmlUrl: string): string {
  return githubRawUrl(canonicalGalaxyUrl(xmlUrl));
}

/** Text content of the first matching child element, trimmed (collapsing the
 *  internal whitespace Galaxy wrappers often wrap `<description>` across). */
function elementText(root: Element | Document, tag: string): string {
  const el = root.querySelector(tag);
  return el?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

/** Parse `<outputs>` `<data>` elements into output channels. `from_work_dir`
 *  (a concrete filename) is preferred as the glob; otherwise `*.<format>` when
 *  the format is a real extension (not Galaxy's dynamic `auto`/`input`). */
export function parseGalaxyOutputs(doc: Document): OutputChannel[] {
  const outs: OutputChannel[] = [];
  doc.querySelectorAll('outputs > data, outputs > collection').forEach((data) => {
    const name = data.getAttribute('name') ?? '';
    if (!name) return;
    const format = data.getAttribute('format') ?? '';
    const fromWorkDir = data.getAttribute('from_work_dir') ?? '';
    const label = data.getAttribute('label') ?? '';
    let pattern = '';
    if (fromWorkDir) pattern = fromWorkDir;
    else if (format && !['auto', 'input', 'data'].includes(format)) pattern = `*.${format}`;
    // Galaxy labels are often Cheetah/macro templates (`${tool.name} on
    // ${on_string}`, `@LABEL@`) — useless as a description, so drop them.
    const description = /[$@]/.test(label) ? '' : label.replace(/\s+/g, ' ').trim();
    outs.push({ name, pattern, description, type: 'file' });
  });
  return outs;
}

export async function fetchGalaxyMeta(xmlUrl: string): Promise<ExtractedMeta> {
  const url = toolXmlUrl(xmlUrl);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  const text = await res.text();
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  if (doc.querySelector('parsererror')) {
    throw new Error('Could not parse the Galaxy tool XML.');
  }

  const tool = doc.querySelector('tool');
  // `name` and `version` may be macro tokens (e.g. "@TOOL_VERSION@"); the id is
  // reliable. Prefer a non-token name, else fall back to the id.
  const rawName = tool?.getAttribute('name') ?? '';
  const id = tool?.getAttribute('id') ?? '';
  const name = rawName && !rawName.includes('@') ? rawName : id;

  // bio.tools only when declared inline (macro-expanded xrefs aren't resolved).
  let biotools = '';
  const xref = Array.from(doc.querySelectorAll('xrefs > xref')).find(
    (x) => x.getAttribute('type') === 'bio.tools',
  );
  const bioId = xref?.textContent?.trim();
  if (bioId) biotools = `https://bio.tools/${bioId}`;

  return {
    name,
    description: elementText(doc, 'description'),
    homepage: '',
    biotools_url: biotools,
    source_url: canonicalGalaxyUrl(xmlUrl),
    outputs: parseGalaxyOutputs(doc),
  };
}
