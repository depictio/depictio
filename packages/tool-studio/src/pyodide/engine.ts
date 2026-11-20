/**
 * Tool Studio's Python engine: Pyodide + polars, the same runtime an exported
 * serverless dashboard embeds (depictio/serverless/pyodide/pin.json, copied to
 * ./generated/pin.json by scripts/genKinds.ts: Pyodide 314.0.7 / CPython
 * 3.14.2, polars 1.33.1, plotly 6.9.0), so what the Studio computes is what
 * depictio computes.
 *
 * Nothing loads until the first call. The Pyodide core and the wheels come
 * from the jsDelivr CDN at the pinned version (`pin.base_url`), each wheel
 * checked against the lock's sha256 by Pyodide; plotly, which is not in the
 * Pyodide distribution, comes from PyPI at the pinned URL and is checked
 * against the pinned sha256 here. The depictio modules a recipe imports
 * (depictio.recipes, recipes.lib, RecipeSource) are the server's own files,
 * served as public/pyodide/depictio_modules.json (see ./depictioModules.ts).
 *
 * The Python half is ./depictio_studio.py.
 */
import pin from './generated/pin.json';
import studioPy from './depictio_studio.py?raw';
import studioFigurePy from './studio_figure.py?raw';

export interface EngineProgress {
  phase: string;
  detail?: string;
}

export interface RecipeRunResult {
  ok: boolean;
  /** Result columns with their polars dtype names. */
  columns: Array<{ name: string; dtype: string }>;
  /** Result as TSV (header + up to 2000 rows). */
  tsv: string;
  rowCount: number;
  /** The recipe's declared OUTPUT_SCHEMA as dtype names (null if it never loaded). */
  outputSchema: Record<string, string> | null;
  stdout: string;
  /** Python traceback tail when ok=false. */
  error?: string;
}

export interface RawRecipeFile {
  /** The RecipeSource.ref this file feeds. */
  ref?: string;
  fileName: string;
  text: string;
  /** Path recorded in a `source_path` column (default: fileName). */
  sourcePath?: string;
}

/** The slice of the Pyodide API the engine uses. */
export interface PyodideApi {
  loadPackage(names: string | string[], opts?: Record<string, unknown>): Promise<unknown>;
  loadPackagesFromImports(code: string, opts?: Record<string, unknown>): Promise<unknown>;
  unpackArchive(buffer: Uint8Array, format: string, opts?: Record<string, unknown>): void;
  runPython(code: string): unknown;
  runPythonAsync(code: string): Promise<unknown>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  pyimport(name: string): any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  globals: { get(name: string): any; set(name: string, value: unknown): void };
  FS: { mkdirTree(path: string): void; writeFile(path: string, data: string | Uint8Array): void };
}

/** Where the engine gets its runtime and files. Swapped by tests only. */
export interface EngineHost {
  loadPyodide(): Promise<PyodideApi>;
  /** `{path: source}` of the depictio modules (depictio_modules.json `files`). */
  loadModules(): Promise<Record<string, string>>;
  /** `{path: source}` of the figure modules (depictio_figure_modules.json
   *  `files`, see ./figureModules.ts). Absent: no exact figure previews. */
  loadFigureModules?(): Promise<Record<string, string>>;
  fetchBytes(url: string): Promise<Uint8Array>;
}

export const PYODIDE_VERSION: string = pin.version;
const MODULE_ROOT = '/home/pyodide/depictio_studio';

const browserHost: EngineHost = {
  async loadPyodide() {
    const mod = await import('pyodide');
    if (mod.version !== pin.version) {
      throw new Error(
        `Pyodide loader ${mod.version} does not match the pinned runtime ${pin.version} ` +
          '(package.json "pyodide" must equal depictio/serverless/pyodide/pin.json version)',
      );
    }
    return (await mod.loadPyodide({
      indexURL: pin.base_url,
      stdout: () => undefined,
      stderr: () => undefined,
    })) as unknown as PyodideApi;
  },
  async loadModules() {
    const url = `${import.meta.env.BASE_URL}pyodide/depictio_modules.json`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`could not load ${url} (${res.status})`);
    return ((await res.json()) as { files: Record<string, string> }).files;
  },
  async loadFigureModules() {
    const url = `${import.meta.env.BASE_URL}pyodide/depictio_figure_modules.json`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`could not load ${url} (${res.status})`);
    return ((await res.json()) as { files: Record<string, string> }).files;
  },
  async fetchBytes(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`could not download ${url} (${res.status})`);
    return new Uint8Array(await res.arrayBuffer());
  },
};

let host: EngineHost = browserHost;
let corePromise: Promise<PyodideApi> | null = null;
let enginePromise: Promise<PyodideApi> | null = null;
let plotlyPromise: Promise<void> | null = null;
let figurePromise: Promise<PyodideApi> | null = null;
const listeners = new Set<(p: EngineProgress) => void>();

function emit(p: EngineProgress): void {
  for (const fn of listeners) {
    try {
      fn(p);
    } catch {
      // a progress listener never breaks the load
    }
  }
}

/** Memoize a load, forgetting it on failure so the next call retries (a
 *  transient CDN error must not brick the engine for the session). */
function once<T>(get: () => Promise<T> | null, set: (p: Promise<T> | null) => void, make: () => Promise<T>) {
  let p = get();
  if (!p) {
    p = make();
    set(p);
    p.catch(() => set(null));
  }
  return p;
}

async function withProgress<T>(onProgress: ((p: EngineProgress) => void) | undefined, run: () => Promise<T>) {
  if (onProgress) listeners.add(onProgress);
  try {
    return await run();
  } finally {
    if (onProgress) listeners.delete(onProgress);
  }
}

function core(): Promise<PyodideApi> {
  return once(
    () => corePromise,
    (p) => (corePromise = p),
    async () => {
      emit({ phase: 'runtime', detail: `Pyodide ${pin.version}` });
      return host.loadPyodide();
    },
  );
}

async function loadPackages(py: PyodideApi, names: string[]): Promise<void> {
  if (!names.length) return;
  emit({ phase: 'packages', detail: names.join(', ') });
  const errors: string[] = [];
  await py.loadPackage(names, {
    messageCallback: () => undefined,
    errorCallback: (msg: string) => errors.push(msg),
  });
  if (errors.length) throw new Error(`could not load ${names.join(', ')}: ${errors.join('; ')}`);
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes as BufferSource);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}

/** plotly at the serverless pin (6.9.0, pure Python, from PyPI), plus the
 *  Pyodide packages it imports. */
function ensurePlotly(py: PyodideApi): Promise<void> {
  return once(
    () => plotlyPromise,
    (p) => (plotlyPromise = p),
    async () => {
      await loadPackages(py, ['narwhals', 'packaging']);
      const meta = pin.extras.plotly;
      emit({ phase: 'packages', detail: `plotly ${meta.version}` });
      const bytes = await host.fetchBytes(meta.url);
      const got = await sha256Hex(bytes);
      if (got !== meta.sha256) throw new Error(`plotly wheel sha256 mismatch (${got})`);
      py.unpackArchive(bytes, 'wheel');
    },
  );
}

function writeModules(py: PyodideApi, files: Record<string, string>): void {
  for (const [path, source] of Object.entries(files)) {
    const full = `${MODULE_ROOT}/${path}`;
    py.FS.mkdirTree(full.slice(0, full.lastIndexOf('/')));
    py.FS.writeFile(full, source);
  }
}

function engine(): Promise<PyodideApi> {
  return once(
    () => enginePromise,
    (p) => (enginePromise = p),
    async () => {
      const py = await core();
      // pyyaml: depictio's record_sheets (YAML samplesheets) imports it.
      await loadPackages(py, ['numpy', 'polars', 'pyyaml']);
      emit({ phase: 'modules', detail: 'depictio.recipes' });
      writeModules(py, { ...(await host.loadModules()), 'depictio_studio.py': studioPy });
      py.runPython(
        `import sys\nif ${JSON.stringify(MODULE_ROOT)} not in sys.path: sys.path.insert(0, ${JSON.stringify(MODULE_ROOT)})`,
      );
      py.pyimport('depictio_studio');
      emit({ phase: 'ready' });
      return py;
    },
  );
}

/** True when this browser can run the engine at all (WebAssembly, fetch,
 *  BigInt64Array for Pyodide's FFI, SubtleCrypto for the plotly check). */
export function engineAvailable(): boolean {
  return (
    typeof WebAssembly === 'object' &&
    typeof WebAssembly.instantiate === 'function' &&
    typeof fetch === 'function' &&
    typeof BigInt64Array === 'function' &&
    typeof globalThis.crypto?.subtle?.digest === 'function'
  );
}

/** Load Pyodide + numpy + polars + the depictio modules (once; retried after a
 *  failure). `onProgress` hears the phases still to come: runtime, packages,
 *  modules, ready. */
export function ensureEngine(onProgress?: (p: EngineProgress) => void): Promise<void> {
  return withProgress(onProgress, async () => {
    await engine();
  });
}

/** The shared interpreter with extra Pyodide packages (and plotly) loaded, for
 *  callers that run their own Python — Code Mode (builder/pyodideRunner.ts).
 *  Does not load polars or the depictio modules. */
export function loadPython(
  packages: string[],
  opts: { plotly?: boolean } = {},
  onProgress?: (p: EngineProgress) => void,
): Promise<PyodideApi> {
  return withProgress(onProgress, async () => {
    const py = await core();
    await loadPackages(py, packages);
    if (opts.plotly) await ensurePlotly(py);
    return py;
  });
}

function call(py: PyodideApi, fn: string, ...args: string[]): string {
  return callIn(py, 'depictio_studio', fn, ...args);
}

function callIn(py: PyodideApi, module: string, fn: string, ...args: string[]): string {
  const mod = py.pyimport(module);
  try {
    return String(mod[fn](...args));
  } finally {
    mod.destroy?.();
  }
}

/** `{column: polars dtype name}` of a text fixture, exactly as `catalog validate`
 *  infers it (read_fixture_schema: `pl.read_csv(separator=<\t for .tsv, else ,>,
 *  infer_schema_length=10_000)`). Rejects with the Python error when polars
 *  cannot parse the file. */
export async function polarsSchema(fileName: string, text: string): Promise<Record<string, string>> {
  const py = await engine();
  const pairs = JSON.parse(call(py, 'polars_schema', fileName, text)) as Array<[string, string]>;
  return Object.fromEntries(pairs);
}

/** Run a catalog recipe the way depictio does (load_recipe → read SOURCES →
 *  validate_sources → transform → validate_schema). Files bind to sources by
 *  `ref`; with no refs, one source takes a single file (or every file, for a
 *  glob source), else each file goes to the source whose path/glob it matches.
 *  Python failures come back as `ok: false` + `error`; the promise rejects only
 *  when the engine itself cannot load. */
export async function runRecipe(code: string, raw: RawRecipeFile[]): Promise<RecipeRunResult> {
  const py = await engine();
  const needed = JSON.parse(call(py, 'imports_needed', code)) as string[];
  if (needed.includes('plotly')) await ensurePlotly(py);
  const fromLock = needed.filter((n) => n !== 'plotly' && n !== 'polars' && n !== 'numpy');
  if (fromLock.length) {
    // Resolved against the Pyodide lock's import names; anything unknown
    // (not in the distribution) is left for the import to report.
    emit({ phase: 'packages', detail: fromLock.join(', ') });
    await py.loadPackagesFromImports(fromLock.map((n) => `import ${n}`).join('\n'), {
      messageCallback: () => undefined,
    });
  }
  return JSON.parse(call(py, 'run_recipe', code, JSON.stringify(raw))) as RecipeRunResult;
}

// ---- exact figures ----------------------------------------------------------

/** The engine plus plotly and depictio's figure modules (./figureModules.ts),
 *  imported once so the first figure does not pay for plotly.express. */
function figureEngine(): Promise<PyodideApi> {
  return once(
    () => figurePromise,
    (p) => (figurePromise = p),
    async () => {
      if (!host.loadFigureModules) throw new Error('this build ships no figure modules');
      const py = await engine();
      await loadPackages(py, ['pydantic']);
      await ensurePlotly(py);
      emit({ phase: 'modules', detail: 'depictio figure builder' });
      writeModules(py, { ...(await host.loadFigureModules()), 'studio_figure.py': studioFigurePy });
      py.pyimport('studio_figure');
      py.runPython(
        [
          'import depictio.api.v1.services.figure.figure_builder',
          'import depictio.api.v1.services.figure.aggregate',
          'import depictio.api.v1.services.figure.style_presets',
          'from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates',
          'ensure_mantine_templates()',
        ].join('\n'),
      );
      emit({ phase: 'ready' });
      return py;
    },
  );
}

/** A UI-mode figure as depictio's API would return it for the component. */
export interface FigureRenderSpec {
  visu_type: string;
  dict_kwargs: Record<string, unknown>;
  /** Component fields `figure_style_payload` reads (figure_style, title,
   *  hide_legend) and `max_points`. */
  [field: string]: unknown;
}

export interface FigureFixture {
  fileName: string;
  /** The fixture file, read by polars as `catalog validate` reads it. */
  text: string;
  /** Row indices the preview filters keep (null/undefined: every row), over
   *  `rows` rows. */
  keep?: number[] | null;
  rows?: number;
}

export interface ExactFigure {
  figure: { data: unknown[]; layout: Record<string, unknown> };
  metadata: {
    visu_type: string;
    was_sampled: boolean;
    displayed_data_count: number;
    total_data_count: number;
    aggregated: boolean;
  };
  /** `create_figure_from_data` failed and returned its error figure; the
   *  messages it logged. */
  errors: string[];
}

/** Load the figure engine (Pyodide, polars, plotly and depictio's figure
 *  modules) without rendering anything. */
export function ensureFigureEngine(onProgress?: (p: EngineProgress) => void): Promise<void> {
  return withProgress(onProgress, async () => {
    await figureEngine();
  });
}

/** Build a UI-mode figure with depictio's own code (`create_figure_from_data`,
 *  the aggregation fast path, `tidy_facet_layout`, `apply_figure_style`) over
 *  the fixture, themed with depictio's mantine_light / mantine_dark template.
 *  Rejects when the engine cannot load or the request cannot be honoured (a
 *  mask over a different row count); a figure depictio itself would draw as an
 *  error comes back with `errors`. */
export async function renderFigure(
  spec: FigureRenderSpec,
  fixture: FigureFixture,
  theme: 'light' | 'dark',
  style?: unknown,
): Promise<ExactFigure> {
  const py = await figureEngine();
  const extra = JSON.parse(callIn(py, 'studio_figure', 'packages_needed', JSON.stringify(spec))) as string[];
  if (extra.length) await loadPackages(py, extra);
  const request = { metadata: spec, theme, style: style ?? null, keep: fixture.keep ?? null, rows: fixture.rows ?? null };
  return JSON.parse(
    callIn(py, 'studio_figure', 'render_figure', JSON.stringify(request), fixture.fileName, fixture.text),
  ) as ExactFigure;
}

/** Test seam: swap the host (null restores the browser one) and forget any
 *  loaded runtime. */
export function __setEngineHostForTests(next: EngineHost | null): void {
  host = next ?? browserHost;
  corePromise = null;
  enginePromise = null;
  plotlyPromise = null;
  figurePromise = null;
  listeners.clear();
}
