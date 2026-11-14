/**
 * Catalog-preview stand-in for the bioimage viewer adapter
 * (`packages/depictio-react-core/src/components/advanced_viz/bioimage/viewer.ts`).
 *
 * The single-file preview inlines every dynamic import, so the real adapter
 * would embed deck.gl, viv and the zarr codecs (several MB) in each preview
 * HTML. The preview can never show an image anyway: the pyramid is streamed
 * from the API, and the offline shim reports no stores. Aliased in by
 * `vite.catalog-preview.config.ts`.
 */
import type { BioimageViewer } from '../../../../packages/depictio-react-core/src/components/advanced_viz/bioimage/viewer';

export async function createBioimageViewer(): Promise<BioimageViewer> {
  throw new Error('The bioimage viewer is not available in the offline catalog preview.');
}
