/**
 * Exact figure previews: depictio's own figure code (create_figure_from_data
 * and the path around it) running in the Pyodide engine, swapped in for the
 * client-side approximation (./figureBuilder.ts) once the engine is loaded.
 *
 * Policy:
 *   - nothing loads on app start; the first figure preview on screen calls
 *     `requestExactFigures()` (RenderPreview), which loads the engine in the
 *     background (~30 MB: Pyodide, polars, plotly, the figure modules);
 *   - until then, and whenever the exact path fails, the shim answers with
 *     the approximation, so a preview is never slower than it was;
 *   - when the engine is ready `epoch` moves, which RenderPreview hands to the
 *     renderer as `refreshTick`, so every figure on screen refetches and gets
 *     the exact one;
 *   - each figure's last answer is recorded by component index (`fidelity`),
 *     which drives the one-line status under the preview.
 *
 * Exact renders are debounced per figure (a burst of filter clicks runs
 * Python once, for the last state) and cached by request (a theme toggle back
 * and forth is instant).
 */
import { create } from 'zustand';
import type { ExactFigure, FigureFixture, FigureRenderSpec } from '../pyodide/engine';

export type ExactStatus = 'idle' | 'loading' | 'ready' | 'failed';
export type Fidelity = 'exact' | 'approximate';

interface ExactFiguresState {
  status: ExactStatus;
  /** Why the engine could not load (status 'failed'). */
  error?: string;
  /** Bumped when the engine becomes ready: figures on screen refetch. */
  epoch: number;
  /** How each figure (by component index) was last drawn, and why not exact. */
  fidelity: Record<string, { fidelity: Fidelity; reason?: string }>;
  /** Milliseconds the engine took to load, once ready (for the status tooltip). */
  loadMs?: number;
}

export const useExactFigures = create<ExactFiguresState>(() => ({
  status: 'idle',
  epoch: 0,
  fidelity: {},
}));

type EngineModule = typeof import('../pyodide/engine');
const loadEngineModule = (): Promise<EngineModule> => import('../pyodide/engine');

/** Start loading the figure engine in the background (once; a failure stays
 *  failed for the session — the approximation keeps serving). */
export function requestExactFigures(): void {
  if (useExactFigures.getState().status !== 'idle') return;
  useExactFigures.setState({ status: 'loading' });
  const t0 = performance.now();
  loadEngineModule()
    .then(async (engine) => {
      if (!engine.engineAvailable()) throw new Error('this browser cannot run Pyodide');
      await engine.ensureFigureEngine();
      useExactFigures.setState((s) => ({
        status: 'ready',
        epoch: s.epoch + 1,
        loadMs: Math.round(performance.now() - t0),
      }));
    })
    .catch((err: unknown) => {
      useExactFigures.setState({ status: 'failed', error: err instanceof Error ? err.message : String(err) });
    });
}

export function exactFiguresReady(): boolean {
  return useExactFigures.getState().status === 'ready';
}

export function recordFidelity(key: string, fidelity: Fidelity, reason?: string): void {
  const cur = useExactFigures.getState().fidelity[key];
  if (cur && cur.fidelity === fidelity && cur.reason === reason) return;
  useExactFigures.setState((s) => ({ fidelity: { ...s.fidelity, [key]: { fidelity, reason } } }));
}

// ---- debounced, cached exact renders ----------------------------------------

/** Raised when a newer request for the same figure replaced this one. */
export class SupersededRender extends Error {
  constructor() {
    super('superseded by a newer render of the same figure');
  }
}

export const EXACT_DEBOUNCE_MS = 120;
const CACHE_SIZE = 48;
const cache = new Map<string, ExactFigure>();
const latest = new Map<string, number>();
let seq = 0;

const fixtureIds = new WeakMap<object, number>();
let nextFixtureId = 0;
function fixtureId(fixture: object): number {
  let id = fixtureIds.get(fixture);
  if (id === undefined) {
    id = ++nextFixtureId;
    fixtureIds.set(fixture, id);
  }
  return id;
}

export interface ExactRequest {
  /** The figure's identity for debouncing (component index, or 'builder'). */
  key: string;
  spec: FigureRenderSpec;
  /** Identifies the fixture for caching (the ParsedFixture object). */
  fixtureRef: object;
  fixture: FigureFixture;
  theme: 'light' | 'dark';
  style?: unknown;
  signal?: AbortSignal;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** The exact figure for `req`: from the cache, else after the debounce, unless
 *  a newer request for the same figure arrives first (SupersededRender) or the
 *  caller aborts. */
export async function exactFigure(req: ExactRequest): Promise<ExactFigure> {
  const cacheKey = JSON.stringify([
    fixtureId(req.fixtureRef),
    req.spec,
    req.theme,
    req.style ?? null,
    req.fixture.keep ?? null,
  ]);
  const hit = cache.get(cacheKey);
  if (hit) {
    cache.delete(cacheKey);
    cache.set(cacheKey, hit);
    return hit;
  }
  const token = ++seq;
  latest.set(req.key, token);
  await sleep(EXACT_DEBOUNCE_MS);
  if (latest.get(req.key) !== token || req.signal?.aborted) throw new SupersededRender();
  const engine = await loadEngineModule();
  const result = await engine.renderFigure(req.spec, req.fixture, req.theme, req.style);
  cache.set(cacheKey, result);
  if (cache.size > CACHE_SIZE) cache.delete(cache.keys().next().value as string);
  return result;
}

/** Test seam: back to a fresh session. */
export function __resetExactFiguresForTests(): void {
  useExactFigures.setState({ status: 'idle', error: undefined, epoch: 0, fidelity: {}, loadMs: undefined });
  cache.clear();
  latest.clear();
}
