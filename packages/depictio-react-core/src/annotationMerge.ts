/**
 * Applying a dropped file to session annotations, with the three modes of the
 * table editor's file merge (`TableMergePanel`): add columns, fill missing,
 * replace. Pure: the panel shows `report` before the reader applies `next`.
 * A drop applies to the labels of one table (`target`); labels of other
 * tables are kept, and a file column named like one of them is left out
 * (names are unique across tables).
 *
 * Every annotation a file writes into is marked `local`: its values came from
 * the file, so they stay in the browser until the reader keeps it on the account.
 */

import type { DropMatch } from './annotationInput';
import {
  type AnnotationColumn,
  type AnnotationTarget,
  type DashboardAnnotations,
  annotationsProblem,
  columnsFor,
  newAnnotationId,
} from './sessionAnnotations';

export type AnnotationMergeMode = 'add_columns' | 'fill_missing' | 'replace';

export interface AnnotationMergeReport {
  mode: AnnotationMergeMode;
  /** File columns that become new annotations. */
  newAnnotations: string[];
  /** Existing annotations the file writes into. */
  updatedAnnotations: string[];
  /** File columns this mode leaves out, with the reason shown to the reader. */
  ignored: { name: string; reason: string }[];
  /** Annotations dropped by `replace`. */
  removedAnnotations: string[];
  /** Labels written. */
  labels: number;
  /** `fill_missing`: labels the file has that differ from the one already set (kept). */
  conflicts: number;
  /** Why nothing can be applied, or null. */
  reason: string | null;
}

/** The mode a drop opens with: fill the annotations the file names when it names only those. */
export function suggestedMergeMode(
  current: DashboardAnnotations,
  target: AnnotationTarget,
  match: DropMatch,
): AnnotationMergeMode {
  const names = new Set(columnsFor(current, target).map((c) => c.name));
  return match.annotations.length > 0 && match.annotations.every((a) => names.has(a.name))
    ? 'fill_missing'
    : 'add_columns';
}

export function planAnnotationMerge(
  current: DashboardAnnotations,
  target: AnnotationTarget,
  match: DropMatch,
  mode: AnnotationMergeMode,
  makeId: () => string = newAnnotationId,
): { next: DashboardAnnotations; report: AnnotationMergeReport } {
  const report: AnnotationMergeReport = {
    mode,
    newAnnotations: [],
    updatedAnnotations: [],
    ignored: [],
    removedAnnotations: [],
    labels: 0,
    conflicts: 0,
    reason: null,
  };
  const fresh = (name: string, values: Record<string, string>): AnnotationColumn => ({
    id: makeId(),
    name,
    dcId: target.dcId,
    keyColumn: target.keyColumn,
    values: { ...values },
    local: true,
  });
  const mine = new Set(columnsFor(current, target).map((c) => c.id));
  const otherNames = new Set(current.columns.filter((c) => !mine.has(c.id)).map((c) => c.name));
  const fileColumns = match.annotations.filter((a) => {
    if (!otherNames.has(a.name)) return true;
    report.ignored.push({ name: a.name, reason: 'name used by labels of another table' });
    return false;
  });
  let columns: AnnotationColumn[];
  let activeColumnId = current.activeColumnId;

  if (mode === 'replace') {
    const replaced = current.columns.filter((c) => mine.has(c.id));
    const added = fileColumns.map((a) => fresh(a.name, a.values));
    columns = [...current.columns.filter((c) => !mine.has(c.id)), ...added];
    report.newAnnotations = fileColumns.map((a) => a.name);
    report.removedAnnotations = replaced.map((c) => c.name);
    report.labels = fileColumns.reduce((n, a) => n + Object.keys(a.values).length, 0);
    if (activeColumnId && mine.has(activeColumnId)) {
      // Keep comparing by the same name if the file brings it back.
      const activeName = replaced.find((c) => c.id === activeColumnId)?.name;
      activeColumnId = added.find((c) => c.name === activeName)?.id ?? null;
    }
  } else {
    columns = current.columns.map((c) => ({ ...c, values: { ...c.values } }));
    for (const a of fileColumns) {
      const existing = columns.find((c) => mine.has(c.id) && c.name === a.name);
      if (mode === 'add_columns') {
        if (existing) {
          report.ignored.push({ name: a.name, reason: 'already an annotation' });
          continue;
        }
        columns.push(fresh(a.name, a.values));
        report.newAnnotations.push(a.name);
        report.labels += Object.keys(a.values).length;
        continue;
      }
      // fill_missing
      if (!existing) {
        report.ignored.push({ name: a.name, reason: 'not an annotation yet' });
        continue;
      }
      let written = 0;
      for (const [key, label] of Object.entries(a.values)) {
        const had = existing.values[key];
        if (had === undefined) {
          existing.values[key] = label;
          written += 1;
        } else if (had !== label) {
          report.conflicts += 1;
        }
      }
      if (written > 0) {
        existing.local = true;
        report.updatedAnnotations.push(a.name);
        report.labels += written;
      }
    }
  }

  const next: DashboardAnnotations = { ...current, columns, activeColumnId };
  if (report.labels === 0 && report.removedAnnotations.length === 0) {
    report.reason =
      mode === 'add_columns'
        ? 'Every column of the file is already an annotation. Use Fill missing or Replace.'
        : mode === 'fill_missing'
          ? 'Nothing to fill: the file only has labels these annotations already hold, or names none of them.'
          : 'The file has no labels.';
  } else {
    report.reason = annotationsProblem(next);
  }
  return { next, report };
}
