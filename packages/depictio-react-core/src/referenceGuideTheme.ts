/**
 * Reference lines (`reference_lines.py`) redrawn in the current colour scheme.
 *
 * The server bakes the guide's colours into the figure for the scheme it was
 * asked for. A figure drawn once and shown in both schemes (the catalog, an
 * offline bundle) would keep the light label on a dark surface, where it all
 * but disappears. The figure records its lines in `layout.meta.depictio_reference`,
 * so the line and its label are found by their value and recoloured from the
 * shared `REFERENCE_GUIDE` tokens of `scheme`; nothing else is touched.
 *
 * Pure: the layout it is given is not modified.
 */
import { referenceGuide } from './palettes';
import type { ColorScheme } from './palettes';

type Json = Record<string, unknown>;

interface Recorded {
  axis: 'x' | 'y';
  value: number;
  label: string | null;
}

const asRecord = (v: unknown): Json | null =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : null;

function recorded(layout: Json): Recorded[] {
  const raw = asRecord(layout.meta)?.depictio_reference;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    const e = asRecord(entry);
    const value = Number(e?.value);
    if (!e || (e.axis !== 'x' && e.axis !== 'y') || !Number.isFinite(value)) return [];
    return [{ axis: e.axis, value, label: typeof e.label === 'string' ? e.label : null }];
  });
}

const same = (a: unknown, b: number) => Number(a) === b;

export function themeReferenceGuides(layout: Json, scheme: ColorScheme): Json {
  const lines = recorded(layout);
  if (lines.length === 0) return layout;
  const guide = referenceGuide(scheme);

  const isGuideShape = (s: Json) =>
    s.type === 'line' &&
    lines.some((l) =>
      l.axis === 'y' ? same(s.y0, l.value) && same(s.y1, l.value) : same(s.x0, l.value) && same(s.x1, l.value),
    );
  const isGuideLabel = (a: Json) =>
    lines.some(
      (l) => l.label !== null && a.text === l.label && same(l.axis === 'y' ? a.y : a.x, l.value),
    );

  const shapes = Array.isArray(layout.shapes)
    ? layout.shapes.map((shape) => {
        const s = asRecord(shape);
        if (!s || !isGuideShape(s)) return shape;
        return { ...s, line: { ...(asRecord(s.line) ?? {}), color: guide.line.color } };
      })
    : layout.shapes;
  const annotations = Array.isArray(layout.annotations)
    ? layout.annotations.map((annotation) => {
        const a = asRecord(annotation);
        if (!a || !isGuideLabel(a)) return annotation;
        return { ...a, font: { ...(asRecord(a.font) ?? {}), color: guide.font.color } };
      })
    : layout.annotations;
  return { ...layout, shapes, annotations };
}
