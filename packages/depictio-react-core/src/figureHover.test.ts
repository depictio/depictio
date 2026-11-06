import { describe, expect, it } from 'vitest';

import { followSeriesHover, seriesColour } from './figureHover';

const hl = (trace: unknown) => (trace as any).hoverlabel;

describe('followSeriesHover', () => {
  it('colours each bar series like the series, with ink that reads on it', () => {
    const data = [
      { type: 'bar', name: 'HIGH', marker: { color: '#e03131' } },
      { type: 'bar', name: 'MODERATE', marker: { color: '#f08c00' } },
    ];
    const out = followSeriesHover(data, data);
    expect(hl(out[0])).toMatchObject({ bgcolor: '#e03131', bordercolor: '#ffffff', font: { color: '#ffffff' } });
    expect(hl(out[1])).toMatchObject({ bgcolor: '#f08c00', font: { color: '#212529' } });
    expect((data[0] as any).hoverlabel).toBeUndefined();
  });

  it('follows the tab hue once a tint repainted the series', () => {
    const before = [{ type: 'bar', marker: { color: '#636efa' }, hoverlabel: { bgcolor: '#636efa' } }];
    const after = [{ type: 'bar', marker: { color: '#0ca678' }, hoverlabel: { bgcolor: '#636efa' } }];
    expect(hl(followSeriesHover(before, after)[0]).bgcolor).toBe('#0ca678');
  });

  it('keeps a label the figure chose on its own', () => {
    const data = [{ type: 'bar', marker: { color: '#e03131' }, hoverlabel: { bgcolor: '#000000' } }];
    expect(followSeriesHover(data, data)).toBe(data);
  });

  it('gives one label colour per point when the points are coloured one by one', () => {
    const data = [{ type: 'bar', marker: { color: ['#e03131', '#f08c00'] } }];
    expect(hl(followSeriesHover(data, data)[0]).bgcolor).toEqual(['#e03131', '#f08c00']);
  });

  it('leaves scales, colour names and traces without a colour on the neutral label', () => {
    const data = [
      { type: 'scatter', mode: 'markers', marker: { color: [1, 2, 3] } },
      { type: 'bar', marker: { color: 'red' } },
      { type: 'bar' },
    ];
    expect(followSeriesHover(data, data)).toBe(data);
  });

  it('reads a line-only scatter from its line', () => {
    expect(seriesColour({ type: 'scatter', mode: 'lines', line: { color: '#1c7ed6' } })).toBe('#1c7ed6');
    expect(seriesColour({ type: 'scatter', mode: 'lines+markers', line: { color: '#1c7ed6' } })).toBeNull();
  });

  it('drops the hover line of a column Plotly Express left unnamed', () => {
    const data = [{ type: 'bar', hovertemplate: 'Impact=HIGH<br>=%{x}<br>Share=%{y}<extra></extra>' }];
    expect((followSeriesHover(data, data)[0] as any).hovertemplate).toBe(
      'Impact=HIGH<br>Share=%{y}<extra></extra>',
    );
  });
});
