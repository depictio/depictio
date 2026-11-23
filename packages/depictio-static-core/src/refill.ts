/**
 * Bind-and-refill runtime (RFC §4, phase 5b) — turn a BindingTable + the
 * current filter mask into a fully-populated Plotly figure.
 *
 * The build side ran the REAL `create_figure_from_data` on unfiltered data and
 * emitted `scaffold` (that exact figure JSON, data arrays stripped) plus, per
 * trace, its group-equality predicates and field→column bindings. Because
 * filtering only removes rows — it can never create a trace, a colour, or a
 * facet — the runtime never re-derives figure structure: it selects each
 * trace's rows (filter mask AND group predicates), projects the bound columns
 * and writes the arrays back into a clone of the scaffold. Layout is NEVER
 * touched; empty traces flip `visible:false` but are never dropped, so trace
 * indices (and trendline `on` references) stay stable — except on a layout
 * Plotly cannot draw hidden traces in (`readsHiddenTraces`), where they are
 * dropped once refilling is done.
 *
 * Every bound array is REPLACED wholesale, in this side's own row order — so
 * the order the build-time figure happened to hold is discarded at first paint,
 * the default (empty) filter state included. That is what lets the builder
 * match a trace to its group by row multiset where row order draws nothing
 * (binding.py's `_order_free_trace`).
 *
 * Group matching convention: `group` values were emitted by the Python
 * builder and arrive through manifest JSON; column values come from the
 * decoded Parquet. Both sides are compared through `serializeOption` — the
 * same str()-mirroring convention the engine's `in` filter/codebooks pin
 * (engine/filters.ts) — which is exact for strings (the overwhelmingly common
 * grouping dtype) and self-consistent for numbers/booleans/bigints since BOTH
 * sides serialize in JS (`57` vs Int64 `57n` → "57"; JSON `true` vs decoded
 * `true` → "true"). The group column itself is always bundled (it is a
 * referenced column of the figure, so export pruning keeps it), so no
 * `__code__` codebook indirection is needed here; a null cell never matches
 * any group, mirroring null-never-matches in the mask kernel. A group value
 * that matches no rows simply yields a hidden trace — same visible outcome as
 * the server rendering an empty subframe for that group.
 *
 * Trendlines: every kind px offers that the binder accepted (`ols` with its
 * options, `lowess`, `rolling`, `expanding`, `ewm`) is refit over the rows
 * the raw trace it was fit against (`on`) keeps under the mask, by a port of
 * px's own trendline functions (`./trendline.ts`): one fitted point per
 * non-missing (x, y) pair, sorted by x, exactly the vertices px draws. Fewer
 * than 2 usable pairs hides the trendline (px emits it empty).
 *
 * Counting mirrors the server's FigureResponse metadata: `displayed` is the
 * points actually plotted — the sum of rows written across RAW traces
 * (trendline vertices excluded; on a partitioning grouping this equals the
 * server's filtered `df.height`) — and `total` is the mask-selected row count
 * (full table length when mask is null).
 */

import type { BindingTable, TraceBinding } from './manifest';
import { fitTrendline } from './trendline';
import { fillTrace, jsonClone, selectRows, traceAt } from './refillHelpers';
import {
  groupedRefill,
  groupingColumns,
  planColoring,
  type GroupingOutcome,
  type GroupingRequest,
} from './grouping';

export interface RefillInput {
  binding: BindingTable;
  /** Full-length source columns by name (e.g. engine.columns bound to an open table). */
  columns(names: string[]): Promise<Record<string, ArrayLike<unknown>>>;
  /** Current filter mask (1 byte per row, 1 = selected); null = no filters. */
  mask: Uint8Array | null;
  /**
   * Selection groups / colour-by / split the figure is asked to be drawn with
   * (`./grouping.ts`). Absent, or a request the binding cannot take, draws the
   * figure as built.
   */
  grouping?: GroupingRequest;
}

export interface RefillResult {
  figure: { data: unknown[]; layout: Record<string, unknown> };
  /** Points plotted across raw traces (server's displayed_data_count). */
  displayed: number;
  /** Mask-selected row count (server's total_data_count). */
  total: number;
  /** Set when the figure was recoloured: the server's `group_colored` / `column_colored`. */
  grouping?: GroupingOutcome;
}

export async function refillFigure(input: RefillInput): Promise<RefillResult> {
  const { binding, mask } = input;

  // The scaffold is manifest JSON — a JSON deep-clone is lossless and leaves
  // the manifest object pristine for the next refill/theme flip.
  const scaffold = binding.scaffold as {
    data?: unknown[];
    layout?: Record<string, unknown>;
  };
  const data = jsonClone(scaffold.data ?? []) as Record<string, unknown>[];
  const layout = jsonClone(scaffold.layout ?? {}) as Record<string, unknown>;

  // Project every needed column once: union of bound source columns and
  // group columns across traces (trendlines read the on-trace's x/y, already
  // in the union).
  const needed = new Set<string>();
  for (const t of binding.traces) {
    for (const col of Object.values(t.fields)) needed.add(col);
    for (const col of Object.keys(t.group)) needed.add(col);
    for (const col of t.customdata ?? []) needed.add(col);
  }
  const cols = needed.size > 0 ? await input.columns([...needed]) : {};

  const first = needed.size > 0 ? cols[[...needed][0]] : undefined;
  const rows = first !== undefined ? first.length : (mask?.length ?? 0);

  let total = rows;
  if (mask !== null) {
    total = 0;
    for (let i = 0; i < mask.length; i++) total += mask[i];
  }

  // ---- groups, colour-by, split ---------------------------------------------
  // A request px would honour redraws the figure from its rows (`grouping.ts`):
  // the scaffold's traces are cut and merged by the new colour, so none of the
  // per-trace work below applies. A request this binding cannot take, or a
  // column the table does not carry, leaves the figure as built.
  if (input.grouping) {
    const extra = groupingColumns(input.grouping).filter((c) => !(c in cols));
    let available = true;
    if (extra.length > 0) {
      try {
        Object.assign(cols, await input.columns(extra));
      } catch {
        available = false;
      }
    }
    const plan = available
      ? planColoring(input.grouping, cols, rows, scaffold.layout)
      : null;
    const grouped = plan ? groupedRefill(binding, cols, mask, rows, plan) : null;
    if (grouped) {
      return { figure: grouped.figure, displayed: grouped.displayed, total, grouping: grouped.outcome };
    }
  }

  // ---- raw traces ----------------------------------------------------------
  const hidden = new Set<number>();
  const selectionByTrace = new Map<number, number[]>();
  let displayed = 0;

  for (const t of binding.traces) {
    const trace = traceAt(data, t.i);
    const sel = selectRows(t, cols, mask, rows);
    selectionByTrace.set(t.i, sel);
    displayed += sel.length;
    fillTrace(trace, t, cols, sel);
    if (sel.length === 0) {
      // Empty group under this filter: the server would render an empty
      // subframe → nothing visible. Hide, never drop — indices stay stable.
      trace.visible = false;
      hidden.add(t.i);
    }
  }

  // ---- trendlines ----------------------------------------------------------
  for (const tl of binding.trendlines) {
    const trace = traceAt(data, tl.i);
    const src = binding.traces.find((t) => t.i === tl.on);
    if (!src) {
      throw new Error(`refill: trendline ${tl.i} references unbound trace ${tl.on}`);
    }
    const xCol = src.fields['x'];
    const yCol = src.fields['y'];
    if (!xCol || !yCol) {
      throw new Error(`refill: trendline ${tl.i} source trace ${tl.on} has no x/y binding`);
    }
    const sel = selectionByTrace.get(tl.on) ?? [];
    const fit = fitTrendline(tl.kind ?? 'ols', tl.options ?? {}, cols[xCol], cols[yCol], sel);
    if (fit === null) {
      // px leaves the trace empty below 2 usable (x, y) pairs.
      trace.visible = false;
      hidden.add(tl.i);
      continue;
    }
    trace.x = fit.x;
    trace.y = fit.y;
  }

  // Indices only had to stay stable while refilling (trendlines name their
  // source trace by index). Plotly itself cannot always take a hidden trace:
  // see `readsHiddenTraces`. There the hidden ones are dropped, which draws
  // the same figure (a hidden trace takes no bar slot and no legend entry) and
  // is what px builds from the filtered frame anyway: no trace for an empty
  // group.
  const out = readsHiddenTraces(layout) ? data.filter((_t, i) => !hidden.has(i)) : data;
  return { figure: { data: out, layout }, displayed, total };
}

/** Category orders Plotly resolves by reading every trace's coordinates
 *  (`findCategories` in plotly.js `category_order_defaults.js`). */
const DATA_CATEGORY_ORDER =
  /^(category (ascending|descending)|(total|min|max|sum|mean|geometric mean|median) (ascending|descending))$/;

/**
 * True when Plotly would crash on a `visible: false` trace in this layout.
 *
 * A hidden trace's full data carries no `x` / `y` (Plotly stops coercing it at
 * `visible: false`), but an axis ordered by its data (`categoryorder: "total
 * descending"`, …) reads `x.length` of every trace on it while supplying
 * defaults. That threw inside `Plotly.react`, left a half-built plot, and the
 * next resize and the unmount threw again as page errors (`reading 'length'`,
 * then `reading 'selectAll'` in `cleanPlot`): viralrecon's "Calls per gene"
 * under a lineage that has no NONSENSE call.
 */
export function readsHiddenTraces(layout: Record<string, unknown>): boolean {
  return Object.entries(layout).some(([key, axis]) => {
    if (!/^[xy]axis\d*$/.test(key) || axis === null || typeof axis !== 'object') return false;
    const order = (axis as { categoryorder?: unknown }).categoryorder;
    return typeof order === 'string' && DATA_CATEGORY_ORDER.test(order);
  });
}
