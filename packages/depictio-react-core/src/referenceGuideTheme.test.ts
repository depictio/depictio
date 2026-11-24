import { describe, expect, it } from 'vitest';

import { referenceGuide } from './palettes';
import { themeReferenceGuides } from './referenceGuideTheme';

const light = referenceGuide('light');
const dark = referenceGuide('dark');

const layout = {
  meta: { depictio_reference: [{ axis: 'y', value: 23.5, label: 'median of this table' }] },
  shapes: [
    { type: 'line', xref: 'x domain', x0: 0, x1: 1, y0: 23.5, y1: 23.5, line: { ...light.line } },
    { type: 'rect', x0: 0, x1: 1, y0: 0, y1: 5, line: { color: '#e03131' } },
  ],
  annotations: [
    { text: 'median of this table', x: 1, y: 23.5, font: { ...light.font } },
    { text: 'a note', x: 1, y: 23.5, font: { color: '#e03131' } },
  ],
};

describe('themeReferenceGuides', () => {
  it('redraws the recorded line and its label in the dark tokens', () => {
    const out = themeReferenceGuides(layout, 'dark') as typeof layout;
    expect(out.shapes[0].line.color).toBe(dark.line.color);
    expect(out.annotations[0].font.color).toBe(dark.font.color);
    expect((out.annotations[0].font as { size: number }).size).toBe(light.font.size);
  });

  it('leaves every other shape and annotation, and the input, alone', () => {
    const out = themeReferenceGuides(layout, 'dark') as typeof layout;
    expect(out.shapes[1]).toBe(layout.shapes[1]);
    expect(out.annotations[1]).toBe(layout.annotations[1]);
    expect(layout.annotations[0].font.color).toBe(light.font.color);
  });

  it('returns a figure without recorded lines unchanged', () => {
    const plain = { shapes: [], annotations: [] };
    expect(themeReferenceGuides(plain, 'dark')).toBe(plain);
  });
});
