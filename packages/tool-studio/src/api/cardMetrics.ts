/**
 * The card's secondary-strip payloads (`__breakdown__` and `__<layout>__`).
 *
 * Computed by depictio-static-core's `cardLayouts` — the ports of the server's
 * `services/card_breakdown.compute_breakdown` and
 * `services/card_metrics.numeric_layout_payload` the exported serverless
 * dashboard runs — over the rows the active filters keep. This module only
 * adapts a Studio frame to the kernels' column getter (see `layoutGetter`).
 *
 * Still pinned against the real Python: `scripts/card_metrics_golden.py` runs
 * the server modules over `e2e/golden/card_metrics.csv` and
 * `src/test/cardMetrics.test.ts` asserts these functions reproduce it.
 *
 * Every function returns `null` where the Python returns `None`: the strip is
 * then not rendered at all.
 */
import type { BreakdownPayload } from 'depictio-react-core';
import {
  computeBreakdown as breakdownKernel,
  evenness,
  numericLayoutPayload as layoutKernel,
  type Bitmask,
} from 'depictio-static-core';
import type { StudioFrame } from './frame';
import { layoutGetter } from './frameEngine';

export { evenness };

/** Layouts backed by a numeric payload keyed `__<layout>__` (`NUMERIC_LAYOUTS`). */
export function numericLayoutPayload(
  frame: StudioFrame,
  card: Record<string, unknown>,
  column: string,
  layout: string,
  mask: Bitmask | null = null,
): Record<string, unknown> | null {
  return layoutKernel(layoutGetter(frame), mask, frame.height, card, column, layout);
}

/** The `__breakdown__` payload the categorical layouts read. */
export function computeBreakdown(
  frame: StudioFrame,
  column: string,
  breakdownCol: string,
  aggregation: string,
  topNCount = 3,
  mask: Bitmask | null = null,
): BreakdownPayload | null {
  return breakdownKernel(
    layoutGetter(frame),
    mask,
    frame.height,
    column,
    breakdownCol,
    aggregation,
    topNCount,
  ) as BreakdownPayload | null;
}
