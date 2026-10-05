/**
 * Stand-in for `3dmol` in the single-file catalog preview build.
 *
 * `vite.catalog-preview.config.ts` aliases the bare `3dmol` import here. The
 * preview is ONE self-contained HTML with every dynamic import inlined, so the
 * real 3Dmol.js would be carried by every catalog page, protein or not. The
 * molecule_3d renderer catches the throw below and shows the message as its
 * empty state; the dashboards and the viewer bundle load the real library.
 */
export const CATALOG_PREVIEW_STUB = true;

export const PREVIEW_UNAVAILABLE_MESSAGE = '3D preview unavailable in the catalog';

function unavailable(): never {
  throw new Error(PREVIEW_UNAVAILABLE_MESSAGE);
}

export const createViewer = unavailable;
export const createViewerGrid = unavailable;
export const createStereoViewer = unavailable;
export const download = unavailable;

export default { createViewer, createViewerGrid, createStereoViewer, download };
