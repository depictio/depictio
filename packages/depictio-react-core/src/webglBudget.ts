import { useEffect, useRef, useState } from 'react';

/**
 * Browsers cap the number of *live* WebGL contexts per renderer process —
 * Chrome's limit is 16. Plotly allocates **three** GL canvases for every
 * `scattergl` plot (`gl-canvas-context`, `gl-canvas-focus`, `gl-canvas-pick`),
 * so a page can only host about five of them. Past that the browser silently
 * drops the *oldest* contexts: the canvas goes blank while the SVG axes,
 * annotations and titles stay put. The user sees the markers paint for a
 * couple of seconds and then vanish.
 *
 * Measured on the 32-component benchmark dashboard (11 `scattergl` plots):
 * 33 GL canvases, 16 live, **17 lost** — five plots rendered empty.
 *
 * This module hands out a bounded number of GL slots. Plots that miss out fall
 * back to SVG `scatter`, which has no context limit. They render fewer points
 * (SVG costs one DOM node per marker) but they *render*, which is the whole
 * point.
 */

/** Live GL plots allowed at once. 4 × 3 canvases = 12, leaving headroom under
 *  Chrome's 16 for anything else on the page that wants a context. */
const MAX_GL_PLOTS = 4;

/** Marker budget for a plot that fell back to SVG. One DOM node per marker, so
 *  this is the difference between a slow dashboard and an unusable one. */
export const SVG_MAX_POINTS = 3000;

const holders = new Set<string>();
const listeners = new Map<string, () => void>();
let counter = 0;

function reoffer(except: string): void {
  for (const [id, listener] of listeners) {
    if (id !== except) listener();
  }
}

/**
 * Claim one of the bounded WebGL slots for the lifetime of the component.
 *
 * Slots go out in mount order, which on a dashboard grid means top-to-bottom —
 * the plots the user sees first keep the fast renderer. A slot is released on
 * unmount and immediately re-offered, so scrolling a plot out of the tree (or
 * a component being deleted in edit mode) upgrades whoever is waiting.
 *
 * Ask at mount, from the component's *kind*, not once its data has arrived:
 * deciding on the fetched point count hands the slots to whichever fetch
 * happened to finish first, which is neither stable across reloads nor what
 * the user is looking at. A plot that turns out to be small wastes its slot,
 * which costs nothing — GL draws few points perfectly well.
 *
 * @param wanted `false` for a component that never draws GL at all (a box
 *   plot, a bar chart), so it never occupies a slot.
 * @returns whether GL may be used. `false` means render SVG instead.
 */
export function useWebglSlot(wanted: boolean): boolean {
  const idRef = useRef<string | null>(null);
  if (idRef.current === null) {
    counter += 1;
    idRef.current = `gl-${counter}`;
  }
  const id = idRef.current;
  const [granted, setGranted] = useState(false);

  useEffect(() => {
    const evaluate = () => {
      if (!wanted) {
        if (holders.delete(id)) reoffer(id);
        setGranted(false);
        return;
      }
      if (holders.has(id) || holders.size < MAX_GL_PLOTS) {
        holders.add(id);
        setGranted(true);
        return;
      }
      setGranted(false);
    };
    listeners.set(id, evaluate);
    evaluate();
    return () => {
      listeners.delete(id);
      if (holders.delete(id)) reoffer(id);
    };
  }, [wanted, id]);

  return granted;
}

/** Every index when no reduction is needed, otherwise an evenly-spaced subset
 *  of at most `cap` indices. Deterministic — the same frame always yields the
 *  same picture, so a re-render doesn't reshuffle the cloud. */
function strideIndices(n: number, cap: number): number[] | null {
  if (n <= cap) return null;
  const stride = n / cap;
  const out: number[] = new Array(cap);
  for (let k = 0; k < cap; k += 1) out[k] = Math.floor(k * stride);
  return out;
}

export type PlotlyTrace = Record<string, unknown>;

/** Plotly.py 6 serialises numeric columns as `{dtype, bdata}` with the values
 *  base64-encoded rather than as a JSON array, so server-built figures need
 *  decoding before their points can be counted or subset. */
const TYPED_ARRAYS: Record<string, new (buf: ArrayBuffer) => ArrayLike<number>> = {
  f8: Float64Array,
  f4: Float32Array,
  i1: Int8Array,
  u1: Uint8Array,
  i2: Int16Array,
  u2: Uint16Array,
  i4: Int32Array,
  u4: Uint32Array,
};

/** The per-point values of a trace field as something indexable, or `null` if
 *  the field isn't per-point data (a scalar colour, a title, a dtype we don't
 *  know). */
function asPointArray(value: unknown): ArrayLike<unknown> | null {
  if (Array.isArray(value)) return value;
  if (value && typeof value === 'object') {
    const spec = value as { dtype?: unknown; bdata?: unknown };
    if (typeof spec.dtype === 'string' && typeof spec.bdata === 'string') {
      const Ctor = TYPED_ARRAYS[spec.dtype];
      if (!Ctor) return null;
      const binary = atob(spec.bdata);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      return new Ctor(bytes.buffer);
    }
  }
  return null;
}

/** Number of points a trace draws, across both array encodings. */
export function traceLength(trace: PlotlyTrace): number {
  return asPointArray(trace.x)?.length ?? asPointArray(trace.y)?.length ?? 0;
}

function pickIndices(value: unknown, idx: number[], n: number): unknown {
  const points = asPointArray(value);
  if (points === null || points.length !== n) return value;
  return idx.map((i) => points[i]);
}

/**
 * Adapt a `scattergl` trace to whichever renderer the plot actually got.
 *
 * With a slot the trace passes through untouched. Without one it becomes an
 * SVG `scatter` trace, downsampled to {@link SVG_MAX_POINTS} — every
 * per-point array on the trace (`x`, `y`, `text`, `customdata`,
 * `marker.color`, `marker.size`) is subset by the same indices so the point
 * identities stay aligned.
 */
export function adaptGlTrace<T extends PlotlyTrace>(trace: T, glGranted: boolean): PlotlyTrace {
  if (glGranted || trace.type !== 'scattergl') return trace;

  const n = traceLength(trace);
  const idx = strideIndices(n, SVG_MAX_POINTS);
  if (idx === null) return { ...trace, type: 'scatter' };

  const marker = (trace.marker as Record<string, unknown> | undefined) ?? undefined;
  const out: PlotlyTrace = { ...trace, type: 'scatter' };
  for (const key of Object.keys(trace)) {
    if (key === 'marker' || key === 'type') continue;
    out[key] = pickIndices(trace[key], idx, n);
  }
  if (marker) {
    const nextMarker: Record<string, unknown> = { ...marker };
    for (const key of Object.keys(marker)) {
      nextMarker[key] = pickIndices(marker[key], idx, n);
    }
    out.marker = nextMarker;
  }
  return out;
}

/** {@link adaptGlTrace} across a whole `data` array. */
export function adaptGlTraces(traces: readonly PlotlyTrace[], glGranted: boolean): PlotlyTrace[] {
  return traces.map((t) => adaptGlTrace(t, glGranted));
}
