import { describe, expect, it } from 'vitest';
import { applyChromePlotly } from './plotlyPatch';
import { BASE_CHROME_STYLE } from './chromeStyle';
import type { ChromeStyle } from './chromeStyle';

// A Glass-like patch: no axis lines, horizontal grid only.
const style: ChromeStyle = {
  ...BASE_CHROME_STYLE,
  plotly: () => ({
    xaxis: { showline: false, showgrid: false, ticks: '' },
    yaxis: { showline: false, showgrid: true, ticks: '' },
  }),
};

describe('applyChromePlotly', () => {
  it('lets the style drop the lines of axes that say nothing of them', () => {
    const out = applyChromePlotly({ xaxis: { title: 'x' }, yaxis: {} }, 'light', style);
    expect((out.xaxis as any).showline).toBe(false);
    expect((out.yaxis as any).showgrid).toBe(true);
  });

  it('keeps the axis furniture of a figure that draws its own axis lines', () => {
    const own = { showline: true, linewidth: 3, linecolor: '#333', showgrid: false };
    const out = applyChromePlotly({ xaxis: { ...own }, yaxis: { ...own } }, 'dark', style);
    expect(out.xaxis).toMatchObject(own);
    expect(out.yaxis).toMatchObject(own);
    // The rest of the patch still applies.
    expect((out.yaxis as any).ticks).toBe('');
  });
});
