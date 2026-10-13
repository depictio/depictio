/**
 * Reading and recolouring a plotly-upset figure.
 *
 * Everything here is read off the figure's structure rather than trace names,
 * so it holds in every colouring mode: each trace places intersections at
 * x = 0..n-1 except the horizontal set-size bars, whose y is the set index,
 * and the dot matrix is whatever sits on a y axis labelled with the set names.
 * The hover emphasis (upsetHover.ts) and the intersection selection
 * (upsetSelection.ts) read the same structure through these helpers.
 */

import { pinnedCategoryColor, type CategoryColorSource } from '../../categoryColors';

export type Trace = Record<string, unknown>;
export type Layout = Record<string, unknown>;

export function isSetSizeBars(t: Trace): boolean {
  return t.type === 'bar' && t.orientation === 'h';
}

export function hasMarkers(t: Trace): boolean {
  return t.type === 'scatter' && String(t.mode ?? '').includes('markers');
}

export function values(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

/** Trace references (`y`, `y2`, …) of the y axes labelled with set names. */
export function setNameAxes(layout: Layout): Set<string> {
  const refs = new Set<string>();
  for (const [key, axis] of Object.entries(layout)) {
    const match = /^yaxis(\d*)$/.exec(key);
    if (match && Array.isArray((axis as { ticktext?: unknown } | null)?.ticktext)) {
      refs.add(`y${match[1]}`);
    }
  }
  return refs;
}

export function isMatrixDots(t: Trace, axes: Set<string>): boolean {
  return hasMarkers(t) && axes.has(String(t.yaxis ?? 'y'));
}

/** The matrix dots of a set that belongs to the intersection: the only ones
 *  carrying a label. The empty dots of the other sets have none. */
export function isFilledMatrixDots(t: Trace, axes: Set<string>): boolean {
  return isMatrixDots(t, axes) && t.hovertext != null;
}

/** The set names by row index: `names[y]` is the set drawn at height `y`. */
export function upsetSetNames(layout: Layout): string[] {
  for (const [key, axis] of Object.entries(layout)) {
    if (!/^yaxis\d*$/.test(key)) continue;
    const a = axis as { ticktext?: unknown; tickvals?: unknown } | null;
    const text = values(a?.ticktext);
    if (text.length === 0) continue;
    const at = values(a?.tickvals);
    const names: string[] = [];
    text.forEach((name, i) => {
      const y = at.length === text.length ? Number(at[i]) : i;
      if (Number.isInteger(y) && y >= 0) names[y] = String(name);
    });
    return names;
  }
  return [];
}

/** The sets each intersection joins, by intersection (x) index. */
export function upsetColumnSets(data: Trace[], layout: Layout): Map<number, string[]> {
  const axes = setNameAxes(layout);
  const names = upsetSetNames(layout);
  const rows = new Map<number, Set<number>>();
  for (const t of data) {
    if (!isFilledMatrixDots(t, axes)) continue;
    const ys = values(t.y);
    values(t.x).forEach((x, i) => {
      const column = Number(x);
      const y = Number(ys[i]);
      if (!Number.isInteger(column) || !Number.isInteger(y)) return;
      if (!rows.has(column)) rows.set(column, new Set());
      rows.get(column)!.add(y);
    });
  }
  const out = new Map<number, string[]>();
  for (const [column, ys] of rows) {
    out.set(
      column,
      [...ys].sort((a, b) => a - b).map((y) => names[y] ?? String(y)),
    );
  }
  return out;
}

/**
 * The colour each set is drawn in, or null to keep the figure as the server
 * drew it.
 *
 * The sets of an UpSet are the values of some categorical column of the
 * underlying data (a locality, a habitat): the recipe pivoted on it and they
 * came out as column names. So their colours are that column's
 * `category_colors`, the ones every other figure of the dashboard draws them
 * in. `column` names it; without one, the column is found by value, as the
 * worker finds the filter that narrows the sets: the one `category_colors`
 * column that pins every set drawn. Several that pin them all but disagree are
 * left alone rather than guessed between.
 *
 * `overrides` is the component's own `set_colors`, which wins per set.
 */
export function resolveUpsetSetColors(
  source: CategoryColorSource | null | undefined,
  setNames: readonly string[],
  options: { column?: string | null; overrides?: Record<string, string> | null } = {},
): Record<string, string> | null {
  const sets = setNames.filter(Boolean);
  if (sets.length === 0) return null;
  const pinnedFor = (column: string): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const name of sets) {
      const colour = pinnedCategoryColor(source, column, name);
      if (colour) out[name] = colour;
    }
    return out;
  };

  let pinned: Record<string, string> = {};
  if (options.column) {
    pinned = pinnedFor(options.column);
  } else {
    const columns = new Set([
      ...Object.keys(source?.category_colors ?? {}),
      ...Object.keys(source?.inherited_category_colors ?? {}),
    ]);
    const complete = new Set<string>();
    for (const column of columns) {
      const map = pinnedFor(column);
      if (Object.keys(map).length === sets.length) complete.add(JSON.stringify(map));
    }
    if (complete.size === 1) pinned = JSON.parse([...complete][0]) as Record<string, string>;
  }

  const merged: Record<string, string> = { ...pinned };
  for (const name of sets) {
    const own = options.overrides?.[name];
    if (own) merged[name] = own;
  }
  return Object.keys(merged).length ? merged : null;
}

/** plotly-upset's ink: the bars, filled dots and edges of the plain look. */
const LIBRARY_INK = '#333333';

function isInk(c: unknown): boolean {
  return typeof c === 'string' && c.toLowerCase() === LIBRARY_INK;
}

/**
 * The plain matrix redrawn for a dark background.
 *
 * plotly-upset draws for paper: near-black ink for what is there (bars, filled
 * dots, the edges that join a column's dots) and a light grey for the empty
 * dots. On a dark theme that inverts the reading, the empty dots standing out
 * and the edges vanishing. `ink` and `empty` are the theme's replacements; any
 * colour the figure was given on purpose (a set's, a degree's) is left as is.
 */
export function inkUpsetForDark(
  data: Trace[],
  layout: Layout,
  colours: { ink: string; empty: string },
): Trace[] {
  const axes = setNameAxes(layout);
  const swap = (c: unknown) =>
    Array.isArray(c) ? c.map((v) => (isInk(v) ? colours.ink : v)) : isInk(c) ? colours.ink : c;
  return data.map((t) => {
    const marker = t.marker as Record<string, unknown> | undefined;
    const line = t.line as Record<string, unknown> | undefined;
    if (isMatrixDots(t, axes) && !isFilledMatrixDots(t, axes)) {
      return { ...t, marker: { ...marker, color: colours.empty } };
    }
    let out = t;
    if (marker && (isInk(marker.color) || (Array.isArray(marker.color) && marker.color.some(isInk)))) {
      out = { ...out, marker: { ...marker, color: swap(marker.color) } };
    }
    if (line && isInk(line.color)) out = { ...out, line: { ...line, color: colours.ink } };
    return out;
  });
}

function colourAt(original: unknown, i: number): unknown {
  return Array.isArray(original) ? original[i] : original;
}

/** `marker.color` with one entry per point: the set's colour where it has
 *  one, the colour the point already had otherwise. */
function recoloured(t: Trace, setAt: (i: number) => string | undefined): Trace {
  const marker = (t.marker as Record<string, unknown> | undefined) ?? {};
  const n = Math.max(values(t.x).length, values(t.y).length);
  const color = Array.from({ length: n }, (_, i) => setAt(i) ?? colourAt(marker.color, i));
  return { ...t, marker: { ...marker, color } };
}

/**
 * The figure with each set drawn in its colour: its size bar, its filled dots
 * in the matrix, and the bar of the intersection that is that set alone.
 *
 * Only the per-set intersection colouring has single-set bars to give a set's
 * colour to. It is the one mode in which the server colours the intersection
 * bars one by one (an array `marker.color`), which is how it is recognised
 * here; a bar several sets share keeps the neutral grey the server gave it, so
 * the matrix underneath stays the one place that spells out the membership.
 * The single colour and the degree colouring are the author's choice and stay
 * as they are.
 */
export function colourUpsetSets(
  data: Trace[],
  layout: Layout,
  colors: Record<string, string> | null,
): Trace[] {
  if (!colors || Object.keys(colors).length === 0) return data;
  const axes = setNameAxes(layout);
  const names = upsetSetNames(layout);
  const setOfRow = (y: unknown) => {
    const name = names[Number(y)];
    return name === undefined ? undefined : colors[name];
  };
  const columnSets = upsetColumnSets(data, layout);

  return data.map((t) => {
    if (isSetSizeBars(t)) {
      const ys = values(t.y);
      return recoloured(t, (i) => setOfRow(ys[i]));
    }
    if (isFilledMatrixDots(t, axes)) {
      const ys = values(t.y);
      return recoloured(t, (i) => setOfRow(ys[i]));
    }
    const perBar = Array.isArray((t.marker as { color?: unknown } | undefined)?.color);
    if (t.type === 'bar' && perBar) {
      const xs = values(t.x);
      return recoloured(t, (i) => {
        const sets = columnSets.get(Number(xs[i]));
        return sets && sets.length === 1 ? colors[sets[0]] : undefined;
      });
    }
    return t;
  });
}

/**
 * The layout with a dot in its set's colour before each set name, the same
 * cue the filter chips use. A dot rather than coloured text: a dark category
 * colour on a dark theme leaves a name unreadable, a dot of it does not.
 */
export function withUpsetSetLabelDots(
  layout: Layout,
  colors: Record<string, string> | null,
): Layout {
  if (!colors || Object.keys(colors).length === 0) return layout;
  const out: Layout = { ...layout };
  for (const [key, axis] of Object.entries(layout)) {
    if (!/^yaxis\d*$/.test(key)) continue;
    const a = axis as Record<string, unknown> | null;
    if (!a || !Array.isArray(a.ticktext)) continue;
    out[key] = {
      ...a,
      ticktext: a.ticktext.map((name) => {
        const colour = colors[String(name)];
        return colour ? `<span style="color:${colour}">●</span> ${String(name)}` : name;
      }),
    };
  }
  return out;
}
