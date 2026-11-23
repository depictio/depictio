/**
 * Port of the post-load half of the ``compute_sankey`` Celery task
 * (``_sankey_result_from_frame``, depictio/api/v1/celery_tasks.py), which the
 * static runtime replays over the bundled Parquet (serverless RFC §13: sankey
 * is `compute_live`, like contact_map). The server's own figures carry no
 * palette — the renderer recolours client-side — so none is built here either.
 * Parity: `test/sankey.test.ts`, whose expected values were produced by the
 * Python function on the same inputs.
 */

/** `SankeyPayload` minus the load the server does first (filters applied upstream). */
export interface SankeyRequest {
  step_cols: string[];
  value_col?: string | null;
  sort_mode?: 'alphabetical' | 'total_flow' | 'input' | null;
  min_link_value?: number | null;
  step_filters?: Record<string, string[]> | null;
  /** Columns whose distinct values come back as `step_options` (default: step_cols). */
  option_cols?: string[] | null;
}

const MISSING = '(missing)';

/** Python `sorted` on a str list: code-point order (comparePolars' string branch). */
const compareCodePoint = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** Polars `cast(pl.Utf8)`: BigInt → decimal, null stays null. */
const asString = (v: unknown): string | null =>
  v === null || v === undefined ? null : typeof v === 'bigint' ? v.toString() : String(v);

/** `_sankey_result_from_frame`'s value coercion: NULL and the empty string
 *  both become the literal "(missing)" node label, everything else its string. */
const stepValue = (v: unknown): string => {
  const s = asString(v) ?? '';
  return s === '' ? MISSING : s;
};

/** Polars `cast(pl.Float64)`: a NULL weight is dropped by the caller so one
 *  bad row cannot poison the aggregate into NaN (the server-side filter's
 *  whole point); a non-numeric string degrades to a drop instead of the
 *  strict cast's error. */
const asWeight = (v: unknown): number | null => {
  if (v === null || v === undefined) return null;
  if (typeof v === 'bigint') return Number(v);
  if (typeof v === 'number') return v;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
};

interface AggregatedLink {
  sourceCol: string;
  targetCol: string;
  sourceValue: string;
  targetValue: string;
  value: number;
}

/**
 * `_sankey_result_from_frame` (celery_tasks.py) over column arrays: the frame
 * the server loaded is the bundled table under `mask` (the dashboard filters,
 * already resolved). Returns the exact result dict the Celery task returns
 * (figure + node metadata + step_options), minus `load_ms`/`compute_ms` —
 * the caller owns timing.
 */
export function sankeyFromColumns(
  columns: Record<string, ArrayLike<unknown>>,
  nRows: number,
  mask: ArrayLike<number> | null,
  req: SankeyRequest,
): Record<string, unknown> {
  const stepCols = req.step_cols;
  if (stepCols.length < 2) throw new Error('compute_sankey: step_cols must have ≥2 columns');

  const at = (col: string, i: number): unknown =>
    columns[col] ? columns[col][i] : undefined;
  const hasCol = (col: string): boolean => Boolean(columns[col]);
  for (const col of stepCols) {
    if (!hasCol(col)) throw new Error(`compute_sankey: column "${col}" is not in the frame`);
  }

  // The loaded frame (dashboard filters are the row mask).
  let sel: number[] = [];
  for (let i = 0; i < nRows; i++) {
    if (mask !== null && mask[i] !== 1) continue;
    sel.push(i);
  }
  const inputRows = sel.length;

  // step_options read BEFORE the step filters, so a picked value never hides
  // the others; a missing option column is skipped, a duplicate de-duplicated.
  const stepOptions: Record<string, string[]> = {};
  for (const col of req.option_cols ?? stepCols) {
    if (!hasCol(col) || col in stepOptions) continue;
    const seen = new Set<string>();
    for (const i of sel) seen.add(asString(at(col, i)) ?? '');
    stepOptions[col] = [...seen].sort(compareCodePoint);
  }

  // Per-step filters applied AFTER global filter_metadata. A NULL never
  // matches (polars' `is_in` on a null predicate filters the row out).
  for (const [col, allowed] of Object.entries(req.step_filters ?? {})) {
    if (stepCols.includes(col) && allowed.length) {
      const keep = new Set(allowed);
      sel = sel.filter((i) => {
        const s = asString(at(col, i));
        return s !== null && keep.has(s);
      });
    }
  }

  // Materialise the weight column: a NULL weight is dropped before summing so
  // one bad row cannot poison the aggregate into NaN; without a value column
  // every row counts 1.0.
  const valueCol = req.value_col || null;
  if (valueCol) {
    if (!hasCol(valueCol)) throw new Error(`compute_sankey: column "${valueCol}" is not in the frame`);
    sel = sel.filter((i) => asWeight(at(valueCol, i)) !== null);
  }

  // Build per-adjacent-pair link aggregates: (src_value, tgt_value) → sum of
  // weights, in order of first appearance (`maintain_order=True`), pairs in
  // step order. Weights read row-by-row over the kept rows.
  const linkFrames: { sourceCol: string; targetCol: string; sums: Map<string, number> }[] = [];
  for (let p = 0; p + 1 < stepCols.length; p++) {
    const sums = new Map<string, number>();
    for (const i of sel) {
      const src = stepValue(at(stepCols[p], i));
      const tgt = stepValue(at(stepCols[p + 1], i));
      const w = valueCol ? (asWeight(at(valueCol, i)) as number) : 1.0;
      const key = `${src}\u0001${tgt}`;
      sums.set(key, (sums.get(key) ?? 0) + w);
    }
    linkFrames.push({ sourceCol: stepCols[p], targetCol: stepCols[p + 1], sums });
  }

  let links: AggregatedLink[] = [];
  for (const frame of linkFrames) {
    for (const [key, value] of frame.sums) {
      const [sourceValue, targetValue] = key.split('\u0001');
      links.push({ sourceCol: frame.sourceCol, targetCol: frame.targetCol, sourceValue, targetValue, value });
    }
  }

  const minValue = req.min_link_value ?? 0;
  if (minValue > 0) links = links.filter((l) => l.value >= minValue);

  // Node universe: one node per (step, value) pair, in step order. Sort
  // values within a step by chosen mode; total_flow falls back to
  // alphabetical when there are no links to rank from.
  const stepValues = (stepCol: string): string[] => {
    if (req.sort_mode === 'input') {
      const seen = new Set<string>();
      const out: string[] = [];
      for (const i of sel) {
        const v = stepValue(at(stepCol, i));
        if (!seen.has(v)) {
          seen.add(v);
          out.push(v);
        }
      }
      return out;
    }
    if (req.sort_mode === 'total_flow' && links.length > 0) {
      // total per label = outgoing + incoming sums for this step's links.
      const totals = new Map<string, number>();
      for (const l of links) {
        if (l.sourceCol === stepCol) totals.set(l.sourceValue, (totals.get(l.sourceValue) ?? 0) + l.value);
        if (l.targetCol === stepCol) totals.set(l.targetValue, (totals.get(l.targetValue) ?? 0) + l.value);
      }
      return [...totals.keys()].sort((a, b) => {
        const ta = totals.get(a) as number;
        const tb = totals.get(b) as number;
        if (ta !== tb) return tb - ta; // descending total
        return compareCodePoint(a, b); // ascending label
      });
    }
    const seen = new Set<string>();
    for (const i of sel) seen.add(stepValue(at(stepCol, i)));
    return [...seen].sort(compareCodePoint);
  };

  const nodeRows: { label: string; step: string; step_index: number }[] = [];
  const seen = new Map<string, number>();
  for (let s = 0; s < stepCols.length; s++) {
    for (const v of stepValues(stepCols[s])) {
      const key = `${stepCols[s]}\u0001${v}`;
      if (seen.has(key)) continue;
      seen.set(key, nodeRows.length);
      nodeRows.push({ label: v, step: stepCols[s], step_index: s });
    }
  }

  // Resolve link source/target to node indices; a link whose endpoint is
  // outside the node universe is dropped (defensive, as in the server).
  const sources: number[] = [];
  const targets: number[] = [];
  const values: number[] = [];
  const linkLabels: string[] = [];
  for (const l of links) {
    const sk = seen.get(`${l.sourceCol}\u0001${l.sourceValue}`);
    const tk = seen.get(`${l.targetCol}\u0001${l.targetValue}`);
    if (sk === undefined || tk === undefined) continue;
    sources.push(sk);
    targets.push(tk);
    values.push(l.value);
    linkLabels.push(`${l.sourceValue} → ${l.targetValue}`);
  }

  // Plotly figure — minimal layout, renderer adds template / dark mode.
  const figDict = {
    data: [
      {
        type: 'sankey',
        arrangement: 'snap',
        node: {
          label: nodeRows.map((n) => n.label),
          pad: 14,
          thickness: 18,
        },
        link: {
          source: sources,
          target: targets,
          value: values,
          label: linkLabels,
        },
      },
    ],
    layout: { font: { size: 12 }, margin: { l: 8, r: 8, t: 24, b: 8 } },
  };

  const totalFlow = values.reduce<number>((acc, v) => acc + v, 0);

  return {
    figure: figDict,
    nodes: nodeRows,
    step_cols: stepCols,
    node_count: nodeRows.length,
    link_count: values.length,
    total_flow: totalFlow,
    row_count: sel.length,
    // Rows before the step filters; the flow above aggregates all of them.
    input_rows: inputRows,
    step_options: stepOptions,
  };
}
