/**
 * Row selection and trace filling shared by `refill.ts` (the figure as built)
 * and `grouping.ts` (the figure recoloured or split by selection groups).
 * Pure functions over the bound columns; nothing here knows about plotly
 * beyond "a trace is an object with dotted field paths".
 */

import type { TraceBinding } from './manifest';
import { serializeOption } from './engine/filters';

export function jsonClone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

export function traceAt(data: Record<string, unknown>[], i: number): Record<string, unknown> {
  const trace = data[i];
  if (trace === undefined || trace === null || typeof trace !== 'object') {
    throw new Error(`refill: binding references trace ${i} but scaffold has ${data.length} traces`);
  }
  return trace;
}

/** Rows selected for one trace: filter mask AND every group-equality predicate. */
export function selectRows(
  t: TraceBinding,
  cols: Record<string, ArrayLike<unknown>>,
  mask: Uint8Array | null,
  rows: number,
): number[] {
  const preds = Object.entries(t.group).map(([col, groupValue]) => {
    const values = cols[col];
    if (values === undefined) {
      throw new Error(`refill: group column "${col}" was not projected`);
    }
    const key = serializeOption(groupValue);
    return { values, key };
  });
  const out: number[] = [];
  for (let i = 0; i < rows; i++) {
    if (mask !== null && mask[i] === 0) continue;
    let ok = true;
    for (const { values, key } of preds) {
      const v = values[i];
      // Null never matches any predicate (same rule as the mask kernel).
      if (v === null || v === undefined || serializeOption(v) !== key) {
        ok = false;
        break;
      }
    }
    if (ok) out.push(i);
  }
  return out;
}

/** Project the selected rows of a column into a plain, Plotly-safe array
 *  (bigint → number; undefined holes → null), in row order. */
export function gather(values: ArrayLike<unknown> | undefined, sel: number[], col: string): unknown[] {
  if (values === undefined) {
    throw new Error(`refill: bound column "${col}" was not projected`);
  }
  const out: unknown[] = new Array(sel.length);
  for (let k = 0; k < sel.length; k++) {
    const v = values[sel[k]];
    out[k] = v === undefined ? null : typeof v === 'bigint' ? Number(v) : v;
  }
  return out;
}

/** Write `value` at a dotted field path (e.g. 'marker.size'), creating
 *  intermediate objects as needed; sibling keys are preserved. */
export function setPath(obj: Record<string, unknown>, path: string, value: unknown): void {
  const parts = path.split('.');
  let cur = obj;
  for (let k = 0; k < parts.length - 1; k++) {
    const next = cur[parts[k]];
    if (typeof next !== 'object' || next === null || Array.isArray(next)) {
      cur[parts[k]] = {};
    }
    cur = cur[parts[k]] as Record<string, unknown>;
  }
  cur[parts[parts.length - 1]] = value;
}

/** Write one trace's bound arrays (and its positional `customdata`) for the
 *  rows `sel` selects. */
export function fillTrace(
  trace: Record<string, unknown>,
  t: TraceBinding,
  cols: Record<string, ArrayLike<unknown>>,
  sel: number[],
): void {
  for (const [path, col] of Object.entries(t.fields)) {
    setPath(trace, path, gather(cols[col], sel, col));
  }
  if (t.customdata !== undefined && t.customdata.length > 0) {
    // px stacks hover_data/custom_data into one (n, k) array and the
    // hovertemplate addresses it POSITIONALLY (`%{customdata[2]}`), so the
    // binding's column order is the contract: zip the gathered columns back
    // in that order and every index in the (untouched) hovertemplate keeps
    // pointing at the value the server put there.
    const gathered = t.customdata.map((col) => gather(cols[col], sel, col));
    const rowsOut: unknown[][] = new Array(sel.length);
    for (let k = 0; k < sel.length; k++) {
      rowsOut[k] = gathered.map((values) => values[k]);
    }
    trace.customdata = rowsOut;
  }
}
