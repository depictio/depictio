/**
 * src/pyodide/engine.ts with the runtime mocked: laziness, memoization, retry,
 * progress, the files written into Pyodide, package loading per recipe import,
 * the plotly pin check, and the JSON contract with depictio_studio.py. The
 * Python half runs for real in pyodideEngine.node.test.ts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  __setEngineHostForTests,
  engineAvailable,
  ensureEngine,
  loadPython,
  polarsSchema,
  runRecipe,
  type EngineHost,
  type PyodideApi,
} from '../pyodide/engine';
import pin from '../pyodide/generated/pin.json';

function fakePyodide(overrides: Record<string, (...a: string[]) => string> = {}) {
  const fs = new Map<string, string | Uint8Array>();
  const studio = {
    polars_schema: vi.fn(() => JSON.stringify([['date', 'String'], ['reads', 'Int64']])),
    imports_needed: vi.fn(() => JSON.stringify(['polars', 'pydantic'])),
    run_recipe: vi.fn(() =>
      JSON.stringify({
        ok: true,
        columns: [{ name: 'x', dtype: 'Int64' }],
        tsv: 'x\n1\n',
        rowCount: 1,
        outputSchema: { x: 'Int64' },
        stdout: '',
      }),
    ),
    destroy: vi.fn(),
    ...overrides,
  };
  const py = {
    loadPackage: vi.fn(async (_names: unknown, _opts?: unknown): Promise<unknown> => undefined),
    loadPackagesFromImports: vi.fn(async () => undefined),
    unpackArchive: vi.fn(),
    runPython: vi.fn(),
    runPythonAsync: vi.fn(async () => undefined),
    pyimport: vi.fn(() => studio),
    globals: { get: vi.fn(), set: vi.fn() },
    FS: { mkdirTree: vi.fn(), writeFile: vi.fn((p: string, d: string | Uint8Array) => fs.set(p, d)) },
  };
  return { py, studio, fs };
}

function hostFor(py: unknown, extra: Partial<EngineHost> = {}): EngineHost & { [k: string]: ReturnType<typeof vi.fn> } {
  return {
    loadPyodide: vi.fn(async () => py as PyodideApi),
    loadModules: vi.fn(async () => ({
      'depictio/recipes/__init__.py': '# recipes',
      'depictio/__init__.py': '',
    })),
    fetchBytes: vi.fn(async () => new Uint8Array([1, 2, 3])),
    ...extra,
  } as never;
}

afterEach(() => __setEngineHostForTests(null));

describe('engine loading', () => {
  it('loads nothing until the first call, then boots once', async () => {
    const { py, fs } = fakePyodide();
    const host = hostFor(py);
    __setEngineHostForTests(host);
    expect(host.loadPyodide).not.toHaveBeenCalled();

    const phases: string[] = [];
    await ensureEngine((p) => phases.push(p.phase));
    await ensureEngine();
    await polarsSchema('f.csv', 'a\n1\n');

    expect(host.loadPyodide).toHaveBeenCalledTimes(1);
    expect(host.loadModules).toHaveBeenCalledTimes(1);
    expect(py.loadPackage).toHaveBeenCalledWith(['numpy', 'polars', 'pyyaml'], expect.any(Object));
    expect(phases).toEqual(['runtime', 'packages', 'modules', 'ready']);
    // The depictio modules and the engine's own Python land on sys.path's root.
    expect([...fs.keys()]).toEqual(
      expect.arrayContaining([
        '/home/pyodide/depictio_studio/depictio/recipes/__init__.py',
        '/home/pyodide/depictio_studio/depictio_studio.py',
      ]),
    );
    expect(String(fs.get('/home/pyodide/depictio_studio/depictio_studio.py'))).toContain('def run_recipe');
    expect(py.pyimport).toHaveBeenCalledWith('depictio_studio');
  });

  it('retries after a failed load instead of memoizing the failure', async () => {
    const { py } = fakePyodide();
    const loadPyodide = vi
      .fn()
      .mockRejectedValueOnce(new Error('CDN down'))
      .mockResolvedValueOnce(py as never);
    __setEngineHostForTests(hostFor(py, { loadPyodide }));
    await expect(ensureEngine()).rejects.toThrow('CDN down');
    await expect(ensureEngine()).resolves.toBeUndefined();
    expect(loadPyodide).toHaveBeenCalledTimes(2);
  });

  it('turns a package error callback into a rejection', async () => {
    const { py } = fakePyodide();
    py.loadPackage.mockImplementationOnce(async (_n: unknown, opts?: unknown) => {
      (opts as { errorCallback: (m: string) => void }).errorCallback('polars: 404');
      return undefined;
    });
    __setEngineHostForTests(hostFor(py));
    await expect(ensureEngine()).rejects.toThrow('polars: 404');
  });

  it('reports what the browser can do', () => {
    expect(typeof engineAvailable()).toBe('boolean');
    const saved = globalThis.WebAssembly;
    // @ts-expect-error simulate a browser without WebAssembly
    delete globalThis.WebAssembly;
    try {
      expect(engineAvailable()).toBe(false);
    } finally {
      globalThis.WebAssembly = saved;
    }
  });
});

describe('polarsSchema / runRecipe contract', () => {
  let fake: ReturnType<typeof fakePyodide>;
  beforeEach(() => {
    fake = fakePyodide();
    __setEngineHostForTests(hostFor(fake.py));
  });

  it('keeps the column order Python reports', async () => {
    const schema = await polarsSchema('data.tsv', 'date\treads\n2024-01-01\t3\n');
    expect(Object.entries(schema)).toEqual([
      ['date', 'String'],
      ['reads', 'Int64'],
    ]);
    expect(fake.studio.polars_schema).toHaveBeenCalledWith('data.tsv', 'date\treads\n2024-01-01\t3\n');
  });

  it('passes the files as JSON and loads the packages the recipe imports', async () => {
    const raw = [{ ref: 'cov', fileName: 'a.tsv', text: 'x\n1\n' }];
    const res = await runRecipe('code', raw);
    expect(res).toMatchObject({ ok: true, rowCount: 1, outputSchema: { x: 'Int64' } });
    expect(fake.studio.run_recipe).toHaveBeenCalledWith('code', JSON.stringify(raw));
    // polars is already there; pydantic resolves through the Pyodide lock.
    expect(fake.py.loadPackagesFromImports).toHaveBeenCalledWith('import pydantic', expect.any(Object));
    expect(fake.py.unpackArchive).not.toHaveBeenCalled();
  });

  it('fetches plotly at the pin and refuses a wheel whose sha256 differs', async () => {
    fake.studio.imports_needed.mockReturnValue(JSON.stringify(['plotly', 'polars']));
    await expect(runRecipe('import plotly.colors', [])).rejects.toThrow('sha256 mismatch');
    const host = hostFor(fake.py);
    __setEngineHostForTests(host);
    await expect(runRecipe('import plotly.colors', [])).rejects.toThrow('sha256 mismatch');
    expect(host.fetchBytes).toHaveBeenCalledWith(pin.extras.plotly.url);
    expect(fake.py.loadPackage).toHaveBeenCalledWith(['narwhals', 'packaging'], expect.any(Object));
  });

  it('unpacks plotly once when the hash matches (Code Mode path)', async () => {
    const bytes = new TextEncoder().encode('wheel');
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    const hex = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
    const original = pin.extras.plotly.sha256;
    pin.extras.plotly.sha256 = hex;
    try {
      const host = hostFor(fake.py, { fetchBytes: vi.fn(async () => bytes) });
      __setEngineHostForTests(host);
      await loadPython(['pandas'], { plotly: true });
      await loadPython(['pandas'], { plotly: true });
      expect(fake.py.unpackArchive).toHaveBeenCalledTimes(1);
      expect(fake.py.unpackArchive).toHaveBeenCalledWith(bytes, 'wheel');
      // Code Mode never pays for polars or the depictio modules.
      expect(fake.py.loadPackage).not.toHaveBeenCalledWith(['numpy', 'polars', 'pyyaml'], expect.anything());
      expect(host.loadModules).not.toHaveBeenCalled();
    } finally {
      pin.extras.plotly.sha256 = original;
    }
  });
});

describe('pin', () => {
  it('matches the pyodide loader version in package.json', async () => {
    const pkg = (await import('../../package.json')).default as { dependencies: Record<string, string> };
    expect(pkg.dependencies.pyodide).toBe(pin.version);
    expect(pin.base_url).toBe(`https://cdn.jsdelivr.net/pyodide/v${pin.version}/full/`);
  });
});
