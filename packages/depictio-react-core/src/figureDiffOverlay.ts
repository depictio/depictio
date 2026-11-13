/**
 * Before/after overlay for one Plotly figure (#1397).
 *
 * Pure functions: they take the figure the server drew (data + layout) and the
 * `component_diff` answer, and return what to *add* (traces) and what to
 * *restyle* (patches). The input is never mutated, so a renderer can apply the
 * overlay in a memo and drop it by dropping the memo.
 *
 * What each diff shape draws:
 *  - points   a ring on every point that is new, a ghost marker where a
 *             removed point was, a dotted segment from where a moved point was
 *             to where it is (scatter3d gets scatter3d equivalents; only the
 *             new points can be placed there, the diff carries no z);
 *  - groups   a ghost outline bar at the previous value of each bar, a tick
 *             at the previous median of a box, an outline on a new bar;
 *  - samples  the bars, lines and heatmap rows of the samples seen before
 *             fade; the new ones keep their own colours, lines drawn on top
 *             (MultiQC draws one trace, bar or row per sample);
 *  - rows     the points (or bars) whose `customdata`, `ids` or `text` hold a
 *             new or changed row key are ringed. Nothing otherwise: the
 *             side-by-side view lists the rows.
 *
 * Every added trace is named `__depictio_diff_*` (see {@link isDiffTraceName})
 * so the annotation layer and selection code can skip them, like the other
 * `__depictio_` overlay traces.
 */
import type {
  ComponentDiff,
  DiffGroup,
  DiffGroups,
  DiffPoints,
  DiffRows,
  DiffSamples,
} from './api';
import { DIFF_TRACE_PREFIX } from './annotations/layer';
import { sampleIdsForTrace } from './annotations/multiqc';
import { decodeBdata, isPlotlyTypedArray } from './plotlyData';

export type PlotlyTraceLike = Record<string, unknown>;

export interface PlotlyFigureLike {
  data?: unknown[];
  layout?: Record<string, unknown>;
}

/** A restyle of one existing trace: shallow-merged over it by {@link applyFigureDiffOverlay}. */
export interface TracePatch {
  traceIndex: number;
  patch: Record<string, unknown>;
}

export interface FigureDiffOverlay {
  /** Traces to append after the figure's own. */
  traces: PlotlyTraceLike[];
  /** Restyles of the figure's own traces. */
  patches: TracePatch[];
  /** How many marks of the diff found a place in the figure. */
  matched: number;
}

export interface DiffColors {
  /** New / changed marks. */
  primary: string;
  /** What used to be there. */
  ghost: string;
  /** The ring around a new point: the text colour, so it reads over any
   *  trace colour (the primary can be the very hue of the new points). */
  contrast?: string;
}

/** How far the points already there fade while new ones are shown. */
export const DIFF_DIM_OPACITY = 0.18;

export { DIFF_TRACE_PREFIX };

export const DIFF_HOVER = {
  added: 'New since your last visit',
  removed: 'Was here',
  moved: 'Moved',
  changed: 'Changed since your last visit',
} as const;

export const isDiffTraceName = (name: unknown): boolean =>
  typeof name === 'string' && name.startsWith(DIFF_TRACE_PREFIX);

const EMPTY: FigureDiffOverlay = { traces: [], patches: [], matched: 0 };

// Last resort when the theme variables are not there (a detached document):
// named colours, not a palette.
const FALLBACK_PRIMARY = 'royalblue';
const FALLBACK_GHOST = 'gray';

/**
 * The theme's colours, read when the overlay is built: Mantine's primary and a
 * mid grey. Plotly cannot take a `var(...)`, so the variable is resolved here.
 */
export function resolveDiffColors(root?: Element): DiffColors {
  try {
    const el = root ?? document.documentElement;
    const style = getComputedStyle(el);
    const read = (name: string) => style.getPropertyValue(name).trim();
    return {
      primary: read('--mantine-primary-color-filled') || FALLBACK_PRIMARY,
      ghost: read('--mantine-color-gray-5') || FALLBACK_GHOST,
      contrast: read('--mantine-color-text') || undefined,
    };
  } catch {
    return { primary: FALLBACK_PRIMARY, ghost: FALLBACK_GHOST };
  }
}

const str = (v: unknown): string => (v === null || v === undefined ? '' : String(v));

function arrayOf(field: unknown): unknown[] | null {
  if (Array.isArray(field)) return field;
  if (isPlotlyTypedArray(field)) return decodeBdata(field);
  if (ArrayBuffer.isView(field)) return Array.from(field as unknown as ArrayLike<unknown>);
  return null;
}

const typeOf = (t: PlotlyTraceLike): string => (typeof t.type === 'string' ? t.type : 'scatter');
const isHorizontal = (t: PlotlyTraceLike): boolean => t.orientation === 'h';
const asTraces = (data: unknown[] | undefined): PlotlyTraceLike[] =>
  (data ?? []).filter((t): t is PlotlyTraceLike => !!t && typeof t === 'object');

const num = (v: unknown): number | null => {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
};

const fmt = (v: unknown): string => {
  const n = num(v);
  return n === null ? str(v) : String(Math.round(n * 1000) / 1000);
};

// ── points ─────────────────────────────────────────────────────────────────

function ringTrace(
  name: string,
  dim3: boolean,
  xs: unknown[],
  ys: unknown[],
  zs: unknown[] | null,
  hover: string[],
  color: string,
): PlotlyTraceLike {
  return {
    type: dim3 ? 'scatter3d' : 'scatter',
    mode: 'markers',
    name,
    x: xs,
    y: ys,
    ...(dim3 && zs ? { z: zs } : {}),
    marker: {
      symbol: 'circle-open',
      size: dim3 ? 8 : 14,
      color,
      ...(dim3 ? {} : { line: { width: 2, color } }),
    },
    hovertext: hover,
    hoverinfo: 'text',
    showlegend: false,
  };
}

function ghostTrace(
  name: string,
  dim3: boolean,
  xs: unknown[],
  ys: unknown[],
  hover: string[],
  color: string,
): PlotlyTraceLike {
  return {
    type: dim3 ? 'scatter3d' : 'scatter',
    mode: 'markers',
    name,
    x: xs,
    y: ys,
    marker: { symbol: 'circle', size: dim3 ? 4 : 9, color, opacity: 0.4 },
    hovertext: hover,
    hoverinfo: 'text',
    showlegend: false,
  };
}

const withKey = (label: string, key: string | null): string => (key ? `${key}: ${label}` : label);

/** The z of the figure's own point at (x, y), for the 3D case. */
function zLookup(traces: PlotlyTraceLike[]): (x: unknown, y: unknown) => unknown | undefined {
  const index = new Map<string, unknown>();
  for (const t of traces) {
    if (typeOf(t) !== 'scatter3d') continue;
    const xs = arrayOf(t.x);
    const ys = arrayOf(t.y);
    const zs = arrayOf(t.z);
    if (!xs || !ys || !zs) continue;
    for (let i = 0; i < Math.min(xs.length, ys.length, zs.length); i++) {
      index.set(`${str(xs[i])}|${str(ys[i])}`, zs[i]);
    }
  }
  return (x, y) => index.get(`${str(x)}|${str(y)}`);
}

const MARKER_TYPES = new Set(['scatter', 'scattergl']);

/**
 * Fade the figure's own points that are not new (or moved), so the new ones
 * keep their colour and stand out. Per point, through `marker.opacity`; a
 * trace with no new point fades whole. 3D markers take no per-point opacity.
 */
function dimOldPoints(traces: PlotlyTraceLike[], fresh: Map<string, number>): TracePatch[] {
  if (fresh.size === 0) return [];
  const left = new Map(fresh);
  const patches: TracePatch[] = [];
  traces.forEach((t, traceIndex) => {
    if (!MARKER_TYPES.has(typeOf(t))) return;
    const mode = typeof t.mode === 'string' ? t.mode : 'markers';
    if (!mode.includes('markers')) return;
    const xs = arrayOf(t.x);
    const ys = arrayOf(t.y);
    if (!xs || !ys) return;
    const marker = (t.marker as Record<string, unknown> | undefined) ?? {};
    const own = marker.opacity;
    const base = (i: number): number => {
      const v = Array.isArray(own) ? num(own[i]) : num(own);
      return v === null ? 1 : v;
    };
    const n = Math.min(xs.length, ys.length);
    const opacity: number[] = new Array(n);
    for (let i = 0; i < n; i++) {
      const k = `${str(xs[i])}|${str(ys[i])}`;
      const c = left.get(k) ?? 0;
      if (c > 0) {
        left.set(k, c - 1);
        opacity[i] = base(i);
      } else {
        opacity[i] = base(i) * DIFF_DIM_OPACITY;
      }
    }
    patches.push({ traceIndex, patch: { marker: { ...marker, opacity } } });
  });
  return patches;
}

export function pointsOverlay(
  figure: PlotlyFigureLike,
  diff: DiffPoints,
  colors: DiffColors,
): FigureDiffOverlay {
  const traces = asTraces(figure.data);
  const dim3 = traces.some((t) => typeOf(t) === 'scatter3d');
  const zOf = dim3 ? zLookup(traces) : null;
  const out: PlotlyTraceLike[] = [];
  let matched = 0;

  // Added: ring at the point's own position.
  {
    const xs: unknown[] = [];
    const ys: unknown[] = [];
    const zs: unknown[] = [];
    const hover: string[] = [];
    for (const p of diff.added) {
      if (dim3) {
        const z = zOf?.(p.x, p.y);
        if (z === undefined) continue;
        zs.push(z);
      }
      xs.push(p.x);
      ys.push(p.y);
      hover.push(withKey(DIFF_HOVER.added, p.key));
    }
    if (xs.length) {
      out.push(
        ringTrace(`${DIFF_TRACE_PREFIX}added`, dim3, xs, ys, dim3 ? zs : null, hover, colors.contrast ?? colors.primary),
      );
      matched += xs.length;
    }
  }

  // Removed: a ghost where the point was. Not drawable in 3D (no z in the diff).
  if (!dim3) {
    const rem = diff.removed;
    if (rem.length) {
      out.push(
        ghostTrace(
          `${DIFF_TRACE_PREFIX}removed`,
          false,
          rem.map((p) => p.x),
          rem.map((p) => p.y),
          rem.map((p) => withKey(DIFF_HOVER.removed, p.key)),
          colors.ghost,
        ),
      );
      matched += rem.length;
    }

    // Moved: ghost at the old position, dotted segment, ring at the new one.
    const moved = diff.changed;
    if (moved.length) {
      const sx: unknown[] = [];
      const sy: unknown[] = [];
      const st: string[] = [];
      for (const m of moved) {
        const label = withKey(DIFF_HOVER.moved, m.key);
        sx.push(m.before.x, m.after.x, null);
        sy.push(m.before.y, m.after.y, null);
        st.push(label, label, '');
      }
      out.push({
        type: 'scatter',
        mode: 'lines',
        name: `${DIFF_TRACE_PREFIX}moved`,
        x: sx,
        y: sy,
        line: { color: colors.primary, width: 1.5, dash: 'dot' },
        hovertext: st,
        hoverinfo: 'text',
        showlegend: false,
        connectgaps: false,
      });
      out.push(
        ghostTrace(
          `${DIFF_TRACE_PREFIX}moved_from`,
          false,
          moved.map((m) => m.before.x),
          moved.map((m) => m.before.y),
          moved.map((m) => withKey(`${DIFF_HOVER.removed} (before it moved)`, m.key)),
          colors.ghost,
        ),
      );
      out.push(
        ringTrace(
          `${DIFF_TRACE_PREFIX}moved_to`,
          false,
          moved.map((m) => m.after.x),
          moved.map((m) => m.after.y),
          null,
          moved.map((m) => withKey(DIFF_HOVER.moved, m.key)),
          colors.primary,
        ),
      );
      matched += moved.length;
    }
  }
  // Fade what was already there, so the new and moved points keep their colour.
  const fresh = new Map<string, number>();
  if (!dim3) {
    for (const p of [...diff.added, ...diff.changed.map((m) => m.after)]) {
      const k = `${str(p.x)}|${str(p.y)}`;
      fresh.set(k, (fresh.get(k) ?? 0) + 1);
    }
  }
  return { traces: out, patches: dimOldPoints(traces, fresh), matched };
}

// ── groups ─────────────────────────────────────────────────────────────────

const BAR_LIKE = new Set(['bar', 'histogram']);

interface GroupTarget {
  traceIndex: number;
  trace: PlotlyTraceLike;
  group: DiffGroup;
  category: string;
}

function categoriesOf(t: PlotlyTraceLike): unknown[] | null {
  return arrayOf(isHorizontal(t) ? t.y : t.x);
}
function valuesOf(t: PlotlyTraceLike): unknown[] | null {
  return arrayOf(isHorizontal(t) ? t.x : t.y);
}

const isNumericAxis = (cats: unknown[] | null): boolean =>
  !!cats && cats.length > 0 && cats.every((c) => typeof c === 'number');

/** The figure's traces a diff group is drawn by: same colour value, a type we can mark. */
function traceFor(
  traces: PlotlyTraceLike[],
  diff: DiffGroups,
  group: DiffGroup,
): { index: number; trace: PlotlyTraceLike } | null {
  const colorValue = diff.color ? str(group.group[diff.color]) : null;
  for (let i = 0; i < traces.length; i++) {
    const t = traces[i];
    const type = typeOf(t);
    if (!(BAR_LIKE.has(type) || type === 'box' || type === 'violin' || type === 'scatter' || type === 'scattergl')) {
      continue;
    }
    if (type.startsWith('scatter') && t.stackgroup) continue;
    if (colorValue !== null) {
      if (str(t.name) !== colorValue && str(t.legendgroup) !== colorValue) continue;
    }
    return { index: i, trace: t };
  }
  return null;
}

/** Slot-sharing fields: a ghost with them sits where its bar or box sits. */
function slotOf(t: PlotlyTraceLike): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (t.offsetgroup !== undefined) out.offsetgroup = t.offsetgroup;
  if (t.alignmentgroup !== undefined) out.alignmentgroup = t.alignmentgroup;
  if (t.orientation !== undefined) out.orientation = t.orientation;
  if (t.xaxis !== undefined) out.xaxis = t.xaxis;
  if (t.yaxis !== undefined) out.yaxis = t.yaxis;
  return out;
}

const place = (horizontal: boolean, category: unknown, value: unknown) =>
  horizontal ? { x: value, y: category } : { x: category, y: value };

/**
 * With a colour column, each colour value is its own trace: the traces that
 * hold no new, changed or removed group fade, so a new species (a new run's
 * whole colour) reads at a glance even where a bar-by-bar mark cannot be
 * placed (a binned histogram). Nothing fades when every trace has news.
 */
function dimUntouchedTraces(traces: PlotlyTraceLike[], diff: DiffGroups): { patches: TracePatch[]; touched: number } {
  if (!diff.color) return { patches: [], touched: 0 };
  const touched = new Set<number>();
  for (const g of diff.groups) {
    const found = traceFor(traces, diff, g);
    if (found) touched.add(found.index);
  }
  if (touched.size === 0) return { patches: [], touched: 0 };
  const patches: TracePatch[] = [];
  traces.forEach((t, traceIndex) => {
    if (touched.has(traceIndex)) return;
    const type = typeOf(t);
    if (!(BAR_LIKE.has(type) || type === 'box' || type === 'violin' || type.startsWith('scatter'))) return;
    if (t.name === undefined && t.legendgroup === undefined) return;
    const own = num(t.opacity);
    patches.push({ traceIndex, patch: { opacity: (own ?? 1) * DIFF_DIM_OPACITY } });
  });
  return { patches, touched: patches.length ? touched.size : 0 };
}

export function groupsOverlay(
  figure: PlotlyFigureLike,
  diff: DiffGroups,
  colors: DiffColors,
): FigureDiffOverlay {
  const traces = asTraces(figure.data);
  const layout = figure.layout ?? {};
  const barmode = typeof layout.barmode === 'string' ? layout.barmode : 'group';
  const stacked = barmode === 'stack' || barmode === 'relative';
  // A normalised stack plots shares, not the values the diff holds.
  const normalised = Boolean(layout.barnorm);

  const targets: GroupTarget[] = [];
  for (const group of diff.groups) {
    const found = traceFor(traces, diff, group);
    if (!found) continue;
    const category = diff.x ? str(group.group[diff.x]) : '';
    const t = found.trace;
    const type = typeOf(t);
    const cats = categoriesOf(t);
    // A binned histogram has no bar per distinct value.
    if (type === 'histogram' && (isNumericAxis(cats) || cats === null)) continue;
    if (!diff.x && type !== 'box') continue;
    targets.push({ traceIndex: found.index, trace: t, group, category });
  }
  const dimmed = dimUntouchedTraces(traces, diff);
  if (targets.length === 0) {
    return dimmed.touched ? { traces: [], patches: dimmed.patches, matched: dimmed.touched } : EMPTY;
  }

  const out: PlotlyTraceLike[] = [];
  const patches: TracePatch[] = [...dimmed.patches];
  let matched = 0;

  // Per-trace accumulators.
  const ghostBars = new Map<number, { cats: string[]; vals: number[]; hover: string[] }>();
  const ghostBoxes = new Map<number, { cats: string[]; vals: number[]; hover: string[] }>();
  const ticks = { x: [] as unknown[], y: [] as unknown[], hover: [] as string[], horizontal: false, set: false };
  const rings = { x: [] as unknown[], y: [] as unknown[], hover: [] as string[] };
  const addedBars = new Map<number, Set<string>>();

  const pushTick = (horizontal: boolean, category: unknown, value: unknown, hover: string) => {
    const p = place(horizontal, category, value);
    ticks.x.push(p.x);
    ticks.y.push(p.y);
    ticks.hover.push(hover);
    ticks.horizontal = horizontal;
    ticks.set = true;
  };

  // Stacked bars: where each trace's top was before, per category.
  const stackTop = (category: string, upTo: number): number => {
    let pos = 0;
    let neg = 0;
    for (let j = 0; j <= upTo; j++) {
      const tj = traces[j];
      if (typeOf(tj) !== 'bar') continue;
      const cats = categoriesOf(tj);
      const vals = valuesOf(tj);
      if (!cats || !vals) continue;
      const diffGroup = diff.groups.find((g) => {
        if (diff.x && str(g.group[diff.x]) !== category) return false;
        const f = traceFor(traces, diff, g);
        return f?.index === j;
      });
      let v: number | null;
      if (diffGroup) v = diffGroup.status === 'added' ? 0 : num(diffGroup.before);
      else {
        const at = cats.findIndex((c) => str(c) === category);
        v = at >= 0 ? num(vals[at]) : null;
      }
      if (v === null) continue;
      if (v >= 0) pos += v;
      else neg += v;
    }
    return pos !== 0 || neg === 0 ? pos : neg;
  };

  for (const { traceIndex, trace, group, category } of targets) {
    const type = typeOf(trace);
    const horizontal = isHorizontal(trace);
    const before = num(group.before);
    const after = num(group.after);
    const hoverWas = `${DIFF_HOVER.removed}: ${fmt(group.before)}${category ? ` (${category})` : ''}`;

    if (group.status === 'added') {
      // A new bar / box / group: outline or ring it where it is.
      if (type === 'bar' || type === 'histogram') {
        const set = addedBars.get(traceIndex) ?? new Set<string>();
        set.add(category);
        addedBars.set(traceIndex, set);
      } else if (after !== null) {
        const p = place(horizontal, category || str(trace.name), after);
        rings.x.push(p.x);
        rings.y.push(p.y);
        rings.hover.push(`${DIFF_HOVER.added}${category ? `: ${category}` : ''}`);
      }
      matched += 1;
      continue;
    }
    if (before === null) continue;

    if (type === 'bar' || type === 'histogram') {
      if (stacked) {
        if (normalised) continue;
        pushTick(horizontal, category, stackTop(category, traceIndex), hoverWas);
      } else {
        const acc = ghostBars.get(traceIndex) ?? { cats: [], vals: [], hover: [] };
        acc.cats.push(category);
        acc.vals.push(before);
        acc.hover.push(hoverWas);
        ghostBars.set(traceIndex, acc);
      }
      matched += 1;
    } else if (type === 'box') {
      const acc = ghostBoxes.get(traceIndex) ?? { cats: [], vals: [], hover: [] };
      acc.cats.push(category);
      acc.vals.push(before);
      acc.hover.push(hoverWas);
      ghostBoxes.set(traceIndex, acc);
      matched += 1;
    } else {
      // violin, line: a tick at the previous value.
      pushTick(horizontal, category, before, hoverWas);
      matched += 1;
    }
  }

  for (const [traceIndex, acc] of ghostBars) {
    const trace = traces[traceIndex];
    const horizontal = isHorizontal(trace);
    out.push({
      type: 'bar',
      name: `${DIFF_TRACE_PREFIX}ghost_bar`,
      ...(horizontal ? { x: acc.vals, y: acc.cats } : { x: acc.cats, y: acc.vals }),
      ...slotOf(trace),
      marker: { color: 'rgba(0,0,0,0)', line: { color: colors.ghost, width: 2 } },
      hovertext: acc.hover,
      hoverinfo: 'text',
      showlegend: false,
    });
  }
  for (const [traceIndex, acc] of ghostBoxes) {
    const trace = traces[traceIndex];
    const horizontal = isHorizontal(trace);
    // A box with no category column sits on the bare value axis.
    const bare = acc.cats.every((c) => c === '');
    const positioned = bare
      ? horizontal
        ? { x: acc.vals }
        : { y: acc.vals }
      : horizontal
        ? { x: acc.vals, y: acc.cats }
        : { x: acc.cats, y: acc.vals };
    out.push({
      type: 'box',
      name: `${DIFF_TRACE_PREFIX}ghost_box`,
      ...positioned,
      ...slotOf(trace),
      boxpoints: false,
      fillcolor: 'rgba(0,0,0,0)',
      line: { color: colors.ghost, width: 2 },
      hovertext: acc.hover,
      hoverinfo: 'text',
      showlegend: false,
    });
  }
  if (ticks.set) {
    out.push({
      type: 'scatter',
      mode: 'markers',
      name: `${DIFF_TRACE_PREFIX}ghost_tick`,
      x: ticks.x,
      y: ticks.y,
      marker: {
        symbol: ticks.horizontal ? 'line-ns' : 'line-ew',
        size: 18,
        color: colors.ghost,
        line: { color: colors.ghost, width: 3 },
      },
      hovertext: ticks.hover,
      hoverinfo: 'text',
      showlegend: false,
    });
  }
  if (rings.x.length) {
    out.push({
      type: 'scatter',
      mode: 'markers',
      name: `${DIFF_TRACE_PREFIX}added`,
      x: rings.x,
      y: rings.y,
      marker: { symbol: 'diamond-open', size: 14, color: colors.primary, line: { color: colors.primary, width: 2 } },
      hovertext: rings.hover,
      hoverinfo: 'text',
      showlegend: false,
    });
  }
  // New bars: outline them in place, whatever the barmode.
  for (const [traceIndex, cats] of addedBars) {
    const trace = traces[traceIndex];
    const names = categoriesOf(trace) ?? [];
    const marker = (trace.marker as Record<string, unknown> | undefined) ?? {};
    const line = (marker.line as Record<string, unknown> | undefined) ?? {};
    const baseWidth = (i: number) => {
      const w = line.width;
      return Array.isArray(w) ? w[i] ?? 0 : typeof w === 'number' ? w : 0;
    };
    const baseColor = (i: number) => {
      const c = line.color;
      return Array.isArray(c) ? c[i] : c ?? 'rgba(0,0,0,0)';
    };
    const isNew = names.map((c) => cats.has(str(c)));
    if (!isNew.some(Boolean)) continue;
    patches.push({
      traceIndex,
      patch: {
        marker: {
          ...marker,
          line: {
            ...line,
            width: names.map((_, i) => (isNew[i] ? 3 : baseWidth(i))),
            color: names.map((_, i) => (isNew[i] ? colors.primary : baseColor(i))),
          },
        },
      },
    });
  }
  return { traces: out, patches, matched };
}

// ── samples (MultiQC) ──────────────────────────────────────────────────────

/**
 * Fade what the samples seen before drew; the new samples keep their own
 * colours, so their values still read (MultiQC colours by status).
 */
export function samplesOverlay(
  figure: PlotlyFigureLike,
  diff: DiffSamples,
  _colors?: DiffColors,
): FigureDiffOverlay {
  const added = new Set(diff.added.map(str));
  if (added.size === 0) return EMPTY;
  const traces = asTraces(figure.data);
  const patches: TracePatch[] = [];
  let matched = 0;
  const perTrace: Array<{ index: number; ids: unknown[] | null; trace: PlotlyTraceLike }> = [];
  traces.forEach((trace, index) => {
    perTrace.push({ index, trace, ids: sampleIdsForTrace(trace) });
  });
  const out: PlotlyTraceLike[] = [];
  for (const { index, trace } of perTrace) {
    if (typeOf(trace) !== 'heatmap') continue;
    const rows = heatmapRowsOverlay(trace, index, added);
    if (rows) {
      out.push(rows.trace);
      patches.push(rows.patch);
      matched += rows.matched;
    }
  }
  const hit = perTrace.some((p) => p.ids?.some((id) => id !== null && added.has(str(id))));
  if (!hit) return out.length ? { traces: out, patches, matched } : EMPTY;

  for (const { index, trace, ids } of perTrace) {
    if (!ids) continue;
    const isAdded = ids.map((id) => id !== null && added.has(str(id)));
    if (typeOf(trace) === 'bar') {
      // The bars keep their own colours (the values are what is read): only
      // the bars of the samples seen before fade.
      const marker = (trace.marker as Record<string, unknown> | undefined) ?? {};
      const baseOpacity = typeof marker.opacity === 'number' ? marker.opacity : 1;
      patches.push({
        traceIndex: index,
        patch: {
          marker: {
            ...marker,
            opacity: isAdded.map((a) => (a ? baseOpacity : baseOpacity * DIFF_DIM_OPACITY)),
          },
        },
      });
      matched += isAdded.filter(Boolean).length;
    } else {
      const own = isAdded.some(Boolean);
      if (!own) {
        patches.push({ traceIndex: index, patch: { opacity: DIFF_DIM_OPACITY } });
        continue;
      }
      // Drawn again after every trace, in its own colour and a little wider,
      // so it sits on top of the faded lines; the original stays under it and
      // keeps its hover.
      const lineStyle = (trace.line as Record<string, unknown> | undefined) ?? {};
      out.push({
        ...trace,
        name: `${DIFF_TRACE_PREFIX}sample_${str(trace.name)}`,
        line: { ...lineStyle, width: Math.max(1.5, Number(lineStyle.width) || 0) + 1 },
        opacity: 1,
        showlegend: false,
        hoverinfo: 'skip',
        hovertemplate: undefined,
      });
      matched += 1;
    }
  }
  return { traces: out, patches, matched };
}

/**
 * A heatmap with one row (or column) per sample, as MultiQC's status checks:
 * the heatmap is dimmed and drawn again on top with only the new samples'
 * cells (the others null, so transparent). Plotly cannot restyle one row of a
 * heatmap, and a mark drawn over the row would hide the very cells to read.
 */
function heatmapRowsOverlay(
  trace: PlotlyTraceLike,
  index: number,
  added: Set<string>,
): { trace: PlotlyTraceLike; patch: TracePatch; matched: number } | null {
  if (trace.visible === false) return null;
  const z = arrayOf(trace.z)?.map((row) => arrayOf(row));
  if (!z?.length || z.some((row) => row === null)) return null;
  const rows = z as unknown[][];
  const isNew = (cats: unknown[] | null) => (cats ?? []).map((c) => added.has(str(c)));
  const newRows = isNew(arrayOf(trace.y));
  const newCols = isNew(arrayOf(trace.x));
  const nRows = newRows.filter(Boolean).length;
  const nCols = newCols.filter(Boolean).length;
  if (nRows === 0 && nCols === 0) return null;
  const byRow = nRows >= nCols;
  const kept = rows.map((row, i) =>
    row.map((v, j) => ((byRow ? newRows[i] : newCols[j]) ? v : null)),
  );
  return {
    trace: {
      ...trace,
      name: `${DIFF_TRACE_PREFIX}heatmap_${index}`,
      z: kept,
      opacity: 1,
      showscale: false,
      hoverinfo: 'skip',
      hovertemplate: undefined,
    },
    patch: { traceIndex: index, patch: { opacity: DIFF_DIM_OPACITY } },
    matched: byRow ? nRows : nCols,
  };
}

// ── rows (advanced viz) ────────────────────────────────────────────────────

const ROW_TYPES_2D = new Set(['scatter', 'scattergl']);

/** Every string a point can name its row by: customdata, ids, text, hovertext. */
function pointNames(t: PlotlyTraceLike, i: number): string[] {
  const names: string[] = [];
  const push = (v: unknown) => {
    if (v === null || v === undefined) return;
    if (Array.isArray(v)) v.forEach(push);
    else if (typeof v !== 'object') names.push(String(v));
  };
  const at = (field: unknown) => {
    const arr = arrayOf(field);
    if (arr) push(arr[i]);
    else if (typeof field === 'string' && i === 0) push(field);
  };
  at(t.customdata);
  at(t.ids);
  at(t.text);
  at(t.hovertext);
  return names;
}

/**
 * Mark the points whose row key is new or changed. A generic matcher: it
 * knows nothing of the viz kind, only that most renderers put the row's id in
 * `customdata`, `ids` or `text`. A kind that does not leaves the figure alone.
 */
export function rowsOverlay(
  figure: PlotlyFigureLike,
  diff: DiffRows,
  colors: DiffColors,
): FigureDiffOverlay {
  const added = new Set(diff.added.map((r) => r.key).filter((k): k is string => k !== null));
  const changed = new Set(diff.changed.map((r) => r.key));
  if (added.size === 0 && changed.size === 0) return EMPTY;
  const traces = asTraces(figure.data);
  const out: PlotlyTraceLike[] = [];
  const patches: TracePatch[] = [];
  let matched = 0;

  const rings = (
    name: string,
    dim3: boolean,
    p: { x: unknown[]; y: unknown[]; z: unknown[] },
    label: string,
  ) =>
    ringTrace(name, dim3, p.x, p.y, dim3 ? p.z : null, p.x.map(() => label), colors.primary);

  const addedPts = { x: [] as unknown[], y: [] as unknown[], z: [] as unknown[] };
  const changedPts = { x: [] as unknown[], y: [] as unknown[], z: [] as unknown[] };
  let dim3 = false;

  traces.forEach((t, index) => {
    const type = typeOf(t);
    const is2d = ROW_TYPES_2D.has(type);
    const is3d = type === 'scatter3d';
    const isBar = type === 'bar';
    if (!is2d && !is3d && !isBar) return;
    const xs = arrayOf(t.x);
    const ys = arrayOf(t.y);
    const zs = is3d ? arrayOf(t.z) : null;
    if (!xs || !ys || (is3d && !zs)) return;
    const n = Math.min(xs.length, ys.length);
    const mark: Array<'added' | 'changed' | null> = [];
    let any = false;
    for (let i = 0; i < n; i++) {
      const names = pointNames(t, i);
      const kind = names.some((nm) => added.has(nm))
        ? 'added'
        : names.some((nm) => changed.has(nm))
          ? 'changed'
          : null;
      mark.push(kind);
      if (kind) any = true;
    }
    if (!any) return;
    if (isBar) {
      const marker = (t.marker as Record<string, unknown> | undefined) ?? {};
      const line = (marker.line as Record<string, unknown> | undefined) ?? {};
      patches.push({
        traceIndex: index,
        patch: {
          marker: {
            ...marker,
            line: {
              ...line,
              width: mark.map((m, i) => (m ? 3 : Array.isArray(line.width) ? line.width[i] ?? 0 : Number(line.width) || 0)),
              color: mark.map((m, i) => (m ? colors.primary : Array.isArray(line.color) ? line.color[i] : line.color ?? 'rgba(0,0,0,0)')),
            },
          },
        },
      });
      matched += mark.filter(Boolean).length;
      return;
    }
    if (is3d) dim3 = true;
    mark.forEach((m, i) => {
      if (!m) return;
      const bucket = m === 'added' ? addedPts : changedPts;
      bucket.x.push(xs[i]);
      bucket.y.push(ys[i]);
      if (zs) bucket.z.push(zs[i]);
      matched += 1;
    });
  });

  if (addedPts.x.length) {
    out.push(rings(`${DIFF_TRACE_PREFIX}added`, dim3, addedPts, DIFF_HOVER.added));
  }
  if (changedPts.x.length) {
    out.push(rings(`${DIFF_TRACE_PREFIX}changed`, dim3, changedPts, DIFF_HOVER.changed));
  }
  return { traces: out, patches, matched };
}

// ── entry points ───────────────────────────────────────────────────────────

/** What to draw over `figure` for `diff`. Empty for an unsupported diff or no match. */
export function buildFigureDiffOverlay(
  figure: PlotlyFigureLike | null | undefined,
  diff: ComponentDiff | null | undefined,
  colors: DiffColors,
): FigureDiffOverlay {
  if (!figure || !diff || diff.supported === false) return EMPTY;
  switch (diff.shape) {
    case 'points':
      return pointsOverlay(figure, diff, colors);
    case 'groups':
      return groupsOverlay(figure, diff, colors);
    case 'samples':
      return samplesOverlay(figure, diff, colors);
    case 'rows':
      return rowsOverlay(figure, diff, colors);
    default:
      return EMPTY;
  }
}

/** The figure's traces with the overlay applied: patched copies, then the added traces. */
export function applyFigureDiffOverlay(
  data: unknown[],
  overlay: FigureDiffOverlay,
): unknown[] {
  if (overlay.traces.length === 0 && overlay.patches.length === 0) return data;
  const byIndex = new Map<number, Record<string, unknown>>();
  for (const p of overlay.patches) byIndex.set(p.traceIndex, { ...(byIndex.get(p.traceIndex) ?? {}), ...p.patch });
  const base = byIndex.size
    ? data.map((t, i) => (byIndex.has(i) && t && typeof t === 'object' ? { ...(t as object), ...byIndex.get(i) } : t))
    : data;
  return overlay.traces.length ? [...base, ...overlay.traces] : base;
}

// ── the legend chip ────────────────────────────────────────────────────────

export interface DiffSummaryParts {
  added: number;
  removed: number;
  /** Moved points, changed bars or rows. */
  moved: number;
  movedLabel: string;
}

export function diffSummaryParts(diff: ComponentDiff | null | undefined): DiffSummaryParts | null {
  if (!diff || diff.supported === false) return null;
  switch (diff.shape) {
    case 'points':
      return {
        added: diff.counts.added,
        removed: diff.counts.removed,
        moved: diff.counts.changed,
        movedLabel: 'moved',
      };
    case 'groups':
      return {
        added: diff.counts.added,
        removed: diff.counts.removed,
        moved: diff.counts.changed,
        movedLabel: 'changed',
      };
    case 'samples':
      return { added: diff.counts.added, removed: diff.counts.removed, moved: 0, movedLabel: 'changed' };
    case 'rows':
      return {
        added: diff.counts.added,
        removed: diff.counts.removed,
        moved: diff.counts.changed,
        movedLabel: 'changed',
      };
    default:
      return null;
  }
}

/** "Compared with your last visit: +3 · −1 · 2 moved". */
export function diffSummaryText(diff: ComponentDiff | null | undefined): string | null {
  const parts = diffSummaryParts(diff);
  if (!parts) return null;
  const bits: string[] = [];
  if (parts.added) bits.push(`+${parts.added}`);
  if (parts.removed) bits.push(`−${parts.removed}`);
  if (parts.moved) bits.push(`${parts.moved} ${parts.movedLabel}`);
  return `Compared with your last visit: ${bits.length ? bits.join(' · ') : 'no differences'}`;
}
