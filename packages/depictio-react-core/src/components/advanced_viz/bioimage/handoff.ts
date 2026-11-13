// "Open in ...": the dedicated viewers a bioimage store is handed off to, and
// the URL each one opens. Depictio shows the image in its dashboard context;
// deep inspection (3D, plates, every channel at once) is theirs (ADR 0001).
//
// Which URL a viewer gets, in three tiers (see the API's bioimage_handoff):
//  1. a remote store: its own https URL;
//  2. a store of a public project: its URL on this server (read with CORS);
//  3. a private store: a signed link valid for a while, made on click.

import type { BioimageFormat } from '../../../api';
import { HANDOFF_LOGOS } from './handoffLogos';
import type { NgffContainerLayout } from './layout';

export type HandoffTargetId = 'vizarr' | 'validator' | 'neuroglancer' | 'vitessce';

export interface HandoffTarget {
  id: HandoffTargetId;
  label: string;
  /** One line under the name: what the viewer is good at. */
  description: string;
  /** The viewer's own logo, a data URI. */
  logo: string;
}

export const HANDOFF_TARGETS: readonly HandoffTarget[] = [
  {
    id: 'vizarr',
    label: 'vizarr',
    description: 'Every channel and plane at once, whole plates included',
    logo: HANDOFF_LOGOS.vizarr,
  },
  {
    id: 'neuroglancer',
    label: 'Neuroglancer',
    description: 'The volume in 3D, with slices along each axis',
    logo: HANDOFF_LOGOS.neuroglancer,
  },
  {
    id: 'vitessce',
    label: 'Vitessce',
    description: 'A spatial view with per-channel layer controls',
    logo: HANDOFF_LOGOS.vitessce,
  },
  {
    id: 'validator',
    label: 'OME-NGFF validator',
    description: 'Checks the store against the OME-NGFF spec, key by key',
    logo: HANDOFF_LOGOS.validator,
  },
];

/** A channel as the tile draws it. */
export interface HandoffChannel {
  index: number;
  /** `#rrggbb`. */
  color: string;
  visible: boolean;
  /** The contrast window: values at or below [0] are black, at or above [1] full colour. */
  window: readonly [number, number];
}

/** What the tile shows, so the other viewer opens on the same picture rather
 *  than on its own defaults (Neuroglancer stretches uint16 over 0-65535 and
 *  shows black; Vitessce asks for three channels and fails on two). */
export interface HandoffView {
  channels: readonly HandoffChannel[];
  /** The plane shown, for stores with that axis. */
  z?: number | null;
  t?: number | null;
  /** Image size in pixels at full resolution, to frame it whole. */
  width?: number | null;
  height?: number | null;
}

/** What a target needs to know about the store it opens. */
export interface HandoffStore {
  name: string;
  format: BioimageFormat;
  layout?: NgffContainerLayout | null;
  /** The image group inside the store that the tile draws (a plate's well field). */
  imagePath?: string | null;
  view?: HandoffView | null;
}

/** Most channels Vitessce's raster layer shades at once. */
const VITESSCE_MAX_CHANNELS = 6;

function hexToRgb(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return [255, 255, 255];
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
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

/**
 * A Vitessce view config: the image in a spatial view with its layer
 * controls, on the tile's channels (colour, window), plane and framing.
 *
 * Uses the `spatial` / `layerController` views and an explicit
 * `spatialImageLayer`: left to itself (`spatialBeta` with `initStrategy:
 * auto`), Vitessce selects three channels and throws "index out of bounds"
 * on a two-channel store, drawing nothing.
 */
export function vitessceConfig(url: string, store: HandoffStore): Record<string, unknown> {
  const view = store.view;
  const plane: Record<string, number> = {};
  if (view?.z != null) plane.z = view.z;
  if (view?.t != null) plane.t = view.t;
  const shown = (view?.channels ?? []).filter((c) => c.visible).slice(0, VITESSCE_MAX_CHANNELS);
  const channels = (shown.length
    ? shown
    : [{ index: 0, color: '#ffffff', visible: true, window: null }]
  ).map((c) => ({
    selection: { c: c.index, ...plane },
    color: hexToRgb(c.color),
    visible: true,
    ...(c.window ? { slider: [c.window[0], c.window[1]] } : {}),
  }));
  const coordinationSpace: Record<string, Record<string, unknown>> = {
    spatialImageLayer: {
      A: [
        {
          type: 'raster',
          index: 0,
          visible: true,
          opacity: 1,
          colormap: null,
          transparentColor: null,
          domainType: 'Min/Max',
          channels,
        },
      ],
    },
  };
  const scopes: Record<string, string> = { spatialImageLayer: 'A' };
  if (view?.width && view?.height) {
    // Pixel coordinates; zoom 0 is one image pixel per screen pixel.
    coordinationSpace.spatialZoom = {
      A: Math.round(Math.log2(700 / Math.max(view.width, view.height)) * 100) / 100,
    };
    coordinationSpace.spatialTargetX = { A: view.width / 2 };
    coordinationSpace.spatialTargetY = { A: view.height / 2 };
    Object.assign(scopes, { spatialZoom: 'A', spatialTargetX: 'A', spatialTargetY: 'A' });
  }
  const file =
    store.format === 'ome-tiff'
      ? {
          fileType: 'raster.json',
          options: {
            schemaVersion: '0.0.2',
            images: [{ name: store.name, type: 'ome-tiff', url }],
            renderLayers: [store.name],
          },
        }
      : { fileType: 'raster.ome-zarr', url };
  return {
    version: '1.0.16',
    name: store.name,
    description: 'Opened from Depictio',
    initStrategy: 'auto',
    datasets: [{ uid: 'image', name: store.name, files: [file] }],
    coordinationSpace,
    layout: [
      { component: 'spatial', x: 0, y: 0, w: 9, h: 12, coordinationScopes: scopes },
      { component: 'layerController', x: 9, y: 0, w: 3, h: 12, coordinationScopes: scopes },
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
      // Neuroglancer shows channel 0 first and stretches it over the whole
      // dtype range unless told otherwise: hand it the tile's window.
      const first = store.view?.channels.find((c) => c.index === 0);
      const layer: Record<string, unknown> = { type: 'image', name: store.name, source: `zarr://${url}` };
      if (first) layer.shaderControls = { normalized: { range: [first.window[0], first.window[1]] } };
      const state = { layers: [layer], layout: '4panel' };
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
): Array<{ label: string; text: string; logo?: string }> {
  const url = storeUrl.replace(/\/+$/, '');
  const out: Array<{ label: string; text: string; logo?: string }> = [{ label: 'Store URL', text: url }];
  if (store.format !== 'ome-tiff') {
    out.push({
      label: 'napari',
      text: `napari --plugin napari-ome-zarr ${url}`,
      logo: HANDOFF_LOGOS.napari,
    });
  }
  return out;
}
