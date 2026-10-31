/**
 * Keeps a figure's picked points highlighted after the pick.
 *
 * A click selects in Plotly's own state, which lasts until the next render and
 * covers only the subplot clicked: on a faceted bar chart the other panels
 * never dimmed, and the refetch the pick triggers wiped even that. The pick is
 * also a dashboard filter, so the figure can redraw it from there: every trace
 * whose `customdata` carries the selection column gets `selectedpoints`, and
 * Plotly dims the rest. A pick made on another tile of the same collection (a
 * table row, a browser feature) on the same column highlights here too.
 */
import type { InteractiveFilter } from './api';
import { extractCustomdataIds } from './plotlyData';

const SELECTION_SOURCES = new Set(['scatter_selection', 'table_selection', 'jbrowse_selection']);

/** The values picked on `column`, by this tile or a tile reading the same
 *  collection; null when nothing is picked. */
export function standingSelectionValues(
  filters: readonly InteractiveFilter[] | undefined,
  own: { index: string; dcId?: string; column: string | null },
): Set<string> | null {
  if (!own.column) return null;
  const values = new Set<string>();
  for (const f of filters ?? []) {
    if (!f.source || !SELECTION_SOURCES.has(f.source)) continue;
    if (!Array.isArray(f.value) || f.value.length === 0) continue;
    const column = f.column_name ?? f.metadata?.selection_column ?? f.metadata?.column_name ?? null;
    if (column !== own.column) continue;
    const sameTile = f.index === own.index;
    const sameCollection = Boolean(own.dcId) && f.metadata?.dc_id === own.dcId;
    if (!sameTile && !sameCollection) continue;
    for (const v of f.value) values.add(String(v));
  }
  return values.size > 0 ? values : null;
}

/** `data` with `selectedpoints` set on every trace that carries ids. A trace
 *  with no ids (a reference line, an annotation) is returned as it is. */
export function markSelectedPoints<T extends { customdata?: unknown }>(
  data: readonly T[],
  selected: ReadonlySet<string>,
  selectionColumnIndex: number,
): T[] {
  return data.map((trace) => {
    const ids = extractCustomdataIds(trace?.customdata, selectionColumnIndex);
    if (ids.length === 0) return trace;
    const selectedpoints: number[] = [];
    ids.forEach((id, i) => {
      if (selected.has(id)) selectedpoints.push(i);
    });
    return { ...trace, selectedpoints };
  });
}
