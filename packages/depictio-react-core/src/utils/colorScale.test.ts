import { describe, expect, it } from 'vitest';

import { COLOUR_SCALES } from '../components/advanced_viz/colourScales';
import { COLORSCALE_NAMES, plotlyColorscale, sampleColorscale } from './colorScale';

describe('sampleColorscale', () => {
  it('holds every advanced-viz colour scale, so none falls back to Blues', () => {
    const blues = [sampleColorscale('Blues', 0), sampleColorscale('Blues', 1)];
    for (const name of COLOUR_SCALES) {
      expect(COLORSCALE_NAMES).toContain(name);
      expect([sampleColorscale(name, 0), sampleColorscale(name, 1)]).not.toEqual(blues);
    }
  });

  it('runs the matplotlib maps dark to light and RdBu blue to red, like Plotly', () => {
    expect(sampleColorscale('Plasma', 0)).toEqual([13, 8, 135]);
    expect(sampleColorscale('Plasma', 1)).toEqual([240, 249, 33]);
    expect(sampleColorscale('Magma', 0)).toEqual([0, 0, 4]);
    expect(sampleColorscale('RdBu', 0)).toEqual([5, 10, 172]);
    expect(sampleColorscale('RdBu', 1)).toEqual([178, 10, 28]);
  });

  it('hands Plotly explicit stops for the scales it holds', () => {
    const stops = plotlyColorscale('Inferno');
    expect(Array.isArray(stops)).toBe(true);
    expect((stops as Array<[number, string]>)[0]).toEqual([0, 'rgb(0,0,4)']);
  });
  it('emits stops for every advanced-viz scale, since plotly.js knows only some by name', () => {
    for (const name of COLOUR_SCALES) {
      const stops = plotlyColorscale(name);
      expect(Array.isArray(stops)).toBe(true);
      const arr = stops as Array<[number, string]>;
      expect(arr[0][0]).toBe(0);
      expect(arr[arr.length - 1][0]).toBe(1);
      expect(arr.every(([, c]) => /^rgb\(\d+,\d+,\d+\)$/.test(c))).toBe(true);
    }
    expect((plotlyColorscale('Plasma') as Array<[number, string]>)[0]).toEqual([0, 'rgb(13,8,135)']);
  });

  it('passes a name it does not hold through, for plotly.js builtins', () => {
    expect(plotlyColorscale('Hot')).toBe('Hot');
  });
});
