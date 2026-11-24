/**
 * The structure of a clustered heatmap (dendrogram branches, annotation cell
 * outlines) drawn in the plot's muted ink of the scheme on show.
 *
 * plotly-complexheatmap draws that structure in a fixed near-black
 * (`#444444` branches, `#333333` outlines), which vanishes on a dark surface
 * and reads heavier than the data on a light one. Only those two library
 * colours are replaced; every colour the data carries is left as it came.
 */
type Trace = Record<string, unknown>;

const LIBRARY_INK = new Set(['#444444', '#333333']);

const isInk = (c: unknown): boolean => typeof c === 'string' && LIBRARY_INK.has(c.toLowerCase());

export function inkStructure<T>(data: T[], ink: string): T[] {
  return data.map((trace) => {
    const t = trace as unknown as Trace;
    if (!t || typeof t !== 'object') return trace;
    const line = t.line as Trace | undefined;
    const marker = t.marker as Trace | undefined;
    const markerLine = marker?.line as Trace | undefined;
    const lineInk = line && isInk(line.color);
    const outlineInk = markerLine && isInk(markerLine.color);
    if (!lineInk && !outlineInk) return trace;
    const out: Trace = { ...t };
    if (lineInk) out.line = { ...line, color: ink };
    if (outlineInk) out.marker = { ...marker, line: { ...markerLine, color: ink } };
    return out as unknown as T;
  });
}
