/**
 * Site-level JSON of the multi-file catalog (`versions.json`, `releases.json`,
 * `modules/<tool>.json`), fetched on demand and cached. Every fetch resolves to
 * null on any failure (404, network, not JSON, wrong shape): a bare export has
 * none of these files and the UI around them simply stays hidden.
 *
 * Only a success or a 404 (the file really is absent) stays cached. A network
 * error or a non-404 HTTP error resolves to null too but is dropped from the
 * cache, so the next display tries again instead of staying empty for the session.
 *
 * Only ever called when `g.lazyOutputs` is set (the site build); the single-file
 * bundle never reaches this module's fetches.
 */
import { moduleUrl, siteFileUrl } from './siteTree';
import type { CatalogGlobal } from './shared';

export type Bump = 'major' | 'minor' | 'patch' | 'downgrade' | null;

/** Mantine theme colour of each bump, for the badge. */
export const BUMP_COLOR: Record<string, string> = {
  major: 'red',
  minor: 'blue',
  patch: 'gray',
  downgrade: 'orange',
};

export interface ModuleRender {
  index: string;
  component_type?: string;
  _yaml?: string | null;
  /** The module revision this render last changed in, when it says. */
  version?: string;
}
export interface ModuleOutput {
  id: string;
  name?: string;
  /** The module revision this output last changed in, when it says. */
  version?: string;
  renders?: ModuleRender[];
}
export interface ModuleVersion {
  version: string;
  bump?: Bump;
  releases: string[];
  /** The module changelog's entry for this version, when it has one. */
  date?: string;
  changelog?: string[];
  outputs: ModuleOutput[];
}
export interface ModuleHistory {
  id: string;
  name?: string;
  versions: ModuleVersion[];
}
export interface VersionsFile {
  /** The `latest` slot's name, or null when the site has no `latest/` slot. */
  latest?: string | null;
  versions: string[];
}
export interface ReleaseChanges {
  added?: string[];
  removed?: string[];
  bumped?: { id: string; from: string; to: string; bump?: Bump }[];
  outputs_added?: string[];
  outputs_removed?: string[];
}
export interface ReleaseEntry {
  slot: string;
  version?: string;
  published?: string;
  previous?: string | null;
  changes?: ReleaseChanges;
}
export interface ReleasesFile {
  releases: ReleaseEntry[];
}

type Fetcher = (url: string) => Promise<Pick<Response, 'ok' | 'status' | 'json'>>;

/** Fetch `url` as JSON through `cache`. Exported with injectable `fetcher` and
 *  `cache` so `dev/catalog_site_check.mjs` can exercise the caching rule. */
export function fetchJsonCached<T>(
  url: string,
  valid: (v: unknown) => v is T,
  cache: Map<string, Promise<T | null>>,
  fetcher: Fetcher = (u) => fetch(u),
): Promise<T | null> {
  const hit = cache.get(url);
  if (hit) return hit;
  const p: Promise<T | null> = fetcher(url)
    .then((r) => {
      if (r.status === 404) return null; // absent for real: cached
      if (!r.ok) throw new Error(`HTTP ${r.status}`); // transient: retried next time
      return r.json().then((v: unknown) => (valid(v) ? v : null));
    })
    .catch(() => {
      if (cache.get(url) === p) cache.delete(url);
      return null;
    });
  cache.set(url, p);
  return p;
}

const cache = new Map<string, Promise<unknown>>();

function fetchJson<T>(url: string, valid: (v: unknown) => v is T): Promise<T | null> {
  return fetchJsonCached(url, valid, cache as Map<string, Promise<T | null>>);
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

const ctx = (g: CatalogGlobal) => ({
  href: window.location.href,
  dataBase: g.dataBase ?? 'data/',
});

export function fetchVersions(g: CatalogGlobal): Promise<VersionsFile | null> {
  const { href, dataBase } = ctx(g);
  return fetchJson(
    siteFileUrl(href, dataBase, 'versions.json'),
    (v): v is VersionsFile => isObj(v) && Array.isArray(v.versions),
  );
}

export function fetchReleases(g: CatalogGlobal): Promise<ReleasesFile | null> {
  const { href, dataBase } = ctx(g);
  return fetchJson(
    siteFileUrl(href, dataBase, 'releases.json'),
    (v): v is ReleasesFile => isObj(v) && Array.isArray(v.releases),
  );
}

export function fetchModule(g: CatalogGlobal, toolId: string): Promise<ModuleHistory | null> {
  const { href, dataBase } = ctx(g);
  return fetchJson(
    moduleUrl(href, dataBase, toolId),
    (v): v is ModuleHistory => isObj(v) && Array.isArray(v.versions) && v.versions.length > 0,
  );
}
