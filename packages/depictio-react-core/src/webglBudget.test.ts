import { describe, expect, it, vi } from 'vitest';

import { releaseRemovedGlCanvases } from './webglBudget';

/** A Plotly GL canvas as the reaper sees it: the class Plotly stamps, and the
 *  regl datum carrying the context. */
function glCanvas(opts: { connected?: boolean; lost?: boolean; withRegl?: boolean } = {}) {
  const { connected = false, lost = false, withRegl = true } = opts;
  const loseContext = vi.fn();
  const getExtension = vi.fn(() => ({ loseContext }));
  const canvas = {
    nodeType: 1,
    isConnected: connected,
    classList: { contains: (token: string) => token === 'gl-canvas' },
    __data__: withRegl
      ? { regl: { _gl: { isContextLost: () => lost, getExtension } } }
      : { key: 'pickLayer' },
  };
  return { canvas, loseContext, getExtension };
}

/** A removed tile subtree holding some canvases. */
function subtree(canvases: unknown[]) {
  return {
    nodeType: 1,
    isConnected: false,
    classList: { contains: () => false },
    querySelectorAll: (selector: string) => (selector === 'canvas.gl-canvas' ? canvases : []),
  };
}

describe('releaseRemovedGlCanvases', () => {
  // Regression: a tile that refetches unmounts its Plotly plot, and Plotly
  // removes the GL canvases without losing their contexts. Those zombies
  // count toward Chrome's 16 until GC, so a lasso-then-save on a scrnaseq
  // UMAP evicted the UMAP's own live context and blanked it ~2 s later.
  it('loses the context of every GL canvas in a removed subtree', () => {
    const a = glCanvas();
    const b = glCanvas();
    const released = releaseRemovedGlCanvases([subtree([a.canvas, b.canvas])]);
    expect(released).toBe(2);
    expect(a.loseContext).toHaveBeenCalledTimes(1);
    expect(b.loseContext).toHaveBeenCalledTimes(1);
  });

  it('handles a GL canvas removed on its own (a plot whose traces stop being GL)', () => {
    const a = glCanvas();
    expect(releaseRemovedGlCanvases([a.canvas])).toBe(1);
    expect(a.loseContext).toHaveBeenCalledTimes(1);
  });

  it('leaves a canvas that is back in the document alone (moved, not dropped)', () => {
    const a = glCanvas({ connected: true });
    expect(releaseRemovedGlCanvases([a.canvas])).toBe(0);
    expect(a.getExtension).not.toHaveBeenCalled();
  });

  it('skips canvases with no regl context and contexts already lost', () => {
    const pick = glCanvas({ withRegl: false });
    const gone = glCanvas({ lost: true });
    expect(releaseRemovedGlCanvases([subtree([pick.canvas, gone.canvas])])).toBe(0);
    expect(gone.loseContext).not.toHaveBeenCalled();
  });

  it('ignores text nodes and elements without GL canvases', () => {
    expect(releaseRemovedGlCanvases([{ nodeType: 3 }, subtree([])])).toBe(0);
  });
});
