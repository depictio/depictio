/**
 * `3dmol` in the static runtime: the conditional 3Dmol.js add-on.
 *
 * The base runtime leaves 3Dmol.js out (budget, RFC §13.4). A producer that
 * bundles a molecule_3d tile appends the library's own minified UMD build as
 * a classic `<script data-depictio-addon="3dmol">` (depictio/serverless/
 * addons.py), which defines `window["3Dmol"]` while the document parses —
 * before this deferred module runs. This module forwards to that global; with
 * no add-on it is the catalog stub (`CATALOG_PREVIEW_STUB`), so the tile shows
 * its "unavailable" message instead of a broken canvas.
 */
interface ThreeDmolGlobal {
  createViewer: (...args: unknown[]) => unknown;
  createViewerGrid: (...args: unknown[]) => unknown;
  createStereoViewer: (...args: unknown[]) => unknown;
  download: (...args: unknown[]) => unknown;
}

function lib(): ThreeDmolGlobal | undefined {
  const g = globalThis as unknown as Record<string, unknown>;
  return (g['3Dmol'] ?? g.$3Dmol) as ThreeDmolGlobal | undefined;
}

export const PREVIEW_UNAVAILABLE_MESSAGE =
  '3D preview unavailable: this bundle was built without the 3Dmol.js add-on';

/** True when no add-on is embedded (the hooks probe this flag). */
export const CATALOG_PREVIEW_STUB = !lib();

function call<K extends keyof ThreeDmolGlobal>(name: K, args: unknown[]): unknown {
  const l = lib();
  if (!l) throw new Error(PREVIEW_UNAVAILABLE_MESSAGE);
  return (l[name] as (...a: unknown[]) => unknown)(...args);
}

export const createViewer = (...args: unknown[]) => call('createViewer', args);
export const createViewerGrid = (...args: unknown[]) => call('createViewerGrid', args);
export const createStereoViewer = (...args: unknown[]) => call('createStereoViewer', args);
// Downloads reach the PDB / PubChem: never from a bundle.
export const download = (): never => {
  throw new Error('3Dmol downloads are not available in a read-only bundle');
};

export default { createViewer, createViewerGrid, createStereoViewer, download };
