/**
 * The one place GenomeSpy's imperative API is touched.
 *
 * Mount model: the renderer owns a `<div>`, this hook `embed()`s into it once
 * the spec is ready and `finalize()`s on unmount or whenever the spec, the
 * renderer backend or the theme changes. Row-only updates (a filter moved, the
 * refresh tick fired) go through `api.datasets.set()` and never remount.
 *
 * The library is `import()`ed here rather than at module top so the
 * advanced_viz chunk does not carry it: Vite emits it as `vendor-genomespy`
 * (see depictio/viewer/vite.config.ts) and only a dashboard with a
 * genome_view tile ever downloads it. `./minimal` skips the BAM / VCF /
 * BigWig / parquet parsers; the chosen renderer backend is registered by its
 * side-effect module.
 *
 * The dev viewer container has no `node_modules` of its own, so this import
 * fails there until the image is rebuilt. That failure surfaces as the tile's
 * error message rather than a blank canvas, which is the point of keeping the
 * import inside the hook.
 */
import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

import type { EmbedResult } from '@genome-spy/core/types/embedApi.js';
import type { RootSpec } from '@genome-spy/core/spec/root.js';
import { attachZoomGate } from '../../zoomGateDom';
import { BRUSH_PARAM, DATASET_NAME, GENOME_SCALE_NAME } from './genomeSpySpec';
import type { Contig } from './genomeSpySpec';

export type GenomeSpyBackend = 'webgl' | 'canvas';

export interface UseGenomeSpyOptions {
  /** Which backend to register and request. `webgl` costs one GL context
   *  (see webglBudget.ts); `canvas` costs none and keeps every feature. */
  backend: GenomeSpyBackend;
  /**
   * True when the spec declares `data.lazy` blocks (a file-backed track).
   *
   * The lazy sources for vcf / bam / bigwig / bigbed / gff3 / tabix /
   * indexedFasta are registered by the *fat* entry point only: `./minimal`
   * deliberately skips them, which is why it is the default. Passing `true`
   * loads `@genome-spy/core` instead, and with it those parsers and their
   * @gmod dependencies. Table-backed tiles keep the minimal bundle and their
   * current download size; a dashboard without a file track never fetches the
   * fat chunk.
   */
  lazySources?: boolean;
  /** Called with the picked row on a mark click. */
  onPick?: (datum: Readonly<Record<string, unknown>>) => void;
  /** Called with the brushed genome interval (linearised coordinates), or
   *  `null` when the brush is cleared. */
  onBrush?: (interval: number[] | null) => void;
  /** Called with the row under the pointer, and `null` when it leaves the
   *  marks or the canvas. Best effort: it needs GenomeSpy's `mouseover`
   *  event, and a build without it simply never calls this. */
  onHover?: (datum: Readonly<Record<string, unknown>> | null) => void;
  /** What a drag does, appended to the zoom hint ("drag to select"). */
  dragHint?: string;
}

export interface UseGenomeSpyResult {
  /** Resolved once the embed is live; `null` while loading or after teardown. */
  api: EmbedResult | null;
  /** Message from a failed embed, or `null`. */
  error: string | null;
  /** True when this embed replaced another and reopened on the view the old
   *  one showed (see {@link readViewDomain}): the region in force needs no
   *  zoom of its own on it. */
  restoredView: boolean;
}

/**
 * Embeds this hook has torn down. React publishes the successor one render
 * late, so in the commit where a viz control changes the spec, the renderer's
 * own effects still hold the old embed, and GenomeSpy throws on any data or
 * zoom call made through it ("Cannot update named data through a finalized
 * embed"). The helpers below skip a finalized embed; its successor is built
 * from the current rows and zooms again when it arrives.
 */
const finalizedEmbeds = new WeakSet<EmbedResult>();

/** Tear an embed down and remember it, so later calls through it are no-ops. */
export function finalizeGenomeSpy(api: EmbedResult): void {
  finalizedEmbeds.add(api);
  api.finalize();
}

/** False once the hook has torn `api` down. */
export function isGenomeSpyLive(api: EmbedResult): boolean {
  return !finalizedEmbeds.has(api);
}

/**
 * Contigs of a GenomeSpy built-in assembly (hg38, mm10, …).
 *
 * Resolved through the same dynamic import as the embed so the package stays
 * out of the synchronous chunk. Returns `null` for an unknown assembly, which
 * is the signal to derive the contig list from the rows instead.
 */
export async function loadAssemblyContigs(assembly: string): Promise<Contig[] | null> {
  try {
    const { getContigs } = await import('@genome-spy/core/genome/genomes.js');
    return getContigs(assembly);
  } catch {
    return null;
  }
}

/**
 * Embed `spec` into `container`. `spec` should be memoised by the caller and
 * only change when the *shape* changes (columns, mark, threshold, theme):
 * every change tears the embed down and rebuilds it. Pass the same object and
 * call {@link setGenomeSpyRows} to swap data in place.
 */
export function useGenomeSpy(
  container: RefObject<HTMLDivElement | null>,
  spec: RootSpec | null,
  {
    backend,
    lazySources = false,
    onPick,
    onBrush,
    onHover,
    dragHint = 'drag to select',
  }: UseGenomeSpyOptions,
): UseGenomeSpyResult {
  const [api, setApi] = useState<EmbedResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restoredView, setRestoredView] = useState(false);
  // What the torn-down embed showed, so a rebuild (a mark, a lane or a theme
  // changed) reopens there rather than on the whole genome.
  const lastViewRef = useRef<unknown[] | null>(null);
  // Callbacks are read through refs so a new closure from the renderer's
  // render does not count as a reason to remount the embed.
  const onPickRef = useRef(onPick);
  const onBrushRef = useRef(onBrush);
  onPickRef.current = onPick;
  onBrushRef.current = onBrush;
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;
  // Read when the embed (re)mounts: a drag mode change rebuilds the spec.
  const dragHintRef = useRef(dragHint);
  dragHintRef.current = dragHint;

  useEffect(() => {
    const el = container.current;
    if (!el || !spec) return undefined;
    let cancelled = false;
    let live: EmbedResult | undefined;
    const unsubscribes: Array<() => void> = [];
    // GenomeSpy zooms the genome axis on a plain wheel. The gate on its host
    // keeps that wheel from the canvas: the page scrolls, Ctrl / Cmd + wheel
    // and a two-finger pinch zoom. Its hint shows on this axis's first hover,
    // long enough to read, with what a drag does.
    const detachZoomGate = attachZoomGate(el, {
      ownHint: { visibleMs: 6000, extra: dragHintRef.current },
    });

    (async () => {
      const [{ embed }] = await Promise.all([
        // Two separate literal specifiers, not one computed one: Vite only
        // code-splits an `import()` whose argument it can see, so this is what
        // keeps the fat bundle out of a dashboard that has no file track.
        lazySources ? import('@genome-spy/core') : import('@genome-spy/core/minimal'),
        backend === 'webgl'
          ? import('@genome-spy/core/rendering/webgl.js')
          : import('@genome-spy/core/rendering/canvas.js'),
      ]);
      if (cancelled) return;
      const result = await embed(el, spec, {
        renderer: backend,
        // GenomeSpy would otherwise render its own param widgets under the
        // canvas; Depictio's Settings popover is where controls live.
        inputBindingContainer: 'none',
        onError: (err) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
          return true;
        },
      });
      if (cancelled) {
        result.finalize();
        return;
      }
      live = result;
      unsubscribes.push(
        result.views.root().marks.subscribe('click', (event) => {
          onPickRef.current?.(event.hit.datum);
        }),
      );
      // Hover is optional: the event name is not in every GenomeSpy build, so
      // the subscription is guarded and a failure costs only the hover publish.
      try {
        const marks = result.views.root().marks as unknown as {
          subscribe?: (
            type: string,
            cb: (event: { hit?: { datum?: Record<string, unknown> } | null }) => void,
          ) => void;
        };
        if (typeof marks.subscribe === 'function') {
          marks.subscribe('mouseover', (event) => {
            onHoverRef.current?.(event?.hit?.datum ?? null);
          });
        }
      } catch {
        // No hover event in this build.
      }
      const onLeave = () => onHoverRef.current?.(null);
      el.addEventListener('mouseleave', onLeave);
      unsubscribes.push(() => el.removeEventListener('mouseleave', onLeave));
      try {
        // `commit`: once, when the drag is released. The default delivery
        // fires on every pointer move, and each one became a dashboard filter:
        // a refetch and a reframe per pixel, in the middle of the gesture.
        const brush = result.params.getSelection(BRUSH_PARAM);
        if (brush.type === 'interval') {
          unsubscribes.push(
            brush.subscribe(
              (snapshot) => {
                const x = snapshot.intervals.x;
                onBrushRef.current?.(snapshot.active && x ? [x[0], x[1]] : null);
              },
              { delivery: 'commit' },
            ),
          );
        }
      } catch {
        // The spec legitimately declares no brush param when the tile's
        // `region_filter_enabled` is off.
      }
      const restored = await restoreViewDomain(result, lastViewRef.current);
      if (cancelled) return;
      setError(null);
      setRestoredView(restored);
      setApi(result);
    })().catch((err: unknown) => {
      if (!cancelled) setError(err instanceof Error ? err.message : String(err));
    });

    return () => {
      cancelled = true;
      detachZoomGate();
      for (const off of unsubscribes) off();
      if (live) {
        lastViewRef.current = readViewDomain(live) ?? lastViewRef.current;
        finalizeGenomeSpy(live);
      }
      setApi(null);
    };
  }, [container, spec, backend, lazySources]);

  return { api, error, restoredView };
}

interface ViewScale {
  getComplexDomain?: () => unknown;
  isZoomable?: () => boolean;
  zoomTo?: (domain: unknown, options?: { duration?: number }) => Promise<void>;
}

const genomeScale = (api: EmbedResult): ViewScale | undefined => {
  try {
    return (api as unknown as OverlayApi).getScaleResolutionByName?.(GENOME_SCALE_NAME) as
      | ViewScale
      | undefined;
  } catch {
    return undefined;
  }
};

/**
 * The genome axis's current view, as loci (`{chrom, pos}` pairs) rather than
 * linearised offsets, so it still means the same place on an embed whose
 * contig list differs. `null` when the build does not say.
 */
export function readViewDomain(api: EmbedResult): unknown[] | null {
  if (!isGenomeSpyLive(api)) return null;
  try {
    const domain = genomeScale(api)?.getComplexDomain?.();
    return Array.isArray(domain) && domain.length >= 2 ? domain : null;
  } catch {
    return null;
  }
}

/**
 * Put a view read by {@link readViewDomain} on `api`, at once. False when
 * there is none, or when it does not fit this axis (a contig it lacks).
 */
export async function restoreViewDomain(api: EmbedResult, domain: unknown[] | null): Promise<boolean> {
  if (!domain) return false;
  const scale = genomeScale(api);
  if (!scale?.zoomTo || !scale.isZoomable?.()) return false;
  try {
    await scale.zoomTo(domain, { duration: 0 });
    return true;
  } catch {
    return false;
  }
}

/**
 * Clear the region brush drawn on the axis, through the selection's own
 * `clear()`. A cleared brush may reach the subscription as `null`, which the
 * tile reads as "no region".
 */
export function clearGenomeSpyBrush(api: EmbedResult): void {
  if (!isGenomeSpyLive(api)) return;
  try {
    api.params.getSelection(BRUSH_PARAM).clear();
  } catch {
    // No brush param (region filter off) or no setter in this build.
  }
}

/**
 * Replace a dataset's rows in place, without a remount. GenomeSpy throws from
 * inside the swap on a row it cannot place (a contig the axis does not name):
 * caught here, so one tile keeps its previous rows rather than the error
 * reaching the dashboard's error boundary. False when the rows were refused.
 */
export function setGenomeSpyRows(
  api: EmbedResult,
  rows: Record<string, unknown>[],
  dataset: string = DATASET_NAME,
): boolean {
  if (!isGenomeSpyLive(api)) return false;
  try {
    api.datasets.set(dataset, rows);
    return true;
  } catch (err) {
    console.warn(`genomespy: rows of ${dataset} refused`, err);
    return false;
  }
}

/**
 * Zoom the genome axis to `[start, end]` on `chrom`, or back to the whole
 * genome when the region is null.
 *
 * Two callers: a tile with `follow_region_filter` on, whenever another tile's
 * region lands in the dashboard's filter list, and the emitting tile itself
 * after its locus field or `default_region` publishes a region (see
 * `ownRegionZoom`). `zoomTo` takes a complex domain (a pair of `{chrom, pos}`
 * loci), so nothing here has to know the linearised offsets.
 *
 * The whole genome needs `contigs`: the public scale API has no "reset zoom",
 * so it is spelled as the span from the first contig's start to the last
 * contig's end. An open-ended region (a chromosome with no range) is closed
 * with the contig's own length for the same reason.
 */
export async function zoomToRegion(
  api: EmbedResult,
  region: { chrom: string; start: number; end: number } | null,
  contigs?: readonly Contig[] | null,
): Promise<void> {
  if (!isGenomeSpyLive(api)) return;
  const scale = api.getScaleResolutionByName(GENOME_SCALE_NAME);
  if (!scale || !scale.isZoomable()) return;
  if (!region) {
    if (!contigs?.length) return;
    const last = contigs[contigs.length - 1];
    await scale.zoomTo([
      { chrom: contigs[0].name, pos: 0 },
      { chrom: last.name, pos: last.size },
    ]);
    return;
  }
  const end = Number.isFinite(region.end)
    ? region.end
    : (contigs?.find((c) => c.name === region.chrom)?.size ?? region.start + 1);
  await scale.zoomTo([
    { chrom: region.chrom, pos: region.start },
    { chrom: region.chrom, pos: end },
  ]);
}

/** The slice of the embed API the overlays use, checked at runtime: the
 *  installed `@genome-spy/core` types are not always available, and a build
 *  may lack either call. */
interface OverlayApi {
  updateNamedData?: (name: string, rows: unknown[]) => void;
  datasets?: { set?: (name: string, rows: unknown[]) => void };
  getScaleResolutionByName?: (name: string) => unknown;
}

/**
 * Replace the rows of one of the overlay layers' named data sources.
 *
 * Prefers `api.updateNamedData`, the call GenomeSpy defines for `data.name`
 * sources, and falls back to `api.datasets.set` (the same swap the data lanes
 * use). Returns which one took the rows, or `null` when the embed is finalized
 * or has neither, which is the caller's cue for the DOM fallback. Nothing here
 * is a brush, a filter or a zoom.
 */
export function pushOverlayRows(
  api: EmbedResult,
  name: string,
  rows: unknown[],
): 'named' | 'dataset' | null {
  if (!isGenomeSpyLive(api)) return null;
  const a = api as unknown as OverlayApi;
  try {
    if (typeof a.updateNamedData === 'function') {
      a.updateNamedData(name, rows);
      return 'named';
    }
    if (typeof a.datasets?.set === 'function') {
      a.datasets.set(name, rows);
      return 'dataset';
    }
  } catch {
    // A source the spec does not declare (a file-backed tile): no overlay.
  }
  return null;
}

/** The linearised domain the genome axis shows now, or `null` when the build
 *  does not expose it (the DOM fallback then draws nothing). */
export function readScaleDomain(api: EmbedResult): [number, number] | null {
  if (!isGenomeSpyLive(api)) return null;
  try {
    const res = (api as unknown as OverlayApi).getScaleResolutionByName?.(GENOME_SCALE_NAME) as
      | {
          getDomain?: () => unknown;
          getScale?: () => { domain?: () => unknown } | undefined;
        }
      | undefined;
    const raw = res?.getDomain?.() ?? res?.getScale?.()?.domain?.();
    if (!Array.isArray(raw) || raw.length < 2) return null;
    const lo = Number(raw[0]);
    const hi = Number(raw[raw.length - 1]);
    return Number.isFinite(lo) && Number.isFinite(hi) ? [lo, hi] : null;
  } catch {
    return null;
  }
}

/** Notify `cb` when the genome axis zooms or pans, where the build says so.
 *  Returns the unsubscribe (a no-op when there is no such event). */
export function onScaleDomainChange(api: EmbedResult, cb: () => void): () => void {
  try {
    const res = (api as unknown as OverlayApi).getScaleResolutionByName?.(GENOME_SCALE_NAME) as
      | {
          addEventListener?: (type: string, cb: () => void) => void;
          removeEventListener?: (type: string, cb: () => void) => void;
        }
      | undefined;
    if (typeof res?.addEventListener !== 'function') return () => {};
    res.addEventListener('domain', cb);
    return () => res.removeEventListener?.('domain', cb);
  } catch {
    return () => {};
  }
}
