import { describe, expect, it } from 'vitest';
import { DEFAULT_THEME } from '@mantine/core';
import { applyLayoutTheme } from './plotlyTheme';

const theme = DEFAULT_THEME;

describe('applyLayoutTheme axis lines', () => {
  it('retints the line of an axis that does not draw its own', () => {
    const out = applyLayoutTheme({ xaxis: { linecolor: '#123456' } }, false, theme);
    expect((out.xaxis as any).linecolor).not.toBe('#123456');
  });

  it('keeps the colour of an axis line the figure draws itself', () => {
    const out = applyLayoutTheme({ xaxis: { showline: true, linecolor: '#123456', linewidth: 3 } }, true, theme);
    expect(out.xaxis).toMatchObject({ showline: true, linecolor: '#123456', linewidth: 3 });
  });
});
