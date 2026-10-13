import { useEffect, useMemo, useRef } from 'react';
// Vite resolve.alias in depictio/viewer/vite.config.ts rewrites bare
// `plotly.js` to `plotly.js/dist/plotly`, so this import grabs the prebuilt
// browser UMD bundle that react-plotly.js itself uses internally — no
// `buffer/` source walk, no extra bundle weight, single Plotly instance.
import Plotly from 'plotly.js';

import type { InteractiveFilter } from '../api';

/**
 * Wipe a plot's drawn selection when its own selection is cleared from
 * outside: the chrome's reset, or a group saved from it.
 *
 * react-plotly.js is a controlled wrapper for `data` + `layout`, but the
 * drawn selection lives in Plotly's internal UI state (`layout.selections`
 * and per-trace `selectedpoints`) which isn't reflected back into our props.
 * Forcing those to null via `relayout` / `restyle` is the documented escape
 * hatch.
 *
 * Returns the ref to hand the graph div to, from the plot's `onInitialized`
 * and `onUpdate`.
 */
export function usePlotSelectionReset(
  filters: InteractiveFilter[],
  index: string,
): React.MutableRefObject<HTMLElement | null> {
  const gdRef = useRef<HTMLElement | null>(null);

  const hasOwnSelection = useMemo(
    () =>
      filters.some(
        (f) =>
          f.index === index &&
          f.source === 'scatter_selection' &&
          Array.isArray(f.value) &&
          f.value.length > 0,
      ),
    [filters, index],
  );

  // Track whether this component had its own selection on the previous render
  // so the clear only fires on the true→false transition. Without this gate
  // it would also run on first mount, before any selection ever existed.
  const prevHadOwnSelection = useRef(false);

  useEffect(() => {
    const wasActive = prevHadOwnSelection.current;
    prevHadOwnSelection.current = hasOwnSelection;
    if (!wasActive || hasOwnSelection) return;

    const gd = gdRef.current;
    if (!gd) return;

    // relayout({selections: null}) wipes drawn selection shapes (lasso/box
    // outline) and restyle({selectedpoints: null}) restores the un-dimmed
    // look on every trace. Wrapped in try/catch because the gd may have
    // unmounted between scheduling and running, and Plotly raises on a
    // detached div.
    try {
      // Casts: @types/plotly.js wants Plotly types on gd but the wrapper
      // exposes a regular HTMLElement that Plotly accepts at runtime; and
      // `selections` / `selectedpoints` aren't in the typed layout/style
      // surface but Plotly accepts them as a known clear-state idiom.
      const target = gd as unknown as Parameters<typeof Plotly.relayout>[0];
      Plotly.relayout(target, { selections: null } as Partial<Plotly.Layout>).catch(() => {});
      const data = (gd as unknown as { data?: unknown[] }).data;
      const traceCount = Array.isArray(data) ? data.length : 0;
      if (traceCount > 0) {
        const indices = Array.from({ length: traceCount }, (_, i) => i);
        Plotly.restyle(
          target,
          { selectedpoints: [null] } as Partial<Plotly.PlotData>,
          indices,
        ).catch(() => {});
      }
    } catch {
      // best-effort: gd may have unmounted between schedule and run
    }
  }, [hasOwnSelection]);

  return gdRef;
}
