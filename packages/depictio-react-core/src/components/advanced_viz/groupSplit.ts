/**
 * Colour or split an already-built advanced_viz figure by the dashboard's
 * analysis groups.
 *
 * Figure and card components get their grouping from the server: the render
 * task annotates the frame with `__depictio_group__` and hands the column to
 * Plotly Express as `color=` or `facet_col=`. advanced_viz renderers cannot
 * take that route — they receive rows and build their traces in the browser,
 * and several of them (Manhattan, volcano, QQ) do arithmetic the server-side
 * builder knows nothing about. So the same intent is applied one step later,
 * on the finished figure, by partitioning the points that already carry an
 * identity in `customdata`.
 *
 * The join key is the one the component already uses to *emit* selections
 * (`advancedVizSelectionColumn`): a lasso on a PCoA saves a group of sample
 * ids, and it is those same sample ids its points carry in `customdata`.
 *
 * The join is on the values, not on the column *name*, and that is deliberate.
 * The same identifier is spelled differently from one data collection to the
 * next — the sampling-sites map emits `sample`, the PCoA of the very same
 * samples calls it `sample_id` — which is the whole reason cross-DC links
 * exist. Requiring the names to agree would leave a group made on the map
 * silently inert on the ordination it was made to interrogate.
 *
 * What keeps that from being a guess is the refusal below: if not one point
 * carries a value any group claims, the figure is returned untouched instead
 * of being redrawn with everything in "Other". A group from an unrelated
 * column therefore costs a lookup and changes nothing.
 */

import type { GroupRenderState } from '../../selectionGroups';

/** Kept in step with `OTHER_LABEL` / `OTHER_COLOR` in
 *  `depictio/api/v1/services/figure/groups.py`, so a split advanced_viz and a
 *  split figure name and paint the unassigned bucket identically. */
export const OTHER_LABEL = 'Other';
export const OTHER_COLOR = '#adb5bd';

/** Mirrors `MAX_FACET_CATEGORIES` / `FACET_COL_WRAP` in `celery_tasks.py`. */
export const MAX_FACET_PANELS = 12;
export const FACET_COL_WRAP = 4;

export interface FigureLike {
  data: any[];
  layout: any;
}

export interface GroupSplitOptions {
  groupRender?: GroupRenderState;
  /** Index, inside a point's `customdata` tuple, of the value identifying the
   *  row it was built from. Normally the slot the renderer already hands
   *  `extractScatterSelection`, so what a lasso emits and what a group is read
   *  back against cannot drift apart. */
  identitySlot?: number;
  /** Set false by renderers whose axes cannot be faceted (a 3D scene, a
   *  polar or geo subplot): "Split" then degrades to colouring rather than
   *  producing a broken layout. */
  facetable?: boolean;
  /** What to do, when splitting, with traces that carry no identity. The two
   *  kinds look alike and cannot be told apart from here, so the renderer
   *  says which it has:
   *
   *  - `'repeat'` (default) for a *constant*: a QQ plot's y=x line, a guide
   *    that is equally true in every panel and has to be drawn in each.
   *  - `'drop'` for a *summary over all the points*: a density overlay, a
   *    centroid marker. Repeating one inside a per-group panel would claim
   *    the whole cohort's shape is that group's.
   *
   *  Layout shapes are always repeated: a threshold is a constant by
   *  construction. */
  contextTraces?: 'repeat' | 'drop';
  /** False keeps the legend hidden when the host has deliberately turned it
   *  off. Grouping otherwise switches it on, because the group names are the
   *  only thing saying which colour is which. */
  showLegend?: boolean;
}

/** Whether grouping is on and this component is able to read it at all. Says
 *  nothing about whether any point will actually match — only the split
 *  itself can answer that, and it answers by leaving the figure alone. */
export function canSplitByGroups(opts: GroupSplitOptions): boolean {
  return applicableGroups(opts).length > 0;
}

function applicableGroups(opts: GroupSplitOptions): GroupRenderState['groups'] {
  const { groupRender, identitySlot } = opts;
  if (!groupRender?.colorByGroup) return [];
  if (typeof identitySlot !== 'number' || identitySlot < 0) return [];
  return (groupRender.groups ?? []).filter((g) => (g.values ?? []).length > 0);
}

/** Per-point arrays sliced alongside the coordinates. `marker.color` is not
 *  here on purpose: grouping *replaces* colour rather than reordering it. */
const POINT_KEYS = ['x', 'y', 'z', 'customdata', 'text', 'hovertext', 'ids'] as const;
const MARKER_POINT_KEYS = ['size', 'symbol', 'opacity'] as const;

function sliceAt(value: any, idx: number[]): any {
  return Array.isArray(value) ? idx.map((i) => value[i]) : value;
}

/** One group's slice of a trace: same shape, fewer points, one flat colour. */
function sliceTrace(trace: any, idx: number[], name: string, color: string): any {
  const out: any = { ...trace };
  for (const key of POINT_KEYS) {
    if (key in out) out[key] = sliceAt(out[key], idx);
  }
  if (out.marker && typeof out.marker === 'object') {
    const marker: any = { ...out.marker };
    for (const key of MARKER_POINT_KEYS) {
      if (key in marker) marker[key] = sliceAt(marker[key], idx);
    }
    if (marker.line && typeof marker.line === 'object') {
      const line: any = { ...marker.line };
      for (const key of ['color', 'width'] as const) {
        if (key in line) line[key] = sliceAt(line[key], idx);
      }
      marker.line = line;
    }
    // The group's colour is the whole point of the override, so whatever the
    // renderer was painting with — a per-point array, a continuous scale, a
    // shared coloraxis — gives way to it, and the colorbar that went with it
    // is dropped rather than left labelling nothing.
    marker.color = color;
    delete marker.colorscale;
    delete marker.coloraxis;
    delete marker.showscale;
    delete marker.colorbar;
    delete marker.cmin;
    delete marker.cmax;
    delete marker.cmid;
    out.marker = marker;
  }
  out.name = name;
  out.legendgroup = name;
  out.showlegend = true;
  return out;
}

/** Axis suffix Plotly uses: panel 0 is the bare `x`/`y`, panel 1 is `x2`/`y2`. */
function axisSuffix(panel: number): string {
  return panel === 0 ? '' : String(panel + 1);
}

/** Evenly spaced domains with a gutter, in Plotly paper coordinates. */
function domains(count: number, gap: number): Array<[number, number]> {
  const span = (1 - gap * (count - 1)) / count;
  return Array.from({ length: count }, (_, i) => {
    const start = i * (span + gap);
    return [start, start + span] as [number, number];
  });
}

/** Retarget one shape or annotation onto a panel's axes. A `paper` x-reference
 *  becomes that panel's domain, which is what keeps a full-width threshold
 *  line full-width *inside its panel* instead of across the whole figure. */
function retarget(obj: any, panel: number): any {
  const suffix = axisSuffix(panel);
  const out = { ...obj };
  for (const [ref, letter] of [
    ['xref', 'x'],
    ['yref', 'y'],
  ] as const) {
    const value = out[ref];
    if (typeof value !== 'string') continue;
    if (value === 'paper') out[ref] = `${letter}${suffix} domain`;
    else if (value === letter) out[ref] = `${letter}${suffix}`;
    else if (value === `${letter} domain`) out[ref] = `${letter}${suffix} domain`;
  }
  return out;
}

/**
 * Apply the dashboard's grouping to a finished figure.
 *
 * Returns the input unchanged whenever there is nothing to apply, so a
 * renderer can call it unconditionally at the end of its figure memo.
 */
export function splitFigureByGroups(figure: FigureLike, opts: GroupSplitOptions): FigureLike {
  const groups = applicableGroups(opts);
  if (groups.length === 0) return figure;

  const {
    identitySlot = 0,
    groupRender,
    facetable = true,
    contextTraces = 'repeat',
    showLegend = true,
  } = opts;
  const showOther = groupRender?.showOther !== false;

  // value -> group. Built in declaration order so an id claimed by two groups
  // lands in the first, matching the server's when/then chain.
  const assignment = new Map<string, string>();
  const colors = new Map<string, string>();
  for (const g of groups) {
    colors.set(g.name, g.color);
    for (const v of g.values) {
      if (!assignment.has(String(v))) assignment.set(String(v), g.name);
    }
  }
  colors.set(OTHER_LABEL, OTHER_COLOR);

  const labelOf = (point: any): string => {
    const key = point?.[identitySlot];
    if (key === undefined || key === null) return OTHER_LABEL;
    return assignment.get(String(key)) ?? OTHER_LABEL;
  };

  // Partition every trace that carries identities. A trace without customdata
  // is context (a centroid marker, a fitted line): it belongs to no group and
  // is carried through instead of being dropped.
  const partitioned: Array<{ trace: any; buckets: Map<string, number[]> }> = [];
  const context: any[] = [];
  const present = new Set<string>();
  for (const trace of figure.data ?? []) {
    const cd = trace?.customdata;
    if (!Array.isArray(cd) || cd.length === 0) {
      context.push(trace);
      continue;
    }
    const buckets = new Map<string, number[]>();
    cd.forEach((point: any, i: number) => {
      const label = labelOf(point);
      if (!showOther && label === OTHER_LABEL) return;
      const bucket = buckets.get(label);
      if (bucket) bucket.push(i);
      else buckets.set(label, [i]);
    });
    for (const label of buckets.keys()) present.add(label);
    partitioned.push({ trace, buckets });
  }
  if (partitioned.length === 0) return figure;

  // Panel order: the groups as the user declared them, "Other" last.
  const order = groups.map((g) => g.name).filter((n) => present.has(n));
  // Not one point belongs to any group: these ids are not this component's.
  // Say so by changing nothing, rather than repainting the figure "Other".
  if (order.length === 0) return figure;
  if (present.has(OTHER_LABEL)) order.push(OTHER_LABEL);

  const facet =
    groupRender?.display === 'facet' && facetable && order.length <= MAX_FACET_PANELS;

  if (!facet) {
    const data: any[] = [];
    const seen = new Set<string>();
    for (const { trace, buckets } of partitioned) {
      for (const label of order) {
        const idx = buckets.get(label);
        if (!idx || idx.length === 0) continue;
        const sliced = sliceTrace(trace, idx, label, colors.get(label) ?? OTHER_COLOR);
        sliced.showlegend = !seen.has(label);
        seen.add(label);
        data.push(sliced);
      }
    }
    // Context traces keep their own identity but stop competing for the
    // legend, which now names groups. Nothing is dropped here: every point is
    // still in the one panel, so a summary over all of them stays true.
    for (const trace of context) data.push({ ...trace, showlegend: false });
    const layout = { ...figure.layout, showlegend: showLegend };
    delete layout.coloraxis;
    return { data, layout };
  }

  const cols = Math.min(order.length, FACET_COL_WRAP);
  const rows = Math.ceil(order.length / cols);
  const xDomains = domains(cols, 0.06);
  const yDomains = domains(rows, 0.12).reverse(); // first panel on the top row

  const baseX = { ...(figure.layout?.xaxis ?? {}) };
  const baseY = { ...(figure.layout?.yaxis ?? {}) };
  const layout: any = { ...figure.layout, showlegend: showLegend };
  delete layout.coloraxis;
  const annotations: any[] = (figure.layout?.annotations ?? [])
    .filter((a: any) => a?.xref === 'paper' && a?.yref === 'paper')
    .map((a: any) => ({ ...a }));
  const shapes: any[] = [];

  const data: any[] = [];
  const seen = new Set<string>();
  order.forEach((label, panel) => {
    const suffix = axisSuffix(panel);
    const col = panel % cols;
    const row = Math.floor(panel / cols);
    const [x0, x1] = xDomains[col];
    const [y0, y1] = yDomains[row];
    const lastRow = row === rows - 1;

    layout[`xaxis${suffix}`] = {
      ...baseX,
      domain: [x0, x1],
      anchor: `y${suffix}`,
      // Linked ranges: panels of the same quantity must be read against each
      // other, which is the only reason to split them in the first place.
      ...(panel > 0 ? { matches: 'x', title: undefined } : {}),
      ...(lastRow ? {} : { showticklabels: false }),
    };
    layout[`yaxis${suffix}`] = {
      ...baseY,
      domain: [y0, y1],
      anchor: `x${suffix}`,
      ...(panel > 0 ? { matches: 'y', title: undefined } : {}),
      ...(col === 0 ? {} : { showticklabels: false }),
    };

    annotations.push({
      text: label,
      x: (x0 + x1) / 2,
      y: Math.min(y1 + 0.03, 1),
      xref: 'paper',
      yref: 'paper',
      xanchor: 'center',
      yanchor: 'bottom',
      showarrow: false,
      font: { size: 12, color: colors.get(label) ?? OTHER_COLOR },
    });

    for (const { trace, buckets } of partitioned) {
      const idx = buckets.get(label);
      if (!idx || idx.length === 0) continue;
      const sliced = sliceTrace(trace, idx, label, colors.get(label) ?? OTHER_COLOR);
      sliced.xaxis = `x${suffix}`;
      sliced.yaxis = `y${suffix}`;
      sliced.showlegend = !seen.has(label);
      seen.add(label);
      data.push(sliced);
    }
    for (const shape of figure.layout?.shapes ?? []) shapes.push(retarget(shape, panel));
    if (contextTraces === 'repeat') {
      for (const trace of context) {
        data.push({
          ...trace,
          xaxis: `x${suffix}`,
          yaxis: `y${suffix}`,
          showlegend: false,
        });
      }
    }
  });

  layout.annotations = annotations;
  if (shapes.length > 0) layout.shapes = shapes;
  return { data, layout };
}
