/**
 * Exact figure previews wired into the api shim, with the Pyodide engine
 * mocked: approximation first, background load on request, the exact figure
 * once ready (filters as a row mask, theme, style), debounce, cache, and the
 * fallbacks (engine fails to load, a render fails, a package Pyodide lacks).
 * The Python half runs for real in figureEngine.node.test.ts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { InteractiveFilter } from 'depictio-react-core/api';

const engine = vi.hoisted(() => ({
  engineAvailable: vi.fn(() => true),
  ensureFigureEngine: vi.fn(async () => undefined),
  renderFigure: vi.fn(),
}));
vi.mock('../pyodide/engine', () => engine);

import { parseFixture } from '../catalog/parseFixture';
import { registerComponent, setActiveFixture, unregisterComponent } from '../api/fixtureRegistry';
import { previewFigure, renderFigure } from '../api/studioApi';
import {
  __resetExactFiguresForTests,
  requestExactFigures,
  useExactFigures,
} from '../viz/exactFigures';

const CSV = ['gene,log2fc,sample', 'A,1.5,S1', 'B,-0.5,S1', 'C,2.0,S2', 'D,0.1,S3'].join('\n');
const META = { index: 'fig-1', component_type: 'figure', visu_type: 'scatter', dict_kwargs: { x: 'gene', y: 'log2fc' } };

const pick = (value: string[]): InteractiveFilter => ({
  index: 'flt',
  value,
  column_name: 'sample',
  interactive_component_type: 'MultiSelect',
  metadata: { dc_id: 'studio', column_name: 'sample', interactive_component_type: 'MultiSelect' },
});

function exactResult(tag = 'exact') {
  return {
    figure: { data: [{ type: 'scattergl', name: tag }], layout: { template: { layout: { font: { color: '#343a40' } } } } },
    metadata: { visu_type: 'scatter', was_sampled: false, displayed_data_count: 4, total_data_count: 4, aggregated: false },
    errors: [],
  };
}

async function becomeReady() {
  requestExactFigures();
  await vi.waitFor(() => expect(useExactFigures.getState().status).toBe('ready'));
}

beforeEach(() => {
  __resetExactFiguresForTests();
  engine.engineAvailable.mockReturnValue(true);
  engine.ensureFigureEngine.mockReset().mockResolvedValue(undefined);
  engine.renderFigure.mockReset().mockResolvedValue(exactResult());
  setActiveFixture(parseFixture('golden.csv', CSV));
  registerComponent(META);
});
afterEach(() => unregisterComponent('fig-1'));

describe('exact figure previews', () => {
  it('answers with the approximation until the engine is loaded, and loads nothing by itself', async () => {
    const res = await renderFigure('d', 'fig-1', [], 'dark');
    expect(engine.ensureFigureEngine).not.toHaveBeenCalled();
    expect(engine.renderFigure).not.toHaveBeenCalled();
    // The approximation: plotly.js traces themed client-side, no template.
    expect((res.figure.layout as Record<string, unknown>).template).toBeUndefined();
    expect((res.figure.layout as { font: { color: string } }).font.color).toBe('#c1c2c5');
    expect(useExactFigures.getState().fidelity['fig-1']).toEqual({ fidelity: 'approximate', reason: 'loading' });
  });

  it('loads once on request, moves the epoch, then serves depictio’s figure untouched', async () => {
    requestExactFigures();
    requestExactFigures();
    expect(useExactFigures.getState().status).toBe('loading');
    await vi.waitFor(() => expect(useExactFigures.getState().status).toBe('ready'));
    expect(engine.ensureFigureEngine).toHaveBeenCalledTimes(1);
    expect(useExactFigures.getState().epoch).toBe(1);

    const res = await renderFigure('d', 'fig-1', [], 'dark', false, undefined, { style: { figure_style: 'minimal' } });
    expect(res.figure).toEqual(exactResult().figure);
    expect(res.metadata).toMatchObject({ visu_type: 'scatter', filter_applied: false, full_data_loaded: true });
    const [spec, fixture, theme, style] = engine.renderFigure.mock.calls[0];
    expect(spec).toEqual({ visu_type: 'scatter', dict_kwargs: { x: 'gene', y: 'log2fc' } });
    expect(fixture).toEqual({ fileName: 'golden.csv', text: CSV, keep: null, rows: 4 });
    expect(theme).toBe('dark');
    expect(style).toEqual({ figure_style: 'minimal' });
    expect(useExactFigures.getState().fidelity['fig-1']).toEqual({ fidelity: 'exact', reason: undefined });
  });

  it('hands the preview filters over as the kept row indices', async () => {
    await becomeReady();
    const res = await renderFigure('d', 'fig-1', [pick(['S1', 'S3'])], 'light');
    expect(engine.renderFigure.mock.calls[0][1]).toMatchObject({ keep: [0, 1, 3], rows: 4 });
    expect(res.metadata.filter_applied).toBe(true);
  });

  it('debounces a burst of renders of one figure to the last one, and caches it', async () => {
    await becomeReady();
    const first = renderFigure('d', 'fig-1', [pick(['S1'])], 'light');
    const last = renderFigure('d', 'fig-1', [pick(['S2'])], 'light');
    const [a, b] = await Promise.all([first, last]);
    expect(engine.renderFigure).toHaveBeenCalledTimes(1);
    expect(engine.renderFigure.mock.calls[0][1]).toMatchObject({ keep: [2] });
    // The superseded one got the approximation (its caller has moved on).
    expect((a.figure.layout as Record<string, unknown>).template).toBeUndefined();
    expect(b.figure).toEqual(exactResult().figure);

    await renderFigure('d', 'fig-1', [pick(['S2'])], 'light');
    expect(engine.renderFigure).toHaveBeenCalledTimes(1);
  });

  it('falls back to the approximation when a render fails', async () => {
    await becomeReady();
    engine.renderFigure.mockRejectedValueOnce(new Error('the preview filters were computed over 4 rows, polars reads 5'));
    const res = await renderFigure('d', 'fig-1', [], 'light');
    expect((res.figure.layout as Record<string, unknown>).template).toBeUndefined();
    expect(useExactFigures.getState().fidelity['fig-1']).toEqual({
      fidelity: 'approximate',
      reason: 'the preview filters were computed over 4 rows, polars reads 5',
    });
  });

  it('falls back when depictio errored on a package Pyodide lacks, but keeps a real error figure', async () => {
    await becomeReady();
    engine.renderFigure.mockResolvedValueOnce({
      ...exactResult(),
      errors: ["Figure creation failed: No module named 'plotly_complexheatmap'"],
    });
    let res = await renderFigure('d', 'fig-1', [], 'light');
    expect((res.figure.layout as Record<string, unknown>).template).toBeUndefined();

    engine.renderFigure.mockResolvedValueOnce({
      ...exactResult('error'),
      errors: ["Figure creation failed: Value of 'x' is not the name of a column"],
    });
    res = await renderFigure('d', 'fig-1', [], 'dark');
    expect(res.figure).toEqual(exactResult('error').figure);
  });

  it('stays on the approximation for the session when the engine cannot load', async () => {
    engine.ensureFigureEngine.mockRejectedValueOnce(new Error('could not download pyodide.asm.wasm'));
    requestExactFigures();
    await vi.waitFor(() => expect(useExactFigures.getState().status).toBe('failed'));
    expect(useExactFigures.getState().error).toContain('pyodide.asm.wasm');
    requestExactFigures();
    expect(engine.ensureFigureEngine).toHaveBeenCalledTimes(1);
    const res = await renderFigure('d', 'fig-1', [], 'light');
    expect(engine.renderFigure).not.toHaveBeenCalled();
    expect(res.figure.data?.length).toBeGreaterThan(0);
  });

  it('does not load where Pyodide cannot run', async () => {
    engine.engineAvailable.mockReturnValue(false);
    requestExactFigures();
    await vi.waitFor(() => expect(useExactFigures.getState().status).toBe('failed'));
    expect(engine.ensureFigureEngine).not.toHaveBeenCalled();
  });

  it('serves the builder preview in the app scheme, under its own debounce key', async () => {
    await becomeReady();
    document.documentElement.setAttribute('data-mantine-color-scheme', 'dark');
    try {
      await previewFigure({ metadata: { visu_type: 'histogram', dict_kwargs: { x: 'log2fc' }, figure_style: 'minimal' } });
    } finally {
      document.documentElement.removeAttribute('data-mantine-color-scheme');
    }
    const [spec, , theme] = engine.renderFigure.mock.calls[0];
    expect(theme).toBe('dark');
    expect(spec).toEqual({ visu_type: 'histogram', dict_kwargs: { x: 'log2fc' }, figure_style: 'minimal' });
    expect(useExactFigures.getState().fidelity.builder?.fidelity).toBe('exact');
  });

  it('a cache hit supersedes an older render still in flight', async () => {
    await becomeReady();
    // Warm the cache for S2.
    await renderFigure('d', 'fig-1', [pick(['S2'])], 'light');
    // A slow S1 render starts, then S2 (cached) answers at once.
    let release!: (v: unknown) => void;
    engine.renderFigure.mockImplementationOnce(() => new Promise((r) => (release = r)));
    const slow = renderFigure('d', 'fig-1', [pick(['S1'])], 'light');
    await vi.waitFor(() => expect(engine.renderFigure).toHaveBeenCalledTimes(2));
    const fresh = await renderFigure('d', 'fig-1', [pick(['S2'])], 'light');
    expect(fresh.figure).toEqual(exactResult().figure);
    release(exactResult('stale'));
    // The stale S1 answer is not handed out as an exact figure.
    const late = await slow;
    expect(late.figure).not.toEqual(exactResult('stale').figure);
  });

  it('an aborted render is not served after the engine answers', async () => {
    await becomeReady();
    const { exactFigure, SupersededRender } = await import('../viz/exactFigures');
    let release!: (v: unknown) => void;
    engine.renderFigure.mockImplementationOnce(() => new Promise((r) => (release = r)));
    const ctrl = new AbortController();
    const fixture = parseFixture('golden.csv', CSV);
    const p = exactFigure({
      key: 'k',
      spec: { visu_type: 'bar', dict_kwargs: {} },
      fixtureRef: fixture,
      fixture: { fileName: 'golden.csv', text: CSV, keep: null, rows: 4 },
      theme: 'light',
      signal: ctrl.signal,
    });
    await vi.waitFor(() => expect(engine.renderFigure).toHaveBeenCalled());
    ctrl.abort();
    release(exactResult());
    await expect(p).rejects.toBeInstanceOf(SupersededRender);
  });

  it('a newer builder preview aborts the one before it', async () => {
    await becomeReady();
    let release!: (v: unknown) => void;
    engine.renderFigure.mockImplementationOnce(() => new Promise((r) => (release = r)));
    const older = previewFigure({ metadata: { visu_type: 'histogram', dict_kwargs: { x: 'log2fc' } } });
    await vi.waitFor(() => expect(engine.renderFigure).toHaveBeenCalledTimes(1));
    const newer = await previewFigure({ metadata: { visu_type: 'bar', dict_kwargs: { x: 'gene' } } });
    expect(newer.figure).toEqual(exactResult().figure);
    release(exactResult('stale'));
    expect((await older).figure).not.toEqual(exactResult('stale').figure);
  });
});
