/**
 * Selecting an UpSet intersection as a dashboard filter.
 *
 * An intersection is a set of rows of the matrix: the elements (taxa, peaks,
 * genes) found in exactly the sets it joins. Clicking it selects them, as a
 * lasso selects points, by emitting the values they hold in the component's
 * `selection_column`: a column the other tiles' data shares, so every tile
 * narrows to those elements.
 *
 * The members are worked out here, from the rows of the matrix under the same
 * filters the worker built the figure from, rather than shipped with the
 * figure. Membership is exclusive, as in plotly-upset: a row belongs to the
 * intersection whose sets are exactly the drawn sets it is in. Only the drawn
 * sets count, so a filter that narrowed the sets narrows the membership the
 * same way it narrowed the figure.
 */

/** The identity of an intersection: its sets, in a stable order. */
export function upsetIntersectionKey(sets: readonly string[]): string {
  return JSON.stringify([...sets].sort());
}

function isMember(v: unknown): boolean {
  if (v === true) return true;
  const n = Number(v);
  return Number.isFinite(n) && n === 1;
}

/**
 * The selection values of every intersection, keyed by `upsetIntersectionKey`.
 *
 * `rows` is the matrix column-wise (the data endpoint's shape). A row in none
 * of `setNames` belongs to no drawn intersection and is skipped, as the worker
 * drops it; a row with no value in `selectionColumn` adds nothing.
 */
export function upsetIntersectionMembers(
  rows: Record<string, unknown[]>,
  setNames: readonly string[],
  selectionColumn: string,
): Map<string, string[]> {
  const ids = rows[selectionColumn] ?? [];
  const columns = setNames.map((name) => rows[name] ?? []);
  const members = new Map<string, Set<string>>();
  for (let i = 0; i < ids.length; i++) {
    const sets = setNames.filter((_, s) => isMember(columns[s][i]));
    if (sets.length === 0) continue;
    const key = upsetIntersectionKey(sets);
    if (!members.has(key)) members.set(key, new Set());
    const id = ids[i];
    if (id === null || id === undefined || id === '') continue;
    members.get(key)!.add(String(id));
  }
  return new Map([...members].map(([key, ids]) => [key, [...ids].sort()]));
}

function sameValues(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const set = new Set(a);
  return b.every((v) => set.has(v));
}

/**
 * The intersection the component's selection filter stands for, or null.
 *
 * `ownValues` is the selection the dashboard currently holds for this
 * component; null when there is none, which is how a Reset elsewhere clears
 * the highlight. `picked` is the intersection last clicked here, trusted while
 * a selection stands: its members can change under a later filter without the
 * selection being a different one. Without it (the component was remounted),
 * the intersection is recognised by its values.
 */
export function selectedUpsetIntersection(
  picked: string | null,
  ownValues: readonly string[] | null,
  members: Map<string, string[]> | null,
): string | null {
  if (!ownValues || ownValues.length === 0) return null;
  if (picked) return picked;
  if (!members) return null;
  for (const [key, ids] of members) {
    if (sameValues(ids, ownValues)) return key;
  }
  return null;
}

/** The intersection (x) index whose sets have this key, or null. */
export function upsetColumnOf(columnSets: Map<number, string[]>, key: string | null): number | null {
  if (!key) return null;
  for (const [column, sets] of columnSets) {
    if (upsetIntersectionKey(sets) === key) return column;
  }
  return null;
}
