/**
 * URL arithmetic for the multi-file catalog site (see docs/design/catalog-site.md).
 *
 * Pure functions, no DOM and no fetch, so `dev/catalog_site_check.mjs` can run them
 * under Node. A slot (`latest/`, `v1.22.0/`) serves `data/index.json`; the site
 * root, the slot's parent, holds `objects/`, `modules/`, `versions.json` and
 * `releases.json`.
 */

export interface OutputRef {
  output: { id: string; dataRef?: string | null };
  /** Content hash of the output's payload in `objects/` (a published slot). */
  dataRef?: string | null;
}

const withSlash = (s: string): string => (s.endsWith('/') ? s : `${s}/`);

/** The site root: the parent of the slot that `dataBase` (e.g. `data/`) lives in. */
export function siteRootUrl(baseHref: string, dataBase = 'data/'): URL {
  const dataDir = new URL(withSlash(dataBase), baseHref);
  return new URL('../../', dataDir);
}

/** A file at the site root, e.g. `versions.json` or `modules/ivar.json`. */
export function siteFileUrl(baseHref: string, dataBase: string, path: string): string {
  return new URL(path, siteRootUrl(baseHref, dataBase)).href;
}

export const moduleUrl = (baseHref: string, dataBase: string, toolId: string): string =>
  siteFileUrl(baseHref, dataBase, `modules/${encodeURIComponent(toolId)}.json`);

/** Where one output's payload is: `objects/<dataRef>.json` at the site root when the
 *  entry has a `dataRef`, else `<dataBase>outputs/<id>.json` (a bare export, left
 *  relative exactly as before). */
export function outputFileUrl(entry: OutputRef, dataBase: string, baseHref: string): string {
  const ref = entry.dataRef ?? entry.output.dataRef;
  if (ref) return siteFileUrl(baseHref, dataBase, `objects/${encodeURIComponent(ref)}.json`);
  return `${withSlash(dataBase)}outputs/${encodeURIComponent(entry.output.id)}.json`;
}

/** The slot the page is served from: the directory holding `index.html`.
 *  Accepted when it is `latest` or listed in `versions`; otherwise falls back to
 *  `v<indexVersion>` when that is listed, else null. */
export function currentSlot(
  pathname: string,
  versions: string[],
  indexVersion?: string | null,
): string | null {
  const segs = pathname.split('/').filter(Boolean);
  if (segs.length && /\.[a-z0-9]+$/i.test(segs[segs.length - 1])) segs.pop();
  const last = segs.length ? decodeURIComponent(segs[segs.length - 1]) : '';
  if (last === 'latest' || versions.includes(last)) return last;
  if (indexVersion) {
    const v = indexVersion.startsWith('v') ? indexVersion : `v${indexVersion}`;
    if (versions.includes(v)) return v;
  }
  return null;
}

/** `<root>/<slot>/` keeping the current query and hash (release selector). */
export function slotHref(
  baseHref: string,
  dataBase: string,
  slot: string,
  search = '',
  hash = '',
): string {
  const u = new URL(`${encodeURIComponent(slot)}/`, siteRootUrl(baseHref, dataBase));
  u.search = search;
  u.hash = hash;
  return u.href;
}

/** `<root>/<slot>/?theme=<theme>#output=<id>` (or `#tool=<id>`). */
export function openInSlotHref(
  baseHref: string,
  dataBase: string,
  slot: string,
  theme: string | undefined,
  target: { output?: string; tool?: string },
): string {
  const u = new URL(`${encodeURIComponent(slot)}/`, siteRootUrl(baseHref, dataBase));
  if (theme) u.search = `?theme=${encodeURIComponent(theme)}`;
  u.hash = target.output
    ? `#output=${encodeURIComponent(target.output)}`
    : `#tool=${encodeURIComponent(target.tool ?? '')}`;
  return u.href;
}

/** Among the slots shipping a version, the most recent one. `order` is newest
 *  first (`latest`, then versions.json); without it, the first listed. */
export function pickSlot(releases: string[], order: string[] = []): string | null {
  if (!releases.length) return null;
  let best: string | null = null;
  let bestRank = Infinity;
  for (const r of releases) {
    const rank = order.indexOf(r);
    if (rank !== -1 && rank < bestRank) {
      best = r;
      bestRank = rank;
    }
  }
  return best ?? releases[0];
}
