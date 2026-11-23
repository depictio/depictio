import { describe, expect, it } from 'vitest';

import { inkStructure } from './heatmapInk';

describe('inkStructure', () => {
  it('redraws the library ink of branches and outlines in the given ink', () => {
    const [branch, cell] = inkStructure(
      [
        { type: 'scatter', mode: 'lines', line: { color: '#444444', width: 1 } },
        { type: 'bar', marker: { color: '#925FC4', line: { color: '#333333', width: 0.5 } } },
      ],
      '#909296',
    ) as Record<string, any>[];
    expect(branch.line).toEqual({ color: '#909296', width: 1 });
    expect(cell.marker.line.color).toBe('#909296');
    expect(cell.marker.color).toBe('#925FC4');
  });

  it('leaves data colours alone', () => {
    const heat = { type: 'heatmap', z: [[1]] };
    const coloured = { type: 'scatter', line: { color: '#925FC4' } };
    const out = inkStructure([heat, coloured], '#909296');
    expect(out[0]).toBe(heat);
    expect(out[1]).toBe(coloured);
  });
});
