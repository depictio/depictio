import { describe, expect, it } from 'vitest';

import type { ZoomWindow } from '../../../highlight/zoomSync';
import { windowSpan } from './zoomFollow';

const win = (start: number, end: number, fit = false): ZoomWindow => ({
  sourceIndex: 'a',
  start,
  end,
  fit,
});
const bounds = { first: 1, last: 300, chain: null };

describe('windowSpan', () => {
  it('frames every residue the window touches', () => {
    expect(windowSpan(win(10.4, 40.6), bounds)).toEqual({ chain: null, start: 10, end: 40 });
    expect(windowSpan(win(10, 41), bounds)).toEqual({ chain: null, start: 10, end: 40 });
  });

  it('frames the whole model for a fitted source or a window covering it', () => {
    expect(windowSpan(win(10, 40, true), bounds)).toBeNull();
    expect(windowSpan(win(0.5, 301), bounds)).toBeNull();
  });

  it('clamps to the model and names the chain framed', () => {
    expect(windowSpan(win(280, 320), { ...bounds, chain: 'A' })).toEqual({
      chain: 'A',
      start: 280,
      end: 300,
    });
  });

  it('frames nothing for a window past the model', () => {
    expect(windowSpan(win(400, 450), bounds)).toBeUndefined();
  });
});
