/**
 * The record a card shows when no selection reaches it.
 *
 * `RecordCardConfig.default_record` names one value of `id_col`. It is the
 * card's opening state, not a selection: a real pick in a linked tile always
 * wins, and clearing that pick brings the default back. The echo line says
 * which of the two the reader is looking at, so a default card never reads as
 * the record somebody clicked.
 */

import type { InteractiveFilter } from '../../../api';
import type { RecordSelection } from './recordSelection';

export type RecordTarget =
  | { kind: 'selection'; selection: RecordSelection }
  | { kind: 'default'; column: string; value: string };

/** What the card follows: the selection when there is one, else the default. */
export function resolveRecordTarget(
  selection: RecordSelection | null,
  options: { idCol: string; defaultRecord?: string | null },
): RecordTarget | null {
  if (selection) return { kind: 'selection', selection };
  const value = options.defaultRecord == null ? '' : String(options.defaultRecord).trim();
  if (!value) return null;
  return { kind: 'default', column: options.idCol, value };
}

/** Column and values the loaded rows are narrowed against, client-side. */
export function targetMatch(
  target: RecordTarget | null,
): { column: string | null; values: string[]; ownCollection: boolean } | null {
  if (!target) return null;
  if (target.kind === 'default') {
    return { column: target.column, values: [target.value], ownCollection: true };
  }
  return target.selection;
}

/**
 * An equality filter on `id_col` for the default record. It carries no
 * `source`, so it is never mistaken for a reader's pick, and it is only ever
 * sent with the card's own fetch: it never reaches the dashboard's filters.
 */
export function defaultRecordFilter(
  index: string,
  dcId: string | undefined,
  column: string,
  value: string,
): InteractiveFilter {
  return {
    index: `${index}::default_record`,
    value: [value],
    column_name: column,
    interactive_component_type: 'MultiSelect',
    metadata: {
      dc_id: dcId,
      column_name: column,
      interactive_component_type: 'MultiSelect',
    },
  };
}

/** Echo line: `default: <value>` or `selected: N`. */
export function recordEcho(target: RecordTarget | null, recordCount: number | null): string | undefined {
  if (!target) return undefined;
  if (target.kind === 'default') return `default: ${target.value}`;
  const n = recordCount ?? target.selection.values.length;
  return `selected: ${n}`;
}

/**
 * The id of the best row for `default_record_by`: the highest value of `byCol`
 * (the lowest when `ascending`), nulls and non-numbers skipped. Ties keep the
 * first row. Null when no row has a value.
 */
export function bestRecordId(
  rows: Record<string, unknown[]> | null | undefined,
  idCol: string,
  byCol: string,
  ascending = false,
): string | null {
  const ids = rows?.[idCol];
  const values = rows?.[byCol];
  if (!ids || !values) return null;
  let best: number | null = null;
  let bestId: string | null = null;
  for (let i = 0; i < ids.length; i++) {
    const v = values[i];
    const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() ? Number(v) : NaN;
    if (!Number.isFinite(n) || ids[i] == null) continue;
    if (best === null || (ascending ? n < best : n > best)) {
      best = n;
      bestId = String(ids[i]);
    }
  }
  return bestId;
}
