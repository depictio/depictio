import { beforeEach, describe, expect, it, vi } from 'vitest';

// A stand-in for react-plotly.js's component, so the real Plotly never loads.
// Its componentDidUpdate is the original's change test (identity of data,
// layout and config, frames length, revision), counting a redraw where the
// original would call Plotly.react.
const stub = vi.hoisted(() => {
  interface Props {
    data?: unknown;
    layout?: unknown;
    config?: unknown;
    frames?: unknown[];
    revision?: number;
    onClick?: () => void;
  }
  const calls = { mounts: 0, redraws: 0, syncs: 0 };
  class Plot {
    props: Props;
    p: Promise<unknown> = Promise.resolve();
    el: { on: () => void } | null = { on: () => {} };
    unmounting = false;
    attached: (() => void) | undefined;
    constructor(props: Props) {
      this.props = props;
    }
    componentDidMount() {
      calls.mounts += 1;
    }
    componentDidUpdate(prev: Props) {
      const frames = (f?: unknown[]) => (f && f.length ? f.length : 0);
      const figureChanged = !(
        prev.layout === this.props.layout &&
        prev.data === this.props.data &&
        prev.config === this.props.config &&
        frames(prev.frames) === frames(this.props.frames)
      );
      const revisionDefined = prev.revision !== undefined;
      const revisionChanged = prev.revision !== this.props.revision;
      if (!figureChanged && (!revisionDefined || !revisionChanged)) return;
      calls.redraws += 1;
      this.syncEventHandlers();
    }
    syncEventHandlers() {
      calls.syncs += 1;
      this.attached = this.props.onClick;
    }
    syncWindowResize() {}
  }
  return { Plot, calls };
});

vi.mock('react-plotly.js', () => ({ default: stub.Plot }));

const { sameContent, signatureOf } = await import('./plotlySkipIdenticalUpdate');

type Props = ConstructorParameters<typeof stub.Plot>[0];

const figure = (y: number[] = [1, 2, 3]): Props => ({
  data: [{ type: 'bar', x: ['a', 'b', 'c'], y }],
  layout: { title: { text: 'T' }, xaxis: {} },
  config: { displaylogo: false, responsive: true },
  revision: 0,
});

/** Mounts, then hands the plot `next` the way React does: props first, then the hook. */
function mount(props: Props) {
  const plot = new stub.Plot(props);
  plot.componentDidMount();
  return {
    plot,
    update(next: Props) {
      const prev = plot.props;
      plot.props = next;
      plot.componentDidUpdate(prev);
    },
  };
}

beforeEach(() => {
  stub.calls.mounts = 0;
  stub.calls.redraws = 0;
  stub.calls.syncs = 0;
});

describe('signatureOf / sameContent', () => {
  it('treats fresh objects with the same content as equal', () => {
    expect(sameContent(figure().data, figure().data)).toBe(true);
    expect(sameContent(figure([1, 2, 3]).data, figure([1, 2, 4]).data)).toBe(false);
  });

  it('never calls a figure holding a function equal, even to itself printed alike', () => {
    const withFn = () => ({ modeBarButtonsToAdd: [{ name: 'x', click: () => {} }] });
    expect(sameContent(withFn(), withFn())).toBe(false);
    const same = withFn();
    expect(sameContent(same, same)).toBe(true); // identity still holds
  });

  it('sees a change inside a typed array of the same length', () => {
    const a = { y: new Float64Array([1, 2, 3]) };
    const b = { y: new Float64Array([1, 2, 3]) };
    const c = { y: new Float64Array([1, 2, 4]) };
    expect(sameContent(a, b)).toBe(true);
    expect(sameContent(a, c)).toBe(false);
    // Same bytes, other element type: not the same figure.
    expect(sameContent({ y: new Uint8Array(8) }, { y: new Int8Array(8) })).toBe(false);
  });

  it('keeps the signature an object had when first signed', () => {
    const layout: Record<string, unknown> = { xaxis: {} };
    const before = signatureOf(layout);
    (layout.xaxis as Record<string, unknown>).range = [0, 10]; // Plotly writing back
    expect(signatureOf(layout)).toBe(before);
    expect(sameContent(layout, { xaxis: {} })).toBe(true);
  });
});

describe('patched componentDidUpdate', () => {
  it('skips the redraw of a fresh but identical figure', () => {
    const { update } = mount(figure());
    update(figure());
    update(figure());
    expect(stub.calls.redraws).toBe(0);
  });

  it('redraws when the data changes', () => {
    const { update } = mount(figure([1, 2, 3]));
    update(figure([1, 2, 9]));
    expect(stub.calls.redraws).toBe(1);
  });

  it('redraws on a revision bump with the same figure', () => {
    const { update } = mount(figure());
    update({ ...figure(), revision: 1 });
    expect(stub.calls.redraws).toBe(1);
  });

  it('redraws when the number of frames changes', () => {
    const { update } = mount({ ...figure(), frames: [{ name: 'a' }] });
    update({ ...figure(), frames: [{ name: 'a' }, { name: 'b' }] });
    expect(stub.calls.redraws).toBe(1);
  });

  it('always redraws a figure whose config holds a function', () => {
    const cfg = () => ({ modeBarButtonsToAdd: [{ name: 'x', click: () => {} }] });
    const { update } = mount({ ...figure(), config: cfg() });
    update({ ...figure(), config: cfg() });
    expect(stub.calls.redraws).toBe(1);
  });

  it('signs a changed figure before it is drawn, so the next identical copy is skipped', () => {
    const { plot, update } = mount(figure([1, 2, 3]));
    update(figure([4, 5, 6])); // data differs: the layout comparison short-circuits
    expect(stub.calls.redraws).toBe(1);
    // Plotly writes the autorange back into the layout object it drew.
    ((plot.props.layout as Record<string, Record<string, unknown>>).xaxis).range = [0, 2];
    update(figure([4, 5, 6]));
    expect(stub.calls.redraws).toBe(1);
  });

  it('still attaches the new event handlers when the redraw is skipped', async () => {
    const first = vi.fn();
    const second = vi.fn();
    const { plot, update } = mount({ ...figure(), onClick: first });
    update({ ...figure(), onClick: second });
    expect(stub.calls.redraws).toBe(0);
    await plot.p;
    expect(plot.attached).toBe(second);
  });

  it('does not touch the graph div of a plot unmounted before the resync runs', async () => {
    const { plot, update } = mount(figure());
    update({ ...figure(), onClick: vi.fn() });
    plot.unmounting = true;
    await plot.p;
    expect(stub.calls.syncs).toBe(0);
  });
});
