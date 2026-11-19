/**
 * On-demand per-output payloads for the multi-file catalog site.
 *
 * The site ships `data/index.json` (tool/output metadata + an EMPTY data map)
 * and one `data/outputs/<id>.json` per output. The offline api shim reads
 * everything from `window.__CATALOG_PREVIEW__.data`, so loading an output means
 * merging its partial `data` into that map and its `fixturePreview` into the
 * entry before the renderers mount.
 *
 * The single-file bundle embeds the full payload and never sets `lazyOutputs`,
 * so none of this runs there.
 */
import type { CatalogGlobal, FixturePreview, OutputEntry } from './shared';

interface OutputFile {
  fixturePreview?: FixturePreview | null;
  data?: Record<string, unknown>;
}

const loaded = new Set<string>();
const inflight = new Map<string, Promise<void>>();

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

/** Key-by-key merge of an output's partial OfflineData into the shared map.
 *  `cards` has nested sub-maps (values / secondary / aggregations). */
export function mergeOutputData(
  target: Record<string, unknown>,
  partial: Record<string, unknown>,
): void {
  for (const [section, value] of Object.entries(partial)) {
    if (!isObj(value)) continue;
    const dst = (isObj(target[section]) ? target[section] : (target[section] = {})) as Record<
      string,
      unknown
    >;
    if (section === 'cards') {
      for (const [sub, subVal] of Object.entries(value)) {
        if (!isObj(subVal)) continue;
        const subDst = (isObj(dst[sub]) ? dst[sub] : (dst[sub] = {})) as Record<string, unknown>;
        Object.assign(subDst, subVal);
      }
    } else {
      Object.assign(dst, value);
    }
  }
}

export const isLazy = (g: CatalogGlobal | undefined): boolean => Boolean(g?.lazyOutputs);

export const isOutputLoaded = (id: string): boolean => loaded.has(id);

/** Fetch + merge one output's payload (idempotent, cached in memory). */
export function ensureOutputLoaded(g: CatalogGlobal, entry: OutputEntry): Promise<void> {
  const id = entry.output.id;
  if (loaded.has(id)) return Promise.resolve();
  const pending = inflight.get(id);
  if (pending) return pending;
  const base = g.dataBase ?? 'data/';
  const p = fetch(`${base}outputs/${encodeURIComponent(id)}.json`)
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status} while loading output "${id}"`);
      return r.json() as Promise<OutputFile>;
    })
    .then((file) => {
      const data = (g.data ?? (g.data = {})) as Record<string, unknown>;
      mergeOutputData(data, file.data ?? {});
      if (file.fixturePreview !== undefined) entry.fixturePreview = file.fixturePreview;
      loaded.add(id);
    })
    .finally(() => {
      inflight.delete(id);
    });
  inflight.set(id, p);
  return p;
}
