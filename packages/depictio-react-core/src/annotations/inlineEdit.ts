/**
 * Pure helpers behind editing a saved annotation: the live preview of the
 * editor's unsaved changes, and where the inline editor opens on a component.
 */
import type { AnnotationPatchInput } from './edit';
import type { Annotation, RenderableAnnotation } from './types';

/** The editor's unsaved changes for one thread, drawn in place of the saved version. */
export interface AnnotationEditDraft {
  threadId: string;
  patch: AnnotationPatchInput;
}

/** A point in viewport (client) coordinates. */
export interface ClientPoint {
  x: number;
  y: number;
}

/**
 * `annotation` with the patch applied, as it would be once saved. An empty
 * label (the field is being retyped) keeps the saved one, so the shape never
 * loses its caption mid-edit.
 */
export function applyAnnotationPatch(annotation: Annotation, patch: AnnotationPatchInput): Annotation {
  const next: Annotation = { ...annotation };
  if (patch.label !== undefined && patch.label !== '') next.label = patch.label;
  if (patch.color !== undefined) next.color = patch.color;
  if (patch.style !== undefined) next.style = patch.style;
  if (patch.geometry !== undefined) next.geometry = patch.geometry;
  return next;
}

/**
 * The draft after an editor of `threadId` reports `patch`. An empty patch
 * (nothing changed yet, or the editor closed) clears that thread's draft but
 * never another thread's.
 */
export function nextEditDraft(
  prev: AnnotationEditDraft | null,
  threadId: string,
  patch: AnnotationPatchInput | null,
): AnnotationEditDraft | null {
  if (!patch || Object.keys(patch).length === 0) return prev?.threadId === threadId ? null : prev;
  return { threadId, patch };
}

/**
 * `items` with the draft drawn over its thread's annotation. Returns `items`
 * itself when the draft is empty or targets none of them, so memoised
 * renderers see no change.
 */
export function withEditDraft(
  items: RenderableAnnotation[],
  draft: AnnotationEditDraft | null,
): RenderableAnnotation[] {
  if (!draft || Object.keys(draft.patch).length === 0) return items;
  const at = items.findIndex((i) => i.id === draft.threadId);
  if (at < 0) return items;
  const next = items.slice();
  next[at] = { ...items[at], annotation: applyAnnotationPatch(items[at].annotation, draft.patch) };
  return next;
}

/**
 * Items per component with the draft applied. Only the component holding the
 * thread gets a new array; the record itself is kept when nothing changes.
 */
export function itemsWithEditDraft(
  items: Record<string, RenderableAnnotation[]>,
  draft: AnnotationEditDraft | null,
): Record<string, RenderableAnnotation[]> {
  if (!draft) return items;
  for (const [key, list] of Object.entries(items)) {
    const next = withEditDraft(list, draft);
    if (next !== list) return { ...items, [key]: next };
  }
  return items;
}

/**
 * Viewport coordinates of the pointer behind a click: a DOM mouse event, or a
 * Plotly event carrying it as `event` (`plotly_click`, `plotly_clickannotation`).
 */
export function clientPointFromEvent(event: unknown): ClientPoint | null {
  if (!event || typeof event !== 'object') return null;
  const read = (e: unknown): ClientPoint | null => {
    const m = e as { clientX?: unknown; clientY?: unknown } | null;
    return m && typeof m.clientX === 'number' && typeof m.clientY === 'number'
      ? { x: m.clientX, y: m.clientY }
      : null;
  };
  return read(event) ?? read((event as { event?: unknown }).event);
}

export interface FrameRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Offset of the editor's anchor inside the component's frame: the click
 * position, clamped to the frame, or its centre when there is no click.
 */
export function anchorOffset(anchor: ClientPoint | null, frame: FrameRect): { left: number; top: number } {
  if (!anchor) return { left: frame.width / 2, top: frame.height / 2 };
  const clamp = (v: number, max: number) => Math.min(Math.max(v, 0), Math.max(max, 0));
  return { left: clamp(anchor.x - frame.left, frame.width), top: clamp(anchor.y - frame.top, frame.height) };
}
