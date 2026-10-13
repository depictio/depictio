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

import { Deck, OrthographicView } from '@deck.gl/core';
import { BitmapLayer, PolygonLayer, ScatterplotLayer } from '@deck.gl/layers';
import {
  MultiscaleImageLayer,
  getChannelStats,
  loadOmeTiff,
  loadOmeZarrFromStore,
} from '@hms-dbmi/viv';

import type { BioimageSource, BioimageTiffSource, BioimageZarrStore } from '../../../api';
import {
  axisSizes,
  hexToRgb,
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
import { labelContourRgba } from './labelContours';
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
  id: string;
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
  onZoomChange?: (zoom: number) => void;
  /** A finished lasso or rectangle, in image coordinates. */
  onRoi?: (polygon: Polygon) => void;
  onError?: (error: Error) => void;
}

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
/** Screen pixels a lasso has to travel before it records another vertex. */
const LASSO_MIN_STEP_PX = 3;
const DEFAULT_ACCENT: Rgb = [250, 176, 5];
/** Largest label plane drawn as an outline: the finest pyramid level under this many pixels. */
const LABEL_MAX_PIXELS = 4_000_000;
/** Where an OME-Zarr store keeps its first label image (NGFF `labels/<name>`). */
const LABEL_PREFIX = 'labels/0';

type PixelSource = {
  shape: number[];
  dtype: string;
  labels: string[];
  getRaster(opts: { selection: Record<string, number> }): Promise<{ data: ArrayLike<number> }>;
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

/** The store seen from inside `labels/0`, so the image reader finds that group's `.zattrs`. */
function labelsSubStore(store: BioimageZarrStore): BioimageZarrStore {
  const at = (key: string) => `${LABEL_PREFIX}/${key.replace(/^\/+/, '')}`;
  return {
    get: (key, opts) => store.get(at(key), opts),
    getRange: (key, range, opts) => store.getRange(at(key), range, opts),
  };
}

/** The store's first label image, or null when it has none (or it cannot be read).
 *  The outline is an extra on top of the image: a failure here must not break the image. */
async function openLabels(store: BioimageZarrStore): Promise<PixelSource[] | null> {
  try {
    const loaded = await loadOmeZarrFromStore(labelsSubStore(store) as never);
    return loaded.data as unknown as PixelSource[];
  } catch {
    return null;
  }
}

/** Finest level whose plane stays under the outline budget; the coarsest otherwise. */
function labelLevel(pyramid: PixelSource[]): PixelSource {
  const fits = pyramid.find((level) => {
    const w = level.shape[level.labels.indexOf('x')] ?? 0;
    const h = level.shape[level.labels.indexOf('y')] ?? 0;
    return w * h <= LABEL_MAX_PIXELS;
  });
  return fits ?? pyramid[pyramid.length - 1];
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
  // Label outline: the store's label pyramid, and the outline of the plane on screen.
  let labelPyramid: PixelSource[] | null = null;
  let labelImage: { key: string; canvas: HTMLCanvasElement } | null = null;
  let loadToken = 0;
  // Load whose first viewport has been reported, so onViewportLoad fires once per load.
  let readyToken = -1;
  let userMoved = false;
  let disposed = false;
  let viewState: ViewState = { target: [0, 0, 0], zoom: 0 };

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
      if (readyToken === loadToken || !data) return;
      const id = `bioimage-image-${loadToken}`;
      const layer = deck.props.layers.find((l) => (l as { id?: string } | null)?.id === id);
      const managed = (
        deck as unknown as { layerManager?: { getLayers(): Array<{ id: string; isLoaded: boolean }> } }
      ).layerManager
        ?.getLayers()
        .find((l) => l.id === id);
      if (layer && managed?.isLoaded) markReady();
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

  function markReady() {
    if (readyToken === loadToken) return;
    readyToken = loadToken;
    opts.onViewportLoad?.();
  }

  // Redraw the outline for the plane on screen. A read superseded by a newer
  // plane or load is dropped; a failed read leaves the outline off.
  const refreshLabels = async () => {
    const pyramid = labelPyramid;
    if (!pyramid || !info) return;
    const token = loadToken;
    const { z, t } = plane;
    const key = `${token}:${z}:${t}`;
    if (labelImage?.key === key) return;
    const level = labelLevel(pyramid);
    const w = level.shape[level.labels.indexOf('x')] ?? 0;
    const h = level.shape[level.labels.indexOf('y')] ?? 0;
    try {
      const selection = selectionFor(level.labels, { c: 0, z, t });
      const raster = await level.getRaster({ selection });
      if (disposed || token !== loadToken || z !== plane.z || t !== plane.t) return;
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const rgba = labelContourRgba(raster.data, w, h);
      ctx.putImageData(new ImageData(rgba as never, w, h), 0, 0);
      labelImage = { key, canvas };
      render();
    } catch {
      labelImage = null;
    }
  };

  const render = () => {
    if (disposed) return;
    const layers: unknown[] = [];
    if (data && info) {
      const shown = renderedChannels(channels);
      const labels = info.labels;
      // `colors` belongs to viv's default ColorPaletteExtension, which the
      // layer's own prop type does not list, hence the loose object.
      const imageProps: Record<string, unknown> = {
        // Keyed by load, so a new store starts from an empty tile cache.
        id: `bioimage-image-${loadToken}`,
        loader: data,
        selections: shown.map((c) => selectionFor(labels, { c: c.index, z: plane.z, t: plane.t })),
        colors: shown.map((c) => hexToRgb(c.color) ?? [255, 255, 255]),
        contrastLimits: shown.map((c) => c.contrastLimits),
        channelsVisible: shown.map((c) => c.visible),
        onViewportLoad: () => markReady(),
        onTileError: (err: unknown) => {
          if (isBoundsError(err)) return;
          opts.onError?.(err instanceof Error ? err : new Error(String(err)));
        },
      };
      layers.push(new MultiscaleImageLayer(imageProps as never));
    }
    if (labelImage && info) {
      layers.push(
        new BitmapLayer({
          id: 'bioimage-labels',
          image: labelImage.canvas,
          // Row 0 is the top of the image, as in the tiles, and the labels cover the whole image.
          bounds: [0, info.height, info.width, 0],
          pickable: false,
          // Nearest keeps each outline pixel crisp when zoomed in.
          textureParameters: { minFilter: 'nearest', magFilter: 'nearest' },
        }),
      );
    }
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

  const onPointerDown = (e: PointerEvent) => {
    if (mode === 'pan' || e.button !== 0) return;
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

  const onPointerUp = (e: PointerEvent) => {
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
      labelImage = null;
      labelPyramid = source.kind === 'zarr' ? await openLabels(source.store) : null;
      if (token !== loadToken || disposed) throw new LoadSupersededError();
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
      void refreshLabels();
      return info;
    },

    setChannels(next) {
      channels = [...next];
      render();
    },

    setSelection(sel) {
      if (sel.z === plane.z && sel.t === plane.t) return;
      plane = { z: sel.z, t: sel.t };
      render();
      void refreshLabels();
    },

    setPoints(next, radius) {
      points = next;
      pointRadius = radius;
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
