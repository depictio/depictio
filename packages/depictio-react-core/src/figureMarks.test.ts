import { describe, expect, it } from 'vitest';

import { applyMarksOff } from './figureMarks';

describe('applyMarksOff', () => {
  const marked = {
    data: [
      { type: 'bar', y: [3, 2], texttemplate: '%{y:,.0f}', textposition: 'outside' },
      { type: 'box', name: 'a (n=2)' },
    ],
    layout: { xaxis: { ticktext: ['a (n=2)'] }, annotations: [{ text: '3 more not shown' }] },
  };

  it('sets back and drops what the marks changed, trace by trace and on the layout', () => {
    const out = applyMarksOff(marked, {
      data: [
        { i: 0, unset: ['texttemplate', 'textposition'] },
        { i: 1, set: { name: 'a' } },
      ],
      layout: { set: { xaxis: {} }, unset: ['annotations'] },
    });
    expect(out).toEqual({
      data: [{ type: 'bar', y: [3, 2] }, { type: 'box', name: 'a' }],
      layout: { xaxis: {} },
    });
  });

  it('leaves the input untouched and returns it as is without a patch', () => {
    const before = JSON.stringify(marked);
    applyMarksOff(marked, { data: [{ i: 0, unset: ['texttemplate'] }] });
    expect(JSON.stringify(marked)).toBe(before);
    expect(applyMarksOff(marked, null)).toBe(marked);
  });

  it('ignores an index the figure does not have', () => {
    expect(applyMarksOff(marked, { data: [{ i: 9, set: { x: 1 } }] }).data).toEqual(marked.data);
  });
});
