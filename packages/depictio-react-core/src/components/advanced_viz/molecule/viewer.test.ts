import { describe, expect, it, vi } from 'vitest';

import {
  createStructureViewer,
  frameSelection,
  normaliseRepresentations,
  overlayLayerKeys,
  representationStyle,
  selectionStyle,
  SITE_MAX_RESIDUES,
  type MarkSpec,
  type ViewerColours,
} from './viewer';

// A 3Dmol stand-in for the node test environment: `createViewer` appends a
// canvas to the host, as the real one does, and counts the shapes it draws.
interface FakeCanvas {
  released: boolean;
  getContext(): null;
  remove(): void;
}

class FakeHost {
  canvases: FakeCanvas[] = [];
  listeners = new Map<string, Set<(e: unknown) => void>>();
  addEventListener(type: string, fn: (e: unknown) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(fn);
  }
  removeEventListener(type: string, fn: (e: unknown) => void) {
    this.listeners.get(type)?.delete(fn);
  }
  fire(type: string, event: Record<string, unknown> = {}) {
    for (const fn of this.listeners.get(type) ?? []) fn(event);
  }
  querySelectorAll(_sel: string) {
    return this.canvases;
  }
  addCanvas(): FakeCanvas {
    const canvas: FakeCanvas = {
      released: false,
      getContext: () => null,
      remove: () => {
        canvas.released = true;
        this.canvases = this.canvases.filter((c) => c !== canvas);
      },
    };
    this.canvases.push(canvas);
    return canvas;
  }
}

const drawn = { spheres: 0, removed: 0, labels: 0 };
// Every camera fit, as the selection it was fitted to (undefined: whole model).
const fits: unknown[] = [];

vi.mock('3dmol', () => ({
  createViewer: (host: FakeHost) => {
    const canvas = host.addCanvas();
    return {
      getCanvas: () => canvas,
      setHoverDuration: () => {},
      addModel: () => ({ selectedAtoms: () => [] }),
      removeAllModels: () => {},
      removeAllSurfaces: () => {},
      setHoverable: () => {},
      setClickable: () => {},
      setStyle: () => {},
      addStyle: () => {},
      zoomTo: (sel?: unknown) => {
        fits.push(sel && Object.keys(sel as object).length ? sel : undefined);
      },
      resize: () => {},
      render: () => {},
      spin: () => {},
      clear: () => {},
      addSphere: () => {
        drawn.spheres += 1;
        return {};
      },
      removeShape: () => {
        drawn.removed += 1;
      },
      addLabel: () => {
        drawn.labels += 1;
        return {};
      },
      removeLabel: () => {},
      selectedAtoms: (sel: { resi: number | string }) => [
        { x: 0, y: 0, z: 0, resn: 'ALA', resi: Number(sel.resi) || 1 },
      ],
    };
  },
}));

const COLOURS: ViewerColours = {
  background: 'white',
  selection: 'grape',
  site: 'red',
  highlight: 'pink',
  labelText: 'black',
  labelBackground: 'gray',
};
const callbacks = { onHover: () => {}, onClick: () => {} };

const mark = (position: number, emphasised = false): MarkSpec => ({
  chain: 'A',
  position,
  radius: 1,
  colour: 'red',
  label: `p.A${position}V`,
  emphasised,
});

describe('overlayLayerKeys', () => {
  it('keeps the marks key when only the emphasis or the hover changes', () => {
    const plain = overlayLayerKeys({ marks: [mark(1), mark(2)], showLabels: false, highlight: null });
    const hovered = overlayLayerKeys({
      marks: [mark(1), mark(2, true)],
      showLabels: false,
      highlight: { chain: 'A', start: 2, end: 2 },
    });
    expect(hovered.marks).toBe(plain.marks);
    expect(hovered.emphasis).not.toBe(plain.emphasis);
    expect(hovered.highlight).not.toBe(plain.highlight);
  });
});

describe('createStructureViewer', () => {
  it('disposes only the canvas it drew on, not a newer viewer on the same host', async () => {
    const host = new FakeHost();
    const stale = await createStructureViewer(host as unknown as HTMLElement, COLOURS, callbacks);
    const live = await createStructureViewer(host as unknown as HTMLElement, COLOURS, callbacks);
    const [staleCanvas, liveCanvas] = host.canvases;
    stale.dispose();
    expect(staleCanvas.released).toBe(true);
    expect(liveCanvas.released).toBe(false);
    expect(host.canvases).toEqual([liveCanvas]);
    live.dispose();
    expect(host.canvases).toEqual([]);
  });

  it('redraws only the emphasis and highlight layers on a hover', async () => {
    const host = new FakeHost();
    const viewer = await createStructureViewer(host as unknown as HTMLElement, COLOURS, callbacks);
    viewer.load('ATOM', 'pdb');
    const marks = [mark(1), mark(2), mark(3)];
    viewer.setOverlay({ marks, showLabels: false, highlight: null });
    expect(drawn.spheres).toBe(3);

    Object.assign(drawn, { spheres: 0, removed: 0, labels: 0 });
    // The same marks as a new array (a parent re-render): nothing is redrawn.
    viewer.setOverlay({ marks: [...marks], showLabels: false, highlight: null });
    expect(drawn).toEqual({ spheres: 0, removed: 0, labels: 0 });

    // A hover lights mark 2 and one residue: two spheres and a label, no mark churn.
    viewer.setOverlay({
      marks: [mark(1), mark(2, true), mark(3)],
      showLabels: false,
      highlight: { chain: 'A', start: 5, end: 5 },
    });
    expect(drawn).toEqual({ spheres: 2, removed: 0, labels: 1 });

    Object.assign(drawn, { spheres: 0, removed: 0, labels: 0 });
    viewer.setOverlay({ marks, showLabels: false, highlight: null });
    expect(drawn).toEqual({ spheres: 0, removed: 2, labels: 0 });
    viewer.dispose();
  });
});

describe('resize re-fit', () => {
  const setup = async () => {
    const host = new FakeHost();
    const viewer = await createStructureViewer(host as unknown as HTMLElement, COLOURS, callbacks);
    viewer.load('ATOM', 'pdb');
    fits.length = 0;
    return { host, viewer };
  };

  it('re-fits the whole model on resize until the reader moves the camera', async () => {
    const { host, viewer } = await setup();
    viewer.resize();
    expect(fits).toEqual([undefined]);

    // A click (no drag) does not count as moving the view.
    host.fire('pointerdown', { clientX: 10, clientY: 10 });
    host.fire('pointermove', { clientX: 11, clientY: 10, buttons: 1 });
    host.fire('pointerup');
    viewer.resize();
    expect(fits).toHaveLength(2);

    // A drag does: the next resize keeps the reader's camera.
    host.fire('pointerdown', { clientX: 10, clientY: 10 });
    host.fire('pointermove', { clientX: 40, clientY: 30, buttons: 1 });
    host.fire('pointerup');
    viewer.resize();
    expect(fits).toHaveLength(2);

    // Reset hands the camera back to the fit.
    viewer.resetView();
    fits.length = 0;
    viewer.resize();
    expect(fits).toEqual([undefined]);
    viewer.dispose();
    expect(host.listeners.get('wheel')?.size ?? 0).toBe(0);
  });

  it('keeps a focused span in frame, and a wheel or a new load toggles the flag', async () => {
    const { host, viewer } = await setup();
    viewer.focus({ chain: 'A', start: 20, end: 40 }, false);
    fits.length = 0;
    viewer.resize();
    expect(fits).toEqual([{ chain: 'A', resi: '20-40' }]);

    host.fire('wheel');
    viewer.resize();
    expect(fits).toHaveLength(1);

    viewer.load('ATOM', 'pdb');
    fits.length = 0;
    viewer.resize();
    expect(fits).toEqual([undefined]);
    viewer.dispose();
  });
});

describe('representations', () => {
  const colour = { colorfunc: 'f' };

  it('orders, dedupes and never draws nothing', () => {
    expect(normaliseRepresentations(['surface', 'cartoon', 'surface'])).toEqual(['cartoon', 'surface']);
    expect(normaliseRepresentations([])).toEqual(['cartoon']);
    expect(normaliseRepresentations(null)).toEqual(['cartoon']);
    expect(normaliseRepresentations('stick')).toEqual(['stick']);
  });

  it('keeps a cartoon under a surface drawn alone, so the model stays pickable', () => {
    expect(normaliseRepresentations(['surface'])).toEqual(['cartoon', 'surface']);
    const { style, surface } = representationStyle('surface', colour);
    expect(surface).toBe(true);
    expect(Object.keys(style).sort()).toEqual(['cartoon', 'line']);
  });

  it('combines representations into one style, each with the same colouring', () => {
    const { style, surface } = representationStyle(['cartoon', 'stick', 'surface'], colour);
    expect(surface).toBe(true);
    expect(style.cartoon).toMatchObject({ arrows: true, colorfunc: 'f' });
    expect(style.stick).toMatchObject({ radius: 0.15, colorfunc: 'f' });
    expect(style.sphere).toBeUndefined();
  });

  it('draws sticks with spheres as ball and stick', () => {
    const { style } = representationStyle(['stick', 'sphere'], { colorscheme: 'amino' });
    expect(style.stick).toMatchObject({ radius: 0.12, colorscheme: 'amino' });
    expect(style.sphere).toMatchObject({ scale: 0.22, colorscheme: 'amino' });
    expect(style.cartoon).toBeUndefined();
  });

  it('draws a trace as a thin cartoon, and a cartoon wins over a trace', () => {
    expect(representationStyle('trace', colour).style.cartoon).toMatchObject({ style: 'trace' });
    expect(representationStyle(['cartoon', 'trace'], colour).style.cartoon).toMatchObject({
      arrows: true,
    });
  });
});

describe('selectionStyle', () => {
  it('draws a picked site as red ball and stick', () => {
    const style = selectionStyle({ start: 12, end: 12 }, true, COLOURS);
    expect(style).toEqual({
      stick: { radius: 0.2, color: 'red' },
      sphere: { scale: 0.3, color: 'red' },
    });
  });

  it('keeps plain selection sticks past the site cap, or when the site is off', () => {
    const long = { start: 1, end: SITE_MAX_RESIDUES + 1 };
    expect(selectionStyle(long, true, COLOURS)).toEqual({ stick: { radius: 0.22, color: 'grape' } });
    expect(selectionStyle({ start: 3, end: 5 }, false, COLOURS)).toEqual({
      stick: { radius: 0.22, color: 'grape' },
    });
    expect(selectionStyle({ start: 1, end: SITE_MAX_RESIDUES }, true, COLOURS)).toHaveProperty('sphere');
  });
});

describe('frameSelection', () => {
  it('widens a short pick around its centre so its neighbourhood stays in view', () => {
    expect(frameSelection({ chain: 'A', start: 31, end: 31 })).toEqual({ chain: 'A', resi: '25-37' });
    expect(frameSelection({ chain: '', start: 2, end: 3 })).toEqual({ resi: '1-9' });
  });

  it('keeps a long enough span as it is', () => {
    expect(frameSelection({ chain: 'B', start: 10, end: 40 })).toEqual({ chain: 'B', resi: '10-40' });
  });
});
