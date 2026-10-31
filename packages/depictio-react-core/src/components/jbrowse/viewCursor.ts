/**
 * What the genome browser tile tells the other genomic tiles about where the
 * reader is: the position under the pointer and the window on screen. Pure
 * functions over the slice of the LinearGenomeView model they read, so they
 * are testable without a browser.
 *
 * Coordinates leave here the way the bus carries them: 1-based, inclusive.
 */

/** The result of the view's ``pxToBp`` this file reads. */
export interface PxToBpResult {
  refName: string;
  /** 1-based coordinate under the pixel. */
  coord: number;
  /** The pixel is outside every displayed region (before the first, after the last). */
  oob?: boolean;
}

export interface CursorView {
  displayedRegions?: unknown[];
  /** Pixel offset from the left edge of the tracks area to a locus. */
  pxToBp: (px: number) => PxToBpResult;
}

/**
 * The locus under ``clientX``, given the left edge of the tracks area
 * (``tracksLeft``, a bounding-rect ``left``): JBrowse's pixel 0 is that edge,
 * so the conversion is the view's own ``pxToBp`` of the offset into it. ``null``
 * outside the genome (padding past the ends, no region loaded yet).
 */
export function cursorLocus(
  view: CursorView,
  clientX: number,
  tracksLeft: number,
): { refName: string; coord: number } | null {
  if (!view.displayedRegions?.length) return null;
  const px = clientX - tracksLeft;
  if (!Number.isFinite(px) || px < 0) return null;
  const hit = view.pxToBp(px);
  if (!hit || hit.oob || !hit.refName || !Number.isFinite(hit.coord) || hit.coord < 1) return null;
  return { refName: hit.refName, coord: Math.round(hit.coord) };
}

/** One visible block of the view (``dynamicBlocks.contentBlocks``); 0-based
 *  ``start``, end-exclusive, either may be fractional. */
export interface VisibleBlock {
  refName: string;
  start: number;
  end: number;
}

/**
 * The window on screen as a bus window: the first visible block's contig and
 * its extent. A view spanning several contigs reports the first (the others
 * have no single x axis a plot could fit). ``null`` while no block exists yet.
 */
export function visibleWindow(
  blocks: readonly VisibleBlock[] | undefined,
): { entity: string; start: number; end: number } | null {
  const first = blocks?.[0];
  if (!first || !first.refName) return null;
  const start = Math.floor(first.start) + 1;
  const end = Math.ceil(first.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  return { entity: first.refName, start, end };
}

/** An assembly's ``refNameAliases``: every name a contig answers to, mapped
 *  to its canonical reference name (the canonical name maps to itself). */
export type RefNameAliases = Record<string, string>;

/**
 * A lookup from a canonical reference name to the other names the assembly
 * knows it by (UCSC chromAlias: ``NC_045512v2`` is also ``MN908947.3`` and
 * ``NC_045512.2``), or ``undefined`` when there are none. The alias map is
 * read through ``getAliases`` on every call, because an assembly loads them
 * after the view exists; the inverse index is rebuilt only when the map
 * itself changes.
 */
export function createAliasLookup(
  getAliases: () => RefNameAliases | undefined,
): (refName: string) => string[] | undefined {
  let source: RefNameAliases | undefined;
  let inverse = new Map<string, string[]>();
  return (refName) => {
    const map = getAliases();
    if (!map) return undefined;
    if (map !== source) {
      source = map;
      inverse = new Map();
      for (const [alias, canonical] of Object.entries(map)) {
        if (alias === canonical) continue;
        const list = inverse.get(canonical);
        if (list) list.push(alias);
        else inverse.set(canonical, [alias]);
      }
    }
    return inverse.get(refName);
  };
}

/** The slice of a JBrowse assembly the canonical-name lookup reads. */
export interface CanonicalAssembly {
  getCanonicalRefName?: (name: string) => string | undefined;
}

/**
 * The assembly's canonical name for ``name`` ("20" → "chr20"), or undefined
 * when it cannot say. JBrowse *throws* until the assembly's aliases have
 * loaded, and the callers run in effects, where a throw takes the whole
 * viewer down: the lookup is best effort, never fatal.
 */
export function canonicalRefName(
  assembly: CanonicalAssembly | null | undefined,
  name: string,
): string | undefined {
  try {
    return assembly?.getCanonicalRefName?.(name) || undefined;
  } catch {
    return undefined;
  }
}
