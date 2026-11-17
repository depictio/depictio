/**
 * Draws a highlight into Plotly traces: the picked points keep full opacity and
 * get an open ring, everything else in the trace is dimmed.
 *
 * Pure and renderer-agnostic. A trace joins the highlight when it carries a
 * `customdata` array whose entries hold the feature id at `slot`; traces
 * without one (guide lines, label overlays, density heatmaps) are left alone.
 * The caller feeds the result to `Plot` in place of the original traces and
 * keeps the original for anything that matches points by their data.
 */

export interface HighlightPaint {
  /** `customdata` slot holding the feature id. */
  slot: number;
  /** Ring colour; a resolved theme colour (Plotly cannot read CSS variables). */
  ringColor: string;
  /** Opacity of the points that are not picked. */
  dimOpacity?: number;
  /** The row hovered in the table: its point gets a ring of its own, larger,
   *  without dimming anything. */
  hoverKey?: string | null;
}

const DEFAULT_DIM_OPACITY = 0.2;
/** Beyond this many picked points the rings stop adding information and cost
 *  SVG nodes; the dimming alone still shows the selection. */
export const MAX_HIGHLIGHT_RINGS = 500;

type Trace = Record<string, unknown>;

function keyAt(customdata: unknown[], i: number, slot: number): string | null {
  const cd = customdata[i];
  if (cd == null || typeof cd !== 'object') return null;
  const raw = (cd as Record<number, unknown>)[slot];
  return raw == null ? null : String(raw);
}

/** Indices of the points in `trace` whose key is in `keys`; null when the trace
 *  does not carry keys at `slot`. */
export function selectedIndices(
  trace: Trace,
  keys: ReadonlySet<string>,
  slot: number,
): number[] | null {
  const cd = trace.customdata;
  if (!Array.isArray(cd) || cd.length === 0) return null;
  // A trace whose first entry has nothing at `slot` is not keyed on this id.
  let keyed = false;
  const out: number[] = [];
  for (let i = 0; i < cd.length; i++) {
    const k = keyAt(cd, i, slot);
    if (k === null) continue;
    keyed = true;
    if (keys.has(k)) out.push(i);
  }
  return keyed ? out : null;
}

export function applyHighlight(
  data: readonly unknown[] | null | undefined,
  keys: readonly string[],
  paint: HighlightPaint,
): unknown[] | null | undefined {
  if (!data) return data as unknown[] | null | undefined;
  const picked = keys.length ? pickPoints(data, keys, paint) : (data as unknown[]);
  const hover = paint.hoverKey ? hoverRing(data, paint.hoverKey, paint) : null;
  return hover ? [...picked, hover] : picked;
}

/** The ring around the hovered row's point, or null when no trace holds it. */
function hoverRing(data: readonly unknown[], key: string, paint: HighlightPaint): Trace | null {
  const wanted = new Set([key]);
  for (const raw of data) {
    const trace = raw as Trace | null;
    const at = trace ? selectedIndices(trace, wanted, paint.slot) : null;
    const xs = trace?.x;
    const ys = trace?.y;
    if (!at?.length || !Array.isArray(xs) || !Array.isArray(ys)) continue;
    const i = at[0];
    if (xs[i] == null || ys[i] == null) continue;
    return {
      type: 'scatter',
      mode: 'markers',
      name: 'hover',
      x: [xs[i]],
      y: [ys[i]],
      hoverinfo: 'skip',
      showlegend: false,
      marker: {
        symbol: 'circle-open',
        size: 22,
        color: paint.ringColor,
        line: { color: paint.ringColor, width: 3 },
      },
    };
  }
  return null;
}

function pickPoints(
  data: readonly unknown[],
  keys: readonly string[],
  paint: HighlightPaint,
): unknown[] {
  const wanted = new Set(keys);
  const dim = paint.dimOpacity ?? DEFAULT_DIM_OPACITY;
  const out: unknown[] = [];
  const ringX: unknown[] = [];
  const ringY: unknown[] = [];
  let touched = false;

  for (const raw of data) {
    const trace = raw as Trace | null;
    const picked = trace ? selectedIndices(trace, wanted, paint.slot) : null;
    if (!trace || !picked) {
      out.push(raw);
      continue;
    }
    touched = true;
    out.push({
      ...trace,
      selectedpoints: picked,
      selected: { marker: { opacity: 1 } },
      unselected: { marker: { opacity: dim } },
    });
    const xs = trace.x;
    const ys = trace.y;
    if (Array.isArray(xs) && Array.isArray(ys)) {
      for (const i of picked) {
        if (ringX.length >= MAX_HIGHLIGHT_RINGS) break;
        if (xs[i] == null || ys[i] == null) continue;
        ringX.push(xs[i]);
        ringY.push(ys[i]);
      }
    }
  }
  if (!touched) return data as unknown[];
  if (ringX.length > 0) {
    out.push({
      type: 'scatter',
      mode: 'markers',
      name: 'highlight',
      x: ringX,
      y: ringY,
      hoverinfo: 'skip',
      showlegend: false,
      marker: {
        symbol: 'circle-open',
        size: 15,
        color: paint.ringColor,
        line: { color: paint.ringColor, width: 2 },
      },
    });
  }
  return out;
}

/**
 * The layout half: a new `selectionrevision` whenever a change did not come from
 * Plotly's own box/lasso, so Plotly drops the selection state it holds and takes
 * the `selectedpoints` handed in the traces; and a `uirevision`, defaulted, so a
 * redraw caused by a click keeps the reader's zoom instead of resetting it.
 */
export function highlightLayout(
  layout: Record<string, unknown>,
  revision: number,
  uirevision: string,
): Record<string, unknown> {
  const ui = layout.uirevision ?? uirevision;
  const base = layout.selectionrevision ?? ui;
  return {
    ...layout,
    uirevision: ui,
    selectionrevision: `${String(base)}|h${revision}`,
  };
}
