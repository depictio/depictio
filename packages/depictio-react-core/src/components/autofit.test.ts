import { describe, expect, it } from 'vitest';

import { fitLayoutHeights, rowsForHeight } from './autofit';

describe('fitLayoutHeights', () => {
  const members = [
    { index: 'a', component_type: 'text', surface: 'card' },
    { index: 'b', component_type: 'text', surface: 'card' },
    { index: 'c', component_type: 'text' },
  ];
  const layouts = [
    { i: 'a', y: 0, h: 4 },
    { i: 'b', y: 0, h: 4 },
    { i: 'c', y: 0, h: 4 },
  ];

  it('gives framed text tiles on one row the tallest measurement', () => {
    const fitted = fitLayoutHeights(members, layouts, { a: 150, b: 300, c: 150 });
    expect(fitted.map((l) => l.h)).toEqual([rowsForHeight(300), rowsForHeight(300), rowsForHeight(150)]);
  });

  it('lets a framed row shrink to its prose', () => {
    const fitted = fitLayoutHeights(members, layouts, { a: 90, b: 90 });
    expect(fitted[0].h).toBe(1);
    expect(fitted[1].h).toBe(1);
  });
});
