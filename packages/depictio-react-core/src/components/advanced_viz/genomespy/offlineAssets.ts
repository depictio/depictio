/**
 * What a GenomeSpy tile would otherwise fetch, for a host with no network.
 *
 * A static bundle is opened from disk, so two things the live tiles take from
 * the network have to come from elsewhere:
 *
 * - **Fonts.** GenomeSpy ships one font, Lato regular (normal, 400), inside its
 *   own bundle. Any other family, weight or style is fetched on first use from
 *   the A-Frame font repository on raw.githubusercontent.com (its
 *   `METADATA.pb`, then the glyph atlas). A lane title in bold was enough to
 *   send every genome view to GitHub. With `setGenomeSpyFontsEmbeddedOnly`,
 *   the spec is rewritten to the embedded font before it is embedded: the
 *   text keeps its size and colour and loses only its weight or face.
 * - **Gene tables.** `loadGeneAnnotation` fetches
 *   `assets/genomes/<assembly>.genes.json` from the app's base URL. A host can
 *   answer that itself (`setGeneAssetSource`): the static runtime reads the
 *   copy the producer shipped in the bundle, and answers `null` (no lane, no
 *   request) for an assembly it did not ship.
 */

let embeddedFontsOnly = false;

/** Make every GenomeSpy spec use only the font GenomeSpy embeds. */
export function setGenomeSpyFontsEmbeddedOnly(on: boolean): void {
  embeddedFontsOnly = on;
}

export function genomeSpyFontsEmbeddedOnly(): boolean {
  return embeddedFontsOnly;
}

/** The font GenomeSpy embeds (`bmFontManager.js`, DEFAULT_FONT_KEY). */
const EMBEDDED_FAMILIES = new Set(['lato', 'sans-serif']);
const EMBEDDED_WEIGHTS = new Set<unknown>([400, '400', 'normal', 'regular']);

/** A spec key naming a font family (`font`, `labelFont`, `titleFont`, ...). */
const FAMILY_KEY = /^(?:[a-z]+F|f)ont$/;
const WEIGHT_KEY = /^(?:[a-z]+F|f)ontWeight$/;
const STYLE_KEY = /^(?:[a-z]+F|f)ontStyle$/;

/** Data payloads are never font settings and can be large: not walked. */
const SKIPPED_KEYS = new Set(['data', 'values']);

/** True when a font setting would make GenomeSpy fetch a font. */
export function fetchesFont(key: string, value: unknown): boolean {
  if (FAMILY_KEY.test(key)) {
    return typeof value === 'string' && !EMBEDDED_FAMILIES.has(value.trim().toLowerCase());
  }
  if (WEIGHT_KEY.test(key)) {
    const v = typeof value === 'string' ? value.trim().toLowerCase() : value;
    return v !== undefined && v !== null && !EMBEDDED_WEIGHTS.has(v);
  }
  if (STYLE_KEY.test(key)) {
    return typeof value === 'string' && value.trim().toLowerCase() !== 'normal';
  }
  return false;
}

/**
 * `spec` with every font setting GenomeSpy would fetch for removed, so it
 * falls back to the embedded font. Returns the same object when there is
 * nothing to remove (callers memoise on the spec's identity).
 */
export function withEmbeddedFonts<T>(spec: T): T {
  const strip = (node: unknown): unknown => {
    if (Array.isArray(node)) {
      let changed = false;
      const out = node.map((child) => {
        const next = strip(child);
        if (next !== child) changed = true;
        return next;
      });
      return changed ? out : node;
    }
    if (node === null || typeof node !== 'object') return node;
    let changed = false;
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      if (fetchesFont(key, value)) {
        changed = true;
        continue;
      }
      const next = SKIPPED_KEYS.has(key) ? value : strip(value);
      if (next !== value) changed = true;
      out[key] = next;
    }
    return changed ? out : node;
  };
  return strip(spec) as T;
}

/** Answers a gene-table request: the decoded JSON payload, or null for none. */
export type GeneAssetSource = (assembly: string) => Promise<unknown | null>;

let geneAssetSource: GeneAssetSource | null = null;

/** Serve gene tables from the host instead of `assets/genomes/` (null: fetch). */
export function setGeneAssetSource(source: GeneAssetSource | null): void {
  geneAssetSource = source;
}

export function currentGeneAssetSource(): GeneAssetSource | null {
  return geneAssetSource;
}
