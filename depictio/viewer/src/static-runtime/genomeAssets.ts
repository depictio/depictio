/**
 * GenomeSpy tiles offline: fonts and gene tables from the bundle, never the
 * network (`depictio-react-core`'s `genomespy/offlineAssets.ts`).
 *
 * Gene tables: producer A ships one per assembly a genome tile names (the
 * `annotation` / `assembly` of a genome_view, cnv_profile or sashimi tile) as
 * `inline_blobs["genes_<assembly>"]`, gzip-compressed then base64-encoded
 * (`depictio/serverless/gene_assets.py`). An assembly the bundle did not ship
 * resolves to `null`: the tile draws no gene lane rather than fetching
 * `./assets/genomes/<assembly>.genes.json` over file://.
 */
import { setGeneAssetSource, setGenomeSpyFontsEmbeddedOnly } from 'depictio-react-core';

import { rawBundle } from './bundle';

/** The `inline_blobs` key of an assembly's gene table. */
export function geneBlobKey(assembly: string): string {
  return `genes_${assembly}`;
}

function base64Bytes(b64: string): Uint8Array<ArrayBuffer> {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function gunzipText(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return new TextDecoder().decode(bytes);
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).text();
}

/** The shipped gene table of `assembly`, decoded, or null when not shipped. */
export async function bundledGeneTable(
  assembly: string,
  blobs: Record<string, string> | undefined = rawBundle().inline_blobs,
): Promise<unknown | null> {
  const b64 = blobs?.[geneBlobKey(assembly)];
  if (!b64) return null;
  try {
    return JSON.parse(await gunzipText(base64Bytes(b64))) as unknown;
  } catch (e) {
    console.error(`static bundle: the shipped ${assembly} gene table is unreadable`, e);
    return null;
  }
}

/** Point every GenomeSpy tile at the bundle: embedded font, shipped genes. */
export function installOfflineGenomeAssets(): void {
  setGenomeSpyFontsEmbeddedOnly(true);
  setGeneAssetSource((assembly) => bundledGeneTable(assembly));
}
