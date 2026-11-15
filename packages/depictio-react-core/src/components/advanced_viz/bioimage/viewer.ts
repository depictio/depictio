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
import { BitmapLayer, LineLayer, PolygonLayer, ScatterplotLayer } from '@deck.gl/layers';
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
  axisStep,
  hexToRgb,
  MAX_RENDERED_CHANNELS,
  ngffRootAttrs,
  physicalPixelSize,
  renderedChannels,
  referenceChannelsFor,
  resolveChannels,
  selectionFor,
  type AxisStep,
  type ChannelState,
  type ChannelStats,
  type ConfigChannel,
  type Rgb,
} from './channels';
import { matchSelectionsAcrossLevels } from './pyramid';
import {
  fitBoundsViewState,
  boxDisplay,
  fitViewState,
  pointAt,
  rectToPolygon,
  type Bounds,
  type Polygon,
  type Vec2,
} from './geometry';
import { ScaleMatrix } from './matrix';
import { reslice, zAspect, type OrthoCursor, type ReslicedSource } from './ortho';
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
  /** The step between two Z planes and two time points, when the store says. */
  zStep: AxisStep | null;
  tStep: AxisStep | null;
  /** Whether the image can show orthogonal slices (an OME-Zarr volume). */
  ortho: boolean;
}

export interface OverlayPoint {
  /** The id the selection filters on (`selection_column`, else the cell id). */
  id: string;
  /** The cell id, the mask value, when it differs from `id`. */
  label?: string;
  /** Level-0 image pixel coordinates (a box's centre). */
  x: number;
  y: number;
  /** Width and height in level-0 pixels: the point draws as that box. */
  w?: number;
  h?: number;
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
  /** A click (not a drag) in pan mode on a point or box the filters keep. */
  onPointClick?: (id: string) => void;
  onZoomChange?: (zoom: number) => void;
  /** The reader moved the view (pan or zoom), not the tile itself: for tiles
   *  whose views are linked. */
  onViewChange?: (camera: { zoom: number; target: [number, number] }) => void;
  /** A finished lasso or rectangle, in image coordinates. */
  onRoi?: (polygon: Polygon) => void;
  /** A click on an orthogonal slice picked another Z plane. */
  onPlaneChange?: (z: number) => void;
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
 *  `opacity`, in the image's own channel colours; `side` draws it in a
 *  second view on the left, same zoom and position, so the two read side by
 *  side rather than through each other. */
export type CompareMode = 'off' | 'colours' | 'fade' | 'side';

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
  /** Warm the cache with these stores at the current view (metadata and the
   *  tiles of the current plane), so switching to one draws at once. */
  prefetch(stores: readonly BioimageZarrStore[]): Promise<void>;
  /** Open an overlay image (replacing any previous one), or drop it with
   *  null. Rejects with `LoadSupersededError` when a later call replaced it. */
  setOverlay(store: BioimageZarrStore | null): Promise<OverlayInfo | null>;
  setOverlayStyle(style: OverlayStyle): void;
  setHighlighted(ids: ReadonlySet<string>): void;
  /** Show these bounds (level-0 pixels) instead of the whole image, or the
   *  whole image again with null. Applies to later loads too. */
  frame(bounds: Bounds | null): void;
  setSelectionMode(mode: SelectionMode): void;
  /** Show the XZ and YZ slices under the XY plane, through a cursor the
   *  reader moves by clicking; false goes back to the plane alone. Ignored
   *  for an image without Z (see `BioimageInfo.ortho`). */
  setOrtho(on: boolean): void;
  /** Theme sync. `accent` rings highlighted points and draws the ROI. */
  setDark(dark: boolean, accent?: Rgb): void;
  resetView(): void;
  /** Where the view is: zoom and centre in level-0 pixels, deck.gl's
   *  orthographic terms (vizarr and Vitessce use the same). */
  camera(): { zoom: number; target: [number, number] };
  /** Look where a linked tile looks; does not report back through onViewChange. */
  setCamera(camera: { zoom: number; target: readonly [number, number] }): void;
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
/** A store whose shown level has more tiles than this is not prefetched. */
const PREFETCH_MAX_TILES = 16;
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
  zStep?: AxisStep | null;
  tStep?: AxisStep | null;
}

async function openOmeZarr(store: BioimageZarrStore): Promise<OpenedImage> {
  const loaded = await loadOmeZarrFromStore(store as never);
  // NGFF 0.4 (`.zattrs`) or 0.5 (`zarr.json`, attributes under `ome`).
  const rootAttrs = ngffRootAttrs(loaded.metadata);
  return {
    // Volume EM pyramids shrink Z too; viv reads every level at level 0's plane.
    pyramid: matchSelectionsAcrossLevels(loaded.data as unknown as PixelSource[]),
    omero: rootAttrs.omero ?? null,
    physicalSize: physicalPixelSize(rootAttrs),
    zStep: axisStep(rootAttrs, 'z'),
    tStep: axisStep(rootAttrs, 't'),
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
  // The reference's own starting channels (another modality draws these).
  let referenceOwn: ChannelState[] = [];
  let referenceToken = 0;
  // Bumped when a new reference pyramid is in place: its layer id, so the old
  // one keeps its tiles while the next store opens.
  let referenceId = 0;
  // A replaced image or reference stays drawn under its successor until the
  // successor has drawn its tiles: switching steps never flashes black.
  let lastImage: unknown = null;
  let heldImage: unknown = null;
  let lastReference: unknown = null;
  let heldReference: unknown = null;
  let referenceStyle: ReferenceStyle = { mode: 'off', opacity: 0.5, channel: 0 };
  // Overlay image (another modality), drawn over the image and the reference.
  let overlay: { pyramid: PixelSource[]; width: number; height: number; depth: number } | null =
    null;
  let overlayToken = 0;
  let overlayStyle: OverlayStyle = { channels: [], opacity: 0 };

  // Side by side (`side` compare mode): the reference in a second view on the
  // left, the image on the right, one camera for both.
  const SIDE_VIEW = 'side';
  const MAIN_VIEW = 'ortho';
  let split = false;
  // Orthogonal slices: the XY plane on top, XZ and YZ under it, each with its
  // own camera, crossing at `cursor` (level-0 voxels; its Z is the plane).
  const XZ_VIEW = 'slice-xz';
  const YZ_VIEW = 'slice-yz';
  let ortho = false;
  let slices: { xz: ReslicedSource[]; yz: ReslicedSource[] } | null = null;
  let cursor: Omit<OrthoCursor, 'z'> = { x: 0, y: 0 };
  let zScale = 1;
  let sliceStates: Record<string, ViewState> = {
    [XZ_VIEW]: { target: [0, 0, 0], zoom: 0 },
    [YZ_VIEW]: { target: [0, 0, 0], zoom: 0 },
  };
  // The reader moved a slice's camera: framing and plane changes leave it be.
  let slicesMoved = false;
  const orthoOn = () => ortho && slices !== null;
  const hostSize = () => ({
    w: split ? host.clientWidth / 2 : host.clientWidth,
    h: orthoOn() ? host.clientHeight / 2 : host.clientHeight,
  });
  const viewStateProp = () =>
    orthoOn()
      ? { [MAIN_VIEW]: viewState, ...sliceStates }
      : split
        ? { [SIDE_VIEW]: viewState, [MAIN_VIEW]: viewState }
        : viewState;
  /** World extent of a slice: across (X or Y) by Z drawn to scale. */
  const sliceExtent = (id: string): [number, number] =>
    info ? [id === XZ_VIEW ? info.width : info.height, info.sizes.z * zScale] : [1, 1];

  // Points with a size are boxes, except those too small to see at this zoom,
  // which draw (and are picked) as dots at their centre.
  let drawnBoxKey = '';
  const splitPoints = (): { dots: OverlayPoint[]; boxes: OverlayPoint[] } => {
    const scale = 2 ** viewState.zoom;
    const dots: OverlayPoint[] = [];
    const boxes: OverlayPoint[] = [];
    for (const p of points) {
      if (p.w == null || p.h == null) dots.push(p);
      else if (boxDisplay(p, scale) === 'dot') dots.push({ ...p, w: undefined, h: undefined });
      else boxes.push(p);
    }
    return { dots, boxes };
  };
  // What decides the boxes' look: how many show as dots, filled or outlined.
  const boxDisplayKey = (): string => {
    const scale = 2 ** viewState.zoom;
    const counts = { dot: 0, filled: 0, outline: 0 };
    for (const p of points) {
      if (p.w != null && p.h != null) counts[boxDisplay(p, scale)] += 1;
    }
    return `${counts.dot}|${counts.filled}|${counts.outline}`;
  };

  // What the camera fits to: the whole image, or the bounds `frame` asked for.
  let framed: Bounds | null = null;

  const fit = () => {
    if (!info) return;
    const { w, h } = hostSize();
    const whole = fitViewState(info.width, info.height, w, h);
    const v = framed ? fitBoundsViewState(framed, w, h, 0.05) : whole;
    viewState = { ...v, minZoom: whole.zoom - 3, maxZoom: Math.max(8, v.zoom) };
    userMoved = false;
    if (orthoOn()) fitSlices();
    deck.setProps({ viewState: viewStateProp() as never });
    opts.onZoomChange?.(viewState.zoom);
  };

  /** Each slice fitted whole in its pane or, when the plane is framed on some
   *  bounds, at the plane's zoom on the cursor and the current depth. */
  const fitSlices = () => {
    if (!info) return;
    const paneW = host.clientWidth / 2;
    const paneH = host.clientHeight / 2;
    for (const id of [XZ_VIEW, YZ_VIEW]) {
      const [w, h] = sliceExtent(id);
      const whole = fitViewState(w, h, paneW, paneH);
      const across = id === XZ_VIEW ? cursor.x : cursor.y;
      const v = framed
        ? { zoom: viewState.zoom, target: [across, (plane.z + 0.5) * zScale, 0] as ViewState['target'] }
        : whole;
      sliceStates[id] = { ...v, minZoom: whole.zoom - 3, maxZoom: Math.max(8, v.zoom) };
    }
    slicesMoved = false;
  };

  const view = (dragPan: boolean) =>
    new OrthographicView({ id: MAIN_VIEW, controller: { dragPan, doubleClickZoom: dragPan } });
  const views = () => {
    const dragPan = mode === 'pan';
    if (orthoOn()) {
      const panes = { dragPan: true, doubleClickZoom: true };
      return [
        new OrthographicView({
          id: MAIN_VIEW,
          height: '50%',
          controller: { dragPan, doubleClickZoom: dragPan },
        }),
        new OrthographicView({ id: XZ_VIEW, y: '50%', width: '50%', height: '50%', controller: panes }),
        new OrthographicView({
          id: YZ_VIEW,
          x: '50%',
          y: '50%',
          width: '50%',
          height: '50%',
          controller: panes,
        }),
      ];
    }
    if (!split) return view(dragPan);
    const controller = { dragPan, doubleClickZoom: dragPan };
    return [
      new OrthographicView({ id: SIDE_VIEW, x: 0, width: '50%', controller }),
      new OrthographicView({ id: MAIN_VIEW, x: '50%', width: '50%', controller }),
    ];
  };
  // Split, the reference draws only on the left and everything else only on the right.
  const sideFilter = ({ layer, viewport }: { layer: { id: string }; viewport: { id: string } }) =>
    (viewport.id === SIDE_VIEW) === layer.id.startsWith('bioimage-reference');
  // Ortho, a slice's layers draw only in its pane, everything else on the plane.
  const orthoFilter = ({ layer, viewport }: { layer: { id: string }; viewport: { id: string } }) =>
    layer.id.startsWith(XZ_VIEW)
      ? viewport.id === XZ_VIEW
      : layer.id.startsWith(YZ_VIEW)
        ? viewport.id === YZ_VIEW
        : viewport.id === MAIN_VIEW;
  const applyViews = () => {
    deck.setProps({
      views: views() as never,
      layerFilter: (orthoOn() ? orthoFilter : split ? sideFilter : null) as never,
      viewState: viewStateProp() as never,
    });
  };
  const setSplit = (next: boolean) => {
    if (next === split) return;
    split = next;
    applyViews();
    if (!userMoved) fit();
  };

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
      if (heldReference && isLayerLoaded(`bioimage-reference-${referenceId}`)) {
        heldReference = null;
        render();
      }
      if (
        labels &&
        labelsReadyToken !== labelsToken &&
        isLayerLoaded(`bioimage-labels-${labelsToken}`)
      ) {
        markLabelsReady();
      }
    },
    onViewStateChange: ({ viewId, viewState: next }) => {
      if (orthoOn() && (viewId === XZ_VIEW || viewId === YZ_VIEW)) {
        sliceStates = { ...sliceStates, [viewId]: next as unknown as ViewState };
        slicesMoved = true;
        deck.setProps({ viewState: viewStateProp() as never });
        return next as never;
      }
      viewState = next as unknown as ViewState;
      userMoved = true;
      deck.setProps({ viewState: viewStateProp() as never });
      // Boxes change look with the zoom (dot, filled, outlined).
      if (boxDisplayKey() !== drawnBoxKey) render();
      opts.onZoomChange?.(viewState.zoom);
      opts.onViewChange?.({ zoom: viewState.zoom, target: [viewState.target[0], viewState.target[1]] });
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
    if (heldImage) {
      heldImage = null;
      render();
    }
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

  /** The XZ and YZ slices through the cursor, and the cursor's lines on all
   *  three panes. */
  const sliceLayers = (image: BioimageInfo): unknown[] => {
    if (!slices) return [];
    const shown = renderedChannels(channels);
    const matrix = zScale !== 1 ? ScaleMatrix.of2d(1, zScale) : null;
    const layers: unknown[] = [];
    for (const [id, pyramid, at] of [
      [XZ_VIEW, slices.xz, cursor.y],
      [YZ_VIEW, slices.yz, cursor.x],
    ] as const) {
      layers.push(
        imageLayer(pyramid as unknown as PixelSource[], {
          id: `${id}-${loadToken}`,
          loader: pyramid,
          selections: shown.map((c) => ({ c: c.index, t: plane.t, at: Math.floor(at) })),
          colors: shown.map((c) => hexToRgb(c.color) ?? [255, 255, 255]),
          contrastLimits: shown.map((c) => c.contrastLimits),
          channelsVisible: shown.map((c) => c.visible),
          ...(matrix ? { modelMatrix: matrix } : {}),
          onTileError: (err: unknown) => {
            if (isBoundsError(err)) return;
            opts.onError?.(err instanceof Error ? err : new Error(String(err)));
          },
        }),
      );
    }
    // Lines through the voxel centres, in each pane's own world coordinates.
    const z = (plane.z + 0.5) * zScale;
    const depth = image.sizes.z * zScale;
    const cx = Math.floor(cursor.x) + 0.5;
    const cy = Math.floor(cursor.y) + 0.5;
    const lines: Record<string, Array<[Vec2, Vec2]>> = {
      'cursor-xy': [
        [[cx, 0], [cx, image.height]],
        [[0, cy], [image.width, cy]],
      ],
      [`${XZ_VIEW}-cursor`]: [
        [[cx, 0], [cx, depth]],
        [[0, z], [image.width, z]],
      ],
      [`${YZ_VIEW}-cursor`]: [
        [[cy, 0], [cy, depth]],
        [[0, z], [image.height, z]],
      ],
    };
    for (const [id, data] of Object.entries(lines)) {
      layers.push(
        new LineLayer<[Vec2, Vec2]>({
          id,
          data,
          getSourcePosition: (d) => d[0],
          getTargetPosition: (d) => d[1],
          getColor: [...accent, 170],
          getWidth: 1,
          widthUnits: 'pixels',
          updateTriggers: { getColor: accent },
        }),
      );
    }
    return layers;
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
      setSplit(!orthoOn() && comparing && referenceStyle.mode === 'side');
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
      if (heldImage) layers.push(heldImage);
      lastImage = imageLayer(data, imageProps);
      layers.push(lastImage);
      if (comparing && reference) {
        const refAxes = reference[0].labels;
        const colours = referenceStyle.mode === 'colours';
        const own = referenceChannelsFor(shown, channels, referenceOwn, referenceChannels);
        const sameModality = !referenceOwn.length || own.every((c) => shown.includes(c));
        const drawn = colours
          ? sameModality
            ? compared && compared.index < Math.max(referenceChannels, 1)
              ? [compared]
              : []
            : own.slice(0, 1)
          : own;
        if (drawn.length) {
          if (heldReference) layers.push(heldReference);
          lastReference = imageLayer(reference, {
              id: `bioimage-reference-${referenceId}`,
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
              opacity: colours || split ? 1 : referenceStyle.opacity,
              ...(colours ? { parameters: ADDITIVE_BLEND } : {}),
              onTileError: (err: unknown) => {
                if (isBoundsError(err)) return;
                opts.onError?.(err instanceof Error ? err : new Error(String(err)));
              },
            });
          layers.push(lastReference);
        }
      }
    }
    if (orthoOn() && info) layers.push(...sliceLayers(info));
    const overlayed = data && info ? overlayLayer(info) : null;
    if (overlayed) layers.push(overlayed);
    const labelsOverlay = labelsLayer();
    if (labelsOverlay) layers.push(labelsOverlay);
    const { dots, boxes } = splitPoints();
    drawnBoxKey = boxDisplayKey();
    if (boxes.length) {
      layers.push(
        new PolygonLayer<OverlayPoint>({
          id: 'bioimage-boxes',
          data: boxes,
          getPolygon: (p) => {
            const hw = (p.w ?? 0) / 2;
            const hh = (p.h ?? 0) / 2;
            return [
              [p.x - hw, p.y - hh],
              [p.x + hw, p.y - hh],
              [p.x + hw, p.y + hh],
              [p.x - hw, p.y + hh],
            ];
          },
          filled: true,
          stroked: true,
          getFillColor: (p) =>
            boxDisplay(p, 2 ** viewState.zoom) === 'filled'
              ? [...p.color, p.faded ? 10 : 60]
              : [0, 0, 0, 0],
          getLineColor: (p) =>
            highlighted.has(p.id) ? [...accent, 255] : [...p.color, p.faded ? 50 : 230],
          getLineWidth: (p) => (highlighted.has(p.id) ? 3 : 1.25),
          lineWidthUnits: 'pixels',
          updateTriggers: {
            getFillColor: drawnBoxKey,
            getLineColor: [highlightVersion, accent],
            getLineWidth: highlightVersion,
          },
        }),
      );
    }
    if (dots.length) {
      layers.push(
        new ScatterplotLayer<OverlayPoint>({
          id: 'bioimage-points',
          data: dots,
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

  /** The pane under the pointer and the world point there. */
  const locate = (e: PointerEvent): { world: Vec2; screen: Vec2; view: string } | null => {
    const rect = host.getBoundingClientRect();
    const screen: Vec2 = [e.clientX - rect.left, e.clientY - rect.top];
    const vp = deck
      .getViewports()
      .find(
        (v) =>
          screen[0] >= v.x &&
          screen[0] < v.x + v.width &&
          screen[1] >= v.y &&
          screen[1] < v.y + v.height,
      );
    if (!vp) return null;
    const [x, y] = vp.unproject([screen[0] - vp.x, screen[1] - vp.y]);
    return { world: [x, y], screen, view: vp.id };
  };

  // Only the plane (not the reference beside it, nor a slice) picks and selects.
  const toImage = (e: PointerEvent): { world: Vec2; screen: Vec2 } | null => {
    const at = locate(e);
    return at && at.view === MAIN_VIEW ? at : null;
  };

  /** Move the cursor; a click on a slice also moves the plane to its depth. */
  const moveCursor = (next: Partial<OrthoCursor>) => {
    if (!info) return;
    const clamp = (v: number, size: number) => Math.min(size - 1, Math.max(0, Math.floor(v)));
    cursor = {
      x: next.x == null ? cursor.x : clamp(next.x, info.width),
      y: next.y == null ? cursor.y : clamp(next.y, info.height),
    };
    render();
    if (next.z != null) {
      const z = clamp(next.z, info.sizes.z);
      if (z !== plane.z) opts.onPlaneChange?.(z);
    }
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
    if (!start || mode !== 'pan') return;
    const dx = e.clientX - start[0];
    const dy = e.clientY - start[1];
    if (dx * dx + dy * dy > CLICK_MAX_MOVE_PX * CLICK_MAX_MOVE_PX) return;
    const where = orthoOn() ? locate(e) : null;
    if (where && where.view !== MAIN_VIEW) {
      const [u, v] = where.world;
      moveCursor(where.view === XZ_VIEW ? { x: u, z: v / zScale } : { y: u, z: v / zScale });
      return;
    }
    const at = toImage(e);
    if (!at) return;
    if (opts.onPointClick && points.length) {
      // A dot is hit within its drawn radius, in world units at this zoom.
      const slack = pointRadius * 2 ** -viewState.zoom;
      const { dots, boxes } = splitPoints();
      const kept = [...dots, ...boxes].filter((p) => !p.faded);
      const hit = pointAt(kept, at.world[0], at.world[1], slack);
      if (hit) {
        opts.onPointClick(hit.id);
        return;
      }
    }
    if (orthoOn()) moveCursor({ x: at.world[0], y: at.world[1] });
    if (!labels || !opts.onLabelClick) return;
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
      // An image of the same size (a refresh, the next step of a registration,
      // another sample of a series) keeps the camera, and the old image stays
      // drawn until the new one has its tiles. A refresh (`keepView`) also
      // keeps what the reader set up on it.
      const sameFrame = info !== null && info.width === width && info.height === height;
      const xz = reslice(pyramid as never, 'xz');
      const yz = reslice(pyramid as never, 'yz');
      slices = xz && yz ? { xz, yz } : null;
      zScale = zAspect(opened.zStep ?? null, opened.physicalSize);
      if (!sameFrame) cursor = { x: Math.floor(width / 2), y: Math.floor(height / 2) };
      const keep = Boolean(loadOpts?.keepView) && sameFrame;
      heldImage = sameFrame && data ? lastImage : null;
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
        zStep: opened.zStep ?? null,
        tStep: opened.tStep ?? null,
        ortho: slices !== null,
      };
      if (ortho) applyViews();
      if (!sameFrame || !userMoved) fit();
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
      // Framed slices follow the depth the framing moved to.
      if (orthoOn() && framed && !slicesMoved) {
        fitSlices();
        deck.setProps({ viewState: viewStateProp() as never });
      }
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
      const pyramid = matchSelectionsAcrossLevels(loaded.data as unknown as PixelSource[]);
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
      if (!store) {
        reference = null;
        referenceChannels = 0;
        referenceOwn = [];
        heldReference = null;
        render();
        return null;
      }
      // The current reference stays on screen while the next one opens: the
      // side-by-side split would otherwise close and reopen, moving the view.
      const opened = await openOmeZarr(store);
      if (token !== referenceToken || disposed) throw new LoadSupersededError();
      const base = opened.pyramid[0];
      const lab = base.labels;
      heldReference = reference ? lastReference : null;
      reference = opened.pyramid;
      referenceId += 1;
      referenceChannels = lab.includes('c') ? (base.shape[lab.indexOf('c')] ?? 1) : 1;
      referenceOwn = resolveChannels({
        sizeC: referenceChannels,
        dtype: base.dtype,
        omero: opened.omero as never,
      });
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

    async prefetch(stores) {
      const shown = renderedChannels(channels);
      await Promise.all(
        stores.map(async (store) => {
          try {
            const { pyramid } = await openOmeZarr(store);
            if (disposed) return;
            // The level the current zoom draws, its tiles for the shown plane.
            const level =
              pyramid[Math.min(pyramid.length - 1, Math.max(0, Math.round(-viewState.zoom)))];
            const lab = level.labels;
            const size = (axis: string) => level.shape[lab.indexOf(axis)] ?? 1;
            const tile = (level as unknown as { tileSize?: number }).tileSize ?? 512;
            const nx = Math.ceil(size('x') / tile);
            const ny = Math.ceil(size('y') / tile);
            if (!level.getTile || nx * ny > PREFETCH_MAX_TILES) return;
            const getTile = level.getTile.bind(level);
            const wanted = shown.length ? shown : [{ index: 0 } as ChannelState];
            const reads: Promise<unknown>[] = [];
            for (let y = 0; y < ny; y++) {
              for (let x = 0; x < nx; x++) {
                for (const c of wanted) {
                  reads.push(
                    getTile({
                      x,
                      y,
                      selection: selectionFor(lab, { c: c.index, z: plane.z, t: plane.t }),
                    }),
                  );
                }
              }
            }
            await Promise.allSettled(reads);
          } catch {
            /* a warm-up only: the real read reports its own error */
          }
        }),
      );
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
      deck.setProps({ views: views() as never });
      render();
    },

    setOrtho(on) {
      if (on === ortho) return;
      ortho = on;
      applyViews();
      fit();
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

    camera() {
      return { zoom: viewState.zoom, target: [viewState.target[0], viewState.target[1]] };
    },

    setCamera(camera) {
      viewState = {
        ...viewState,
        zoom: camera.zoom,
        target: [camera.target[0], camera.target[1], 0] as ViewState['target'],
      };
      userMoved = true;
      deck.setProps({ viewState: viewStateProp() as never });
      if (boxDisplayKey() !== drawnBoxKey) render();
      opts.onZoomChange?.(viewState.zoom);
    },

    frame(bounds) {
      framed = bounds;
      // The slices cut through what is framed.
      if (bounds && info) {
        cursor = {
          x: Math.min(info.width - 1, Math.max(0, Math.floor((bounds.minX + bounds.maxX) / 2))),
          y: Math.min(info.height - 1, Math.max(0, Math.floor((bounds.minY + bounds.maxY) / 2))),
        };
      }
      fit();
      render();
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
