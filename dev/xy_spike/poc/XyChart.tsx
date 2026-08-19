/**
 * PoC React 18 wrapper around the xy 0.0.6 browser client (issue #945).
 *
 * Answers the issue's central unknown: xy's runtime driven from React with no
 * Reflex anywhere. The client is the wheel's static/standalone.js loaded as a
 * plain <script> (global `xy`) because xy publishes no npm package — a real
 * integration would vendor it or import the ESM static/index.js.
 *
 * Contracts mirrored from depictio-react-core:
 *  - selection.ts: emits an InteractiveFilter-shaped object with
 *    source 'scatter_selection' and value = selection-column strings.
 *    xy's browser xy:select event carries {total, range|polygon} only, so the
 *    wrapper recovers row indices by replaying the region test over the
 *    retained CPU coordinate arrays (see CLIENT_NOTES.md) and maps
 *    positional index -> id via the aligned `ids` array (canonical row order).
 *  - FigureRenderer.tsx: imperative clear + destroy on unmount.
 *
 * PoC-only: not wired into the viewer; no depictio package is touched.
 */

import { useCallback, useEffect, useRef } from "react";

// global from standalone.js (no npm package in xy 0.0.6)
declare const xy: {
  renderStandalone: (el: HTMLElement, spec: unknown, buf: Uint8Array) => XyView;
};

interface XyTraceCpu {
  x: ArrayLike<number>;
  y: ArrayLike<number>;
  xMeta?: { offset: number; scale?: number };
  yMeta?: { offset: number; scale?: number };
}

interface XyGpuTrace {
  n: number;
  _cpu?: XyTraceCpu;
  xMeta: { offset: number; scale?: number };
  yMeta: { offset: number; scale?: number };
}

interface XyView {
  gpuTraces: XyGpuTrace[];
  destroy?: () => void;
  _destroyed?: boolean;
}

export interface InteractiveFilterLike {
  index: string;
  value: string[];
  source: "scatter_selection";
  column_name: string;
  interactive_component_type: "MultiSelect";
}

interface SelectDetail {
  total: number;
  range?: { x0: number; x1: number; y0: number; y1: number };
  polygon?: Array<[number, number]>;
}

/** Replay xy's own local region test to recover selected row indices. */
function recoverIndices(view: XyView, detail: SelectDetail): number[] {
  const out: number[] = [];
  const inPolygon = (px: number, py: number, poly: Array<[number, number]>) => {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i];
      const [xj, yj] = poly[j];
      if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) {
        inside = !inside;
      }
    }
    return inside;
  };
  for (const t of view.gpuTraces) {
    const cpu = t._cpu;
    if (!cpu) continue; // density tier: no local row identity (CLIENT_NOTES)
    const xm = cpu.xMeta ?? t.xMeta;
    const ym = cpu.yMeta ?? t.yMeta;
    const sx = xm.scale ?? 1;
    const sy = ym.scale ?? 1;
    for (let i = 0; i < t.n; i++) {
      const px = (cpu.x[i] as number) / sx + xm.offset;
      const py = (cpu.y[i] as number) / sy + ym.offset;
      if (detail.range) {
        const { x0, x1, y0, y1 } = detail.range;
        if (px >= x0 && px <= x1 && py >= y0 && py <= y1) out.push(i);
      } else if (detail.polygon && inPolygon(px, py, detail.polygon)) {
        out.push(i);
      }
    }
  }
  return out;
}

export interface XyChartProps {
  componentIndex: string;
  specUrl: string;
  blobUrl: string;
  /** selection-column values aligned to canonical row order */
  ids: string[];
  selectionColumn: string;
  onFilterChange?: (f: InteractiveFilterLike) => void;
}

export function XyChart({
  componentIndex,
  specUrl,
  blobUrl,
  ids,
  selectionColumn,
  onFilterChange,
}: XyChartProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<XyView | null>(null);

  useEffect(() => {
    let disposed = false;
    (async () => {
      const [spec, blob] = await Promise.all([
        fetch(specUrl).then((r) => r.json()),
        fetch(blobUrl).then((r) => r.arrayBuffer()),
      ]);
      if (disposed || !hostRef.current) return;
      viewRef.current = xy.renderStandalone(
        hostRef.current,
        spec,
        new Uint8Array(blob),
      );
    })();
    return () => {
      disposed = true;
      viewRef.current?.destroy?.();
      viewRef.current = null;
    };
  }, [specUrl, blobUrl]);

  const handleSelect = useCallback(
    (e: Event) => {
      const detail = (e as CustomEvent<SelectDetail>).detail;
      if (!onFilterChange || !viewRef.current) return;
      const values =
        detail.total > 0
          ? recoverIndices(viewRef.current, detail).map((i) => ids[i])
          : [];
      onFilterChange({
        index: componentIndex,
        value: values,
        source: "scatter_selection",
        column_name: selectionColumn,
        interactive_component_type: "MultiSelect",
      });
    },
    [componentIndex, ids, onFilterChange, selectionColumn],
  );

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    el.addEventListener("xy:select", handleSelect);
    return () => el.removeEventListener("xy:select", handleSelect);
  }, [handleSelect]);

  return <div ref={hostRef} style={{ width: "100%", height: "100%" }} />;
}
