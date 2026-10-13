/**
 * Fetch a fixture from a URL instead of dropping the file.
 *
 * The path glob on the Tool step is a *pattern*, not an address, so there is
 * nothing for the app to pull from a tool source: nf-core's module snapshots
 * carry md5 checksums, not output content. What does exist are corpora of real
 * tool outputs that can be linked directly, and this is how they get in:
 *
 *   nf-core megatests  nf-core-awsmegatests.s3.eu-west-1.amazonaws.com
 *                      → <pipeline>/results-<sha>/… , full-scale pipeline runs
 *   MultiQC            github.com/MultiQC/test-data → data/modules/<tool>/
 *   Galaxy             github.com/galaxyproject/tools-iuc → tools/<tool>/test-data/
 *
 * All three are reachable from a browser with no backend: the megatests bucket
 * answers anonymously with `Access-Control-Allow-Origin: *` (and allows an
 * anonymous ListObjectsV2, which is how scripts/nfcore_monitor.py walks it),
 * and raw.githubusercontent.com sends permissive CORS headers, which the
 * tool-source extractors already rely on. Arbitrary hosts usually do not, and
 * that is a browser rule this app cannot work around: {@link fetchFixtureText}
 * says so plainly rather than reporting an opaque "failed to fetch".
 *
 * The megatests are the closest thing to the real article, being the output of
 * an actual pipeline run rather than a test fixture, so they are what the
 * Fixture step points at first.
 */
import { githubRawUrl } from './githubRaw';

export interface FetchedFixture {
  fileName: string;
  text: string;
  /** Byte length of the response, for the same size cap a dropped file gets. */
  bytes: number;
}

/** Extensions the Fixture step will parse. `.txt` and `.tab` are here because
 *  that is what most real tool outputs are called; the delimiter is sniffed. */
export const TABULAR_EXT_RE = /\.(csv|tsv|txt|tab)$/i;

/** File name a URL implies: last path segment, query and fragment removed. */
export function fileNameFromUrl(url: string): string {
  try {
    return decodeURIComponent(new URL(url).pathname.split('/').filter(Boolean).pop() ?? '');
  } catch {
    return '';
  }
}

/**
 * Fetch `url` as text, rewriting a GitHub web URL to its raw form first (a
 * `…/blob/…` link is what you get from the address bar, and it serves HTML).
 * Throws with an explanation the Fixture step can show as-is.
 */
export async function fetchFixtureText(url: string): Promise<FetchedFixture> {
  const trimmed = url.trim();
  if (!/^https?:\/\//i.test(trimmed)) {
    throw new Error('Paste a full http(s) URL.');
  }
  const raw = githubRawUrl(trimmed);
  const fileName = fileNameFromUrl(raw);
  if (!fileName) throw new Error('That URL has no file name at the end of its path.');
  if (!TABULAR_EXT_RE.test(fileName)) {
    throw new Error(`${fileName} is not a .csv, .tsv, .txt or .tab file.`);
  }

  let res: Response;
  try {
    res = await fetch(raw);
  } catch {
    // A network-level failure in the browser is almost always CORS, and the
    // exception carries no detail by design. Name the likely cause and the way
    // out instead of surfacing "Failed to fetch".
    throw new Error(
      'Could not fetch that URL. The host has to allow cross-origin requests, ' +
        'which most do not; a raw.githubusercontent.com link works. Otherwise ' +
        'download the file and drop it here.',
    );
  }
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} fetching ${fileName}.`);
  }
  const text = await res.text();
  return { fileName, text, bytes: new TextEncoder().encode(text).length };
}
