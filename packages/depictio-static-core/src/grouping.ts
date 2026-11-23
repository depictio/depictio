/**
 * Selection groups, colour-by and split panels for a bound figure.
 *
 * The live viewer asks the server for a figure coloured by the reader's
 * groups (or by a column); the server annotates every row with its group
 * and lets plotly-express colour by that column, or, in "Split", facet by it
 * (`depictio/api/v1/services/figure/groups.py`, applied in
 * `build_figure_preview`). A bundle has no server and no plotly-express, so
 * this module redraws the same figure from what the runtime already holds: the
 * scaffold the build side made with the real `create_figure_from_data`, and
 * the bundled columns.
 *
 * What px does when `color=` changes, and what is reproduced:
 *
 *   - one trace per (colour value, the figure's other grouping combination),
 *     in the colour category order, empty ones absent: the traces of the
 *     scaffold are cut by row group and merged across the colour they had;
 *   - each trace takes the group's name, legend group, colour (`marker.color`
 *     and/or `line.color`, wherever px wrote one), `offsetgroup`, and a
 *     hovertemplate that leads with `<column>=<value>`;
 *   - the legend is titled with the colour column, and a box/violin mode px
 *     had set to overlay because the colour was the position column goes back
 *     to `group`, its categorical axis order to the data's;
 *   - "Split": one panel per category (empty ones too), wrapped at 4 columns,
 *     with px's own subplot geometry (2% / 7% gaps, shared axes, titles on the
 *     outer edge) and `tidy_facet_layout`'s flat, value-only panel labels.
 *
 * What is not (the figure is then drawn as it was built, and the caller is
 * told it was not recoloured, as the server's `group_colored: false`): a
 * trendline (px fits one per colour), a continuous colour scale or any bound
 * colour array, stacked areas, trace types other than the scatter / bar /
 * box / violin / histogram family. A split of a figure that is already faceted
 * keeps the colouring and skips the panels.
 *
 * Pure (no DOM, no React); `refill.ts` calls it from `refillFigure`.
 */

import type { BindingTable, TraceBinding } from './manifest';
import { serializeOption } from './engine/filters';
import { fillTrace, jsonClone, selectRows } from './refillHelpers';

// ---------------------------------------------------------------------------
// constants (mirrors of groups.py)
// ---------------------------------------------------------------------------

/** The synthetic column the server colours by. */
export const GROUP_COLUMN = '__depictio_group__';
export const OTHER_LABEL = 'Other';
/** Neutral grey of the unassigned rows. */
export const OTHER_COLOR = '#adb5bd';
export const MAX_GROUPS = 24;
export const MAX_VALUES_PER_GROUP = 50_000;
export const MAX_NAME_LENGTH = 80;
export const MAX_COLOR_MAP_ENTRIES = 200;
export const MAX_COLUMN_NAME_LENGTH = 200;
/** Panels per row of a split, and the most it will draw before keeping the colours only. */
export const FACET_COL_WRAP = 4;
export const MAX_FACET_CATEGORIES = 12;
/** matplotlib tab10, for a group that arrives without a valid colour. */
const TAB10 = [
  '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
]; // prettier-ignore
/** plotly's default colorway, used when neither a map nor a template gives one. */
const PLOTLY_COLORWAY = [
  '#636efa', '#EF553B', '#00cc96', '#ab63fa', '#FFA15A',
  '#19d3f3', '#FF6692', '#B6E880', '#FF97FF', '#FECB52',
]; // prettier-ignore
const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

// px subplot geometry for `facet_col_wrap` (read off the figures it makes).
const FACET_H_SPACING = 0.02;
const FACET_V_SPACING = 0.07;

// ---------------------------------------------------------------------------
// request
// ---------------------------------------------------------------------------

/** A group in the render payload (`GroupRenderDef` in the viewer). */
export interface GroupDef {
  name: string;
  column_name: string;
  values: string[];
  color: string;
  dc_id?: string;
}

/** The viewer's "Color by <column>" with its stable palette. */
export interface ColorByColumn {
  columnName: string;
  colorMap?: Record<string, string>;
}

/** What `renderFigure` is asked for (`RenderFigureOptions` in the viewer). */
export interface GroupingRequest {
  groups?: GroupDef[];
  colorByGroup?: boolean;
  colorByColumn?: ColorByColumn;
  /** `facet` is the "Split" display. */
  display?: 'color' | 'facet';
  /** Groups only: false drops ungrouped rows instead of drawing them grey. */
  showOther?: boolean;
}

/** What a grouped refill reports back, as the server's response metadata. */
export interface GroupingOutcome {
  groupColored: boolean;
  /** The column the figure was coloured by, `null` when it was not. */
  columnColored: string | null;
}

/** `sanitize_group_defs`: only well-formed entries, names unique, caps enforced. */
export function sanitizeGroupDefs(raw: unknown): GroupDef[] {
  if (!Array.isArray(raw)) return [];
  const out: GroupDef[] = [];
  const seen = new Set<string>();
  for (const entry of raw) {
    if (out.length >= MAX_GROUPS) break;
    if (typeof entry !== 'object' || entry === null) continue;
    const e = entry as Record<string, unknown>;
    if (typeof e.name !== 'string' || e.name.trim() === '') continue;
    if (typeof e.column_name !== 'string' || e.column_name.trim() === '') continue;
    if (!Array.isArray(e.values) || e.values.length === 0) continue;
    const name = e.name.trim().slice(0, MAX_NAME_LENGTH);
    // The fallback label cannot double as a group name.
    if (name === OTHER_LABEL || seen.has(name)) continue;
    const color =
      typeof e.color === 'string' && HEX_COLOR.test(e.color) ? e.color : TAB10[out.length % TAB10.length];
    const clean: GroupDef = {
      name,
      column_name: e.column_name.trim(),
      values: e.values.slice(0, MAX_VALUES_PER_GROUP).map((v) => String(v)),
      color,
    };
    if (typeof e.dc_id === 'string' && e.dc_id.trim() !== '') clean.dc_id = e.dc_id.trim();
    out.push(clean);
    seen.add(name);
  }
  return out;
}

/** `sanitize_color_by_column`: the column name and a hex-only colour map. */
export function sanitizeColorByColumn(raw: unknown): { columnName: string; colorMap: Record<string, string> } | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const r = raw as { columnName?: unknown; column_name?: unknown; colorMap?: unknown; color_map?: unknown };
  const column = r.columnName ?? r.column_name;
  if (typeof column !== 'string' || column.trim() === '') return null;
  const name = column.trim();
  if (name.length > MAX_COLUMN_NAME_LENGTH) return null;
  const colorMap: Record<string, string> = {};
  const rawMap = r.colorMap ?? r.color_map;
  if (typeof rawMap === 'object' && rawMap !== null) {
    for (const [key, value] of Object.entries(rawMap as Record<string, unknown>)) {
      if (Object.keys(colorMap).length >= MAX_COLOR_MAP_ENTRIES) break;
      if (typeof value === 'string' && HEX_COLOR.test(value)) colorMap[key] = value;
    }
  }
  return { columnName: name, colorMap };
}

/** The columns a request reads. Groups win over a column override, as on the server. */
export function groupingColumns(req: GroupingRequest | undefined): string[] {
  if (!req) return [];
  const groups = sanitizeGroupDefs(req.groups);
  if (req.colorByGroup && groups.length > 0) {
    return [...new Set(groups.map((g) => g.column_name))];
  }
  const byColumn = sanitizeColorByColumn(req.colorByColumn);
  return byColumn ? [byColumn.columnName] : [];
}

// ---------------------------------------------------------------------------
// plan: which category each row falls in
// ---------------------------------------------------------------------------

export interface ColoringPlan {
  /** The colour column as px names it: the synthetic one for groups, the column otherwise. */
  column: string;
  /** Category labels, in legend / panel order. */
  categories: string[];
  /** Colour per category label. */
  colors: Record<string, string>;
  /** Per row: index into `categories`, or -1 for a row that is not drawn. */
  rowCategory: Int32Array;
  /** Panels of a split: the categories, or null for the overlay display. */
  facet: boolean;
  outcome: GroupingOutcome;
}

/** The template colorway px draws a mapless colour column from. */
function colorwayOf(scaffoldLayout: Record<string, unknown> | undefined): string[] {
  const template = scaffoldLayout?.template as { layout?: { colorway?: unknown } } | undefined;
  const colorway = template?.layout?.colorway;
  return Array.isArray(colorway) && colorway.length > 0 && colorway.every((c) => typeof c === 'string')
    ? (colorway as string[])
    : PLOTLY_COLORWAY;
}

/**
 * Decide what the request colours by and which category each row falls in.
 * `null` when it cannot apply to these columns (the figure is left as built).
 */
export function planColoring(
  req: GroupingRequest,
  cols: Record<string, ArrayLike<unknown>>,
  rows: number,
  scaffoldLayout?: Record<string, unknown>,
): ColoringPlan | null {
  const display = req.display === 'facet' ? 'facet' : 'color';
  const groups = sanitizeGroupDefs(req.groups);

  if (req.colorByGroup && groups.length > 0) {
    // `group_annotation_expr`: first matching group wins, a group whose column
    // the frame lacks is skipped, everything else is "Other".
    const usable = groups
      .map((g, index) => ({ g, index, values: cols[g.column_name], set: new Set(g.values) }))
      .filter((u) => u.values !== undefined);
    if (usable.length === 0) return null;
    const includeOther = req.showOther !== false;
    const categories = groups.map((g) => g.name);
    const colors: Record<string, string> = {};
    for (const g of groups) colors[g.name] = g.color;
    if (includeOther) {
      categories.push(OTHER_LABEL);
      colors[OTHER_LABEL] = OTHER_COLOR;
    }
    const otherIndex = includeOther ? categories.length - 1 : -1;
    const rowCategory = new Int32Array(rows).fill(otherIndex);
    for (let i = 0; i < rows; i++) {
      for (const u of usable) {
        const v = u.values![i];
        if (v !== null && v !== undefined && u.set.has(serializeOption(v))) {
          rowCategory[i] = u.index;
          break;
        }
      }
    }
    return {
      column: GROUP_COLUMN,
      categories,
      colors,
      rowCategory,
      // `_apply_display`: a split of more than 12 panels stays an overlay.
      facet: display === 'facet' && categories.length <= MAX_FACET_CATEGORIES,
      outcome: { groupColored: true, columnColored: null },
    };
  }

  const byColumn = sanitizeColorByColumn(req.colorByColumn);
  if (!byColumn) return null;
  const values = cols[byColumn.columnName];
  if (values === undefined) return null;
  const mapped = Object.keys(byColumn.colorMap);
  // Categories: the stable map's order, then anything the map lacks in order
  // of appearance (px orders unlisted categories last).
  const categories = [...mapped];
  const known = new Set(categories);
  const labels: (string | null)[] = new Array(rows);
  for (let i = 0; i < rows; i++) {
    const v = values[i];
    if (v === null || v === undefined) {
      // A null colour value is no category: px draws no trace for it.
      labels[i] = null;
      continue;
    }
    const label = serializeOption(v);
    labels[i] = label;
    if (!known.has(label)) {
      known.add(label);
      categories.push(label);
    }
  }
  const palette = colorwayOf(scaffoldLayout);
  const colors: Record<string, string> = {};
  categories.forEach((c, k) => {
    colors[c] = byColumn.colorMap[c] ?? palette[k % palette.length];
  });
  const index = new Map(categories.map((c, k) => [c, k]));
  const rowCategory = new Int32Array(rows);
  for (let i = 0; i < rows; i++) {
    const label = labels[i];
    rowCategory[i] = label === null ? -1 : (index.get(label) ?? -1);
  }
  return {
    column: byColumn.columnName,
    categories,
    colors,
    rowCategory,
    // Unknown cardinality (no stable palette yet) stays an overlay.
    facet: display === 'facet' && mapped.length > 0 && mapped.length <= MAX_FACET_CATEGORIES,
    outcome: { groupColored: false, columnColored: byColumn.columnName },
  };
}

// ---------------------------------------------------------------------------
// eligibility of a binding
// ---------------------------------------------------------------------------

/** Trace types px draws one trace per colour of, in a form this module rewrites. */
const SUPPORTED_TYPES = new Set(['scatter', 'scattergl', 'bar', 'box', 'violin', 'histogram']);
/** A bound path that carries a colour mapping of its own (a continuous scale). */
const COLOR_PATH = /(^|\.)(color|colors|colorscale|coloraxis)(\.|$)/;

type Trace = Record<string, unknown>;

function getPath(obj: Record<string, unknown>, path: string): unknown {
  let cur: unknown = obj;
  for (const part of path.split('.')) {
    if (typeof cur !== 'object' || cur === null) return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

function setDeep(obj: Record<string, unknown>, path: string, value: unknown): void {
  const parts = path.split('.');
  let cur = obj;
  for (let k = 0; k < parts.length - 1; k++) {
    const next = cur[parts[k]];
    if (typeof next !== 'object' || next === null || Array.isArray(next)) cur[parts[k]] = {};
    cur = cur[parts[k]] as Record<string, unknown>;
  }
  cur[parts[parts.length - 1]] = value;
}

/** Why this binding cannot be recoloured, or null. */
export function groupingRefusal(binding: BindingTable): string | null {
  if (binding.trendlines.length > 0) return 'a trendline is fit per colour';
  const data = (binding.scaffold as { data?: Trace[] }).data ?? [];
  for (const t of binding.traces) {
    const trace = data[t.i];
    if (!trace) return 'a bound trace is missing from the scaffold';
    if (!SUPPORTED_TYPES.has(String(trace.type))) return `a ${String(trace.type)} trace`;
    if (trace.stackgroup !== undefined || (trace.fill !== undefined && trace.fill !== 'none')) {
      return 'a stacked or filled trace';
    }
    if (Object.keys(t.fields).some((path) => COLOR_PATH.test(path))) {
      return 'a continuous colour scale';
    }
  }
  return null;
}

/** The discrete colour column the figure was built with, or null. */
function colorColumnOf(binding: BindingTable): string | null {
  if (binding.color_col !== undefined) return binding.color_col;
  // An older binding does not say: the trace whose legend group is the value
  // of one of its group columns is coloured by it.
  const data = (binding.scaffold as { data?: Trace[] }).data ?? [];
  for (const t of binding.traces) {
    const legendgroup = data[t.i]?.legendgroup;
    if (typeof legendgroup !== 'string' || legendgroup === '') continue;
    const hit = Object.entries(t.group).find(([, v]) => serializeOption(v) === legendgroup);
    if (hit) return hit[0];
  }
  return null;
}

/** True when the scaffold draws one cartesian panel, which a split can multiply. */
function singlePanel(binding: BindingTable): boolean {
  const layout = (binding.scaffold as { layout?: Record<string, unknown> }).layout ?? {};
  if (Object.keys(layout).some((k) => /^[xy]axis[2-9]\d*$/.test(k))) return false;
  if (Array.isArray(layout.annotations) && layout.annotations.length > 0) return false;
  if (Array.isArray(layout.shapes) && layout.shapes.length > 0) return false;
  if (Array.isArray(layout.images) && layout.images.length > 0) return false;
  const data = (binding.scaffold as { data?: Trace[] }).data ?? [];
  return binding.traces.every((t) => {
    const trace = data[t.i];
    return trace && (trace.xaxis ?? 'x') === 'x' && (trace.yaxis ?? 'y') === 'y';
  });
}

// ---------------------------------------------------------------------------
// the regrouped figure
// ---------------------------------------------------------------------------

interface Entry {
  category: number;
  base: Trace;
  t: TraceBinding;
  rows: number[];
}

export interface GroupedRefill {
  figure: { data: unknown[]; layout: Record<string, unknown> };
  displayed: number;
  outcome: GroupingOutcome;
}

/**
 * The bound figure redrawn coloured (and, for a split, laid out in panels) by
 * `plan`, over the rows `mask` keeps. `cols` holds every bound and group
 * column. `null` when the binding cannot take the override.
 */
export function groupedRefill(
  binding: BindingTable,
  cols: Record<string, ArrayLike<unknown>>,
  mask: Uint8Array | null,
  rows: number,
  plan: ColoringPlan,
): GroupedRefill | null {
  if (groupingRefusal(binding) !== null) return null;
  const scaffold = binding.scaffold as { data?: Trace[]; layout?: Record<string, unknown> };
  const layout = jsonClone(scaffold.layout ?? {}) as Record<string, unknown>;
  const colorCol = colorColumnOf(binding);

  // One trace per (new colour, the figure's other grouping combination), as px
  // draws it. The rows of a combination are chosen WITHOUT the old colour: a
  // row the old colour column left out (a null there) is drawn now, and the
  // traces of the old colours fold into one.
  const combos = new Map<string, { t: TraceBinding; rest: TraceBinding }>();
  for (const t of binding.traces) {
    const restGroup = Object.fromEntries(Object.entries(t.group).filter(([c]) => c !== colorCol));
    const key = JSON.stringify([Object.entries(restGroup), t.axes]);
    if (!combos.has(key)) combos.set(key, { t, rest: { ...t, group: restGroup } });
  }
  const entries: Entry[] = [];
  let displayed = 0;
  for (const { t, rest } of combos.values()) {
    const cut = new Map<number, number[]>();
    for (const row of selectRows(rest, cols, mask, rows)) {
      const category = plan.rowCategory[row];
      if (category < 0) continue;
      displayed += 1;
      const list = cut.get(category);
      if (list) list.push(row);
      else cut.set(category, [row]);
    }
    for (const [category, list] of cut) {
      entries.push({ category, base: jsonClone((scaffold.data ?? [])[t.i]), t, rows: list });
    }
  }
  // px orders the traces by colour category first.
  const ordered = entries
    .map((entry, order) => ({ entry, order }))
    .sort((a, b) => a.entry.category - b.entry.category || a.order - b.order)
    .map((e) => e.entry);

  const panels = plan.facet && singlePanel(binding) ? plan.categories.length : 0;
  const seenLegend = new Set<string>();
  const data: Trace[] = [];
  for (const entry of ordered) {
    const { base: trace, t } = entry;
    fillTrace(trace, t, cols, entry.rows);
    const label = plan.categories[entry.category];
    const oldValue = colorCol !== null && colorCol in t.group ? serializeOption(t.group[colorCol]) : null;
    restyleTrace(trace, label, plan.colors[label], plan.column, colorCol, oldValue);
    // One legend entry per legend group; the traces of other panels share it.
    const legendgroup = String(trace.legendgroup);
    trace.showlegend = !seenLegend.has(legendgroup);
    seenLegend.add(legendgroup);
    if (panels > 0) {
      const axis = panelAxis(entry.category, panels);
      trace.xaxis = axis === 1 ? 'x' : `x${axis}`;
      trace.yaxis = axis === 1 ? 'y' : `y${axis}`;
    }
    data.push(trace);
  }

  restyleLayout(layout, binding, colorCol, plan.column);
  if (panels > 0) facetLayout(layout, plan.categories, plan.column);
  return { figure: { data, layout }, displayed, outcome: plan.outcome };
}

/** Name, legend group, colour, offset group and hover of one recoloured trace. */
function restyleTrace(
  trace: Trace,
  label: string,
  color: string,
  column: string,
  oldColumn: string | null,
  oldValue: string | null,
): void {
  const oldName = typeof trace.name === 'string' ? trace.name : '';
  if (oldValue !== null && oldName === oldValue) trace.name = label;
  else if (oldValue !== null && oldName.startsWith(`${oldValue}, `)) {
    trace.name = label + oldName.slice(oldValue.length);
  } else trace.name = oldName === '' ? label : `${label}, ${oldName}`;
  // px's legend group is its trace name: every legend part, not the colour alone.
  trace.legendgroup = trace.name;
  if (typeof trace.offsetgroup === 'string' && (trace.offsetgroup === '' || trace.offsetgroup === oldValue)) {
    trace.offsetgroup = label;
  }
  let painted = false;
  // A box or violin outline is not its colour (px strips it transparent).
  const colorPaths = trace.type === 'box' || trace.type === 'violin' ? ['marker.color'] : ['marker.color', 'line.color'];
  for (const path of colorPaths) {
    if (typeof getPath(trace, path) === 'string') {
      setDeep(trace, path, color);
      painted = true;
    }
  }
  if (!painted) setDeep(trace, 'marker.color', color);
  if (typeof trace.hovertemplate === 'string') {
    let hover = trace.hovertemplate;
    // px leads with `<colour column>=<value>`; the old colour's entry goes.
    // (A colour that was also the position column never had one.)
    const old = oldColumn !== null && oldValue !== null ? `${oldColumn}=${oldValue}<br>` : null;
    if (old !== null && hover.startsWith(old)) hover = hover.slice(old.length);
    trace.hovertemplate = `${column}=${label}<br>${hover}`;
  }
}

/** The layout keys a new colour column moves (legend title, box/violin mode, axis order). */
function restyleLayout(
  layout: Record<string, unknown>,
  binding: BindingTable,
  colorCol: string | null,
  column: string,
): void {
  // The legend names every column that splits it: the colour first, then the
  // symbol / dash / pattern columns the figure kept.
  const oldTitle = getPath(layout, 'legend.title.text');
  const kept =
    typeof oldTitle === 'string' && oldTitle !== ''
      ? oldTitle.split(', ').filter((part) => part !== colorCol)
      : [];
  setDeep(layout, 'legend.title.text', [column, ...kept].join(', '));
  if (colorCol === null) return;
  // px overlays a box/violin whose colour is the column it is positioned by;
  // coloured by something else it groups them side by side.
  const positioned = (axis: 'x' | 'y') => binding.traces.some((t) => t.fields[axis] === colorCol);
  for (const key of ['boxmode', 'violinmode']) {
    if (layout[key] === 'overlay' && (positioned('x') || positioned('y'))) layout[key] = 'group';
  }
  // ... and orders that axis by the colour's categories.
  for (const axis of ['x', 'y'] as const) {
    const ax = layout[`${axis}axis`] as Record<string, unknown> | undefined;
    if (ax && positioned(axis) && ax.categoryorder === 'array') {
      delete ax.categoryorder;
      delete ax.categoryarray;
    }
  }
}

// ---------------------------------------------------------------------------
// split panels
// ---------------------------------------------------------------------------

/** Axis number (1-based) of panel `i`: px numbers a wrapped grid bottom row first. */
function panelAxis(i: number, n: number): number {
  const ncols = Math.min(FACET_COL_WRAP, n);
  const nrows = Math.ceil(n / ncols);
  const row = Math.floor(i / ncols);
  return (nrows - 1 - row) * ncols + (i % ncols) + 1;
}

/**
 * Lay a single-panel layout out as one panel per category: px's subplot grid
 * for `facet_col` + `facet_col_wrap=4`, then `tidy_facet_layout` (value-only
 * flat labels, `automargin`) when there is more than one panel.
 */
function facetLayout(layout: Record<string, unknown>, categories: string[], column: string): void {
  const n = categories.length;
  const ncols = Math.min(FACET_COL_WRAP, n);
  const nrows = Math.ceil(n / ncols);
  const width = (1 - (ncols - 1) * FACET_H_SPACING) / ncols;
  const height = (1 - (nrows - 1) * FACET_V_SPACING) / nrows;
  const baseX = jsonClone((layout.xaxis ?? {}) as Record<string, unknown>);
  const baseY = jsonClone((layout.yaxis ?? {}) as Record<string, unknown>);
  const tidy = n > 1;

  const annotations: { axis: number; value: Record<string, unknown> }[] = [];
  for (let a = 1; a <= nrows * ncols; a++) {
    const rowFromBottom = Math.floor((a - 1) / ncols);
    const row = nrows - 1 - rowFromBottom;
    const col = (a - 1) % ncols;
    const x0 = col * (width + FACET_H_SPACING);
    const y1 = 1 - row * (height + FACET_V_SPACING);
    const y0 = y1 - height;

    const x = jsonClone(baseX);
    x.anchor = a === 1 ? 'y' : `y${a}`;
    x.domain = [x0, x0 + width];
    if (a > 1) x.matches = 'x';
    if (rowFromBottom > 0) {
      delete x.title;
      x.showticklabels = false;
    }
    if (tidy) x.automargin = true;
    layout[a === 1 ? 'xaxis' : `xaxis${a}`] = x;

    const y = jsonClone(baseY);
    y.anchor = a === 1 ? 'x' : `x${a}`;
    y.domain = [y0, y1];
    if (a > 1) y.matches = 'y';
    if (col > 0) {
      delete y.title;
      y.showticklabels = false;
    }
    if (tidy) y.automargin = true;
    layout[a === 1 ? 'yaxis' : `yaxis${a}`] = y;
  }
  categories.forEach((label, i) => {
    const axis = panelAxis(i, n);
    const rowFromBottom = Math.floor((axis - 1) / ncols);
    const row = nrows - 1 - rowFromBottom;
    const col = (axis - 1) % ncols;
    const x0 = col * (width + FACET_H_SPACING);
    annotations.push({
      axis,
      value: {
        // px writes `<column>=<value>`; the tidy pass keeps the value.
        text: tidy ? label : `${column}=${label}`,
        showarrow: false,
        x: x0 + width / 2,
        xanchor: 'center',
        xref: 'paper',
        y: 1 - row * (height + FACET_V_SPACING),
        yanchor: 'bottom',
        yref: 'paper',
        font: tidy ? { size: 12 } : {},
      },
    });
  });
  layout.annotations = annotations.sort((a, b) => a.axis - b.axis).map((a) => a.value);
}
