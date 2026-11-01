import { useCallback, useMemo, useSyncExternalStore } from 'react';
import { useMantineColorScheme, useMantineTheme } from '@mantine/core';

import {
  EMPTY_HIGHLIGHT,
  reduceHighlight,
  type HighlightAction,
  type HighlightSource,
  type HighlightState,
  type HoverSource,
} from './highlightModel';

/**
 * One highlight per tile, keyed by the component index.
 *
 * A module-level store rather than context: the renderer that draws the plot
 * and the dispatch that hosts the floating table are siblings under the tile,
 * and neither owns the other's state. Kept apart from the dashboard filters on
 * purpose, see highlightModel.
 */
const states = new Map<string, HighlightState>();
const listeners = new Map<string, Set<() => void>>();

function read(index: string): HighlightState {
  return states.get(index) ?? EMPTY_HIGHLIGHT;
}

function subscribe(index: string, cb: () => void): () => void {
  let set = listeners.get(index);
  if (!set) listeners.set(index, (set = new Set()));
  set.add(cb);
  return () => {
    set!.delete(cb);
    if (set!.size === 0) listeners.delete(index);
  };
}

/** Exported for tests and for non-React callers. */
export function dispatchHighlight(index: string, action: HighlightAction): void {
  const prev = read(index);
  const next = reduceHighlight(prev, action);
  if (next === prev) return;
  states.set(index, next);
  listeners.get(index)?.forEach((cb) => cb());
}

export interface TileHighlight extends HighlightState {
  keySet: ReadonlySet<string>;
  select: (keys: readonly string[], source: HighlightSource) => void;
  toggle: (key: string, source: HighlightSource) => void;
  clear: (source?: HighlightSource) => void;
  /** The key under the pointer on `source`, or null when it leaves. */
  hoverKey: (key: string | null, source: HoverSource) => void;
}

export function useTileHighlight(index: string): TileHighlight {
  const state = useSyncExternalStore(
    useCallback((cb) => subscribe(index, cb), [index]),
    () => read(index),
    () => EMPTY_HIGHLIGHT,
  );
  const keySet = useMemo(() => new Set(state.keys), [state.keys]);
  const select = useCallback(
    (keys: readonly string[], source: HighlightSource) =>
      dispatchHighlight(index, { type: 'set', keys, source }),
    [index],
  );
  const toggle = useCallback(
    (key: string, source: HighlightSource) => dispatchHighlight(index, { type: 'toggle', key, source }),
    [index],
  );
  const clear = useCallback(
    (source: HighlightSource = 'external') => dispatchHighlight(index, { type: 'clear', source }),
    [index],
  );
  const hoverKey = useCallback(
    (key: string | null, source: HoverSource) => dispatchHighlight(index, { type: 'hover', key, source }),
    [index],
  );
  return useMemo(
    () => ({ ...state, keySet, select, toggle, clear, hoverKey }),
    [state, keySet, select, toggle, clear, hoverKey],
  );
}

/** The ring colour for picked points: the theme's primary shade, one step
 *  lighter on a dark scheme. Plotly needs a resolved colour, not a CSS variable. */
export function useHighlightRingColor(): string {
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  const shades = theme.colors[theme.primaryColor] ?? theme.colors.blue;
  return shades[colorScheme === 'dark' ? 4 : 7];
}
