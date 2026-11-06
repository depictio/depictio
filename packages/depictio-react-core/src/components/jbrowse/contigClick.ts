/**
 * The contig a click on a one-bar-per-contig figure names, or null.
 *
 * Read off the clicked mark's category axis: `x`, or `y` on a horizontal bar
 * (`orientation: 'h'` in the figure's kwargs). The summary rows that are not a
 * contig give nothing: a `total` bar, and the `_region` twin mosdepth writes
 * beside a contig when it ran with a capture bed is taken as the contig itself.
 */
export function contigOfClickedMark(
  event: { points?: Array<{ x?: unknown; y?: unknown }> } | null | undefined,
  kwargs?: Record<string, unknown> | null,
): string | null {
  const point = event?.points?.[0];
  if (!point) return null;
  const horizontal = kwargs?.orientation === 'h';
  const raw = horizontal ? point.y : point.x;
  if (typeof raw !== 'string' && typeof raw !== 'number') return null;
  const name = String(raw).trim().replace(/_region$/, '');
  if (name === '' || name.toLowerCase() === 'total') return null;
  return name;
}
