import type { HighlightEvent } from '../../highlight/bus';

/** One band of JBrowse's ``LinearGenomeView.setHighlight`` (0-based start,
 *  end exclusive), drawn across every open track. */
export interface LocusHighlight {
  refName: string;
  start: number;
  end: number;
  assemblyName: string;
  color?: string;
}

/** JBrowse's own alpha for a highlight band it colours itself. */
export const BAND_ALPHA = 0.35;

/**
 * ``color`` (hex, ``rgb()`` or ``rgba()``) as a translucent ``rgba()``, so a
 * band wearing a mark's colour lets the tracks show through. ``null`` for a
 * format this does not read (a named colour, ``hsl()``, ``var()``).
 */
export function withAlpha(color: string | undefined, alpha: number = BAND_ALPHA): string | null {
  if (!color) return null;
  const c = color.trim();
  const hex = /^#([0-9a-f]{3,8})$/i.exec(c)?.[1];
  let rgb: number[] | null = null;
  if (hex && [3, 4, 6, 8].includes(hex.length)) {
    const full = hex.length <= 4 ? [...hex].map((h) => h + h).join('') : hex;
    rgb = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
  } else {
    const m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(c);
    if (m) rgb = [Number(m[1]), Number(m[2]), Number(m[3])];
  }
  if (!rgb || rgb.some((n) => !Number.isFinite(n))) return null;
  return `rgba(${rgb.join(', ')}, ${alpha})`;
}

/**
 * The band a hover on another tile asks for, or ``null`` when the event is
 * not about a position on this assembly.
 *
 * The bus is shared with the protein tiles, whose events name a protein and
 * count residues. ``canonicalRefName`` is the assembly's own lookup (it
 * resolves aliases, so "1" finds "chr1"): an event whose ``entity`` is not a
 * reference sequence of the assembly is ignored, which is what keeps a
 * lollipop's residue hover from drawing a band on a genome.
 *
 * Bus positions are 1-based and inclusive; the band is 0-based and
 * end-exclusive, so a single position becomes a 1 bp band.
 *
 * The band wears the hovered mark's colour (``event.color``) at JBrowse's band
 * alpha; an event without a readable one takes ``fallbackColor`` (the theme).
 */
export function locusHighlight(
  event: HighlightEvent | null,
  canonicalRefName: (name: string) => string | undefined,
  assemblyName: string,
  fallbackColor?: string,
): LocusHighlight | null {
  if (!event || !event.entity) return null;
  const start = Number(event.start);
  const end = Number(event.end ?? event.start);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 1) return null;
  const refName = canonicalRefName(event.entity);
  if (!refName) return null;
  const last = Math.max(start, end);
  const color = withAlpha(event.color) ?? withAlpha(fallbackColor);
  return {
    refName,
    start: start - 1,
    end: last,
    assemblyName,
    ...(color ? { color } : {}),
  };
}

/**
 * Whether the view shows ground outside `region` (`refName` canonical, 0-based
 * like the band): on another contig, or past either edge by more than
 * `tolerance` of the region's span. The band over a region another tile
 * selected is drawn only then: with the view inside the region it would tint
 * every track and mark nothing.
 */
export function viewLeavesRegion(
  visible: readonly { refName: string; start: number; end: number }[],
  region: { refName: string; start: number; end: number },
  tolerance = 0.02,
): boolean {
  const slack = (region.end - region.start) * tolerance;
  return visible.some(
    (v) =>
      v.refName !== region.refName ||
      v.start < region.start - slack ||
      v.end > region.end + slack,
  );
}
