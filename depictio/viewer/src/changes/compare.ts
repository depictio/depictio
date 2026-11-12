/**
 * What the side-by-side "Before | Now" view asks for, and the rows it lists
 * under the two panes (#1397).
 *
 * Pure and free of React so `pnpm run check:changes` can run the real code.
 * Type imports only from the shared package: this module must stay loadable
 * on its own.
 *
 * The "Before" pane is the same component drawn through the reader's earlier
 * dashboard version (its definition) and the data collection's Delta commit at
 * their last visit (its data). Nothing here writes: both are request fields
 * the render endpoints already take (`definition_version`, `data_versions`,
 * `as_of_version`).
 */
import type { ComponentDiff, DataVersionState, DiffPoint } from 'depictio-react-core';

export type BeforePane =
  | {
      kind: 'render';
      /** The version fields for the `DataVersionProvider` around the Before pane. */
      state: DataVersionState;
      /** A caveat shown under the pane heading, when the pin is approximate. */
      note?: string;
    }
  | { kind: 'unavailable'; note: string };

const hasDelta = (diff: ComponentDiff | null | undefined): diff is ComponentDiff & { delta_from: number } =>
  !!diff && typeof diff.delta_from === 'number';

/**
 * How to draw the Before pane of one component.
 *
 *  - figure, table, map, image: the definition of the baseline version and the
 *    collection pinned to the Delta commit the diff compared from. Without that
 *    commit (the diff is unsupported, or the component is a card), the baseline
 *    version's own data stamps are followed instead.
 *  - MultiQC: the report set of the reader's mark (`report_ids_before`, the
 *    reports they saw that still exist) as `report_sets`. A dashboard version
 *    may have been saved before those reports existed, so its stamps are only
 *    the fallback for a diff that carries no report ids.
 *  - advanced viz: its renderers fetch their data without a version, so the
 *    pane is not drawn; the rows table below says what changed.
 */
export function beforePane(
  componentType: string | undefined,
  dcId: string | null | undefined,
  diff: ComponentDiff | null | undefined,
  baselineVersionId: string | null | undefined,
): BeforePane {
  if (componentType === 'advanced_viz') {
    return {
      kind: 'unavailable',
      note: 'The earlier data of this visualisation cannot be redrawn here. The rows that changed are listed below.',
    };
  }
  const definitionVersionId = baselineVersionId || null;
  if (componentType !== 'multiqc' && dcId && hasDelta(diff)) {
    return {
      kind: 'render',
      state: { pins: { [dcId]: diff.delta_from }, definitionVersionId },
    };
  }
  if (
    componentType === 'multiqc' &&
    dcId &&
    diff?.supported &&
    diff.shape === 'samples' &&
    Array.isArray(diff.report_ids_before) &&
    diff.report_ids_before.length > 0
  ) {
    return {
      kind: 'render',
      state: { reportSets: { [dcId]: diff.report_ids_before }, definitionVersionId },
      note: 'The reports you saw at your last visit.',
    };
  }
  if (!definitionVersionId) {
    return {
      kind: 'unavailable',
      note: 'No earlier version of this dashboard is stored for your last visit.',
    };
  }
  return {
    kind: 'render',
    state: { asOfVersionId: definitionVersionId, definitionVersionId },
    note:
      componentType === 'multiqc'
        ? 'The reports shown follow the dashboard version of your last visit.'
        : 'The data shown follows the dashboard version of your last visit.',
  };
}

/** The Now pane reads the live document and the latest data. */
export const NOW_STATE: DataVersionState = {};

export const MAX_TABLE_ROWS = 50;

export interface DiffTableSection {
  id: 'added' | 'removed' | 'changed';
  title: string;
  columns: string[];
  rows: string[][];
  /** Rows beyond the first `MAX_TABLE_ROWS`. */
  more: number;
}

const show = (v: unknown): string => {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') return String(Math.round(v * 1000) / 1000);
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
};

const change = (before: unknown, after: unknown): string =>
  show(before) === show(after) ? show(after) : `${show(before)} → ${show(after)}`;

function section(
  id: DiffTableSection['id'],
  title: string,
  columns: string[],
  rows: string[][],
  limit: number,
): DiffTableSection | null {
  if (rows.length === 0) return null;
  return { id, title, columns, rows: rows.slice(0, limit), more: Math.max(0, rows.length - limit) };
}

/** The keys behind the counts, as compact tables (first `limit` rows each). */
export function diffTables(
  diff: ComponentDiff | null | undefined,
  limit: number = MAX_TABLE_ROWS,
): DiffTableSection[] {
  if (!diff || diff.supported === false) return [];
  const out: Array<DiffTableSection | null> = [];
  switch (diff.shape) {
    case 'points': {
      // Lead with the key; without one, with the colour column (an unkeyed
      // point is only its values), else with x and y alone.
      const lead = diff.key_column ?? diff.color;
      const head = (p: DiffPoint) => (diff.key_column ? [show(p.key)] : diff.color ? [show(p.color)] : []);
      const cols = [...(lead ? [lead] : []), diff.x, diff.y];
      const pointRow = (p: DiffPoint) => [...head(p), show(p.x), show(p.y)];
      out.push(
        section('added', 'New', cols, diff.added.map(pointRow), limit),
        section('removed', 'Gone', cols, diff.removed.map(pointRow), limit),
        section(
          'changed',
          'Moved',
          cols,
          diff.changed.map((m) => [
            ...head(m.after),
            change(m.before.x, m.after.x),
            change(m.before.y, m.after.y),
          ]),
          limit,
        ),
      );
      break;
    }
    case 'groups': {
      const cols = [...diff.group_columns, 'Before', 'After'];
      const row = (g: (typeof diff.groups)[number]) => [
        ...diff.group_columns.map((c) => show(g.group[c])),
        show(g.before),
        show(g.after),
      ];
      out.push(
        section('added', 'New', cols, diff.groups.filter((g) => g.status === 'added').map(row), limit),
        section('removed', 'Gone', cols, diff.groups.filter((g) => g.status === 'removed').map(row), limit),
        section('changed', 'Changed', cols, diff.groups.filter((g) => g.status === 'changed').map(row), limit),
      );
      break;
    }
    case 'samples': {
      out.push(
        section('added', 'New samples', ['Sample'], diff.added.map((s) => [s]), limit),
        section('removed', 'Samples gone', ['Sample'], diff.removed.map((s) => [s]), limit),
      );
      break;
    }
    case 'rows': {
      const cols = [diff.key_column || 'Row', ...diff.value_columns];
      const rowOf = (r: { key: string | null; values: Record<string, unknown> }) => [
        show(r.key),
        ...diff.value_columns.map((c) => show(r.values[c])),
      ];
      out.push(
        section('added', 'New', cols, diff.added.map(rowOf), limit),
        section('removed', 'Gone', cols, diff.removed.map(rowOf), limit),
        section(
          'changed',
          'Changed',
          cols,
          diff.changed.map((r) => [
            show(r.key),
            ...diff.value_columns.map((c) => change(r.before[c], r.after[c])),
          ]),
          limit,
        ),
      );
      break;
    }
  }
  return out.filter((s): s is DiffTableSection => s !== null);
}
