/** Pure helpers of the "Add join" form: name rules, plain-language help per join
 *  type, the sentences describing rows that find no partner, and the default
 *  choice of tables and columns. Kept free of React so they are unit-tested. */

export type JoinHow = 'left' | 'inner' | 'outer' | 'right';

export const JOIN_NAME_MAX = 100;
const JOIN_NAME_PATTERN = /^[A-Za-z0-9_-]+$/;

export const JOIN_TYPE_OPTIONS: ReadonlyArray<{ value: JoinHow; label: string }> = [
  { value: 'left', label: 'Left' },
  { value: 'inner', label: 'Inner' },
  { value: 'outer', label: 'Outer' },
  { value: 'right', label: 'Right' },
];

export const JOIN_TYPE_HELP: Record<JoinHow, string> = {
  left: 'Keep every row of the left table and add the matching values of the right table. Rows without a match get empty values.',
  inner: 'Keep only the rows found in both tables.',
  outer: 'Keep every row of both tables, matched where possible.',
  right:
    'Keep every row of the right table and add the matching values of the left table.',
};

/** The tag of the table a join named `name` produces. */
export const joinResultTag = (name: string): string => `joined_${name.trim()}`;

/** Why `name` cannot name a join, or null when it can (an empty name is not
 *  reported as a problem: the form simply stays incomplete). */
export function validateJoinName(name: string): string | null {
  if (name === '') return null;
  if (name.length > JOIN_NAME_MAX) {
    return `Use at most ${JOIN_NAME_MAX} characters.`;
  }
  if (!JOIN_NAME_PATTERN.test(name)) {
    return /\s/.test(name)
      ? 'Spaces are not allowed: use only letters, digits, _ and -'
      : 'Use only letters, digits, _ and -';
  }
  return null;
}

/** Why a join cannot be created from `columns`, or null when it can. */
export const joinColumnsProblem = (columns: readonly string[]): string | null =>
  columns.length === 0 ? 'Pick at least one column to join on.' : null;

const sanitizeTag = (tag: string): string =>
  tag
    .replace(/[^A-Za-z0-9_-]+/g, '_')
    .replace(/_{2,}/g, '_')
    .replace(/^_+|_+$/g, '');

/** A valid, free join name derived from the two table tags: `<left>_<right>`,
 *  shortened to at most `JOIN_NAME_MAX` characters. A name is free when no join
 *  has it and no table is tagged `joined_<name>` (compared case-insensitively).
 *  Collisions get a `_2`, `_3`, ... suffix. Empty when a tag is missing. */
export function defaultJoinName(
  leftTag: string,
  rightTag: string,
  existing: { joinNames?: Iterable<string>; tags?: Iterable<string> } = {},
): string {
  if (!leftTag || !rightTag) return '';
  const joinNames = new Set([...(existing.joinNames ?? [])].map((n) => n.toLowerCase()));
  const tags = new Set([...(existing.tags ?? [])].map((t) => t.toLowerCase()));
  const taken = (n: string) =>
    joinNames.has(n.toLowerCase()) || tags.has(joinResultTag(n).toLowerCase());

  let left = sanitizeTag(leftTag) || 'left';
  let right = sanitizeTag(rightTag) || 'right';
  if (left.length + 1 + right.length > JOIN_NAME_MAX) {
    const half = Math.floor((JOIN_NAME_MAX - 1) / 2);
    left = left.slice(0, half);
    right = right.slice(0, JOIN_NAME_MAX - 1 - left.length);
  }
  const base = `${left}_${right}`;
  if (!taken(base)) return base;
  for (let i = 2; i < 10000; i += 1) {
    const suffix = `_${i}`;
    const candidate = `${base.slice(0, JOIN_NAME_MAX - suffix.length)}${suffix}`;
    if (!taken(candidate)) return candidate;
  }
  return base;
}

/** The text of an API failure, readable as is. Understands the shapes the
 *  server answers with: a string `detail`, `{code, message}`, a FastAPI
 *  validation list `[{loc, msg}]`, and an error whose message is the raw body
 *  (`409 {"detail": ...}`). Falls back to `fallback` when nothing is readable. */
export function readableApiError(
  err: unknown,
  fallback = 'Something went wrong. Try again.',
): string {
  const fromDetail = (d: unknown): string | null => {
    if (typeof d === 'string') return d.trim() || null;
    if (Array.isArray(d)) {
      const msgs = d
        .map((x) => {
          const m = (x as { msg?: unknown } | null)?.msg;
          return typeof m === 'string' ? m.replace(/^Value error,\s*/i, '').trim() : null;
        })
        .filter((m): m is string => !!m);
      return msgs.length > 0 ? msgs.join('; ') : null;
    }
    if (d && typeof d === 'object') {
      const o = d as { message?: unknown; detail?: unknown; msg?: unknown };
      if (typeof o.message === 'string' && o.message.trim()) return o.message.trim();
      if (typeof o.msg === 'string' && o.msg.trim()) return o.msg.trim();
      if (o.detail !== undefined) return fromDetail(o.detail);
    }
    return null;
  };
  const fromText = (t: string): string | null => {
    const text = t.trim();
    if (!text) return null;
    const start = text.search(/[{[]/);
    if (start >= 0) {
      try {
        const body = JSON.parse(text.slice(start)) as { detail?: unknown };
        const d = Array.isArray(body) ? fromDetail(body) : fromDetail(body?.detail ?? body);
        if (d) return d;
      } catch {
        // not JSON: show the text as is
      }
    }
    return text;
  };

  if (typeof err === 'string') return fromText(err) ?? fallback;
  if (err && typeof err === 'object') {
    const e = err as { detail?: unknown; message?: unknown };
    const d = fromDetail(e.detail);
    if (d) return d;
    if (typeof e.message === 'string') return fromText(e.message) ?? fallback;
  }
  return fallback;
}

export interface JoinRebuildOutcomeLike {
  join: string | null;
  status: 'rebuilt' | 'unchanged' | 'failed';
  error?: string;
  /** It had failed before: say it follows its sources again, rows changed or not. */
  recovered?: boolean;
}

/** The notification for a table write that finished (`done`, e.g. "Data
 *  replaced") given what it did to the joins reading the table. `color` is
 *  'yellow' when a join could not be rebuilt (the joined table is then stale),
 *  null otherwise: the caller keeps its own colour. */
export function joinRebuildNotice(
  done: string,
  joins?: readonly JoinRebuildOutcomeLike[] | null,
): { color: 'yellow' | null; message: string } {
  const list = joins ?? [];
  const failed = list.filter((j) => j.status === 'failed');
  const rebuilt = list.filter(
    (j) => j.status === 'rebuilt' || (j.status === 'unchanged' && j.recovered),
  );
  const base = done.replace(/[.\s]+$/, '');
  if (failed.length > 0) {
    const label = (j: JoinRebuildOutcomeLike) => `'${j.join ?? 'unnamed'}'`;
    if (failed.length === 1) {
      const f = failed[0];
      return {
        color: 'yellow',
        message: `${base}, but join ${label(f)} could not be rebuilt${f.error ? `: ${f.error}` : '.'}`,
      };
    }
    const detail = failed.map((f) => `${label(f)}${f.error ? ` (${f.error})` : ''}`).join(', ');
    return {
      color: 'yellow',
      message: `${base}, but ${failed.length} joins could not be rebuilt: ${detail}`,
    };
  }
  if (rebuilt.length > 0) {
    const names = rebuilt.map((j) => `'${j.join ?? 'unnamed'}'`).join(', ');
    return {
      color: null,
      message: `${base}. ${rebuilt.length === 1 ? 'Join' : 'Joins'} ${names} updated.`,
    };
  }
  return { color: null, message: done };
}

interface JoinDependency {
  name: string;
  left_dc_id?: string | null;
  right_dc_id?: string | null;
  result_tag?: string | null;
  result_dc_tag?: string | null;
}

/** The joins that read the table `dcId` (as left or right side). */
export const joinsReadingTable = <T extends JoinDependency>(
  joins: readonly T[],
  dcId: string,
): T[] => joins.filter((j) => j.left_dc_id === dcId || j.right_dc_id === dcId);

const quoteNames = (names: string[]) => names.map((n) => `'${n}'`).join(', ');

/** Warning shown before clearing a table that joins read. Null when none does. */
export function clearJoinsWarning(joins: readonly JoinDependency[]): string | null {
  if (joins.length === 0) return null;
  const results = joins.map((j) => j.result_tag || j.result_dc_tag || `joined_${j.name}`);
  return joins.length === 1
    ? `Join '${joins[0].name}' reads this table: after clearing, ${results[0]} is rebuilt with this side empty.`
    : `Joins ${quoteNames(joins.map((j) => j.name))} read this table: after clearing, ${results.join(', ')} are rebuilt with this side empty.`;
}

/** Why a table that joins read cannot be deleted yet. Null when none does. */
export function deleteJoinsBlock(joins: readonly JoinDependency[]): string | null {
  if (joins.length === 0) return null;
  return joins.length === 1
    ? `Join '${joins[0].name}' reads this table: delete the join first.`
    : `Joins ${quoteNames(joins.map((j) => j.name))} read this table: delete the joins first.`;
}

/** What the delete dialog of a joined table says: the join it comes from goes
 *  with it (the server removes it, or the next change of a source would write
 *  the table back). Null for a table no join produces. */
export function deleteJoinedTableNotice(
  joins: ReadonlyArray<{ name: string; result_dc_id?: string | null }>,
  dcId: string,
): string | null {
  const producer = joins.find((j) => j.result_dc_id === dcId);
  if (!producer) return null;
  return `This is the table of join '${producer.name}': the join is deleted too. Its sources stay.`;
}

/** What the "Delete join" dialog says about the dashboards using the joined
 *  table; null when none does (the dialog then keeps its generic text). */
export function joinDashboardsSentence(
  resultTag: string,
  dashboards?: ReadonlyArray<{ title: string }> | null,
): string | null {
  const list = dashboards ?? [];
  if (list.length === 0) return null;
  const n = list.length;
  return `Used by ${n} ${n === 1 ? 'dashboard' : 'dashboards'}: ${list
    .map((d) => d.title)
    .join(', ')}. ${n === 1 ? 'Its components' : 'Their components'} on ${resultTag} will show an error until a join of the same name is created again.`;
}

/** True when `name` is a usable, non-empty join name. */
export const isValidJoinName = (name: string): boolean =>
  name.length > 0 && validateJoinName(name) === null;

const rowsOf = (n: number, tag: string): string =>
  `${n} ${n === 1 ? 'row' : 'rows'} of ${tag}`;

export interface UnmatchedSide {
  tag: string;
  unmatched_rows: number;
}

/** What happens to the rows of each table that find no partner in the other,
 *  one sentence per side that has any. */
export function unmatchedSentences(
  how: JoinHow,
  left: UnmatchedSide,
  right: UnmatchedSide,
): string[] {
  const out: string[] = [];
  const side = (self: UnmatchedSide, other: UnmatchedSide, kept: boolean) => {
    if (self.unmatched_rows <= 0) return;
    const one = self.unmatched_rows === 1;
    const verb = one ? 'has' : 'have';
    if (kept) {
      out.push(
        `${rowsOf(self.unmatched_rows, self.tag)} ${verb} no match in ${other.tag}: ${one ? 'its' : 'their'} ${other.tag} columns stay empty.`,
      );
    } else {
      out.push(`${rowsOf(self.unmatched_rows, self.tag)} ${verb} no match: ${one ? 'it is' : 'they are'} left out.`);
    }
  };
  side(left, right, how === 'left' || how === 'outer');
  side(right, left, how === 'right' || how === 'outer');
  return out;
}

export interface JoinTableOption {
  id: string;
  tag: string;
  type: string;
}

/** The collections a join can combine: tables only. */
export const joinableTables = <T extends JoinTableOption>(dcs: T[]): T[] =>
  dcs.filter((d) => (d.type || '').toLowerCase() === 'table');

const OBJECT_ID = /^[0-9a-f]{24}$/i;

/** The tables oldest first. A collection id is a Mongo ObjectId, which starts
 *  with its creation time and ends with a counter, so the ids sort in the order
 *  the tables were added (uploads run one after the other). Ids of another
 *  shape keep their place in the list, after those. */
export function tablesByCreation<T extends { id: string }>(tables: readonly T[]): T[] {
  return tables
    .map((t, i) => ({ t, i }))
    .sort((a, b) => {
      const ka = OBJECT_ID.test(a.t.id) ? a.t.id.toLowerCase() : null;
      const kb = OBJECT_ID.test(b.t.id) ? b.t.id.toLowerCase() : null;
      if (ka && kb && ka !== kb) return ka < kb ? -1 : 1;
      if (ka && !kb) return -1;
      if (!ka && kb) return 1;
      return a.i - b.i;
    })
    .map(({ t }) => t);
}

/** What a fresh form starts from: a left join, no columns picked (the server
 *  suggests them once both tables are known), and the two tables of a link
 *  between tables, source on the left, since a link usually says which table
 *  describes the other. With several, the link whose source (then target) was
 *  added first. Without one, the two oldest tables, oldest on the left: the
 *  server then suggests the key from the columns they share. The same project
 *  always gives the same answer, whatever order its tables are listed in. */
export function defaultJoinSelection(
  tables: JoinTableOption[],
  links: ReadonlyArray<{ source_dc_id?: string; target_dc_id?: string }> = [],
): {
  leftId: string;
  rightId: string;
  how: JoinHow;
  onColumns: string[] | null;
} {
  const ordered = tablesByCreation(tables);
  const rank = new Map(ordered.map((t, i) => [t.id, i]));
  const link = links
    .filter(
      (l) =>
        l.source_dc_id &&
        l.target_dc_id &&
        l.source_dc_id !== l.target_dc_id &&
        rank.has(l.source_dc_id) &&
        rank.has(l.target_dc_id),
    )
    .sort(
      (a, b) =>
        (rank.get(a.source_dc_id as string) as number) -
          (rank.get(b.source_dc_id as string) as number) ||
        (rank.get(a.target_dc_id as string) as number) -
          (rank.get(b.target_dc_id as string) as number),
    )[0];
  if (link) {
    return {
      leftId: link.source_dc_id as string,
      rightId: link.target_dc_id as string,
      how: 'left',
      onColumns: null,
    };
  }
  return {
    leftId: ordered[0]?.id ?? '',
    rightId: ordered[1]?.id ?? '',
    how: 'left',
    onColumns: null,
  };
}

/** The right table's options: every table but the left one. */
export const rightTableOptions = <T extends JoinTableOption>(
  tables: T[],
  leftId: string,
): T[] => tables.filter((t) => t.id !== leftId);

/** The join columns in force: what the user picked (kept to the columns both
 *  tables share; an emptied pick stays empty), else, while the user has not
 *  picked (`picked` is null), what the server suggests, else what it used. */
export function effectiveOnColumns(
  picked: string[] | null,
  preview: {
    on_columns?: string[];
    suggested_on_columns?: string[];
    shared_columns?: string[];
  } | null,
): string[] {
  const shared = preview?.shared_columns;
  if (picked !== null) return picked.filter((c) => !shared || shared.includes(c));
  if (preview?.suggested_on_columns?.length) return preview.suggested_on_columns;
  return preview?.on_columns ?? [];
}

/** "<left>: N rows · <right>: M rows → joined: K rows · J columns". */
export function previewSummary(p: {
  left: { tag: string; rows: number };
  right: { tag: string; rows: number };
  joined_rows: number;
  joined_columns: string[];
}): string {
  const rows = (n: number) => `${n} ${n === 1 ? 'row' : 'rows'}`;
  const cols = p.joined_columns.length;
  return `${p.left.tag}: ${rows(p.left.rows)} · ${p.right.tag}: ${rows(p.right.rows)} → joined: ${rows(p.joined_rows)} · ${cols} ${cols === 1 ? 'column' : 'columns'}`;
}
