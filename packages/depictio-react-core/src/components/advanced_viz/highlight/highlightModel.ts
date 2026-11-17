/**
 * The points a reader has picked out in a tile, shared between the plot and
 * the floating data table.
 *
 * This is a view state, not a filter: nothing here reaches the dashboard's
 * filter array. A selection made in the plot (a click, a box or lasso) lights up
 * the matching rows of the table, and rows ticked in the table light up the
 * matching points of the plot. The join key is the tile's feature id (the
 * volcano's `feature_id_col`), carried as strings on both sides.
 */

/** Where a change came from: decides what the other surface must do about it. */
export type HighlightSource =
  /** Box or lasso: Plotly already draws it, so its own selection state is kept. */
  | 'plot-select'
  /** A click on a point: Plotly drew nothing, and a stale lasso must give way. */
  | 'plot-click'
  /** Rows ticked in the table. */
  | 'table'
  /** The tile's "clear" badge or any other outside reset. */
  | 'external';

export interface HighlightState {
  /** Selected feature ids, deduplicated, in the order they were picked. */
  keys: string[];
  source: HighlightSource | null;
  /**
   * Bumped when Plotly must forget the selection it holds (a change it did not
   * make itself); the renderer folds it into `layout.selectionrevision`.
   */
  revision: number;
  /** Bumped when the plot picked something, so the table scrolls to it. */
  reveal: number;
  /** The point (or row) under the pointer, shown on the other surface: a
   *  hovered row rings its point, a hovered point marks its row. */
  hover: string | null;
  hoverSource: HoverSource | null;
}

/** Which surface the pointer is on. */
export type HoverSource = 'plot' | 'table';

export const EMPTY_HIGHLIGHT: HighlightState = Object.freeze({
  keys: [],
  source: null,
  revision: 0,
  reveal: 0,
  hover: null,
  hoverSource: null,
}) as HighlightState;

export type HighlightAction =
  | { type: 'set'; keys: readonly string[]; source: HighlightSource }
  | { type: 'toggle'; key: string; source: HighlightSource }
  | { type: 'clear'; source: HighlightSource }
  | { type: 'hover'; key: string | null; source: HoverSource };

/** Set equality: the order a selection was made in carries no meaning. */
export function sameKeys(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const set = new Set(b);
  return a.every((k) => set.has(k));
}

function dedupe(keys: readonly string[]): string[] {
  return Array.from(new Set(keys.filter((k) => k !== '')));
}

function next(state: HighlightState, keys: string[], source: HighlightSource): HighlightState {
  // Echoes (the table ticking rows the plot just selected) land here with the
  // same set; returning the same object keeps subscribers from re-rendering.
  if (sameKeys(state.keys, keys)) return state;
  return {
    ...state,
    keys,
    source,
    revision: source === 'plot-select' ? state.revision : state.revision + 1,
    reveal: source.startsWith('plot') && keys.length > 0 ? state.reveal + 1 : state.reveal,
  };
}

export function reduceHighlight(state: HighlightState, action: HighlightAction): HighlightState {
  switch (action.type) {
    case 'set':
      return next(state, dedupe(action.keys), action.source);
    case 'toggle': {
      if (action.key === '') return state;
      const has = state.keys.includes(action.key);
      const keys = has ? state.keys.filter((k) => k !== action.key) : [...state.keys, action.key];
      return next(state, keys, action.source);
    }
    case 'clear':
      return next(state, [], action.source);
    case 'hover': {
      const key = action.key === '' ? null : action.key;
      // Leaving a surface clears only the hover that surface set.
      if (key === null && state.hoverSource !== action.source) return state;
      if (key === state.hover && action.source === state.hoverSource) return state;
      return { ...state, hover: key, hoverSource: key === null ? null : action.source };
    }
  }
}

/**
 * What a click on `key` does to the selection: a plain click picks that point
 * alone (and a second click on it lets go), a click with Shift, Ctrl or Cmd adds
 * it to the points already picked or removes it.
 */
export function selectionFromClick(
  current: readonly string[],
  key: string,
  additive: boolean,
): string[] {
  if (key === '') return [...current];
  if (additive) {
    return current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
  }
  return current.length === 1 && current[0] === key ? [] : [key];
}

/** Whether a Plotly click event was made with a modifier key held. */
export function isAdditiveClick(event: { event?: { shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean } } | null | undefined): boolean {
  const e = event?.event;
  return Boolean(e?.shiftKey || e?.ctrlKey || e?.metaKey);
}
