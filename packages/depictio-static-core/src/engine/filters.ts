/**
 * BoundFilter — the engine-level filter model.
 *
 * Mirrors the server's runtime-filter semantics in
 * `depictio/api/v1/deltatables_utils.py`. Each variant maps to one
 * `add_filter` branch (add_filter:225); the semantics the mask kernel must
 * reproduce are pinned there:
 *
 * - `in` — Select/MultiSelect/SegmentedControl (add_filter:252-258 →
 *   `_categorical_predicate`:138). Values arrive stringified on the wire; on a
 *   String column the server does bare `pl.col(c).is_in(str_values)`
 *   (deltatables_utils.py:193); on typed columns it casts the *values* to the
 *   column dtype and drops any that fail to convert (deltatables_utils.py:215),
 *   so an unconvertible value matches nothing. In the serverless bundle,
 *   categorical non-String columns instead carry an Int32 `__code__<col>`
 *   companion + codebook (manifest.ts DataRef.codebooks): the engine translates
 *   selected values → codes via `serializeOption`, and a value absent from the
 *   codebook matches NOTHING (the manifest-pinned analogue of the failed cast).
 * - `eq` — Slider (add_filter:264-266): `pl.col(c) == value`.
 * - `range` — RangeSlider (add_filter:268-272):
 *   `(col >= min) & (col <= max)` — both bounds INCLUSIVE.
 * - `ts_range` — DateRangePicker/Timeline (add_filter:274-345):
 *   `(date_col >= start) & (date_col <= end)` — both bounds INCLUSIVE.
 *   The engine compares against the `__ts__<col>` epoch-microsecond Int64
 *   companion, in BigInt space (mixing `number` silently truncates > 2^53).
 * - `contains` — TextInput (add_filter:260-262): `pl.col(c).str.contains(v)`,
 *   which in Polars is a REGEX match (not substring), CASE-SENSITIVE,
 *   unanchored. The engine compiles `new RegExp(pattern)` accordingly.
 * - `link_no_match` — the `LINK_NO_MATCH` sentinel
 *   (deltatables_utils.py:135, add_filter:240-250): a cross-DC link resolved
 *   to zero target values appends `pl.lit(False)` — the whole mask is
 *   all-false, regardless of any other filter.
 *
 * Cross-cutting server rules the kernel reproduces:
 *
 * - Filters AND together (`_apply_scan_filters`:1191-1195 folds with `&`).
 * - Per-filter skip on a missing column: a filter whose column is absent from
 *   the table is dropped individually, the rest still apply
 *   (apply_runtime_filters:1986-2010 checks `column_name not in df_columns`;
 *   `_apply_scan_filters`:1174-1187 does the same against the schema). For the
 *   engine, "present" means the physical column it reads: the column itself,
 *   or its `__code__`/`__ts__` companion where that is the read target.
 * - Null never matches any predicate: Polars comparisons and `is_in` on null
 *   evaluate to null, and `filter` drops null rows (verified on Polars 1.42.1:
 *   `is_in`, `==`, `>=/<=`, `str.contains` all drop the null rows).
 * - Empty values never reach the kernel: `add_filter` guards every value
 *   branch with `if value:` and `apply_runtime_filters`:1989-1991 passes
 *   empty-valued components straight through, so the *binder* (a later phase)
 *   must simply not emit a BoundFilter for an empty selection. `link_no_match`
 *   is the one exception — it carries no value and always applies.
 */

export type BoundFilter =
  /** Select / MultiSelect / SegmentedControl (and scatter/table selections). */
  | { kind: 'in'; column: string; values: unknown[] }
  /** RangeSlider — inclusive on both ends; a missing bound is unbounded. */
  | { kind: 'range'; column: string; min?: number; max?: number }
  /**
   * Date pickers via the `__ts__<column>` companion, epoch-MICROseconds.
   * Inclusive on both ends; a missing bound is unbounded. `column` is the
   * logical datetime column; the engine reads its `__ts__` companion.
   */
  | { kind: 'ts_range'; column: string; min?: bigint; max?: bigint }
  /** Slider — exact equality. */
  | { kind: 'eq'; column: string; value: unknown }
  /** TextInput — case-sensitive, unanchored REGEX (Polars str.contains). */
  | { kind: 'contains'; column: string; pattern: string }
  /** Cross-DC link resolved to zero targets → all-false mask. */
  | { kind: 'link_no_match' };

/**
 * Serialize a UI option value to the codebook key convention.
 *
 * The AUTHORITATIVE convention is the Python builder's
 * `depictio.serverless.companions.serialize_option`: keys are the plain
 * Python `str()` rendering of the option value — mirroring the real
 * MultiSelect-options endpoint (`get_unique_values`, deltatables
 * routes.py:689 `sorted({str(v) for v in values})`) — with one deliberate
 * exception: booleans are `"true"`/`"false"` (Polars' rendering, matching the
 * server's Boolean Utf8-fallback predicate; see the companions.py docstring).
 *
 * At runtime this function is almost a no-op: `in` filter values arrive as
 * the option STRINGS the UI holds (fetchUniqueValues returns string[], and in
 * a bundle the options come from `Object.keys(codebook)` — Python-produced
 * strings). So the primary rule is: a string is a codebook key AS-IS, never
 * quoted or transformed.
 *
 * Non-string fallbacks, for values that reach the engine untransformed:
 * - boolean → `"true"`/`"false"` (`String(v)` already renders these — and it
 *   is the one case where Python `str()` would NOT match: the builder lowers
 *   `str(True) == "True"` to `"true"` deliberately).
 * - number → `String(v)`. Caveat: JS `String(2.0) === "2"` while Python
 *   `str(2.0) === "2.0"`, so a float-typed codebook key with a `.0` rendering
 *   cannot be reached from a JS number. Unreachable in practice — values
 *   arrive as option strings, which round-trip exactly.
 * - Date → not expected at runtime (options are strings); falls through to
 *   `String(v)`, whose rendering matches no Python-produced key — i.e. it
 *   matches nothing, the safe outcome.
 * - null/undefined → `String(v)` (`"null"`/`"undefined"`; codebooks only map
 *   non-null values, so these match nothing — correct).
 *
 * A serialized value with no codebook entry matches NOTHING — the engine
 * drops it from the translated code set (manifest.ts DataRef.codebooks
 * contract; server analogue: the failed value-cast drop in
 * _categorical_predicate:215).
 */
export function serializeOption(value: unknown): string {
  if (typeof value === 'string') return value;
  return String(value);
}
