/**
 * Which columns a table grid shows, and in which order.
 *
 * `/render_table` returns every column of the data collection, in the
 * collection's order. Two settings narrow that: the builder's per-column
 * `cols_json[field].hide`, and the YAML `columns` allowlist ("Columns to
 * display"). The allowlist also sets the order, so an author lists the key
 * columns first instead of finding them wherever the recipe wrote them.
 *
 * Kept free of React so the rule is executed by a test.
 */

/** Visible columns of `columns`, in the allowlist's order when there is one
 *  (else the response's own order). Allowlisted names the response does not
 *  hold are skipped. */
export function visibleTableColumns<T extends { field: string }>(
  columns: readonly T[],
  colsJson: Record<string, { hide?: boolean } | undefined> | null | undefined,
  allowList: readonly unknown[] | null | undefined,
): T[] {
  const order =
    Array.isArray(allowList) && allowList.length > 0
      ? new Map(allowList.map((c, i) => [String(c), i] as const))
      : null;
  const visible = columns.filter(
    (c) => colsJson?.[c.field]?.hide !== true && (!order || order.has(c.field)),
  );
  if (order) visible.sort((a, b) => (order.get(a.field) ?? 0) - (order.get(b.field) ?? 0));
  return visible;
}
