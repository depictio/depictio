/**
 * The optional Python runtime of a bundle (Pyodide, serverless RFC §13.6).
 *
 * A producer embeds it only when a tile needs it (depictio/serverless/
 * addons.py::pyodide_html): one JSON meta block (`#depictio-pyodide-meta`:
 * version, packages, pruned lock, the server modules to run) and one inert
 * data block per file (`<script type="application/octet-stream" data-pya>`,
 * base64, gzip where it pays). Nothing is decoded until the first tile asks.
 *
 * Booting from a `file://` page with zero network: Pyodide is told its files
 * live under a fake origin (`BASE`), and `fetch` answers that origin from the
 * decoded blocks (the wasm with `application/wasm`, so streaming compile
 * works). Its two ES modules are imported from `blob:` URLs. Every other
 * request falls through to the page's fetch, which a bundle never uses.
 * Packages load with `checkIntegrity` against the lock's sha256.
 */
import { base64ToBytes } from 'depictio-static-core';

const META_ID = 'depictio-pyodide-meta';
const BASE = 'https://pyodide.bundle.invalid/';

interface PyodideMeta {
  version: string;
  packages: string[];
  extras: string[];
  lock: { packages: Record<string, { file_name: string }> } & Record<string, unknown>;
  modules: Record<string, string>;
}

/** The slice of the Pyodide API this module uses. */
interface PyodideApi {
  loadPackage(names: string[], opts?: Record<string, unknown>): Promise<unknown>;
  unpackArchive(buffer: Uint8Array, format: string, opts?: Record<string, unknown>): void;
  runPython(code: string): unknown;
  pyimport(name: string): Record<string, (...args: unknown[]) => unknown>;
  toPy(value: unknown): unknown;
  FS: { mkdirTree(path: string): void; writeFile(path: string, data: string): void };
}

export interface PythonTimings {
  version: string;
  decode_ms: number;
  boot_ms: number;
  packages_ms: number;
  import_ms: number;
  total_ms: number;
}

declare global {
  interface Window {
    /** Set once the runtime has booted (read by the offline specs). */
    __DEPICTIO_PYODIDE__?: PythonTimings;
  }
}

/** True when this bundle carries the Python runtime. */
export function pythonRuntimeEmbedded(): boolean {
  return typeof document !== 'undefined' && Boolean(document.getElementById(META_ID));
}

async function decode(el: HTMLElement): Promise<Uint8Array> {
  const bytes = base64ToBytes((el.textContent ?? '').trim());
  if (el.dataset.gz !== '1') return bytes;
  const stream = new Blob([bytes as BlobPart]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function installFetch(files: Map<string, Uint8Array>): void {
  const pageFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    if (url.startsWith(BASE)) {
      const name = url.slice(BASE.length).split(/[?#]/)[0];
      const body = files.get(name);
      if (!body) return new Response(`not in the bundle: ${name}`, { status: 404 });
      return new Response(body as BodyInit, {
        headers: {
          'Content-Type': name.endsWith('.wasm') ? 'application/wasm' : 'application/octet-stream',
        },
      });
    }
    return pageFetch(input, init);
  }) as typeof fetch;
}

function blobModule(bytes: Uint8Array): string {
  return URL.createObjectURL(new Blob([bytes as BlobPart], { type: 'text/javascript' }));
}

async function boot(): Promise<PyodideApi> {
  const t0 = performance.now();
  const metaEl = document.getElementById(META_ID);
  if (!metaEl) throw new Error('This bundle was built without the Python runtime.');
  const meta = JSON.parse(metaEl.textContent ?? '{}') as PyodideMeta;
  const files = new Map<string, Uint8Array>();
  for (const el of Array.from(document.querySelectorAll<HTMLElement>('script[data-pya]'))) {
    files.set(el.dataset.pya as string, await decode(el));
  }
  const tDecode = performance.now();
  installFetch(files);

  const need = (name: string) => {
    const f = files.get(name);
    if (!f) throw new Error(`Python runtime: ${name} is missing from the bundle`);
    return f;
  };
  const loader = (await import(/* @vite-ignore */ blobModule(need('pyodide.mjs')))) as {
    loadPyodide: (opts: Record<string, unknown>) => Promise<PyodideApi>;
  };
  const asm = (await import(/* @vite-ignore */ blobModule(need('pyodide.asm.mjs')))) as {
    default: unknown;
  };
  const py = await loader.loadPyodide({
    indexURL: BASE,
    packageBaseUrl: BASE,
    stdLibURL: `${BASE}python_stdlib.zip`,
    lockFileContents: meta.lock,
    createPyodideModule: asm.default,
    stdout: () => undefined,
    stderr: () => undefined,
  });
  const tBoot = performance.now();

  await py.loadPackage(
    meta.packages.map((n) => BASE + meta.lock.packages[n].file_name),
    { checkIntegrity: true, messageCallback: () => undefined },
  );
  const site = String(py.runPython('import site; site.getsitepackages()[0]'));
  for (const extra of meta.extras) py.unpackArchive(need(extra), 'zip', { extractDir: site });
  const root = '/home/pyodide/depictio_bundle';
  for (const [path, source] of Object.entries(meta.modules)) {
    const full = `${root}/${path}`;
    py.FS.mkdirTree(full.slice(0, full.lastIndexOf('/')));
    py.FS.writeFile(full, source);
  }
  py.runPython(`import sys; sys.path.insert(0, ${JSON.stringify(root)})`);
  const tPkgs = performance.now();
  py.pyimport('depictio_bundle');
  const tImport = performance.now();
  window.__DEPICTIO_PYODIDE__ = {
    version: meta.version,
    decode_ms: Math.round(tDecode - t0),
    boot_ms: Math.round(tBoot - tDecode),
    packages_ms: Math.round(tPkgs - tBoot),
    import_ms: Math.round(tImport - tPkgs),
    total_ms: Math.round(tImport - t0),
  };
  return py;
}

let booting: Promise<PyodideApi> | null = null;

/** The booted runtime (boots once, on first use). */
export function python(): Promise<PyodideApi> {
  if (!booting) {
    booting = boot();
    booting.catch(() => {
      booting = null;
    });
  }
  return booting;
}

/** Hand a bundled table (Arrow IPC) to Python once. */
export async function ensureTable(dcId: string, ipc: () => Uint8Array): Promise<void> {
  const py = await python();
  const mod = py.pyimport('depictio_bundle');
  if (mod.has_table(dcId)) return;
  mod.load_table(dcId, ipc());
}

/** Run one entry point of `depictio_bundle.py`; returns its parsed JSON. */
export async function callJob<T>(
  fn: 'code_figure' | 'group_compare' | 'embedding',
  request: unknown,
  dcId: string,
  mask: Uint8Array | null,
): Promise<T> {
  const py = await python();
  const mod = py.pyimport('depictio_bundle');
  try {
    // `undefined`, not `null`: Pyodide hands a JS null to Python as JsNull.
    return JSON.parse(String(mod[fn](JSON.stringify(request), dcId, mask ?? undefined))) as T;
  } catch (err) {
    // A Python exception arrives as a PythonError whose message is the whole
    // traceback; the last line is what the server would have said.
    const text = err instanceof Error ? err.message : String(err);
    const last = text.trim().split('\n').pop() ?? text;
    throw new Error(last.replace(/^[\w.]*(Error|Exception): /, ''));
  }
}
