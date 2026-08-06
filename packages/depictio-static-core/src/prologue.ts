/**
 * In-browser prologue interpreter (RFC phase 6) — execute a component's closed
 * JSON IR (filter / unpivot / group_by / sort / rename) over materialized
 * column arrays with pinned Polars semantics.
 *
 * The Python transpiler emits `manifest.prologues[componentId]`; this module
 * replays it. Polars 1.42.1 (the repo pin) is the authority — every rule below
 * was verified empirically (see also scripts/generate_fixture.py's sibling,
 * the prologue differential fixture, which is the cross-language arbiter):
 *
 *   filter — three-valued logic. A `cmp` involving a null cell (or a null
 *     literal) is null; and/or/not are Kleene (null AND false = false,
 *     null OR true = true, NOT null = null); a row passes only when the tree
 *     is strictly TRUE. NaN follows Polars' TOTAL float ordering, NOT IEEE:
 *     NaN is the greatest float (NaN > +inf is true, NaN <= x is false for
 *     any non-NaN x, x <= NaN is true) and NaN == NaN is TRUE — all verified
 *     on 1.42.1; `comparePolars` already encodes exactly this order.
 *     `is_in` propagates null: a null cell yields null (never a match), EVEN
 *     when the values list contains null (verified: [1,None].is_in([1,None])
 *     → [true, null]).
 *
 *   group_by — maintain_order=True first-appearance group order; a null key
 *     forms its own group; NaN keys group together (NaN == NaN for grouping);
 *     composite keys compare element-wise with null == null. Output columns:
 *     `by` columns first (first-occurrence cell values), then one column per
 *     agg in spec order. Per-group aggs delegate to the SAME scalar kernel
 *     the engine's aggregate() uses (engine/aggregate.ts) — identical traps
 *     (std/var ddof=1 & n<2 → null, count=non-null, nunique counts null,
 *     median interpolates, first/last positional, all-null numeric sum → 0).
 *     `len` is the one fn the kernel does not own: it is the GROUP SIZE (row
 *     count, nulls included, mask-independent), so it is counted here directly.
 *     Its `col` is null for the bare spellings (`pl.len()` / `pl.count()`) and
 *     set for `pl.col(c).len()`, where polars still ignores c's values but
 *     names the output after it and raises when it is missing — so a present
 *     `col` is still required to exist.
 *
 *   unpivot — one block per `on` column in `on` order; original row order
 *     within a block; `index` columns repeated per block; output column order
 *     is [index..., variable, value]; `variable` holds the source column NAME.
 *
 *   sort — pl.DataFrame.sort(by, descending=desc, maintain_order=True): nulls
 *     FIRST in BOTH directions (nulls_last=False is the Polars default; null
 *     placement is not reversed by descending — verified: sort desc of
 *     [2,None,1] is [None,2,1]); NaN is the greatest float and DOES participate
 *     in direction reversal; STABLE — input order preserved on full ties.
 *     Stability is a pinned choice, not a Polars default: `maintain_order` is
 *     False there, so the build side sets it explicitly (prologue_exec.py) to
 *     answer the same way twice, and this interpreter tie-breaks on the input
 *     index to answer the same way as the build side.
 *
 *   rename — every map key must exist (polars raises ColumnNotFoundError);
 *     renaming keeps each column's position; a resulting duplicate name is an
 *     error (polars DuplicateError).
 *
 * Any malformed op, unknown fn, or missing column THROWS a descriptive Error:
 * the caller treats a throw as structural degradation of the component to its
 * frozen payload.
 */

import { aggregateValues, stringifyValue } from './engine/aggregate';
import { comparePolars } from './engine/sortSlice';
import type { CmpOp, Pred, PrologueAgg, PrologueAggFn, PrologueOp, PrologueScalar } from './manifest';

/** Materialized column data: every array has exactly `length` entries. */
export interface ColumnTable {
  columns: Record<string, unknown[]>;
  length: number;
}

const AGG_FNS: ReadonlySet<string> = new Set<PrologueAggFn>([
  'sum',
  'mean',
  'median',
  'min',
  'max',
  'count',
  'len',
  'nunique',
  'std',
  'var',
  'first',
  'last',
]);

const CMP_OPS: ReadonlySet<string> = new Set<CmpOp>(['<', '<=', '>', '>=', '==', '!=']);

/**
 * Run a prologue over a column table. Pure: the input table (and its arrays)
 * is never mutated; each op produces a fresh table. Throws on any malformed
 * op / unknown fn / missing column (see module doc).
 */
export function runPrologue(ops: PrologueOp[], table: ColumnTable): ColumnTable {
  if (!Array.isArray(ops)) {
    throw new Error('prologue: ops must be an array');
  }
  validateTable(table);
  let t = table;
  for (let i = 0; i < ops.length; i++) {
    t = applyOp(ops[i], t, i);
  }
  return t;
}

function validateTable(table: ColumnTable): void {
  if (
    typeof table !== 'object' ||
    table === null ||
    typeof table.length !== 'number' ||
    typeof table.columns !== 'object' ||
    table.columns === null
  ) {
    throw new Error('prologue: input is not a ColumnTable');
  }
  for (const [name, values] of Object.entries(table.columns)) {
    if (!Array.isArray(values)) {
      throw new Error(`prologue: column "${name}" is not an array`);
    }
    if (values.length !== table.length) {
      throw new Error(
        `prologue: column "${name}" has ${values.length} values but table.length is ${table.length}`,
      );
    }
  }
}

function applyOp(op: PrologueOp, t: ColumnTable, i: number): ColumnTable {
  if (typeof op !== 'object' || op === null || typeof (op as { op?: unknown }).op !== 'string') {
    throw new Error(`prologue: op[${i}] is not an object with an "op" field`);
  }
  const where = `op[${i}] ${op.op}`;
  switch (op.op) {
    case 'filter':
      return opFilter(op, t, where);
    case 'unpivot':
      return opUnpivot(op, t, where);
    case 'group_by':
      return opGroupBy(op, t, where);
    case 'sort':
      return opSort(op, t, where);
    case 'rename':
      return opRename(op, t, where);
    default:
      throw new Error(`prologue: op[${i}] has unknown op "${(op as { op: string }).op}"`);
  }
}

// ---------------------------------------------------------------------------
// filter
// ---------------------------------------------------------------------------

/** Kleene truth value: true / false / null (missing). */
type K = boolean | null;

function opFilter(op: Extract<PrologueOp, { op: 'filter' }>, t: ColumnTable, where: string): ColumnTable {
  if (op.pred === undefined) throw new Error(`prologue: ${where} is missing "pred"`);
  const pred = compilePred(op.pred, t, where);
  const keep: number[] = [];
  for (let i = 0; i < t.length; i++) {
    if (pred(i) === true) keep.push(i); // strictly true — null fails the row
  }
  return gatherRows(t, keep);
}

function compilePred(pred: Pred, t: ColumnTable, where: string): (i: number) => K {
  if (typeof pred !== 'object' || pred === null) {
    throw new Error(`prologue: ${where} has a non-object predicate node`);
  }
  const keys = Object.keys(pred);
  if (keys.length !== 1) {
    throw new Error(
      `prologue: ${where} predicate node must have exactly one key, got [${keys.join(', ')}]`,
    );
  }
  const kind = keys[0];
  switch (kind) {
    case 'and':
    case 'or': {
      const children = (pred as { and?: Pred[]; or?: Pred[] })[kind];
      if (!Array.isArray(children)) {
        throw new Error(`prologue: ${where} "${kind}" must hold an array of predicates`);
      }
      const fns = children.map((c) => compilePred(c, t, where));
      if (kind === 'and') {
        // Kleene AND: any false → false; else any null → null; else true.
        return (i) => {
          let sawNull = false;
          for (const f of fns) {
            const r = f(i);
            if (r === false) return false;
            if (r === null) sawNull = true;
          }
          return sawNull ? null : true;
        };
      }
      // Kleene OR: any true → true; else any null → null; else false.
      return (i) => {
        let sawNull = false;
        for (const f of fns) {
          const r = f(i);
          if (r === true) return true;
          if (r === null) sawNull = true;
        }
        return sawNull ? null : false;
      };
    }
    case 'not': {
      const f = compilePred((pred as { not: Pred }).not, t, where);
      return (i) => {
        const r = f(i);
        return r === null ? null : !r; // NOT null = null
      };
    }
    case 'cmp': {
      const c = (pred as { cmp: { col: string; op: CmpOp; value: PrologueScalar } }).cmp;
      if (typeof c !== 'object' || c === null || typeof c.col !== 'string') {
        throw new Error(`prologue: ${where} "cmp" must be {col, op, value}`);
      }
      if (!CMP_OPS.has(c.op)) {
        throw new Error(`prologue: ${where} cmp has unknown operator "${String(c.op)}"`);
      }
      if (c.value !== null && !isScalar(c.value)) {
        throw new Error(`prologue: ${where} cmp value must be a JSON scalar`);
      }
      const values = requireColumn(t, c.col, where);
      const op2 = c.op;
      const target = c.value;
      return (i) => {
        const v = values[i];
        // Polars: any comparison involving null is null (a null literal too —
        // "Comparisons with None always result in null").
        if (v === null || v === undefined || target === null) return null;
        const cRel = compareCells(v, target, c.col, where);
        switch (op2) {
          case '<':
            return cRel < 0;
          case '<=':
            return cRel <= 0;
          case '>':
            return cRel > 0;
          case '>=':
            return cRel >= 0;
          case '==':
            return cRel === 0;
          case '!=':
            return cRel !== 0;
        }
      };
    }
    case 'is_null':
    case 'is_not_null': {
      const node = (pred as Record<string, { col?: unknown }>)[kind];
      if (typeof node !== 'object' || node === null || typeof node.col !== 'string') {
        throw new Error(`prologue: ${where} "${kind}" must be {col}`);
      }
      const values = requireColumn(t, node.col, where);
      const wantNull = kind === 'is_null';
      // is_null/is_not_null are never null themselves.
      return (i) => {
        const isNull = values[i] === null || values[i] === undefined;
        return isNull === wantNull;
      };
    }
    case 'is_in': {
      const node = (pred as { is_in: { col: string; values: PrologueScalar[] } }).is_in;
      if (
        typeof node !== 'object' ||
        node === null ||
        typeof node.col !== 'string' ||
        !Array.isArray(node.values)
      ) {
        throw new Error(`prologue: ${where} "is_in" must be {col, values[]}`);
      }
      const values = requireColumn(t, node.col, where);
      const set = new Set<string>();
      for (const v of node.values) {
        if (v === null) continue; // a null LIST entry never matches anything
        if (!isScalar(v)) {
          throw new Error(`prologue: ${where} is_in values must be JSON scalars`);
        }
        set.add(membershipKey(v));
      }
      return (i) => {
        const v = values[i];
        // Polars is_in propagates null: null cell → null, even when the list
        // contains null (verified on 1.42.1).
        if (v === null || v === undefined) return null;
        return set.has(membershipKey(v));
      };
    }
    default:
      throw new Error(`prologue: ${where} has unknown predicate kind "${kind}"`);
  }
}

/**
 * Three-way compare a non-null cell against a non-null JSON scalar, in
 * Polars' per-dtype order (comparePolars: numeric with NaN as the GREATEST
 * float — which also makes NaN == NaN true, matching Polars float equality;
 * strings by code point; false < true). Cross-dtype comparisons that Polars
 * would raise on (e.g. a string column vs a number literal) throw.
 */
function compareCells(v: unknown, target: string | number | boolean, col: string, where: string): number {
  const vNum = typeof v === 'number' || typeof v === 'bigint';
  if (vNum && typeof target === 'number') return comparePolars(v, target);
  if (typeof v === 'string' && typeof target === 'string') return comparePolars(v, target);
  if (typeof v === 'boolean' && typeof target === 'boolean') return comparePolars(v, target);
  throw new Error(
    `prologue: ${where} cmp on column "${col}" compares incompatible types ` +
      `(${typeof v} cell vs ${typeof target} literal)`,
  );
}

/**
 * Canonical, type-tagged membership key for `is_in`: bigint 5n and number 5
 * meet on "n:5" (same column dtype across JSON and decoded Parquet), but no
 * cross-dtype match ever happens (string "5" ≠ number 5, like Polars).
 */
function membershipKey(v: unknown): string {
  if (typeof v === 'bigint') return 'n:' + v.toString();
  if (typeof v === 'number') return 'n:' + String(v); // String(5.0) === "5"
  if (typeof v === 'boolean') return 'b:' + String(v);
  if (typeof v === 'string') return 's:' + v;
  return 'x:' + stringifyValue(v); // Dates etc. — self-consistent fallback
}

function isScalar(v: unknown): v is string | number | boolean {
  return typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean';
}

// ---------------------------------------------------------------------------
// unpivot
// ---------------------------------------------------------------------------

function opUnpivot(
  op: Extract<PrologueOp, { op: 'unpivot' }>,
  t: ColumnTable,
  where: string,
): ColumnTable {
  const { on, index, variable, value } = op;
  if (!Array.isArray(on) || !on.every((c) => typeof c === 'string')) {
    throw new Error(`prologue: ${where} "on" must be an array of column names`);
  }
  if (!Array.isArray(index) || !index.every((c) => typeof c === 'string')) {
    throw new Error(`prologue: ${where} "index" must be an array of column names`);
  }
  if (typeof variable !== 'string' || variable.length === 0) {
    throw new Error(`prologue: ${where} "variable" must be a non-empty string`);
  }
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`prologue: ${where} "value" must be a non-empty string`);
  }
  for (const c of [...on, ...index]) requireColumn(t, c, where);
  const outNames = [...index, variable, value];
  assertNoDuplicates(outNames, where);

  // One block per `on` column, in `on` order; original row order within.
  const outLength = on.length * t.length;
  const columns: Record<string, unknown[]> = {};
  for (const idxCol of index) {
    const src = t.columns[idxCol];
    const out: unknown[] = new Array(outLength);
    let k = 0;
    for (let b = 0; b < on.length; b++) {
      for (let i = 0; i < t.length; i++) out[k++] = src[i];
    }
    columns[idxCol] = out;
  }
  const varOut: unknown[] = new Array(outLength);
  const valOut: unknown[] = new Array(outLength);
  let k = 0;
  for (const onCol of on) {
    const src = t.columns[onCol];
    for (let i = 0; i < t.length; i++) {
      varOut[k] = onCol; // the source column's NAME
      valOut[k] = src[i];
      k++;
    }
  }
  columns[variable] = varOut;
  columns[value] = valOut;
  return { columns, length: outLength };
}

// ---------------------------------------------------------------------------
// group_by
// ---------------------------------------------------------------------------

function opGroupBy(
  op: Extract<PrologueOp, { op: 'group_by' }>,
  t: ColumnTable,
  where: string,
): ColumnTable {
  const { by, agg } = op;
  if (!Array.isArray(by) || by.length === 0 || !by.every((c) => typeof c === 'string')) {
    throw new Error(`prologue: ${where} "by" must be a non-empty array of column names`);
  }
  if (!Array.isArray(agg)) {
    throw new Error(`prologue: ${where} "agg" must be an array of {col, fn, alias}`);
  }
  for (const entry of agg) {
    const spec = entry as { col?: unknown; fn?: unknown; alias?: unknown } | null;
    if (
      typeof spec !== 'object' ||
      spec === null ||
      typeof spec.fn !== 'string' ||
      typeof spec.alias !== 'string' ||
      spec.alias.length === 0
    ) {
      throw new Error(`prologue: ${where} agg entries must be {col, fn, alias}`);
    }
    if (!AGG_FNS.has(spec.fn)) {
      throw new Error(`prologue: ${where} has unknown agg fn "${spec.fn}"`);
    }
    // `col` is optional ONLY for the bare `len` spellings (group size).
    if (spec.col === null || spec.col === undefined) {
      if (spec.fn !== 'len') {
        throw new Error(`prologue: ${where} agg fn "${spec.fn}" needs a source column`);
      }
      continue;
    }
    if (typeof spec.col !== 'string') {
      throw new Error(`prologue: ${where} agg entries must be {col, fn, alias}`);
    }
    // Present even for `pl.col(c).len()`: polars ignores c's values but still
    // raises ColumnNotFoundError when c is missing.
    requireColumn(t, spec.col, where);
  }
  const byCols = by.map((c) => requireColumn(t, c, where));
  assertNoDuplicates([...by, ...agg.map((a) => a.alias)], where);

  // First-appearance group order (maintain_order=True). Null keys form their
  // own group; NaN keys group together; composite keys compare element-wise.
  const groups = new Map<string, number[]>();
  for (let i = 0; i < t.length; i++) {
    let key = '';
    for (const col of byCols) {
      const cell = groupKeyCell(col[i]);
      // Length-prefixed so a delimiter-looking substring inside a string cell
      // can never collide with a composite-key boundary.
      key += String(cell.length) + '\x1f' + cell;
    }
    const rows = groups.get(key);
    if (rows) rows.push(i);
    else groups.set(key, [i]);
  }

  const columns: Record<string, unknown[]> = {};
  const groupRows = [...groups.values()];
  for (let b = 0; b < by.length; b++) {
    columns[by[b]] = groupRows.map((rows) => byCols[b][rows[0]] ?? null);
  }
  for (const spec of agg) {
    if (spec.fn === 'len') {
      // GROUP SIZE — mask-independent, nulls included; `col` (when present) is
      // only a naming/existence anchor, never read.
      columns[spec.alias] = groupRows.map((rows) => rows.length);
      continue;
    }
    const src = t.columns[spec.col];
    const numeric = inferNumericColumn(src);
    columns[spec.alias] = groupRows.map((rows) => {
      // Gather preserves row order, so first/last stay positional.
      const values = rows.map((r) => src[r]);
      return aggregateValues(values, null, spec.fn, numeric);
    });
  }
  return { columns, length: groups.size };
}

/** Grouping key for one cell: null == null, NaN == NaN, type-tagged. */
function groupKeyCell(v: unknown): string {
  if (v === null || v === undefined) return '\x00';
  if (typeof v === 'number') return Number.isNaN(v) ? 'n:NaN' : 'n:' + String(v);
  if (typeof v === 'bigint') return 'n:' + v.toString();
  if (typeof v === 'boolean') return 'b:' + String(v);
  if (typeof v === 'string') return 's:' + v;
  if (v instanceof Date) return 'd:' + String(v.getTime());
  return 'x:' + stringifyValue(v);
}

/**
 * The prologue has no DataRef dtypes, so numeric-ness (the agg kernel's sum /
 * mean gate) is inferred from the data: numeric when the first non-null value
 * is a number/bigint; an all-null column counts as numeric (a bundled numeric
 * column keeps its dtype when fully null, and the kernel then pins sum → 0,
 * everything else → null — Polars' behavior for an all-null numeric group).
 */
function inferNumericColumn(values: unknown[]): boolean {
  for (const v of values) {
    if (v === null || v === undefined) continue;
    return typeof v === 'number' || typeof v === 'bigint';
  }
  return true;
}

// ---------------------------------------------------------------------------
// sort
// ---------------------------------------------------------------------------

function opSort(op: Extract<PrologueOp, { op: 'sort' }>, t: ColumnTable, where: string): ColumnTable {
  const { by } = op;
  if (!Array.isArray(by) || by.length === 0 || !by.every((c) => typeof c === 'string')) {
    throw new Error(`prologue: ${where} "by" must be a non-empty array of column names`);
  }
  // descending=False is the pl.DataFrame.sort default; when given, desc must
  // pair up with `by` (the IR always emits matching arrays).
  const desc = op.desc === undefined ? by.map(() => false) : op.desc;
  if (!Array.isArray(desc) || desc.length !== by.length || !desc.every((d) => typeof d === 'boolean')) {
    throw new Error(`prologue: ${where} "desc" must be a boolean array matching "by"`);
  }
  const keys = by.map((c, k) => ({ values: requireColumn(t, c, where), desc: desc[k] }));

  const idx: number[] = new Array(t.length);
  for (let i = 0; i < t.length; i++) idx[i] = i;
  idx.sort((a, b) => {
    for (const key of keys) {
      const va = key.values[a] ?? null;
      const vb = key.values[b] ?? null;
      // Polars sort default (nulls_last=False): nulls FIRST in BOTH
      // directions — null placement is NOT reversed by descending (verified:
      // sort desc of [2, None, 1] is [None, 2, 1]).
      if (va === null || vb === null) {
        if (va === null && vb === null) continue;
        return va === null ? -1 : 1;
      }
      // NaN (greatest float, inside comparePolars) DOES reverse with desc.
      const c = comparePolars(va, vb);
      if (c !== 0) return key.desc ? -c : c;
    }
    // Full tie: stable — preserve input order.
    return a - b;
  });
  return gatherRows(t, idx);
}

// ---------------------------------------------------------------------------
// rename
// ---------------------------------------------------------------------------

function opRename(op: Extract<PrologueOp, { op: 'rename' }>, t: ColumnTable, where: string): ColumnTable {
  const { map } = op;
  if (typeof map !== 'object' || map === null || Array.isArray(map)) {
    throw new Error(`prologue: ${where} "map" must be an object of {old: new}`);
  }
  for (const [oldName, newName] of Object.entries(map)) {
    if (!(oldName in t.columns)) {
      // Polars raises ColumnNotFoundError on a missing rename key.
      throw new Error(`prologue: ${where} renames missing column "${oldName}"`);
    }
    if (typeof newName !== 'string' || newName.length === 0) {
      throw new Error(`prologue: ${where} renames "${oldName}" to a non-string/empty name`);
    }
  }
  // Renaming keeps each column's position; duplicates in the result are an
  // error (polars DuplicateError).
  const names = Object.keys(t.columns).map((n) => (n in map ? map[n] : n));
  assertNoDuplicates(names, where);
  const columns: Record<string, unknown[]> = {};
  let k = 0;
  for (const oldName of Object.keys(t.columns)) {
    columns[names[k++]] = t.columns[oldName];
  }
  return { columns, length: t.length };
}

// ---------------------------------------------------------------------------
// shared helpers
// ---------------------------------------------------------------------------

function requireColumn(t: ColumnTable, name: string, where: string): unknown[] {
  const values = t.columns[name];
  if (values === undefined) {
    throw new Error(`prologue: ${where} references missing column "${name}"`);
  }
  return values;
}

function assertNoDuplicates(names: string[], where: string): void {
  const seen = new Set<string>();
  for (const n of names) {
    if (seen.has(n)) {
      throw new Error(`prologue: ${where} would produce duplicate column "${n}"`);
    }
    seen.add(n);
  }
}

/** Project the given row indices into a fresh table (columns in place). */
function gatherRows(t: ColumnTable, idx: number[]): ColumnTable {
  const columns: Record<string, unknown[]> = {};
  for (const [name, src] of Object.entries(t.columns)) {
    const out: unknown[] = new Array(idx.length);
    for (let k = 0; k < idx.length; k++) out[k] = src[idx[k]];
    columns[name] = out;
  }
  return { columns, length: idx.length };
}
