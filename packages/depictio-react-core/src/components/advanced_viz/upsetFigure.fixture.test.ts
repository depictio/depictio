import { describe, expect, it } from 'vitest';

import fixture from './fixtures/upset-colouring.json';
import {
  colourUpsetSets,
  resolveUpsetSetColors,
  upsetSetNames,
  withUpsetSetLabelDots,
} from './upsetFigure';

// The server draws the same recolouring in Python for a figure that never
// reaches this renderer (the PDF of a notebook export): depictio/api/v1/services/
// export/upset_colors.py. Both read this fixture, `expected` written from the
// functions below, so a change to the rules here fails the Python test until
// the port follows (and the fixture is rewritten from this side).
describe('upset recolouring parity fixture', () => {
  const layout = fixture.figure.layout as Record<string, unknown>;
  const data = fixture.figure.data as Record<string, unknown>[];
  const names = upsetSetNames(layout);

  for (const c of fixture.cases) {
    it(c.name, () => {
      const colors = resolveUpsetSetColors({ category_colors: c.category_colors as unknown as Record<string, Record<string, string>> }, names, {
        column: c.column,
        overrides: c.overrides as Record<string, string> | null,
      });
      if (c.expected === null) {
        expect(colors).toBeNull();
        return;
      }
      expect(colors).toEqual(c.expected.colors);
      const coloured = colourUpsetSets(data, layout, colors);
      expect(JSON.parse(JSON.stringify(coloured))).toEqual(c.expected.data);
      expect(withUpsetSetLabelDots(layout, colors)).toEqual(c.expected.layout);
    });
  }
});
