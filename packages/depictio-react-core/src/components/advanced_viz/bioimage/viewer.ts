// Pyramidal bioimage viewer behind a strict interface: OME-Zarr (NGFF 0.4 on
// zarr v2, or NGFF 0.5 on zarr v3, sharded or not; also how a SpatialData
// image is served) and OME-TIFF.
//
// Dynamically imported by BioimageViewerRenderer (deck.gl + viv are heavy and
// WebGL-only), so the main viewer bundle and cold start are untouched. deck
// is driven directly with a single OrthographicView rather than through viv's
// React viewers: the renderer owns the chrome (channels, sliders, ROI tools),
// so all this needs is the multiscale image layer, a points overlay and the
// ROI being drawn.
//
// Coordinates are level-0 image pixels throughout (x right, y down), which is
// the space viv's MultiscaleImageLayer draws in.
//
// A labels store (segmentation mask) draws over the image as a TileLayer on
// its own pyramid: each tile's integer cell ids are coloured on the CPU
// through a lookup table (see ./labels.ts) into an RGBA bitmap, cached per
// tile and style version, and drawn with nearest sampling so ids never blend.

import { Deck, OrthographicView } from '@deck.gl/core';
import { TileLayer } from '@deck.gl/geo-layers';
import { BitmapLayer, PolygonLayer, ScatterplotLayer } from '@deck.gl/layers';
import {
  ImageLayer,
  MultiscaleImageLayer,
  getChannelStats,
  loadOmeTiff,
  loadOmeZarrFromStore,
} from '@hms-dbmi/viv';

import type { BioimageSource, BioimageTiffSource, BioimageZarrStore } from '../../../api';
import {
  axisSizes,
  hexToRgb,
  MAX_RENDERED_CHANNELS,
  ngffRootAttrs,
  physicalPixelSize,
  renderedChannels,
  resolveChannels,
  selectionFor,
  type ChannelState,
  type ChannelStats,
  type ConfigChannel,
  type Rgb,
} from './channels';
import { fitViewState, rectToPolygon, type Polygon, type Vec2 } from './geometry';
import { overlayMatrix, overlayPlane } from './overlay';
import {
  colorizeLabels,
  labelAt,
  labelTileKey,
  type LabelLut,
  type LabelPaint,
  type LabelTile,
} from './labels';
import { normaliseOmeTiffMetadata, type OmeXmlImage } from './omeTiff';

export type SelectionMode = 'pan' | 'lasso' | 'rect';

export interface BioimageInfo {
  labels: string[];
  shape: number[];
  width: number;
  height: number;
  sizes: { c: number; z: number; t: number };
  dtype: string;
  levels: number;
  /** Shape of every pyramid level, level 0 first, in `labels` order. */
  levelShapes: number[][];
  /** Channel state in effect after the load: the starting state (config, then
   *  omero, then data statistics), or the kept one on a `keepView` reload. */
  channels: ChannelState[];
  /** Starting plane, from omero `rdefs` when present. */
  defaultZ: number;
  defaultT: number;
  /** Size of one level-0 pixel along x, or null when the store has no unit. */
  physicalSize: { value: number; unit: string } | null;
}

export interface OverlayPoint {
  /** The id the selection filters on (`selection_column`, else the cell id). */
  id: string;
  /** The cell id, the mask value, when it differs from `id`. */
  label?: string;
  /** Level-0 image pixel coordinates. */
  x: number;
  y: number;
  color: Rgb;
  /** Excluded by the dashboard filters: drawn faint, still there for context. */
  faded: boolean;
}

export interface BioimageViewerOptions {
  /** Every time the tiles covering the viewport have all arrived. */
  onViewportLoad?: () => void;
  /** Once per labels load, when the label tiles covering the viewport arrived. */
  onLabelsLoad?: () => void;
  /** A click (not a drag) in pan mode on the labels: the label under it, 0 for background. */
  onLabelClick?: (label: number) => void;
  onZoomChange?: (zoom: number) => void;
  /** A finished lasso or rectangle, in image coordinates. */
  onRoi?: (polygon: Polygon) => void;
  onError?: (error: Error) => void;
}

/** What a labels store opened as. */
export interface LabelsInfo {
  width: number;
  height: number;
  levels: number;
  dtype: string;
}

/** How the labels draw: colours per cell, fill opacity, outlines, visibility. */
export interface LabelsStyle extends LabelPaint {
  lut: LabelLut;
  visible: boolean;
}

/** How a reference image (a registration's fixed image) is laid over the
 *  image: `colours` draws one channel of each in complementary colours,
 *  added, so aligned structure reads grey-white and an offset shows as green
 *  and magenta fringes; `fade` draws the reference over the image at
 *  `opacity`, in the image's own channel colours. */
export type CompareMode = 'off' | 'colours' | 'fade';

export interface ReferenceStyle {
  mode: CompareMode;
  opacity: number;
  /** Channel compared in `colours` mode. */
  channel: number;
}

/** An overlay image (another modality registered onto this one, e.g. light
 *  microscopy over EM): drawn over the image in its own channels, stretched
 *  to the image's extent (see overlay.ts). */
export interface OverlayStyle {
  channels: readonly ChannelState[];
  /** 0 hides it. */
  opacity: number;
}

/** What an overlay store opened as: its starting channel state and size. */
export interface OverlayInfo {
  channels: ChannelState[];
  width: number;
  height: number;
  depth: number;
}

/** What a reference store opened as. */
export interface ReferenceInfo {
  width: number;
  height: number;
  channels: number;
}

// The green / magenta pair of registration overlays (ImageJ, 3D Slicer): they
// add up to white, so it is a data encoding, not a theme colour.
export const COMPARE_IMAGE_RGB: Rgb = [0, 255, 0];
export const COMPARE_REFERENCE_RGB: Rgb = [255, 0, 255];

const ADDITIVE_BLEND = {
  blend: true,
  blendColorOperation: 'add',
  blendColorSrcFactor: 'one',
  blendColorDstFactor: 'one',
  blendAlphaOperation: 'add',
  blendAlphaSrcFactor: 'one',
  blendAlphaDstFactor: 'one',
} as const;

export interface BioimageLoadOptions {
  /** A reload of the image already shown (a data refresh): when the new image
   *  has the same size, the channel state and plane carry over, and the view
   *  only refits if the reader has not panned or zoomed. */
  keepView?: boolean;
}

export interface BioimageViewer {
  /** Open an image (replacing any previous one) and fit it in view. Resolves
   *  with the image's shape and channel state. A load superseded by a later
   *  one rejects with `LoadSupersededError`. */
  load(
    source: BioimageSource,
    configChannels?: readonly ConfigChannel[],
    loadOpts?: BioimageLoadOptions,
  ): Promise<BioimageInfo>;
  setChannels(channels: readonly ChannelState[]): void;
  setSelection(sel: { z: number; t: number }): void;
  setPoints(points: readonly OverlayPoint[], radius: number): void;
  /** Open a labels store (replacing any previous one), or drop it with null.
   *  Rejects with `LoadSupersededError` when a later call replaced it. */
  setLabels(store: BioimageZarrStore | null): Promise<LabelsInfo | null>;
  setLabelsStyle(style: LabelsStyle): void;
  /** Open a reference image to compare against (replacing any previous one),
   *  or drop it with null. Rejects with `LoadSupersededError` when replaced. */
  setReference(store: BioimageZarrStore | null): Promise<ReferenceInfo | null>;
  setReferenceStyle(style: ReferenceStyle): void;
  /** Open an overlay image (replacing any previous one), or drop it with
   *  null. Rejects with `LoadSupersededError` when a later call replaced it. */
  setOverlay(store: BioimageZarrStore | null): Promise<OverlayInfo | null>;
  setOverlayStyle(style: OverlayStyle): void;
  setHighlighted(ids: ReadonlySet<string>): void;
  setSelectionMode(mode: SelectionMode): void;
  /** Theme sync. `accent` rings highlighted points and draws the ROI. */
  setDark(dark: boolean, accent?: Rgb): void;
  resetView(): void;
  resize(): void;
  dispose(): void;
}

export class LoadSupersededError extends Error {
  constructor() {
    super('Bioimage load superseded');
    this.name = 'LoadSupersededError';
  }
}

/** Past this many pixels the lowest level is not worth scanning for contrast
 *  statistics on the main thread; the dtype range (or omero) stands in. */
const STATS_MAX_PIXELS = 2048 * 2048;
/** Channels whose statistics are computed up front. */
const STATS_MAX_CHANNELS = 16;
/** A single-level image up to this many pixels is read whole, not tiled: its
 *  one chunk is often the whole image (SpatialData's Visium hires image), a
 *  tile size viv's tiled layer draws nothing with below zoom 0. */
const WHOLE_IMAGE_MAX_PIXELS = 4096 * 4096;
/** Screen pixels a lasso has to travel before it records another vertex. */
const LASSO_MIN_STEP_PX = 3;
/** Screen pixels a pointer may move between down and up and still click. */
const CLICK_MAX_MOVE_PX = 4;
const DEFAULT_ACCENT: Rgb = [250, 176, 5];

type PixelSource = {
  shape: number[];
  dtype: string;
  labels: string[];
  getRaster(opts: { selection: Record<string, number> }): Promise<{ data: ArrayLike<number> }>;
  getTile?(opts: {
    x: number;
    y: number;
    selection: Record<string, number>;
    signal?: AbortSignal;
  }): Promise<LabelTile>;
};

/** An opened image, whatever its format: the pyramid (level 0 first) and the
 *  metadata the channel defaults and scale bar read, in the OME-Zarr shape. */
interface OpenedImage {
  pyramid: PixelSource[];
  omero: {
    channels?: object[];
    rdefs?: { defaultZ?: number; defaultT?: number };
  } | null;
  physicalSize: { value: number; unit: string } | null;
}

async function openOmeZarr(store: BioimageZarrStore): Promise<OpenedImage> {
  const loaded = await loadOmeZarrFromStore(store as never);
  // NGFF 0.4 (`.zattrs`) or 0.5 (`zarr.json`, attributes under `ome`).
  const rootAttrs = ngffRootAttrs(loaded.metadata);
  return {
    pyramid: loaded.data as unknown as PixelSource[],
    omero: rootAttrs.omero ?? null,
    physicalSize: physicalPixelSize(rootAttrs),
  };
}

async function openOmeTiff(tiff: BioimageTiffSource): Promise<OpenedImage> {
  let loaded: Awaited<ReturnType<typeof loadOmeTiff>>;
  try {
    // No decoder pool: tiles decode on the main thread, as zarr chunks do,
    // which keeps geotiff's blob-URL workers (and a CSP worker-src) out of it.
    loaded = await loadOmeTiff(tiff.url, { headers: await tiff.headers() });
  } catch (err) {
    // geotiff reports every HTTP failure as the same bare message: the API
    // says why (a 403 on a remote store, a 404), else the parse error stands.
    await tiff.check();
    throw err;
  }
  const pyramid = loaded.data as unknown as PixelSource[];
  if (pyramid[0]?.labels.includes('_c')) {
    throw new Error('Interleaved RGB OME-TIFF is not supported yet');
  }
  const meta = normaliseOmeTiffMetadata(loaded.metadata as unknown as OmeXmlImage);
  return { pyramid, omero: meta.omero, physicalSize: meta.physicalSize };
}

interface ViewState {
  target: [number, number, number];
  zoom: number;
  minZoom?: number;
  maxZoom?: number;
}

let viewerCount = 0;

function isBoundsError(err: unknown): boolean {
  return err instanceof Error && /Tile slice/.test(err.message);
}

export async function createBioimageViewer(
  host: HTMLDivElement,
  opts: BioimageViewerOptions = {},
): Promise<BioimageViewer> {
  let data: PixelSource[] | null = null;
  let info: BioimageInfo | null = null;
  let channels: ChannelState[] = [];
  let plane = { z: 0, t: 0 };
  let points: readonly OverlayPoint[] = [];
  let pointRadius = 6;
  let highlighted: ReadonlySet<string> = new Set();
  let highlightVersion = 0;
  let mode: SelectionMode = 'pan';
  let accent: Rgb = DEFAULT_ACCENT;
  let draft: Polygon | null = null;
  let loadToken = 0;
  // Load whose first viewport has been reported, so onViewportLoad fires once per load.
  let readyToken = -1;
  let userMoved = false;
  let disposed = false;
  let viewState: ViewState = { target: [0, 0, 0], zoom: 0 };
  // Labels overlay: its pyramid, the tiles fetched (for click picking), the
  // style and a version bumped with it, so tiles recolour only on change.
  let labels: { pyramid: PixelSource[]; info: LabelsInfo; tileSize: number } | null = null;
  let labelsToken = 0;
  let labelsReadyToken = -1;
  let labelTiles = new Map<string, LabelTile>();
  let labelsStyle: LabelsStyle | null = null;
  let labelsStyleVersion = 0;
  let bitmaps = new WeakMap<object, { version: number; image: ImageData }>();
  // Reference image (a registration's fixed image), drawn over the image.
  let reference: PixelSource[] | null = null;
  let referenceChannels = 0;
  let referenceToken = 0;
  let referenceStyle: ReferenceStyle = { mode: 'off', opacity: 0.5, channel: 0 };
  // Overlay image (another modality), drawn over the image and the reference.
  let overlay: { pyramid: PixelSource[]; width: number; height: number; depth: number } | null =
    null;
  let overlayToken = 0;
  let overlayStyle: OverlayStyle = { channels: [], opacity: 0 };

  const hostSize = () => ({ w: host.clientWidth, h: host.clientHeight });

  const fit = () => {
    if (!info) return;
    const { w, h } = hostSize();
    const v = fitViewState(info.width, info.height, w, h);
    viewState = { ...v, minZoom: v.zoom - 3, maxZoom: 8 };
    userMoved = false;
    deck.setProps({ viewState });
    opts.onZoomChange?.(viewState.zoom);
  };

  const view = (dragPan: boolean) =>
    new OrthographicView({ id: 'ortho', controller: { dragPan, doubleClickZoom: dragPan } });

  viewerCount += 1;
  const deck = new Deck<OrthographicView>({
    // Also the canvas id, which would otherwise be 'deckgl-overlay' on every tile.
    id: `bioimage-deck-${viewerCount}`,
    parent: host,
    views: view(true),
    viewState,
    layers: [],
    style: { position: 'absolute', inset: '0' },
    // viv's onViewportLoad is skipped when every tile comes from cache or the
    // viewport settles before the tileset reports: the layer's own isLoaded,
    // checked after each frame, covers those cases.
    onAfterRender: () => {
      if (readyToken !== loadToken && data && isLayerLoaded(`bioimage-image-${loadToken}`)) {
        markReady();
      }
      if (
        labels &&
        labelsReadyToken !== labelsToken &&
        isLayerLoaded(`bioimage-labels-${labelsToken}`)
      ) {
        markLabelsReady();
      }
    },
    onViewStateChange: ({ viewState: next }) => {
      viewState = next as unknown as ViewState;
      userMoved = true;
      deck.setProps({ viewState });
      opts.onZoomChange?.(viewState.zoom);
      return viewState as never;
    },
    getCursor: ({ isDragging }) =>
      mode !== 'pan' ? 'crosshair' : isDragging ? 'grabbing' : 'grab',
    onError: (err) => opts.onError?.(err),
  });

  function isLayerLoaded(id: string): boolean {
    const layer = deck.props.layers.find((l) => (l as { id?: string } | null)?.id === id);
    const managed = (
      deck as unknown as { layerManager?: { getLayers(): Array<{ id: string; isLoaded: boolean }> } }
    ).layerManager
      ?.getLayers()
      .find((l) => l.id === id);
    return Boolean(layer && managed?.isLoaded);
  }

  function markReady() {
    if (readyToken === loadToken) return;
    readyToken = loadToken;
    opts.onViewportLoad?.();
  }

  function markLabelsReady() {
    if (labelsReadyToken === labelsToken) return;
    labelsReadyToken = labelsToken;
    opts.onLabelsLoad?.();
  }

  /** The RGBA bitmap of one label tile under the current style, cached. */
  const tileBitmap = (tile: LabelTile): ImageData | null => {
    if (!labelsStyle) return null;
    const key = tile.data as unknown as object;
    const hit = bitmaps.get(key);
    if (hit && hit.version === labelsStyleVersion) return hit.image;
    const rgba = colorizeLabels(tile.data, tile.width, tile.height, labelsStyle.lut, labelsStyle);
    const image = new ImageData(rgba as Uint8ClampedArray<ArrayBuffer>, tile.width, tile.height);
    bitmaps.set(key, { version: labelsStyleVersion, image });
    return image;
  };

  const labelsLayer = () => {
    if (!labels || !labelsStyle?.visible) return null;
    const { pyramid, info: li, tileSize } = labels;
    const token = labelsToken;
    const version = labelsStyleVersion;
    // A ZYX or TCZYX mask follows the image's plane, like the image tiles.
    const { z: planeZ, t: planeT } = plane;
    return new TileLayer<LabelTile | null>({
      id: `bioimage-labels-${token}`,
      tileSize,
      extent: [0, 0, li.width, li.height],
      minZoom: -(li.levels - 1),
      maxZoom: 0,
      // Translucent tiles: never draw a coarse and a fine tile on top of each other.
      refinementStrategy: 'no-overlap',
      getTileData: async ({ index: { x, y, z }, signal }) => {
        const level = Math.round(-z);
        const source = pyramid[level];
        if (!source?.getTile) return null;
        try {
          const selection = selectionFor(source.labels, { c: 0, z: planeZ, t: planeT });
          const tile = await source.getTile({ x, y, selection, signal });
          if (token === labelsToken) labelTiles.set(labelTileKey(level, x, y), tile);
          return tile;
        } catch (err) {
          if (isBoundsError(err) || signal?.aborted) return null;
          throw err;
        }
      },
      // Keep the picking map to the tiles deck still caches, so panning a
      // large mask does not hold every tile (and its bitmap) ever fetched.
      onTileUnload: ({ index: { x, y, z } }) => {
        if (token === labelsToken) labelTiles.delete(labelTileKey(Math.round(-z), x, y));
      },
      renderSubLayers: (props) => {
        const tile = props.data as LabelTile | null;
        const {
          bbox,
          index: { x, y, z },
        } = props.tile as unknown as {
          bbox: { left: number; top: number };
          index: { x: number; y: number; z: number };
        };
        if (!tile || tile.width === 0 || tile.height === 0 || bbox.left < 0 || bbox.top < 0) {
          return null;
        }
        const image = tileBitmap(tile);
        if (!image) return null;
        const scale = 2 ** Math.round(-z);
        return new BitmapLayer({
          id: `${props.id}-bitmap-${x}-${y}-${z}`,
          image: image as never,
          bounds: [
            bbox.left,
            bbox.top + tile.height * scale,
            bbox.left + tile.width * scale,
            bbox.top,
          ],
          // Cell ids never blend: each screen pixel shows one cell's colour.
          textureParameters: { minFilter: 'nearest', magFilter: 'nearest' },
          pickable: false,
        });
      },
      updateTriggers: { getTileData: `${planeZ}:${planeT}`, renderSubLayers: version },
      onViewportLoad: () => {
        if (token === labelsToken) markLabelsReady();
      },
      onTileError: (err: unknown) => {
        if (isBoundsError(err)) return;
        opts.onError?.(err instanceof Error ? err : new Error(String(err)));
      },
    });
  };

  /** A viv image layer over `pyramid`: one plain layer for a small
   *  single-level image (its one chunk is the whole image), else tiled. */
  const imageLayer = (pyramid: PixelSource[], props: Record<string, unknown>) => {
    const [base] = pyramid;
    const lab = base.labels;
    const px = (axis: string) => base.shape[lab.indexOf(axis)] ?? 0;
    if (pyramid.length === 1 && px('x') * px('y') <= WHOLE_IMAGE_MAX_PIXELS) {
      return new ImageLayer({ ...props, loader: base } as never);
    }
    return new MultiscaleImageLayer({ ...props, loader: pyramid } as never);
  };

  /** The overlay over `image`: its shown channels, at the same depth. */
  const overlayLayer = (image: BioimageInfo) => {
    if (!overlay || overlayStyle.opacity <= 0) return null;
    const shown = overlayStyle.channels.filter((c) => c.visible).slice(0, MAX_RENDERED_CHANNELS);
    if (!shown.length) return null;
    const axes = overlay.pyramid[0].labels;
    const z = overlayPlane(plane.z, image.sizes.z, overlay.depth);
    const matrix = overlayMatrix(image, overlay);
    return imageLayer(overlay.pyramid, {
      id: `bioimage-overlay-${overlayToken}`,
      loader: overlay.pyramid,
      selections: shown.map((c) => selectionFor(axes, { c: c.index, z, t: 0 })),
      colors: shown.map((c) => hexToRgb(c.color) ?? [255, 255, 255]),
      contrastLimits: shown.map((c) => c.contrastLimits),
      channelsVisible: shown.map(() => true),
      excludeBackground: true,
      opacity: overlayStyle.opacity,
      ...(matrix ? { modelMatrix: matrix } : {}),
      onTileError: (err: unknown) => {
        if (isBoundsError(err)) return;
        opts.onError?.(err instanceof Error ? err : new Error(String(err)));
      },
    });
  };

  const render = () => {
    if (disposed) return;
    const layers: unknown[] = [];
    if (data && info) {
      const shown = renderedChannels(channels);
      // The image's axis labels (not the labels overlay).
      const axes = info.labels;
      // `colors` belongs to viv's default ColorPaletteExtension, which the
      // layer's own prop type does not list, hence the loose object.
      const imageProps: Record<string, unknown> = {
        // Keyed by load, so a new store starts from an empty tile cache.
        id: `bioimage-image-${loadToken}`,
        loader: data,
        selections: shown.map((c) => selectionFor(axes, { c: c.index, z: plane.z, t: plane.t })),
        colors: shown.map((c) => hexToRgb(c.color) ?? [255, 255, 255]),
        contrastLimits: shown.map((c) => c.contrastLimits),
        channelsVisible: shown.map((c) => c.visible),
        onViewportLoad: () => markReady(),
        onTileError: (err: unknown) => {
          if (isBoundsError(err)) return;
          opts.onError?.(err instanceof Error ? err : new Error(String(err)));
        },
      };
      const comparing = reference !== null && referenceStyle.mode !== 'off';
      const compared =
        channels.find((c) => c.index === referenceStyle.channel) ?? shown[0] ?? null;
      if (comparing && referenceStyle.mode === 'colours' && compared) {
        // One channel of each, green and magenta: the image's own colours would
        // not add up to white where the two agree.
        Object.assign(imageProps, {
          selections: [selectionFor(axes, { c: compared.index, z: plane.z, t: plane.t })],
          colors: [COMPARE_IMAGE_RGB],
          contrastLimits: [compared.contrastLimits],
          channelsVisible: [true],
        });
      }
      layers.push(imageLayer(data, imageProps));
      if (comparing && reference) {
        const refAxes = reference[0].labels;
        const usable = (c: ChannelState) => c.index < Math.max(referenceChannels, 1);
        const colours = referenceStyle.mode === 'colours';
        const drawn = colours ? (compared && usable(compared) ? [compared] : []) : shown.filter(usable);
        if (drawn.length) {
          layers.push(
            imageLayer(reference, {
              id: `bioimage-reference-${referenceToken}`,
              loader: reference,
              selections: drawn.map((c) =>
                selectionFor(refAxes, { c: c.index, z: plane.z, t: plane.t }),
              ),
              colors: colours
                ? [COMPARE_REFERENCE_RGB]
                : drawn.map((c) => hexToRgb(c.color) ?? [255, 255, 255]),
              contrastLimits: drawn.map((c) => c.contrastLimits),
              channelsVisible: drawn.map(() => true),
              // The low-resolution backdrop under the tiles would count twice.
              excludeBackground: true,
              opacity: colours ? 1 : referenceStyle.opacity,
              ...(colours ? { parameters: ADDITIVE_BLEND } : {}),
              onTileError: (err: unknown) => {
                if (isBoundsError(err)) return;
                opts.onError?.(err instanceof Error ? err : new Error(String(err)));
              },
            }),
          );
        }
      }
    }
    const overlayed = data && info ? overlayLayer(info) : null;
    if (overlayed) layers.push(overlayed);
    const labelsOverlay = labelsLayer();
    if (labelsOverlay) layers.push(labelsOverlay);
    if (points.length) {
      layers.push(
        new ScatterplotLayer<OverlayPoint>({
          id: 'bioimage-points',
          data: points as OverlayPoint[],
          getPosition: (p) => [p.x, p.y],
          getFillColor: (p) => [...p.color, p.faded ? 45 : 220],
          getLineColor: [...accent, 255],
          getLineWidth: (p) => (highlighted.has(p.id) ? 2 : 0),
          getRadius: (p) => (highlighted.has(p.id) ? pointRadius * 1.35 : pointRadius),
          stroked: true,
          radiusUnits: 'pixels',
          lineWidthUnits: 'pixels',
          updateTriggers: {
            getLineColor: accent,
            getLineWidth: highlightVersion,
            getRadius: [highlightVersion, pointRadius],
          },
        }),
      );
    }
    if (draft && draft.length > 1) {
      layers.push(
        new PolygonLayer<Polygon>({
          id: 'bioimage-roi-draft',
          data: [draft],
          getPolygon: (d) => d,
          filled: true,
          stroked: true,
          getFillColor: [...accent, 40],
          getLineColor: [...accent, 255],
          lineWidthUnits: 'pixels',
          getLineWidth: 1.5,
          updateTriggers: { getPolygon: draft.length, getFillColor: accent, getLineColor: accent },
        }),
      );
    }
    deck.setProps({ layers: layers as never });
  };

  // ---- ROI drawing -------------------------------------------------------
  // Plain pointer listeners on the host, unprojected through deck's viewport:
  // with dragPan off in the ROI modes, deck does not claim the drag itself.
  let drawing: { start: Vec2; lastScreen: Vec2 } | null = null;

  const toImage = (e: PointerEvent): { world: Vec2; screen: Vec2 } | null => {
    const vp = deck.getViewports()[0];
    if (!vp) return null;
    const rect = host.getBoundingClientRect();
    const screen: Vec2 = [e.clientX - rect.left, e.clientY - rect.top];
    const [x, y] = vp.unproject(screen);
    return { world: [x, y], screen };
  };

  // A click in pan mode picks the label under it; deck still pans on a drag.
  let press: Vec2 | null = null;

  const onPointerDown = (e: PointerEvent) => {
    if (mode === 'pan') {
      press = e.button === 0 ? [e.clientX, e.clientY] : null;
      return;
    }
    if (e.button !== 0) return;
    const at = toImage(e);
    if (!at) return;
    e.preventDefault();
    e.stopPropagation();
    host.setPointerCapture?.(e.pointerId);
    drawing = { start: at.world, lastScreen: at.screen };
    draft = [at.world];
    render();
  };

  const onPointerMove = (e: PointerEvent) => {
    if (!drawing) return;
    const at = toImage(e);
    if (!at) return;
    if (mode === 'rect') {
      draft = rectToPolygon(drawing.start, at.world);
    } else {
      const dx = at.screen[0] - drawing.lastScreen[0];
      const dy = at.screen[1] - drawing.lastScreen[1];
      if (dx * dx + dy * dy < LASSO_MIN_STEP_PX * LASSO_MIN_STEP_PX) return;
      drawing.lastScreen = at.screen;
      draft = [...(draft ?? []), at.world];
    }
    render();
  };

  const onClickUp = (e: PointerEvent) => {
    const start = press;
    press = null;
    if (!start || mode !== 'pan' || !labels || !opts.onLabelClick) return;
    const dx = e.clientX - start[0];
    const dy = e.clientY - start[1];
    if (dx * dx + dy * dy > CLICK_MAX_MOVE_PX * CLICK_MAX_MOVE_PX) return;
    const at = toImage(e);
    if (!at) return;
    const label = labelAt(
      labelTiles,
      at.world[0],
      at.world[1],
      labels.tileSize,
      labels.info.levels,
    );
    if (label !== null) opts.onLabelClick(label);
  };

  const onPointerUp = (e: PointerEvent) => {
    if (e.type === 'pointerup') onClickUp(e);
    else press = null;
    if (!drawing) return;
    host.releasePointerCapture?.(e.pointerId);
    const polygon = draft;
    drawing = null;
    draft = null;
    render();
    if (polygon && polygon.length >= 3) opts.onRoi?.(polygon);
  };

  const listeners = new AbortController();
  const listen = { signal: listeners.signal };
  host.addEventListener('pointerdown', onPointerDown, listen);
  host.addEventListener('pointermove', onPointerMove, listen);
  host.addEventListener('pointerup', onPointerUp, listen);
  host.addEventListener('pointercancel', onPointerUp, listen);

  // Wheel zoom needs Ctrl (Cmd on macOS): a plain wheel over the image scrolls
  // the page, as it does over any other tile. Stopped in the capture phase, so
  // deck's own wheel handler never sees it; a modified wheel passes through to
  // deck's zoom untouched.
  let hint: HTMLDivElement | null = null;
  let hintTimer = 0;
  const showWheelHint = () => {
    if (!hint) {
      hint = document.createElement('div');
      Object.assign(hint.style, {
        position: 'absolute',
        left: '50%',
        bottom: '12px',
        transform: 'translateX(-50%)',
        padding: '4px 10px',
        borderRadius: '6px',
        background: 'rgba(0, 0, 0, 0.7)',
        color: '#fff',
        fontSize: '12px',
        pointerEvents: 'none',
        transition: 'opacity 150ms',
        zIndex: '1',
      });
      hint.textContent = 'Hold Ctrl (⌘ on Mac) and scroll to zoom';
      host.appendChild(hint);
    }
    hint.style.opacity = '1';
    window.clearTimeout(hintTimer);
    hintTimer = window.setTimeout(() => {
      if (hint) hint.style.opacity = '0';
    }, 1200);
  };
  const onWheel = (e: WheelEvent) => {
    if (e.ctrlKey || e.metaKey) return;
    e.stopPropagation();
    showWheelHint();
  };
  host.addEventListener('wheel', onWheel, { ...listen, capture: true, passive: true });

  return {
    async load(source, configChannels, loadOpts) {
      loadToken += 1;
      const token = loadToken;
      const opened =
        source.kind === 'tiff' ? await openOmeTiff(source.tiff) : await openOmeZarr(source.store);
      if (token !== loadToken || disposed) throw new LoadSupersededError();
      const { pyramid, omero } = opened;
      const base = pyramid[0];
      const labels = [...base.labels];
      const shape = [...base.shape];
      const sizes = axisSizes(labels, shape);
      const width = shape[labels.indexOf('x')] ?? shape[shape.length - 1];
      const height = shape[labels.indexOf('y')] ?? shape[shape.length - 2];
      const rdefs = omero?.rdefs;
      const clampIndex = (v: unknown, size: number, fallback: number) =>
        typeof v === 'number' && v >= 0 && v < size ? Math.floor(v) : fallback;
      const defaultZ = clampIndex(rdefs?.defaultZ, sizes.z, Math.floor(sizes.z / 2));
      const defaultT = clampIndex(rdefs?.defaultT, sizes.t, 0);

      // Contrast statistics off the lowest level, for every channel. The slider
      // spans the data range they give; omero's window is the dtype's full range
      // in most stores (0-65535 for a 12-bit image), which would leave the
      // window a sliver of the track. The window itself still comes from the
      // config or omero, in resolveChannels.
      const lowest = pyramid[pyramid.length - 1];
      const lowPixels =
        (lowest.shape[labels.indexOf('x')] ?? 0) * (lowest.shape[labels.indexOf('y')] ?? 0);
      const stats: Array<ChannelStats | null> = [];
      if (lowPixels > 0 && lowPixels <= STATS_MAX_PIXELS) {
        const wanted = Array.from({ length: Math.min(sizes.c, STATS_MAX_CHANNELS) }, (_, c) => c);
        await Promise.all(
          wanted.map(async (c) => {
            try {
              const raster = await lowest.getRaster({
                selection: selectionFor(labels, { c, z: defaultZ, t: defaultT }),
              });
              const s = getChannelStats(raster.data as never);
              stats[c] = {
                domain: [s.domain[0], s.domain[1]],
                contrastLimits: [s.contrastLimits[0], s.contrastLimits[1]],
              };
            } catch {
              stats[c] = null;
            }
          }),
        );
        if (token !== loadToken || disposed) throw new LoadSupersededError();
      }

      const resolved = resolveChannels({
        sizeC: sizes.c,
        dtype: base.dtype,
        omero: omero as never,
        config: configChannels,
        stats,
      });
      // A refresh of the same image keeps what the reader set up on it.
      const keep =
        Boolean(loadOpts?.keepView) &&
        info !== null &&
        info.width === width &&
        info.height === height;
      data = pyramid;
      if (!keep || channels.length !== resolved.length) channels = resolved;
      if (!keep || plane.z >= sizes.z || plane.t >= sizes.t) plane = { z: defaultZ, t: defaultT };
      info = {
        labels,
        shape,
        width,
        height,
        sizes,
        dtype: base.dtype,
        levels: pyramid.length,
        levelShapes: pyramid.map((level) => [...level.shape]),
        channels,
        defaultZ,
        defaultT,
        physicalSize: opened.physicalSize,
      };
      if (!keep || !userMoved) fit();
      render();
      return info;
    },

    setChannels(next) {
      channels = [...next];
      render();
    },

    setSelection(sel) {
      if (sel.z === plane.z && sel.t === plane.t) return;
      plane = { z: sel.z, t: sel.t };
      // Label tiles are per plane: the picking map refills as they reload.
      labelTiles = new Map();
      render();
    },

    setPoints(next, radius) {
      points = next;
      pointRadius = radius;
      render();
    },

    async setLabels(store) {
      labelsToken += 1;
      const token = labelsToken;
      labels = null;
      labelTiles = new Map();
      bitmaps = new WeakMap();
      render();
      if (!store) return null;
      const loaded = await loadOmeZarrFromStore(store as never);
      if (token !== labelsToken || disposed) throw new LoadSupersededError();
      const pyramid = loaded.data as unknown as PixelSource[];
      const base = pyramid[0];
      const lab = base.labels;
      const width = base.shape[lab.indexOf('x')] ?? base.shape[base.shape.length - 1];
      const height = base.shape[lab.indexOf('y')] ?? base.shape[base.shape.length - 2];
      if (/^Float/.test(base.dtype)) {
        throw new Error(`Labels store has dtype ${base.dtype}: cell ids must be integers`);
      }
      const tileSize = (base as unknown as { tileSize?: number }).tileSize ?? 256;
      const labelsInfo = { width, height, levels: pyramid.length, dtype: base.dtype };
      labels = { pyramid, info: labelsInfo, tileSize };
      render();
      return labelsInfo;
    },

    setLabelsStyle(style) {
      labelsStyle = style;
      labelsStyleVersion += 1;
      render();
    },

    async setReference(store) {
      referenceToken += 1;
      const token = referenceToken;
      reference = null;
      referenceChannels = 0;
      render();
      if (!store) return null;
      const opened = await openOmeZarr(store);
      if (token !== referenceToken || disposed) throw new LoadSupersededError();
      const base = opened.pyramid[0];
      const lab = base.labels;
      reference = opened.pyramid;
      referenceChannels = lab.includes('c') ? (base.shape[lab.indexOf('c')] ?? 1) : 1;
      render();
      return {
        width: base.shape[lab.indexOf('x')] ?? 0,
        height: base.shape[lab.indexOf('y')] ?? 0,
        channels: referenceChannels,
      };
    },

    setReferenceStyle(style) {
      referenceStyle = style;
      render();
    },

    async setOverlay(store) {
      overlayToken += 1;
      const token = overlayToken;
      overlay = null;
      render();
      if (!store) return null;
      const opened = await openOmeZarr(store);
      if (token !== overlayToken || disposed) throw new LoadSupersededError();
      const base = opened.pyramid[0];
      const lab = base.labels;
      const size = (axis: string) => (lab.includes(axis) ? (base.shape[lab.indexOf(axis)] ?? 1) : 1);
      overlay = {
        pyramid: opened.pyramid,
        width: size('x'),
        height: size('y'),
        depth: size('z'),
      };
      render();
      return {
        channels: resolveChannels({
          sizeC: size('c'),
          dtype: base.dtype,
          omero: opened.omero as never,
        }),
        width: overlay.width,
        height: overlay.height,
        depth: overlay.depth,
      };
    },

    setOverlayStyle(style) {
      overlayStyle = style;
      render();
    },

    setHighlighted(ids) {
      highlighted = ids;
      highlightVersion += 1;
      render();
    },

    setSelectionMode(next) {
      if (next === mode) return;
      mode = next;
      drawing = null;
      draft = null;
      deck.setProps({ views: view(mode === 'pan') });
      render();
    },

    setDark(_dark, nextAccent) {
      // The image is drawn additively on black whatever the scheme, and the
      // canvas is transparent around it, so only the accent follows the theme.
      if (nextAccent) accent = nextAccent;
      render();
    },

    resetView() {
      fit();
    },

    resize() {
      // deck resizes its canvas itself; an image that was never moved by the
      // user is refitted so it keeps filling the tile.
      if (!userMoved) fit();
      deck.redraw('resize');
    },

    dispose() {
      disposed = true;
      loadToken += 1;
      labelsToken += 1;
      referenceToken += 1;
      overlayToken += 1;
      listeners.abort();
      window.clearTimeout(hintTimer);
      try {
        deck.finalize();
      } catch {
        /* already torn down */
      }
    },
  };
}
