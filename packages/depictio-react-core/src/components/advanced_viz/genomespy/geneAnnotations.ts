/**
 * Lazy loader for the bundled gene tables the `genome_view` annotation lane
 * draws.
 *
 * `@genome-spy/core` ships chromosome *sizes* only (`genome/genomes.js`
 * exports `getContigs(assembly)`), no gene models, so the lane needs an asset
 * of its own. `dev/advanced_viz_kinds/build_genome_gene_assets.py` builds one
 * JSON per assembly from GENCODE and writes it to
 * `depictio/viewer/public/assets/genomes/<assembly>.genes.json`, where Vite
 * copies it into `dist/assets/` and the API's existing `/dashboard/assets`
 * mount serves it.
 *
 * The asset is array-of-arrays, not array-of-objects: the field names appear
 * once in `columns` instead of once per gene, which is what keeps hg38
 * (20 092 protein-coding genes) at 0.8 MB.
 *
 * Nothing here throws at the caller: a host that does not serve the asset
 * (the catalog preview, Tool Studio) simply gets `null` and the tile draws no
 * lane.
 */

import type { GeneRow } from './genomeSpySpec';

interface GeneAssetPayload {
  assembly?: string;
  source?: string;
  columns?: string[];
  genes?: unknown[][];
}

export interface GeneAnnotation {
  assembly: string;
  source: string;
  genes: GeneRow[];
}

/** Where the assets live, relative to the app's base URL. */
export const GENE_ASSET_DIR = 'assets/genomes';

/** Resolved once: `import.meta.env.BASE_URL` is `/dashboard/` in the viewer. */
function assetBase(): string {
  const env = (import.meta as unknown as { env?: { BASE_URL?: string } }).env;
  const base = env?.BASE_URL ?? '/';
  return base.endsWith('/') ? base : `${base}/`;
}

export function geneAssetUrl(assembly: string): string {
  return `${assetBase()}${GENE_ASSET_DIR}/${assembly}.genes.json`;
}

/** Decode the columnar payload into the rows the spec builder wants. */
export function decodeGeneAsset(payload: unknown): GeneAnnotation | null {
  const p = payload as GeneAssetPayload | null;
  if (!p || !Array.isArray(p.genes) || !Array.isArray(p.columns)) return null;
  const idx = (name: string) => p.columns!.indexOf(name);
  const iName = idx('name');
  const iChrom = idx('chrom');
  const iStart = idx('start');
  const iEnd = idx('end');
  const iStrand = idx('strand');
  if (iName < 0 || iChrom < 0 || iStart < 0 || iEnd < 0) return null;

  const genes: GeneRow[] = [];
  for (const row of p.genes) {
    if (!Array.isArray(row)) continue;
    const start = Number(row[iStart]);
    const end = Number(row[iEnd]);
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    genes.push({
      name: String(row[iName]),
      chrom: String(row[iChrom]),
      start,
      end,
      strand: iStrand >= 0 ? String(row[iStrand] ?? '') : '',
    });
  }
  return {
    assembly: typeof p.assembly === 'string' ? p.assembly : '',
    source: typeof p.source === 'string' ? p.source : '',
    genes,
  };
}

/** One in-flight or resolved promise per assembly, for the whole process: a
 *  dashboard with four hg38 tiles fetches the table once. */
const cache = new Map<string, Promise<GeneAnnotation | null>>();

/**
 * Fetch and decode the gene table for `assembly`, or resolve to `null` when
 * the asset is missing or malformed. `'none'` short-circuits without a fetch.
 */
export function loadGeneAnnotation(assembly: string | null | undefined): Promise<GeneAnnotation | null> {
  if (!assembly || assembly === 'none') return Promise.resolve(null);
  const hit = cache.get(assembly);
  if (hit) return hit;
  const pending = fetch(geneAssetUrl(assembly))
    .then((res) => (res.ok ? res.json() : null))
    .then((json) => decodeGeneAsset(json))
    .catch(() => null);
  cache.set(assembly, pending);
  return pending;
}

/** Test seam: drops the memoised assets. */
export function clearGeneAnnotationCache(): void {
  cache.clear();
}
