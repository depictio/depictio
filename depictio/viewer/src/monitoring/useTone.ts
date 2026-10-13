import { useChromeStyle } from 'depictio-react-core';

/** The id of the Glass chrome style; the pages package spells it the same. */
const GLASS = 'glass';

/** Hues that mean something on a tag: success, failure, pending / running,
 *  and "no state". Orange and pink fold into the nearest of them; every other
 *  hue was decoration and goes grey. */
const MEANING: Record<string, string> = {
  green: 'green',
  red: 'red',
  yellow: 'yellow',
  gray: 'gray',
  orange: 'yellow',
  pink: 'red',
};

/**
 * Whether the page wears the Glass chrome, whose tags are hairline chips with
 * their hue reduced to a dot: there a badge's colour is a signal, not a paint.
 * Classic keeps its tinted badges.
 */
export function useQuietTags(): boolean {
  return useChromeStyle().id === GLASS;
}

/**
 * Maps a badge colour to the one to render: unchanged in Classic, reduced to
 * the colours that carry a state in Glass.
 */
export function useTone(): (color: string) => string {
  const quiet = useQuietTags();
  return (color) => (quiet ? (MEANING[color] ?? 'gray') : color);
}
