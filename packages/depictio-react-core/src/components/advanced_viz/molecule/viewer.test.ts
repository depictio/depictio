import { describe, expect, it, vi } from 'vitest';

import { createStructureViewer, overlayLayerKeys, type MarkSpec, type ViewerColours } from './viewer';

// A 3Dmol stand-in for the node test environment: `createViewer` appends a
// canvas to the host, as the real one does, and counts the shapes it draws.
interface FakeCanvas {
  released: boolean;
  getContext(): null;
  remove(): void;
}

class FakeHost {
  canvases: FakeCanvas[] = [];
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
      zoomTo: () => {},
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
