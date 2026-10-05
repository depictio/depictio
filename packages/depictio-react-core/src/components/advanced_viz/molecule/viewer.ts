/**
 * 3D structure viewer behind a narrow interface (3Dmol.js today).
 *
 * Adapted from PR #980's adapter and extended with what the dashboard needs:
 * residue hover and click callbacks, variant marks as spheres, a selection
 * drawn as side-chain sticks, a hover highlight as translucent spheres, labels,
 * representations drawn together (a cartoon under a surface), a picked site
 * as red ball and stick, spin and a disposal that releases the WebGL context.
 *
 * The module is loaded with `import('3dmol')` only, so the library stays in
 * its own chunk. The catalog preview aliases `3dmol` to a stub whose
 * `createViewer` throws; `createStructureViewer` lets that error through and
 * the renderer shows it as the empty state.
 *
 * Cost model: a restyle regenerates the model geometry, so it runs when the
 * colouring, the representation or the selection changes. A hover highlight
 * and the marks are shapes, which are cheap to add and remove, so hovering
 * never restyles. The overlay is three layers redrawn apart (the variant
 * marks, their emphasis, the hover highlight), so a hover only redraws the
 * few shapes it changes, not every mark.
 */

import type { StructureFormat } from './structureText';

export type Representation = 'cartoon' | 'trace' | 'stick' | 'sphere' | 'surface';

/** The residue under the pointer or the click. */
export interface ResidueRef {
  chain: string;
  position: number;
  resn: string;
}

export interface MarkSpec {
  chain: string;
  position: number;
  radius: number;
  colour: string;
  label: string;
  /** Selected elsewhere, or inside the selected range: drawn opaque and labelled. */
  emphasised: boolean;
}

export interface ResidueSpan {
  chain?: string | null;
  start: number;
  end: number;
}

/** Content key of a span, for effect dependencies and memo comparisons. */
export function spanKey(span: ResidueSpan | null): string {
  return span ? `${span.chain ?? ''}:${span.start}-${span.end}` : '';
}

export interface OverlayState {
  marks: MarkSpec[];
  showLabels: boolean;
  highlight: ResidueSpan | null;
}

export interface ViewerColours {
  background: string;
  selection: string;
  /** The picked site's ball and stick (`highlight_site`). */
  site: string;
  highlight: string;
  labelText: string;
  labelBackground: string;
}

/** Colour of one residue (chain, author number, B-factor, and the secondary
 *  structure 3Dmol assigned it: `h` helix, `s` strand, null coil). */
export type ResidueColourFn = (
  chain: string,
  position: number,
  b: number | null,
  ss?: string | null,
) => string;

/**
 * How residues are painted: a colour per residue, or one of 3Dmol's built-in
 * schemes (the `amino` residue-type table) when `scheme` is set.
 */
export interface ResiduePaint {
  colourOf: ResidueColourFn;
  scheme?: string | null;
}

/** The residues of a site drawn as ball and stick at most; a longer range
 *  keeps the plain selection sticks, a red wall of atoms says nothing. */
export const SITE_MAX_RESIDUES = 50;

export interface StructureViewer {
  /** Replace the model and fit the camera to it. */
  load(text: string, format: StructureFormat): void;
  /** Base style: how every residue is coloured, and the representations drawn. */
  setStyle(paint: ResiduePaint, reps: Representation | readonly Representation[]): void;
  /** Selected residues, drawn as sticks over the base style, or as the red
   *  ball and stick of a picked site when `asSite` (short spans only). */
  setSelection(span: ResidueSpan | null, asSite?: boolean): void;
  /** Marks, labels and hover highlight (shapes only, no restyle). */
  setOverlay(overlay: OverlayState): void;
  /** Zoom onto a span, or back onto the whole model with `null`. */
  focus(span: ResidueSpan | null, animate?: boolean): void;
  setColours(colours: ViewerColours): void;
  setSpin(on: boolean): void;
  resetView(): void;
  /** PNG data URL of the current view, or null if the canvas cannot be read. */
  snapshot(): string | null;
  /** Follow the host's new size. The camera is re-fitted (to the focused
   *  span, else the whole model) until the reader moves it by hand. */
  resize(): void;
  dispose(): void;
}

export interface ViewerCallbacks {
  onHover(residue: ResidueRef | null): void;
  onClick(residue: ResidueRef, extend: boolean): void;
}

// ---------------------------------------------------------------------------
// The slice of the 3Dmol API this adapter uses, typed structurally so the
// adapter does not depend on the library's generated declarations.
// ---------------------------------------------------------------------------

interface Atom {
  chain?: string;
  resi?: number;
  resn?: string;
  atom?: string;
  b?: number;
  ss?: string;
  x: number;
  y: number;
  z: number;
}

type Selection = Record<string, unknown>;

interface GlModel {
  selectedAtoms(sel: Selection): Atom[];
}

interface GlViewer {
  addModel(data: string, format: string): GlModel;
  removeAllModels(): void;
  setStyle(sel: Selection, style: Record<string, unknown>): void;
  addStyle(sel: Selection, style: Record<string, unknown>): void;
  addSurface(type: string, style: Record<string, unknown>, sel?: Selection): unknown;
  removeAllSurfaces(): void;
  addSphere(spec: Record<string, unknown>): unknown;
  removeShape(shape: unknown): void;
  addLabel(text: string, spec: Record<string, unknown>): unknown;
  removeLabel(label: unknown): void;
  setHoverable(sel: Selection, on: boolean, hover: unknown, unhover: unknown): void;
  setClickable(sel: Selection, on: boolean, cb: unknown): void;
  setHoverDuration(ms: number): void;
  selectedAtoms(sel: Selection): Atom[];
  zoomTo(sel?: Selection, duration?: number): void;
  setBackgroundColor(colour: string, alpha: number): void;
  spin(axis: string | boolean, speed?: number): void;
  render(): void;
  resize(): void;
  pngURI(): string;
  clear(): void;
  getCanvas?(): HTMLCanvasElement;
  // Internals the adapter neutralises on dispose (see `dispose`).
  container?: unknown;
  divwatcher?: { disconnect(): void };
  intwatcher?: { disconnect(): void };
}

interface ThreeDmolModule {
  createViewer(el: HTMLElement, config: Record<string, unknown>): GlViewer;
}

/** A 3Dmol selection for a residue span; the chain is left out when it is
 *  empty (a PDB with a blank chain column). */
export function spanSelection(span: ResidueSpan): Selection {
  const sel: Selection = { resi: `${span.start}-${span.end}` };
  if (span.chain) sel.chain = span.chain;
  return sel;
}

/** Residues framed around a short pick, so zooming onto one residue keeps its
 *  neighbourhood in view instead of filling the canvas with a single side chain. */
export const FRAME_MIN_RESIDUES = 13;

/** The selection the camera fits for a focused span: the span itself, widened
 *  around its centre to at least `FRAME_MIN_RESIDUES` residues. */
export function frameSelection(span: ResidueSpan): Selection {
  const width = span.end - span.start + 1;
  if (width >= FRAME_MIN_RESIDUES) return spanSelection(span);
  const pad = Math.ceil((FRAME_MIN_RESIDUES - width) / 2);
  return spanSelection({ ...span, start: Math.max(1, span.start - pad), end: span.end + pad });
}

/** Representations to draw, in a fixed order, without repeats: an empty list
 *  is a cartoon, and a surface alone keeps a cartoon under it so the model
 *  stays pickable (3Dmol does not hover or click a surface). */
export function normaliseRepresentations(
  reps: Representation | readonly Representation[] | null | undefined,
): Representation[] {
  let list: readonly Representation[] = [];
  if (typeof reps === 'string') list = [reps];
  else if (reps) list = reps;
  const order: Representation[] = ['cartoon', 'trace', 'stick', 'sphere', 'surface'];
  const out = order.filter((r) => list.includes(r));
  if (out.length === 0) return ['cartoon'];
  if (out.length === 1 && out[0] === 'surface') return ['cartoon', 'surface'];
  return out;
}

/**
 * The 3Dmol style of a set of representations with one colouring, and
 * whether a surface goes on top (a surface is not a style, it is added apart).
 * `colour` is the colour half of every sub-style: `{colorfunc}` or
 * `{colorscheme}`.
 */
export function representationStyle(
  reps: Representation | readonly Representation[] | null | undefined,
  colour: Record<string, unknown>,
): { style: Record<string, unknown>; surface: boolean } {
  const list = normaliseRepresentations(reps);
  const style: Record<string, unknown> = {};
  // A thin backbone line under the ribbons keeps a structure visible when no
  // cartoon geometry is produced (very short peptides, CA-only models).
  if (list.includes('cartoon')) {
    style.cartoon = { arrows: true, ...colour };
    style.line = { ...colour };
  } else if (list.includes('trace')) {
    style.cartoon = { style: 'trace', thickness: 0.5, ...colour };
    style.line = { ...colour };
  }
  // Sticks drawn with spheres are ball and stick: thinner sticks, smaller balls.
  const both = list.includes('stick') && list.includes('sphere');
  if (list.includes('stick')) style.stick = { radius: both ? 0.12 : 0.15, ...colour };
  if (list.includes('sphere')) style.sphere = { scale: both ? 0.22 : 0.28, ...colour };
  if (Object.keys(style).length === 0) style.line = { ...colour };
  return { style, surface: list.includes('surface') };
}

/** The style a selection is drawn with over the base style. */
export function selectionStyle(
  span: ResidueSpan,
  asSite: boolean,
  colours: Pick<ViewerColours, 'selection' | 'site'>,
): Record<string, unknown> {
  const length = span.end - span.start + 1;
  if (asSite && length <= SITE_MAX_RESIDUES) {
    return {
      stick: { radius: 0.2, color: colours.site },
      sphere: { scale: 0.3, color: colours.site },
    };
  }
  return { stick: { radius: 0.22, color: colours.selection } };
}

function residueOf(atom: Atom | null | undefined): ResidueRef | null {
  if (!atom || typeof atom.resi !== 'number') return null;
  return { chain: atom.chain ?? '', position: atom.resi, resn: atom.resn ?? '' };
}

/** Lose the WebGL context of a viewer's canvas and take it out of the page, so
 *  the slot the tile gave back is really free (a context outlives its canvas
 *  otherwise). */
function releaseCanvas(canvas: HTMLCanvasElement): void {
  try {
    const gl =
      (canvas.getContext('webgl2') as WebGL2RenderingContext | null) ??
      (canvas.getContext('webgl') as WebGLRenderingContext | null);
    gl?.getExtension('WEBGL_lose_context')?.loseContext();
  } catch {
    /* a canvas with another context type, or already lost */
  }
  canvas.remove();
}

/** Stand-in container of a disposed viewer: no size, no canvas. */
const DETACHED_CONTAINER = {
  offsetWidth: 0,
  offsetHeight: 0,
  style: {},
  querySelector: () => null,
};

/** Key of a mark's shape: what its sphere and its always-on label depend on. */
function markKey(m: MarkSpec): string {
  return `${m.chain}\u0000${m.position}\u0000${m.radius}\u0000${m.colour}\u0000${m.label}`;
}

/**
 * What each overlay layer is drawn from, as keys: a layer is redrawn only when
 * its key changes. `marks` is the variant spheres (and their labels when every
 * mark is labelled), `emphasis` the marks drawn larger, opaque and labelled
 * on top of them, `highlight` the hover span.
 */
export function overlayLayerKeys(overlay: OverlayState): {
  marks: string;
  emphasis: string;
  highlight: string;
} {
  const { marks, showLabels, highlight } = overlay;
  return {
    marks: `${showLabels ? 1 : 0}|${marks.map(markKey).join('\u0001')}`,
    emphasis: `${showLabels ? 1 : 0}|${marks
      .filter((m) => m.emphasised)
      .map(markKey)
      .join('\u0001')}`,
    highlight: spanKey(highlight),
  };
}

const HIGHLIGHT_MAX_RESIDUES = 60;

export async function createStructureViewer(
  container: HTMLElement,
  colours: ViewerColours,
  callbacks: ViewerCallbacks,
): Promise<StructureViewer> {
  const mod = (await import('3dmol')) as unknown as ThreeDmolModule & {
    default?: ThreeDmolModule;
  };
  const lib: ThreeDmolModule =
    typeof mod.createViewer === 'function' ? mod : (mod.default as ThreeDmolModule);
  // The catalog stub throws here; let it reach the caller.
  const before = new Set(Array.from(container.querySelectorAll('canvas')));
  const viewer = lib.createViewer(container, { backgroundColor: colours.background });
  // The canvas this viewer drew into. Another viewer may share the host (a
  // StrictMode remount, a flicker of the WebGL slot): dispose releases this
  // one only, never the canvas of a viewer created after it.
  const ownCanvas =
    viewer.getCanvas?.() ??
    Array.from(container.querySelectorAll('canvas')).find((c) => !before.has(c)) ??
    null;
  viewer.setHoverDuration(40);

  let current = colours;
  let model: GlModel | null = null;
  let paint: ResiduePaint = { colourOf: () => current.selection };
  let reps: Representation | readonly Representation[] = 'cartoon';
  let selection: ResidueSpan | null = null;
  let selectionAsSite = false;
  // One list of shapes and labels per overlay layer, with the key it was drawn from.
  interface Layer {
    key: string | null;
    shapes: unknown[];
    labels: unknown[];
  }
  const layers: Record<'marks' | 'emphasis' | 'highlight', Layer> = {
    marks: { key: null, shapes: [], labels: [] },
    emphasis: { key: null, shapes: [], labels: [] },
    highlight: { key: null, shapes: [], labels: [] },
  };
  let disposed = false;
  // The camera fit (whole model, or `focusSpan`) goes stale when the canvas
  // changes size after it (autofit tile height, the text split, the legend),
  // so `resize` re-fits it, until the reader drags or wheels the view by
  // hand. `load` and `resetView` hand the camera back to the fit.
  let userMoved = false;
  let focusSpan: ResidueSpan | null = null;
  // A drag, not a click: picking a residue must not count as moving the view.
  const DRAG_THRESHOLD_PX = 4;
  let pressAt: { x: number; y: number } | null = null;
  const onPointerDown = (e: PointerEvent) => {
    pressAt = { x: e.clientX, y: e.clientY };
  };
  const onPointerMove = (e: PointerEvent) => {
    if (!pressAt || !e.buttons) return;
    if (Math.hypot(e.clientX - pressAt.x, e.clientY - pressAt.y) >= DRAG_THRESHOLD_PX) {
      userMoved = true;
    }
  };
  const onPointerUp = () => {
    pressAt = null;
  };
  const onWheel = () => {
    userMoved = true;
  };
  const hostListeners: [string, EventListener][] = [
    ['pointerdown', onPointerDown as EventListener],
    ['pointermove', onPointerMove as EventListener],
    ['pointerup', onPointerUp],
    ['pointercancel', onPointerUp],
    ['wheel', onWheel],
  ];
  const canListen = typeof container.addEventListener === 'function';
  if (canListen) {
    for (const [type, fn] of hostListeners) {
      container.addEventListener(type, fn, { passive: true, capture: true });
    }
  }
  const fitCamera = () => {
    viewer.zoomTo(focusSpan ? frameSelection(focusSpan) : {}, 0);
  };

  const atomColour = (a: Atom) =>
    paint.colourOf(
      a.chain ?? '',
      a.resi ?? 0,
      typeof a.b === 'number' ? a.b : null,
      a.ss === 'h' || a.ss === 's' ? a.ss : null,
    );
  const colourSpec = (): Record<string, unknown> =>
    paint.scheme ? { colorscheme: paint.scheme } : { colorfunc: atomColour };

  const caOf = (chain: string, position: number): Atom | null => {
    const sel: Selection = { resi: position, atom: 'CA' };
    if (chain) sel.chain = chain;
    return viewer.selectedAtoms(sel)[0] ?? null;
  };

  const restyle = () => {
    if (!model) return;
    const { style, surface } = representationStyle(reps, colourSpec());
    viewer.setStyle({}, style);
    if (selection) {
      viewer.addStyle(spanSelection(selection), selectionStyle(selection, selectionAsSite, current));
    }
    viewer.removeAllSurfaces();
    if (surface) {
      viewer.addSurface('VDW', { opacity: 0.85, ...colourSpec() }, {});
    }
    viewer.render();
  };

  const clearLayer = (layer: Layer) => {
    for (const s of layer.shapes) viewer.removeShape(s);
    for (const l of layer.labels) viewer.removeLabel(l);
    layer.shapes = [];
    layer.labels = [];
    layer.key = null;
  };
  const clearOverlay = () => {
    clearLayer(layers.marks);
    clearLayer(layers.emphasis);
    clearLayer(layers.highlight);
  };

  const labelSpec = (at: Atom) => ({
    position: { x: at.x, y: at.y, z: at.z },
    fontSize: 11,
    fontColor: current.labelText,
    backgroundColor: current.labelBackground,
    backgroundOpacity: 0.8,
    borderThickness: 0,
    inFront: true,
    showBackground: true,
    alignment: 'bottomCenter',
  });

  const onAtomHover = (atom: Atom) => callbacks.onHover(residueOf(atom));
  const onAtomUnhover = () => callbacks.onHover(null);
  const onAtomClick = (atom: Atom, _v: unknown, event?: MouseEvent) => {
    const r = residueOf(atom);
    if (r) callbacks.onClick(r, Boolean(event?.shiftKey));
  };

  return {
    load(text, format) {
      viewer.removeAllModels();
      viewer.removeAllSurfaces();
      clearOverlay();
      model = viewer.addModel(text, format === 'mmcif' ? 'cif' : 'pdb');
      viewer.setHoverable({}, true, onAtomHover, onAtomUnhover);
      viewer.setClickable({}, true, onAtomClick);
      restyle();
      focusSpan = null;
      userMoved = false;
      viewer.zoomTo();
      viewer.render();
    },

    setStyle(nextPaint, nextReps) {
      paint = nextPaint;
      reps = nextReps;
      restyle();
    },

    setSelection(span, asSite = false) {
      selection = span;
      selectionAsSite = asSite;
      restyle();
    },

    setOverlay(overlay) {
      if (!model) return;
      const { marks, showLabels, highlight } = overlay;
      const keys = overlayLayerKeys(overlay);
      let changed = false;

      // A mark sphere, hoverable and clickable like the residue under it.
      const drawMark = (layer: Layer, mark: MarkSpec, emphasised: boolean, label: boolean) => {
        const ca = caOf(mark.chain, mark.position);
        if (!ca) return;
        const residue: ResidueRef = {
          chain: mark.chain,
          position: mark.position,
          resn: ca.resn ?? '',
        };
        layer.shapes.push(
          viewer.addSphere({
            center: { x: ca.x, y: ca.y, z: ca.z },
            radius: emphasised ? mark.radius * 1.25 : mark.radius,
            color: mark.colour,
            opacity: emphasised ? 1 : 0.8,
            hoverable: true,
            clickable: true,
            hover_callback: () => callbacks.onHover(residue),
            unhover_callback: () => callbacks.onHover(null),
            callback: (_s: unknown, _v: unknown, event?: MouseEvent) =>
              callbacks.onClick(residue, Boolean(event?.shiftKey)),
          }),
        );
        if (label) layer.labels.push(viewer.addLabel(mark.label, labelSpec(ca)));
      };

      if (layers.marks.key !== keys.marks) {
        clearLayer(layers.marks);
        for (const mark of marks) drawMark(layers.marks, mark, false, showLabels);
        layers.marks.key = keys.marks;
        changed = true;
      }

      // An emphasised mark: a larger opaque sphere over its plain one, and
      // its label unless every mark already carries one.
      if (layers.emphasis.key !== keys.emphasis) {
        clearLayer(layers.emphasis);
        for (const mark of marks) {
          if (mark.emphasised) drawMark(layers.emphasis, mark, true, !showLabels);
        }
        layers.emphasis.key = keys.emphasis;
        changed = true;
      }

      if (layers.highlight.key !== keys.highlight) {
        clearLayer(layers.highlight);
        if (highlight) {
          const n = highlight.end - highlight.start + 1;
          const step = Math.max(1, Math.ceil(n / HIGHLIGHT_MAX_RESIDUES));
          const cas = viewer
            .selectedAtoms({ ...spanSelection(highlight), atom: 'CA' })
            .filter((_a, i) => i % step === 0);
          for (const ca of cas) {
            layers.highlight.shapes.push(
              viewer.addSphere({
                center: { x: ca.x, y: ca.y, z: ca.z },
                radius: 2.2,
                color: current.highlight,
                opacity: 0.45,
              }),
            );
          }
        }
        layers.highlight.key = keys.highlight;
        changed = true;
      }
      if (changed) viewer.render();
    },

    focus(span, animate = true) {
      if (!model) return;
      // A programmatic fit: later resizes keep this span in frame.
      focusSpan = span;
      userMoved = false;
      viewer.zoomTo(span ? frameSelection(span) : {}, animate ? 500 : 0);
    },

    setColours(next) {
      current = next;
      viewer.setBackgroundColor(next.background, 1);
      // Labels and the highlight carry the old colours: redraw them next time.
      layers.emphasis.key = null;
      layers.marks.key = null;
      layers.highlight.key = null;
      restyle();
    },

    setSpin(on) {
      viewer.spin(on ? 'y' : false, 0.5);
    },

    resetView() {
      focusSpan = null;
      userMoved = false;
      viewer.zoomTo();
      viewer.render();
    },

    snapshot() {
      try {
        viewer.render();
        return viewer.pngURI();
      } catch {
        return null;
      }
    },

    resize() {
      if (disposed) return;
      viewer.resize();
      if (model && !userMoved) fitCamera();
      viewer.render();
    },

    dispose() {
      if (disposed) return;
      disposed = true;
      if (canListen) {
        for (const [type, fn] of hostListeners) {
          container.removeEventListener(type, fn, { capture: true });
        }
      }
      try {
        viewer.spin(false);
        viewer.clear();
      } catch {
        /* already torn down */
      }
      // 3Dmol keeps watching the host for resizes and, once its context is
      // lost, adopts whatever canvas it finds there on the next resize: the
      // live viewer's. Stop the watchers and point the stale viewer at an
      // empty stand-in (its window resize listener cannot be removed).
      viewer.divwatcher?.disconnect();
      viewer.intwatcher?.disconnect();
      viewer.container = DETACHED_CONTAINER;
      // Its canvas now, too: 3Dmol swaps in a new one after a lost context.
      const drawnOn = viewer.getCanvas?.();
      for (const canvas of new Set([ownCanvas, drawnOn])) {
        if (canvas && !before.has(canvas)) releaseCanvas(canvas);
      }
    },
  };
}
