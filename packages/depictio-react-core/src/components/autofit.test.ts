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

describe('fitLayoutHeights with an advanced viz', () => {
  const members = [{ index: 'tree', component_type: 'advanced_viz' }];
  const layouts = [{ i: 'tree', y: 0, h: 12 }];

  it('fits one that publishes a height, both ways', () => {
    expect(fitLayoutHeights(members, layouts, { tree: 380 })[0].h).toBe(rowsForHeight(380));
  });

  it('keeps the stored height of one that publishes none', () => {
    expect(fitLayoutHeights(members, layouts, {})[0].h).toBe(12);
    expect(fitLayoutHeights(members, layouts, { tree: 0 })[0].h).toBe(12);
  });
});

describe('fitLayoutHeights with compact cards', () => {
  const layouts = [
    { i: 'a', y: 0, h: 8 },
    { i: 'b', y: 0, h: 8 },
  ];

  it('lets a row of compact cards shrink to the tallest of them', () => {
    const members = [
      { index: 'a', component_type: 'card', variant: 'compact' },
      { index: 'b', component_type: 'card', variant: 'compact' },
    ];
    const fitted = fitLayoutHeights(members, layouts, { a: 60, b: 90 });
    expect(fitted.map((l) => l.h)).toEqual([rowsForHeight(90), rowsForHeight(90)]);
  });

  it('keeps the authored height when a compact card shares its row with another style', () => {
    const members = [
      { index: 'a', component_type: 'card', variant: 'compact' },
      { index: 'b', component_type: 'card', variant: 'headline' },
    ];
    const fitted = fitLayoutHeights(members, layouts, { a: 60, b: 90 });
    expect(fitted.map((l) => l.h)).toEqual([8, 8]);
  });

  it('keeps an accent or split row at its authored height', () => {
    const members = [
      { index: 'a', component_type: 'card', variant: 'accent' },
      { index: 'b', component_type: 'card', variant: 'split' },
    ];
    const fitted = fitLayoutHeights(members, layouts, { a: 60, b: 90 });
    expect(fitted.map((l) => l.h)).toEqual([8, 8]);
  });
});
