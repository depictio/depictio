/**
 * Pure helpers behind the annotation form and editor: style defaults and
 * slider bounds per kind, dropping a marked-points region, and the minimal
 * patch an edit produces.
 */
import {
  DEFAULT_COLOR,
  DEFAULT_LINE_WIDTH,
  DEFAULT_POINT_RING_WIDTH,
  DEFAULT_RANGE_OPACITY,
} from './toPlotly';
import type { Annotation, AnnotationColor, AnnotationStyle, Geometry, MarkedPoints } from './types';

/** Partial update of an annotation, as the editor hands it back. */
export interface AnnotationPatchInput {
  label?: string;
  color?: AnnotationColor;
  /** Replaces the stored style wholesale. */
  style?: AnnotationStyle;
  /** Used to drop or keep a marked-points region. */
  geometry?: Geometry;
}

/** Bounds of the opacity sliders (range band and points region). */
export const FILL_OPACITY_MIN = 0.05;
export const FILL_OPACITY_MAX = 0.6;
/** Bounds of the line and ring width sliders. */
export const STROKE_WIDTH_MIN = 0.5;
export const STROKE_WIDTH_MAX = 6;

/** Whether the geometry is marked points carrying a selected area. */
export function hasRegion(geometry: Geometry): geometry is MarkedPoints {
  return geometry.kind === 'points' && geometry.region != null;
}

/** The geometry without its selected area (other geometries unchanged). */
export function withoutRegion(geometry: Geometry): Geometry {
  if (geometry.kind !== 'points' || geometry.region == null) return geometry;
  const { region: _dropped, ...rest } = geometry;
  return rest;
}

/** Style values as drawn, defaults filled in, for the editor's controls. */
export interface EffectiveStyle {
  opacity: number;
  dash: 'solid' | 'dash' | 'dot';
  width: number;
  fillOpacity: number;
}

export function effectiveStyle(annotation: Annotation): EffectiveStyle {
  const s = annotation.style ?? {};
  return {
    opacity: s.opacity ?? (annotation.kind === 'range' ? DEFAULT_RANGE_OPACITY : 1),
    dash: s.dash ?? 'dash',
    width: s.width ?? (annotation.kind === 'points' ? DEFAULT_POINT_RING_WIDTH : DEFAULT_LINE_WIDTH),
    fillOpacity: s.fill_opacity ?? DEFAULT_RANGE_OPACITY,
  };
}

/** What the editor lets a person change. */
export interface AnnotationEdits {
  label: string;
  color: AnnotationColor;
  style: EffectiveStyle;
  /** Only read when the annotation has a region: false drops it. */
  keepRegion: boolean;
}

function sameNumber(a: number, b: number): boolean {
  return Math.abs(a - b) < 1e-9;
}

/**
 * The fields of `edits` that differ from `annotation`. A changed style is
 * sent whole (the stored style merged with the edited values relevant to the
 * kind), since the API replaces it wholesale. Dropping the region sends the
 * geometry without it.
 */
export function annotationPatch(annotation: Annotation, edits: AnnotationEdits): AnnotationPatchInput {
  const patch: AnnotationPatchInput = {};
  const label = edits.label.trim();
  if (label !== annotation.label) patch.label = label;
  if (edits.color !== (annotation.color ?? DEFAULT_COLOR)) patch.color = edits.color;

  const before = effectiveStyle(annotation);
  const after = edits.style;
  const changed: AnnotationStyle = {};
  switch (annotation.kind) {
    case 'range':
      if (!sameNumber(after.opacity, before.opacity)) changed.opacity = after.opacity;
      break;
    case 'line':
      if (after.dash !== before.dash) changed.dash = after.dash;
      if (!sameNumber(after.width, before.width)) changed.width = after.width;
      break;
    case 'points':
      if (!sameNumber(after.width, before.width)) changed.width = after.width;
      if (
        hasRegion(annotation.geometry) &&
        edits.keepRegion &&
        !sameNumber(after.fillOpacity, before.fillOpacity)
      ) {
        changed.fill_opacity = after.fillOpacity;
      }
      break;
    case 'note':
      break;
  }
  if (Object.keys(changed).length) patch.style = { ...(annotation.style ?? {}), ...changed };

  if (hasRegion(annotation.geometry) && !edits.keepRegion) {
    patch.geometry = withoutRegion(annotation.geometry);
  }
  return patch;
}
