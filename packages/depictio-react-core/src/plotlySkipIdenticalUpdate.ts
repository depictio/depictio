/**
 * Keeps react-plotly.js from redrawing a figure whose content did not change.
 *
 * The component redraws whenever `data`, `layout` or `config` is a new object,
 * and a renderer builds new ones on every render: a filter or selection change
 * on a dashboard re-rendered each tile several times with the same figure (a
 * map redrew 6 times, a bar chart 4-5 times per click), and each redraw
 * re-measures every label. Here a figure that comes back identical to the one
 * drawn is not redrawn, whichever renderer produced it, instead of
 * memoising at each of the ~50 call sites.
 *
 * "Identical" is a content signature (`JSON.stringify`, typed arrays folded to
 * a checksum), computed once per object. A figure holding a function (a custom
 * modebar button, a callback) has no signature and always redraws, since two
 * closures that print alike can differ in what they capture. A changed
 * `revision` still forces the redraw: it is the explicit refresh signal.
 *
 * Like plotlyStrictMode, this patches the `Plot` prototype and must be
 * imported before any Plot mounts.
 */
import Plot from 'react-plotly.js';

interface FigureProps {
  data?: unknown;
  layout?: unknown;
  config?: unknown;
  frames?: unknown[];
  revision?: number;
}

/** The parts of a react-plotly.js instance a skipped update still touches. */
interface PlotInstance {
  props: FigureProps & { onError?: (err: unknown) => void };
  p?: Promise<unknown>;
  el?: { on?: unknown } | null;
  unmounting?: boolean;
  syncEventHandlers?: () => void;
  syncWindowResize?: (invoke: boolean) => void;
}

type DidUpdate = ((this: PlotInstance, prev: FigureProps) => void) & {
  depictioSkipsIdentical?: true;
};
type DidMount = ((this: PlotInstance) => void) & { depictioSkipsIdentical?: true };

const NO_SIGNATURE = Symbol('no-signature');

const signatures = new WeakMap<object, string | typeof NO_SIGNATURE>();

function checksum(view: ArrayBufferView): string {
  const bytes = new Uint8Array(view.buffer, view.byteOffset, view.byteLength);
  let h = 2166136261;
  for (let i = 0; i < bytes.length; i++) h = Math.imul(h ^ bytes[i], 16777619);
  return `${view.constructor.name}:${bytes.length}:${h >>> 0}`;
}

export function signatureOf(value: unknown): string | typeof NO_SIGNATURE {
  if (value === null || typeof value !== 'object') return String(value);
  const cached = signatures.get(value);
  if (cached !== undefined) return cached;
  let sig: string | typeof NO_SIGNATURE;
  try {
    sig = JSON.stringify(value, (_key, v) => {
      if (typeof v === 'function') throw NO_SIGNATURE;
      if (ArrayBuffer.isView(v) && !(v instanceof DataView)) return checksum(v);
      return v;
    });
  } catch (err) {
    if (err !== NO_SIGNATURE) throw err;
    sig = NO_SIGNATURE;
  }
  signatures.set(value, sig);
  return sig;
}

export function sameContent(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') return false;
  const sa = signatureOf(a);
  return sa !== NO_SIGNATURE && sa === signatureOf(b);
}

// react-plotly.js attaches the event handler props (onClick, onSelected, ...)
// and the resize handler only after a redraw. A skipped redraw still has to
// swap them, or the graph div keeps calling the closures of an earlier render.
function resyncHandlers(plot: PlotInstance): void {
  plot.p = (plot.p ?? Promise.resolve())
    .then(() => {
      if (plot.unmounting || typeof plot.el?.on !== 'function') return;
      plot.syncWindowResize?.(false);
      plot.syncEventHandlers?.();
    })
    .catch((err) => plot.props.onError?.(err));
}

const proto = (Plot as unknown as {
  prototype: { componentDidUpdate?: DidUpdate; componentDidMount?: DidMount };
}).prototype;
const didUpdate = proto.componentDidUpdate;
const didMount = proto.componentDidMount;

// Plotly cleans the objects it is handed in place while drawing, so a figure
// is signed before its first draw: signed afterwards it would never match the
// fresh copy the next render hands over.
if (didMount && !didMount.depictioSkipsIdentical) {
  const signing: DidMount = function () {
    const { data, layout, config } = this.props;
    signatureOf(data);
    signatureOf(layout);
    signatureOf(config);
    didMount.call(this);
  };
  signing.depictioSkipsIdentical = true;
  proto.componentDidMount = signing;
}

// Guarded so a hot reload of this module does not wrap the method twice.
if (didUpdate && !didUpdate.depictioSkipsIdentical) {
  const skipping: DidUpdate = function (prev) {
    const next = this.props;
    // Signed before the original can draw them, whichever comparison below
    // short-circuits: a figure first signed after its draw carries what Plotly
    // wrote into it (autoranged axes) and never matches the next fresh copy.
    signatureOf(next.data);
    signatureOf(next.layout);
    signatureOf(next.config);
    const framesChanged = (prev.frames?.length ?? 0) !== (next.frames?.length ?? 0);
    const identical =
      !framesChanged &&
      prev.revision === next.revision &&
      sameContent(prev.data, next.data) &&
      sameContent(prev.layout, next.layout) &&
      sameContent(prev.config, next.config);
    // Handing the original the current props as the previous ones makes it see
    // no change and return before it touches Plotly.
    if (identical) resyncHandlers(this);
    didUpdate.call(this, identical ? next : prev);
  };
  skipping.depictioSkipsIdentical = true;
  proto.componentDidUpdate = skipping;
}
