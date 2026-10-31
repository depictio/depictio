/**
 * Extra hover columns for a point plot whose Plotly `customdata` already has a
 * fixed head (the Manhattan's selection value, chromosome and position). The
 * columns ride after that head, so nothing that reads the head moves.
 */

/** The columns to show, in order, blanks and repeats dropped. */
export function hoverColumnList(cols: readonly string[] | null | undefined): string[] {
  const out: string[] = [];
  for (const c of cols ?? []) {
    if (c && !out.includes(c)) out.push(c);
  }
  return out;
}

/** The values of `cols` for one row, as `customdata` slots. A missing value
 *  is an empty string, so the tooltip line reads `label: ` rather than
 *  `label: undefined`. */
export function hoverRow(
  columns: readonly (readonly unknown[])[],
  row: number,
): unknown[] {
  return columns.map((values) => values[row] ?? '');
}

/** The `<br>label: %{customdata[n]}` lines for `cols`, whose values start at
 *  slot `firstSlot` of `customdata`. */
export function hoverTemplateLines(cols: readonly string[], firstSlot: number): string {
  return cols.map((c, j) => `<br>${c}: %{customdata[${firstSlot + j}]}`).join('');
}
