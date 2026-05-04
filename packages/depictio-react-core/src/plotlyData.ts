/**
 * Decode Plotly's binary typed-array transport format (``{dtype, bdata, shape}``)
 * into a plain ``number[]``. Plotly.js v2+ ships scatter ``x`` / ``y`` /
 * ``customdata`` over the wire as base64-encoded typed arrays (saves ~3-4×
 * bytes vs. JSON arrays for large traces). Plotly's runtime decodes these
 * internally on render — but if we need to read them from React (e.g. to
 * build a "newly arrived points" overlay trace) we have to decode ourselves.
 *
 * Supported dtypes (from Plotly's typed-array spec): i1 i2 i4 u1 u2 u4 f4 f8.
 * Anything unrecognised → empty array, which keeps the highlight code path
 * dormant rather than throwing.
 */

const VIEW_BY_DTYPE: Record<
  string,
  (buf: ArrayBuffer) => ArrayLike<number>
> = {
  i1: (buf) => new Int8Array(buf),
  i2: (buf) => new Int16Array(buf),
  i4: (buf) => new Int32Array(buf),
  u1: (buf) => new Uint8Array(buf),
  u2: (buf) => new Uint16Array(buf),
  u4: (buf) => new Uint32Array(buf),
  f4: (buf) => new Float32Array(buf),
  f8: (buf) => new Float64Array(buf),
};

export interface PlotlyTypedArray {
  dtype: string;
  bdata: string;
  shape?: string;
}

/** Returns true if ``v`` looks like a Plotly typed-array payload. */
export function isPlotlyTypedArray(v: unknown): v is PlotlyTypedArray {
  return (
    !!v &&
    typeof v === 'object' &&
    typeof (v as PlotlyTypedArray).dtype === 'string' &&
    typeof (v as PlotlyTypedArray).bdata === 'string'
  );
}

/** Decode a Plotly typed-array field to a plain ``number[]`` (flat). */
export function decodeBdata(field: PlotlyTypedArray): number[] {
  const make = VIEW_BY_DTYPE[field.dtype];
  if (!make) return [];
  try {
    const binary = atob(field.bdata);
    const buf = new ArrayBuffer(binary.length);
    const bytes = new Uint8Array(buf);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const view = make(buf);
    const out: number[] = new Array(view.length);
    for (let i = 0; i < view.length; i++) out[i] = view[i];
    return out;
  } catch {
    return [];
  }
}

/**
 * Resolve a Plotly trace field that may be either a plain array (legacy /
 * small traces) or a typed-array payload. Returns a flat ``number[]``.
 */
export function asNumberArray(field: unknown): number[] {
  if (Array.isArray(field)) {
    return field.map((v) => Number(v)).filter((v) => !Number.isNaN(v));
  }
  if (isPlotlyTypedArray(field)) {
    return decodeBdata(field);
  }
  return [];
}

/**
 * Pull per-point IDs from a scatter trace's ``customdata``. ``customdata``
 * is shape ``[N, M]`` row-major: N points, M columns of metadata. The id
 * for point ``i`` lives at offset ``i * M + selectionColumnIndex``.
 *
 * Returns a string array (caller may want a Set) — strings keep the IDs
 * comparable across encodings (e.g. backend may emit ints, but we want
 * matching against ``customdata`` from the figure dict to be lossless).
 */
export function extractCustomdataIds(
  customdata: unknown,
  selectionColumnIndex: number,
): string[] {
  if (Array.isArray(customdata)) {
    // Plain JS array: each entry is itself an array of metadata cols.
    const out: string[] = [];
    for (const row of customdata) {
      if (Array.isArray(row)) {
        const v = row[selectionColumnIndex];
        if (v !== null && v !== undefined) out.push(String(v));
      }
    }
    return out;
  }
  if (!isPlotlyTypedArray(customdata)) return [];

  const flat = decodeBdata(customdata);
  if (flat.length === 0) return [];

  // Parse ``shape: "N, M"`` (Plotly emits a string).
  let cols = 1;
  if (typeof customdata.shape === 'string') {
    const parts = customdata.shape.split(',').map((s) => parseInt(s.trim(), 10));
    if (parts.length >= 2 && Number.isFinite(parts[1])) cols = parts[1];
  }
  if (cols <= 0) cols = 1;

  const rows = Math.floor(flat.length / cols);
  const idx = Math.min(Math.max(selectionColumnIndex, 0), cols - 1);
  const out: string[] = new Array(rows);
  for (let i = 0; i < rows; i++) {
    out[i] = String(flat[i * cols + idx]);
  }
  return out;
}
