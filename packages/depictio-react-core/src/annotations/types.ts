/**
 * Annotation types mirroring the backend Pydantic contract in
 * `depictio/models/models/comments.py` (Annotation, Geometry, AnnotationStyle).
 * Keep the two in sync: field names, literals and defaults match one to one.
 */

/** Mantine palette names, in the order the Python model lists them. */
export const ANNOTATION_COLORS = [
  'blue',
  'cyan',
  'teal',
  'green',
  'lime',
  'yellow',
  'orange',
  'red',
  'pink',
  'grape',
  'violet',
  'indigo',
  'gray',
] as const;

export type AnnotationColor = (typeof ANNOTATION_COLORS)[number];

export type AnnotationKind = 'range' | 'line' | 'points' | 'note';

/** A numeric value, a category, or a date string, as Plotly takes it. */
export type AxisValue = number | string;

export const MAX_POINT_IDS = 5000;
export const MAX_REGION_VERTICES = 1000;
export const MAX_LABEL_CHARS = 120;
export const MAX_VARIANT_CHARS = 200;

/** A band across the x axis, drawn behind the data. */
export interface XRange {
  kind: 'x_range';
  x0: AxisValue;
  x1: AxisValue;
}

/** A band across the y axis, drawn behind the data. */
export interface YRange {
  kind: 'y_range';
  y0: number;
  y1: number;
}

/** A dashed reference line, drawn in front of the data. */
export interface RefLine {
  kind: 'ref_line';
  axis: 'x' | 'y';
  value: AxisValue;
}

export interface PointCoord {
  x: AxisValue;
  y: AxisValue;
  /** Index of the trace the point belongs to, when the figure has several. */
  trace?: number | null;
  /**
   * Index of the point in its trace's data, kept for traces drawn away from
   * their data x/y (box, violin, bar) to find the drawn mark again.
   */
  index?: number | null;
}

/** The rectangle a box selection covered. */
export interface BoxRegion {
  shape: 'box';
  x0: AxisValue;
  x1: AxisValue;
  y0: AxisValue;
  y1: AxisValue;
}

/** The polygon a lasso traced: 3..MAX_REGION_VERTICES vertices, `x`/`y` of equal length. */
export interface LassoRegion {
  shape: 'lasso';
  x: AxisValue[];
  y: AxisValue[];
}

export type SelectionRegion = BoxRegion | LassoRegion;

/**
 * Points to circle. Identified by the selection column (`column` + `ids`)
 * when the component has one, else by plain coordinates. `region` keeps the
 * area the selection gesture covered, drawn as a shaded background.
 */
export interface MarkedPoints {
  kind: 'points';
  column?: string | null;
  ids?: Array<string | number>;
  coords?: PointCoord[];
  region?: SelectionRegion | null;
}

/** Arrow head at (`x`, `y`) in data coords; label offset `ax`/`ay` in pixels. */
export interface ArrowNote {
  kind: 'arrow_note';
  x: AxisValue;
  y: AxisValue;
  ax?: number;
  ay?: number;
}

export type Geometry = XRange | YRange | RefLine | MarkedPoints | ArrowNote;
export type GeometryKind = Geometry['kind'];

/** Which geometries each annotation kind accepts (mirrors `_GEOMETRY_KINDS`). */
export const GEOMETRY_KINDS: Record<AnnotationKind, readonly GeometryKind[]> = {
  range: ['x_range', 'y_range'],
  line: ['ref_line'],
  points: ['points'],
  note: ['arrow_note'],
};

export interface AnnotationStyle {
  /** 0..1 */
  opacity?: number | null;
  dash?: 'solid' | 'dash' | 'dot' | null;
  /** (0, 10] */
  width?: number | null;
  /** 0..1, opacity of a marked-points region; 0 draws no background. */
  fill_opacity?: number | null;
}

export interface Annotation {
  kind: AnnotationKind;
  geometry: Geometry;
  label: string;
  /** Defaults to 'yellow' on the backend. */
  color?: AnnotationColor;
  style?: AnnotationStyle;
  /** Visible to viewers of the dashboard (shape and label only). */
  published?: boolean;
  /**
   * The view of the component the shape was drawn on (1..MAX_VARIANT_CHARS
   * chars), for components showing one of several plots, e.g. a MultiQC
   * dataset. Drawn only on that view; unset draws it on every view.
   */
  variant?: string | null;
}

/** An annotation ready to draw: its thread id, badge number and status. */
export interface RenderableAnnotation {
  id: string;
  number: number | null;
  annotation: Annotation;
  status?: string;
  /** The capture waiting for its label: drawn dashed and faded, never clickable. */
  preview?: boolean;
}

/** Id of the preview annotation drawn while a capture awaits its label. */
export const PREVIEW_ANNOTATION_ID = '__preview__';

const CIRCLED_DIGITS = [
  '①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩',
  '⑪', '⑫', '⑬', '⑭', '⑮', '⑯', '⑰', '⑱', '⑲', '⑳',
];

/** ①..⑳ for 1..20, `(n)` beyond (or for 0 / negatives / non-integers). */
export function numberBadge(n: number): string {
  if (Number.isInteger(n) && n >= 1 && n <= CIRCLED_DIGITS.length) return CIRCLED_DIGITS[n - 1];
  return `(${n})`;
}
