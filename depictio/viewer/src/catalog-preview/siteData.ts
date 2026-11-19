/**
 * Site-level JSON of the multi-file catalog (`versions.json`, `releases.json`,
 * `modules/<tool>.json`), fetched on demand and cached. Every fetch resolves to
 * null on any failure (404, network, not JSON, wrong shape): a bare export has
 * none of these files and the UI around them simply stays hidden.
 *
 * Only ever called when `g.lazyOutputs` is set (the site build); the single-file
 * bundle never reaches this module's fetches.
 */
import { moduleUrl, siteFileUrl } from './siteTree';
import type { CatalogGlobal } from './shared';

export type Bump = 'major' | 'minor' | 'patch' | null;

export interface ModuleRender {
  index: string;
  component_type?: string;
  _yaml?: string | null;
}
export interface ModuleOutput {
  id: string;
  name?: string;
  renders?: ModuleRender[];
}
export interface ModuleVersion {
  version: string;
  bump?: Bump;
  releases: string[];
  outputs: ModuleOutput[];
}
export interface ModuleHistory {
  id: string;
  name?: string;
  versions: ModuleVersion[];
}
export interface VersionsFile {
  latest: string;
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

const cache = new Map<string, Promise<unknown>>();

function fetchJson<T>(url: string, valid: (v: unknown) => v is T): Promise<T | null> {
  let p = cache.get(url) as Promise<T | null> | undefined;
  if (!p) {
    p = fetch(url)
      .then((r) => (r.ok ? r.json() : null))
      .then((v) => (valid(v) ? v : null))
      .catch(() => null);
    cache.set(url, p);
  }
  return p;
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
