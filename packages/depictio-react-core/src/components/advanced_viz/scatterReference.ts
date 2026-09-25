/**
 * Which side of a scatter_xy reference line a point is on.
 *
 * The same reading as the Manhattan threshold: "above" is the greater value.
 * Against a horizontal line that is y above `value`, against a vertical one x
 * beyond `value`, and against the diagonal y greater than x. Points on the
 * line are below it.
 */

export type ReferenceLine = 'none' | 'diagonal' | 'horizontal' | 'vertical';
export type ReferenceHighlight = 'none' | 'above' | 'below';

export interface XY {
  x: number;
  y: number;
}

/**
 * The predicate that says whether a point is on the highlighted side, or
 * `null` when there is nothing to highlight: no line, no side asked for, or a
 * horizontal / vertical line with no value to sit at.
 */
export function highlightPredicate(
  line: ReferenceLine,
  value: number | null | undefined,
  highlight: ReferenceHighlight,
): ((p: XY) => boolean) | null {
  if (highlight === 'none') return null;
  let above: ((p: XY) => boolean) | null = null;
  if (line === 'diagonal') above = (p) => p.y > p.x;
  else if (line === 'horizontal' && value != null) above = (p) => p.y > value;
  else if (line === 'vertical' && value != null) above = (p) => p.x > value;
  if (!above) return null;
  const wantAbove = highlight === 'above';
  return (p) => above(p) === wantAbove;
}
