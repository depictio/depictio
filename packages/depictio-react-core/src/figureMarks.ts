/**
 * The catalog preview's "Automatic marks" switch.
 *
 * The server draws a figure's automatic marks (bar labels, group n, cell
 * values, the "N more not shown" note) and ships, next to the marked figure,
 * the patch that takes them off again (`marks_off_patch` in
 * `depictio/api/v1/services/figure/annotations.py`). Top-level keys only: a
 * mark replaces a key whole (`textfont`, `xaxis`, `annotations`).
 */

export interface MarksPatchPart {
  set?: Record<string, unknown>;
  unset?: string[];
}

export interface MarksOffPatch {
  data?: Array<MarksPatchPart & { i: number }>;
  layout?: MarksPatchPart;
}

export interface PlotlyFigureLike {
  data?: unknown[];
  layout?: Record<string, unknown>;
  [key: string]: unknown;
}

function patched(target: Record<string, unknown>, part: MarksPatchPart): Record<string, unknown> {
  const out: Record<string, unknown> = { ...target, ...(part.set ?? {}) };
  for (const key of part.unset ?? []) delete out[key];
  return out;
}

/** `figure` with its marks taken off by `patch`; the input is left untouched. */
export function applyMarksOff<F extends PlotlyFigureLike>(
  figure: F,
  patch: MarksOffPatch | null | undefined,
): F {
  if (!patch) return figure;
  const data = [...(figure.data ?? [])];
  for (const entry of patch.data ?? []) {
    const trace = data[entry.i];
    if (trace && typeof trace === 'object') {
      data[entry.i] = patched(trace as Record<string, unknown>, entry);
    }
  }
  const layout = patch.layout ? patched(figure.layout ?? {}, patch.layout) : figure.layout;
  return { ...figure, data, layout };
}
