/**
 * Row highlighting for table annotations. A table only takes "points"
 * annotations keyed by its row-id column (`MarkedPoints {column, ids}`); each
 * marked row gets a coloured stripe + tint and a numbered badge. Pure helpers,
 * no React / AG Grid: TableRenderer maps the result onto row classes.
 */
import type { AnnotationColor, MarkedPoints, RenderableAnnotation } from './types';
import { ANNOTATION_COLORS, MAX_POINT_IDS, numberBadge } from './types';

/** Colour the backend stores when an annotation has none. */
export const DEFAULT_ROW_ANNOTATION_COLOR: AnnotationColor = 'yellow';

export interface RowAnnotationMark {
  /** Thread id of the annotation that styles the row. */
  id: string;
  color: AnnotationColor;
  number: number | null;
  /** The styling annotation is the one focused in the comments drawer. */
  highlighted: boolean;
  /** Badge numbers of every annotation covering the row, ascending. */
  numbers: number[];
}

/** Row id (stringified row-id column value) → how the row is marked. */
export type RowAnnotationMap = Map<string, RowAnnotationMark>;

/** Whether a table annotation applies to rows keyed by `rowIdColumn`. */
export function isRowAnnotation(item: RenderableAnnotation, rowIdColumn: string): boolean {
  const g = item.annotation.geometry;
  return g.kind === 'points' && g.column === rowIdColumn && Array.isArray(g.ids) && g.ids.length > 0;
}

function safeColor(c: AnnotationColor | undefined): AnnotationColor {
  return c && (ANNOTATION_COLORS as readonly string[]).includes(c) ? c : DEFAULT_ROW_ANNOTATION_COLOR;
}

/** Ascending by number, unnumbered last; stable otherwise. */
function byNumber(a: RenderableAnnotation, b: RenderableAnnotation): number {
  const an = a.number ?? Number.POSITIVE_INFINITY;
  const bn = b.number ?? Number.POSITIVE_INFINITY;
  return an === bn ? 0 : an < bn ? -1 : 1;
}

/**
 * Which rows are marked, and by which annotation. When several annotations
 * cover a row, the focused one (`highlightId`) wins, then the lowest number.
 * Annotations on another column, coordinate-only points and other kinds are
 * ignored: they cannot be matched to table rows.
 */
export function buildRowAnnotationMap(
  items: readonly RenderableAnnotation[],
  rowIdColumn: string | null | undefined,
  highlightId: string | null = null,
): RowAnnotationMap {
  const map: RowAnnotationMap = new Map();
  if (!rowIdColumn) return map;
  const relevant = items.filter((i) => isRowAnnotation(i, rowIdColumn)).sort(byNumber);
  // The focused annotation claims its rows first; the rest go by number.
  const ordered = highlightId
    ? [...relevant.filter((i) => i.id === highlightId), ...relevant.filter((i) => i.id !== highlightId)]
    : relevant;
  for (const item of ordered) {
    const ids = (item.annotation.geometry as MarkedPoints).ids ?? [];
    for (const raw of ids) {
      if (raw === null || raw === undefined) continue;
      const key = String(raw);
      const existing = map.get(key);
      if (existing) {
        if (item.number != null && !existing.numbers.includes(item.number)) {
          existing.numbers.push(item.number);
          existing.numbers.sort((a, b) => a - b);
        }
        continue;
      }
      map.set(key, {
        id: item.id,
        color: safeColor(item.annotation.color),
        number: item.number,
        highlighted: highlightId != null && item.id === highlightId,
        numbers: item.number != null ? [item.number] : [],
      });
    }
  }
  return map;
}

/** AG Grid row classes for a marked row (see styles/table-annotations.css). */
export function rowAnnotationClasses(mark: RowAnnotationMark | undefined): string[] {
  if (!mark) return [];
  const classes = ['depictio-row-annotated', `depictio-row-annotated-${mark.color}`];
  if (mark.highlighted) classes.push('depictio-row-annotated-active');
  return classes;
}

/** Badge text of the numbered column, e.g. "①③"; '' for unmarked rows. */
export function rowAnnotationBadge(mark: RowAnnotationMark | undefined): string {
  if (!mark) return '';
  return mark.numbers.map(numberBadge).join('');
}

/**
 * Geometry for the rows selected in annotate mode: distinct ids from the row-id
 * column, capped at MAX_POINT_IDS. Null when nothing identifiable is selected.
 */
export function markedRowsFromSelection(
  rows: ReadonlyArray<Record<string, unknown> | null | undefined>,
  rowIdColumn: string,
): MarkedPoints | null {
  const seen = new Set<string>();
  const ids: Array<string | number> = [];
  for (const row of rows) {
    const v = row?.[rowIdColumn];
    if (typeof v !== 'string' && typeof v !== 'number') continue;
    if (typeof v === 'number' && !Number.isFinite(v)) continue;
    const key = String(v);
    if (seen.has(key)) continue;
    seen.add(key);
    ids.push(v);
    if (ids.length >= MAX_POINT_IDS) break;
  }
  return ids.length ? { kind: 'points', column: rowIdColumn, ids } : null;
}
