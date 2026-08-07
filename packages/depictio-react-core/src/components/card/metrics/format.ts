/** Number formatting shared by every secondary-metric layout.
 *
 *  One module so a value cannot be printed three different ways depending on
 *  which strip happens to draw it.
 */

/** Full-precision-ish rendering for a stat list or an axis anchor. */
export function formatSecondary(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return '—';
    if (!Number.isInteger(v)) return v.toFixed(4).replace(/\.?0+$/, '');
    return String(v);
  }
  return String(v);
}

/** Compact number for tight captions: 1.2B / 45.3k / 812. */
export function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}k`;
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2);
}

/** Axis-friendly rendering of a bin edge or a threshold — enough precision to
 *  distinguish adjacent values without spilling out of a 260px card. */
export function axisNumber(value: number): string {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e4 || (abs > 0 && abs < 0.01)) return value.toExponential(1);
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

/** Percent from a 0–1 share, without the false precision of "33.333%". */
export function percent(share: number, digits = 0): string {
  if (!Number.isFinite(share)) return '—';
  return `${(share * 100).toFixed(digits)}%`;
}

/** Convert a hex colour ("#FF7F00" or "FF7F00") to an `rgba(...)` string with
 *  the given alpha. Returns a teal fallback for invalid input, which is the
 *  accent cards without an explicit colour have always used. */
export function hexWithAlpha(hex: string | null | undefined, alpha: number): string {
  const fallback = `rgba(69,184,172,${alpha})`;
  if (!hex || typeof hex !== 'string') return fallback;
  // rgb()/rgba() inputs keep their channels with the requested alpha. Without
  // this, neutral tokens like METRIC.remainder fell through to the teal
  // fallback, so an "All"/"Other" ring rank-tinted teal while its siblings
  // drew the intended gray.
  const rgba = hex.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (rgba) return `rgba(${rgba[1]},${rgba[2]},${rgba[3]},${alpha})`;
  const cleaned = hex.replace('#', '').trim();
  if (cleaned.length !== 6 || !/^[0-9a-fA-F]{6}$/.test(cleaned)) return fallback;
  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

/** Opacity ramp for ranked segments of one accent colour. Rank 0 is the most
 *  opaque; nothing falls below 0.3, where a segment stops being distinguishable
 *  from the neutral track behind it. */
export function rankTint(color: string | null | undefined, rank: number): string {
  return hexWithAlpha(color, Math.max(0.3, 0.85 - rank * 0.16));
}
