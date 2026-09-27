// Pyramidal bioimage viewer behind a strict interface: OME-Zarr (NGFF 0.4,
// which is also how a SpatialData image is served) and OME-TIFF.
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
import { PolygonLayer, ScatterplotLayer } from '@deck.gl/layers';
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
  const rootAttrs = loaded.metadata as unknown as {
    omero?: OpenedImage['omero'];
    multiscales?: never[];
  };
  return {
    pyramid: loaded.data as unknown as PixelSource[],
    omero: rootAttrs.omero ?? null,
    physicalSize: physicalPixelSize(rootAttrs as never),
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

      // Contrast statistics off the lowest level, only for channels that
      // have no window from the config or omero.
      const lowest = pyramid[pyramid.length - 1];
      const lowPixels =
        (lowest.shape[labels.indexOf('x')] ?? 0) * (lowest.shape[labels.indexOf('y')] ?? 0);
      const pinned = new Set(
        (configChannels ?? []).filter((c) => c.contrast_limits).map((c) => c.index),
      );
      const omeroChannels = (omero?.channels ?? []) as Array<{
        window?: { start?: number; end?: number };
      }>;
      const stats: Array<ChannelStats | null> = [];
      if (lowPixels > 0 && lowPixels <= STATS_MAX_PIXELS) {
        const wanted = Array.from({ length: Math.min(sizes.c, STATS_MAX_CHANNELS) }, (_, c) => c)
          .filter((c) => !pinned.has(c))
          .filter((c) => typeof omeroChannels[c]?.window?.end !== 'number');
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
      render();
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
      try {
        deck.finalize();
      } catch {
        /* already torn down */
      }
    },
  };
}
