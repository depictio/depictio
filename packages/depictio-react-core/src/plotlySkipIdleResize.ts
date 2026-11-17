/**
 * Keeps `Plotly.Plots.resize` from redrawing a figure whose box did not change.
 *
 * See `components/idleResize.ts` for why a resize of an unchanged box is a full
 * redraw. A resize that finds the box at a new size runs as before; only the
 * one that finds it where the last draw left it is skipped.
 *
 * Like plotlyStrictMode, this patches a shared object (Plotly's `Plots`) and
 * must be imported before any Plot mounts.
 */
import Plotly from 'plotly.js';

import { resizeIsIdle, type ResizableGraphDiv } from './components/idleResize';

type Resize = ((gd: unknown) => Promise<unknown>) & { depictioSkipsIdle?: true };

const plots = Plotly.Plots as unknown as { resize?: Resize };
const resize = plots.resize;

// Guarded so a hot reload of this module does not wrap the function twice.
if (resize && !resize.depictioSkipsIdle) {
  const skipping: Resize = function (this: unknown, gd: unknown) {
    if (typeof HTMLElement !== 'undefined' && gd instanceof HTMLElement) {
      const style = getComputedStyle(gd);
      const box = { width: parseFloat(style.width), height: parseFloat(style.height) };
      if (resizeIsIdle(gd as unknown as ResizableGraphDiv, box)) return Promise.resolve(gd);
    }
    return resize.call(this, gd);
  };
  skipping.depictioSkipsIdle = true;
  plots.resize = skipping;
}
