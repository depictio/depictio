/**
 * Selection groups derived from session annotations.
 *
 * For the active annotation, each distinct non-empty label becomes one group
 * `{name: label, dcId, columnName: keyColumn, values: keys}`, so the Analysis
 * panel filters, colours and splits by it like any other group. Derived groups
 * carry `annotationColumnId`; recomputing replaces exactly those and leaves
 * groups made by lasso or table selection alone. A label keeps its colour and
 * its filter toggle across recomputations.
 */

import {
  type AnnotationColumn,
  type DashboardAnnotations,
  MAX_SERVER_GROUPS,
} from './annotations';
import { TAB10_PALETTE } from './colors';
import { nextGroupColor, type SelectionGroup, uniqueGroupName } from './selectionGroups';

/** The server's name for rows in no group (`OTHER_LABEL`); a group may not take it. */
const OTHER_LABEL = 'Other';

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

/** Distinct labels of a column, in natural order. */
export function distinctLabels(column: AnnotationColumn): string[] {
  return [...new Set(Object.values(column.values).filter((v) => v !== ''))].sort(collator.compare);
}

export type Budget = { ok: true } | { ok: false; reason: string };

/** Whether a column can drive the comparison without the server dropping groups. */
export function annotationColumnBudget(
  column: AnnotationColumn,
  groups: SelectionGroup[],
): Budget {
  const labels = distinctLabels(column).length;
  if (labels === 0) return { ok: false, reason: 'This annotation has no labels yet.' };
  const others = groups.filter((g) => !g.annotationColumnId).length;
  if (labels + others > MAX_SERVER_GROUPS) {
    const room = MAX_SERVER_GROUPS - others;
    return {
      ok: false,
      reason:
        others > 0
          ? `Charts show at most ${MAX_SERVER_GROUPS} groups: this annotation has ${labels} labels and ${others} other groups exist, so it can have at most ${Math.max(room, 0)}.`
          : `Charts show at most ${MAX_SERVER_GROUPS} groups: this annotation has ${labels} labels.`,
    };
  }
  return { ok: true };
}

/**
 * The full group list once `annotations` are applied to `groups`.
 * Pure: `now` stamps groups that did not exist before.
 */
export function deriveAnnotationGroups(
  annotations: DashboardAnnotations | null,
  groups: SelectionGroup[],
  palette: readonly string[] = TAB10_PALETTE,
  now: number = Date.now(),
): SelectionGroup[] {
  const manual = groups.filter((g) => !g.annotationColumnId);
  const column = annotations?.columns.find((c) => c.id === annotations.activeColumnId);
  if (!annotations || !column || !annotationColumnBudget(column, manual).ok) return manual;

  const previous = new Map(
    groups
      .filter((g) => g.annotationColumnId === column.id)
      .map((g) => [g.annotationLabel ?? g.name, g] as const),
  );
  const keysByLabel = new Map<string, string[]>();
  for (const [key, label] of Object.entries(column.values)) {
    if (!label) continue;
    const keys = keysByLabel.get(label) ?? [];
    keys.push(key);
    keysByLabel.set(label, keys);
  }

  const out = [...manual];
  // A placeholder so no derived group is named like the server's "Other".
  const reserved = { id: '__other__', name: OTHER_LABEL } as SelectionGroup;
  for (const label of distinctLabels(column)) {
    const prev = previous.get(label);
    const values = (keysByLabel.get(label) ?? []).sort(collator.compare);
    out.push({
      id: prev?.id ?? `annotation:${column.id}:${label}`,
      name: uniqueGroupName(label, [...out, reserved]),
      color: prev?.color ?? nextGroupColor(out, palette),
      dcId: annotations.dcId,
      columnName: annotations.keyColumn,
      values,
      createdAt: prev?.createdAt ?? now,
      filterActive: prev?.filterActive ?? false,
      annotationColumnId: column.id,
      annotationLabel: label,
    });
  }
  return out;
}

/** Whether two group lists are the same, so a recomputation can keep the old array. */
export function sameGroups(a: SelectionGroup[], b: SelectionGroup[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((g, i) => {
    const h = b[i];
    return (
      g.id === h.id &&
      g.name === h.name &&
      g.color === h.color &&
      g.dcId === h.dcId &&
      g.columnName === h.columnName &&
      g.filterActive === h.filterActive &&
      g.annotationColumnId === h.annotationColumnId &&
      g.annotationLabel === h.annotationLabel &&
      g.values.length === h.values.length &&
      g.values.every((v, j) => v === h.values[j])
    );
  });
}
