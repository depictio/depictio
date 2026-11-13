// "Open in ...": the dedicated viewers a bioimage store is handed off to, and
// the URL each one opens. Depictio shows the image in its dashboard context;
// deep inspection (3D, plates, every channel at once) is theirs (ADR 0001).
//
// Which URL a viewer gets, in three tiers (see the API's bioimage_handoff):
//  1. a remote store: its own https URL;
//  2. a store of a public project: its URL on this server (read with CORS);
//  3. a private store: a signed link valid for a while, made on click.

import type { BioimageFormat } from '../../../api';
import type { NgffContainerLayout } from './layout';

export type HandoffTargetId = 'vizarr' | 'validator' | 'neuroglancer' | 'vitessce';

export interface HandoffTarget {
  id: HandoffTargetId;
  label: string;
  description: string;
  icon: string;
}

export const HANDOFF_TARGETS: readonly HandoffTarget[] = [
  {
    id: 'vizarr',
    label: 'vizarr',
    description: 'Every channel and plane of the image, plates included',
    icon: 'tabler:photo-search',
  },
  {
    id: 'neuroglancer',
    label: 'Neuroglancer',
    description: 'Volumes in 3D and orthogonal slices',
    icon: 'tabler:box',
  },
  {
    id: 'vitessce',
    label: 'Vitessce',
    description: 'The image in a spatial view with layer controls',
    icon: 'tabler:layout-dashboard',
  },
  {
    id: 'validator',
    label: 'OME-NGFF validator',
    description: 'Check the store against the NGFF spec, key by key',
    icon: 'tabler:checklist',
  },
];

/** What a target needs to know about the store it opens. */
export interface HandoffStore {
  name: string;
  format: BioimageFormat;
  layout?: NgffContainerLayout | null;
  /** The image group inside the store that the tile draws (a plate's well field). */
  imagePath?: string | null;
}

/** Why `target` cannot open `store`, or null when it can. */
export function unsupportedReason(target: HandoffTargetId, store: HandoffStore): string | null {
  const zarr = store.format !== 'ome-tiff';
  switch (target) {
    case 'vizarr':
      return zarr ? null : 'vizarr opens OME-Zarr stores only';
    case 'validator':
      return zarr ? null : 'The validator checks OME-Zarr stores only';
    case 'neuroglancer':
      return zarr ? null : 'Neuroglancer opens OME-Zarr stores only';
    case 'vitessce':
      return null;
  }
}

/** The URL of the group a target opens: the store root for the targets that
 *  walk a plate themselves (vizarr, the validator), else the image drawn. */
function sourceUrl(target: HandoffTargetId, storeUrl: string, store: HandoffStore): string {
  const root = storeUrl.replace(/\/+$/, '');
  if (target === 'vizarr' || target === 'validator' || !store.imagePath) return root;
  return `${root}/${store.imagePath.replace(/^\/+/, '')}`;
}

/** A minimal Vitessce view config: the image in a spatial view, with its layer controls. */
export function vitessceConfig(url: string, store: HandoffStore): Record<string, unknown> {
  return {
    version: '1.0.16',
    name: store.name,
    description: 'Opened from Depictio',
    initStrategy: 'auto',
    datasets: [
      {
        uid: 'image',
        name: store.name,
        files: [
          {
            fileType: store.format === 'ome-tiff' ? 'image.ome-tiff' : 'image.ome-zarr',
            url,
          },
        ],
      },
    ],
    coordinationSpace: {},
    layout: [
      { component: 'spatialBeta', x: 0, y: 0, w: 9, h: 12 },
      { component: 'layerControllerBeta', x: 9, y: 0, w: 3, h: 12 },
    ],
  };
}

/** The address that opens `storeUrl` (an absolute URL a browser can fetch) in `target`. */
export function handoffUrl(
  target: HandoffTargetId,
  storeUrl: string,
  store: HandoffStore,
): string {
  const url = sourceUrl(target, storeUrl, store);
  switch (target) {
    case 'vizarr':
      return `https://hms-dbmi.github.io/vizarr/?source=${encodeURIComponent(url)}`;
    case 'validator':
      return `https://ome.github.io/ome-ngff-validator/?source=${encodeURIComponent(url)}`;
    case 'neuroglancer': {
      // The state lives in the fragment, so it never reaches Neuroglancer's server.
      const state = {
        layers: [{ type: 'image', name: store.name, source: `zarr://${url}` }],
        layout: '4panel',
      };
      return `https://neuroglancer-demo.appspot.com/#!${encodeURIComponent(JSON.stringify(state))}`;
    }
    case 'vitessce': {
      const config = JSON.stringify(vitessceConfig(url, store));
      return `https://vitessce.io/#?url=data:,${encodeURIComponent(config)}`;
    }
  }
}

/** Commands to paste into a desktop tool, for the store at `storeUrl`. */
export function copyCommands(
  storeUrl: string,
  store: HandoffStore,
): Array<{ label: string; text: string }> {
  const url = storeUrl.replace(/\/+$/, '');
  const out = [{ label: 'Store URL', text: url }];
  if (store.format !== 'ome-tiff') {
    out.push({ label: 'napari', text: `napari --plugin napari-ome-zarr ${url}` });
  }
  return out;
}
