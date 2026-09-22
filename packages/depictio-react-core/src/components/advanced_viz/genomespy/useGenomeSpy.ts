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
import type { IntervalSelection } from '@genome-spy/core/types/selectionTypes.js';
import type { RootSpec } from '@genome-spy/core/spec/root.js';
import { BRUSH_PARAM, DATASET_NAME, GENOME_SCALE_NAME } from './genomeSpySpec';
import type { Contig } from './genomeSpySpec';

export type GenomeSpyBackend = 'webgl' | 'canvas';

export interface UseGenomeSpyOptions {
  /** Which backend to register and request. `webgl` costs one GL context
   *  (see webglBudget.ts); `canvas` costs none and keeps every feature. */
  backend: GenomeSpyBackend;
  /** Called with the picked row on a mark click. */
  onPick?: (datum: Readonly<Record<string, unknown>>) => void;
  /** Called with the brushed genome interval (linearised coordinates), or
   *  `null` when the brush is cleared. */
  onBrush?: (interval: number[] | null) => void;
}

export interface UseGenomeSpyResult {
  /** Resolved once the embed is live; `null` while loading or after teardown. */
  api: EmbedResult | null;
  /** Message from a failed embed, or `null`. */
  error: string | null;
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
  { backend, onPick, onBrush }: UseGenomeSpyOptions,
): UseGenomeSpyResult {
  const [api, setApi] = useState<EmbedResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Callbacks are read through refs so a new closure from the renderer's
  // render does not count as a reason to remount the embed.
  const onPickRef = useRef(onPick);
  const onBrushRef = useRef(onBrush);
  onPickRef.current = onPick;
  onBrushRef.current = onBrush;

  useEffect(() => {
    const el = container.current;
    if (!el || !spec) return undefined;
    let cancelled = false;
    let live: EmbedResult | undefined;
    const unsubscribes: Array<() => void> = [];

    (async () => {
      const [{ embed }] = await Promise.all([
        import('@genome-spy/core/minimal'),
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
      try {
        const brush = result.getParam<IntervalSelection>(BRUSH_PARAM);
        unsubscribes.push(
          brush.subscribe((value) => {
            onBrushRef.current?.(value?.intervals?.x ?? null);
          }),
        );
      } catch {
        // The spec legitimately declares no brush param when the tile's
        // `region_filter_enabled` is off.
      }
      setError(null);
      setApi(result);
    })().catch((err: unknown) => {
      if (!cancelled) setError(err instanceof Error ? err.message : String(err));
    });

    return () => {
      cancelled = true;
      for (const off of unsubscribes) off();
      live?.finalize();
      setApi(null);
    };
  }, [container, spec, backend]);

  return { api, error };
}

/** Replace the track's rows in place, without a remount. */
export function setGenomeSpyRows(api: EmbedResult, rows: Record<string, unknown>[]): void {
  api.datasets.set(DATASET_NAME, rows);
}

/**
 * Zoom the genome axis to `[start, end]` on `chrom`, or back to the whole
 * genome when the region is null.
 *
 * This is the consumer side of the region filter: a tile with
 * `follow_region_filter` on calls it whenever another tile's brush (or a
 * chromosome multi-select in the sidebar) lands in the dashboard's filter
 * list. `zoomTo` takes a complex domain (a pair of `{chrom, pos}` loci), so
 * nothing here has to know the linearised offsets.
 */
export async function zoomToRegion(
  api: EmbedResult,
  region: { chrom: string; start: number; end: number } | null,
): Promise<void> {
  const scale = api.getScaleResolutionByName(GENOME_SCALE_NAME);
  if (!scale || !scale.isZoomable()) return;
  if (!region) {
    // An empty complex domain is not a thing; the whole-genome view is the
    // scale's own default domain, which `zoomTo` restores when handed it.
    return;
  }
  await scale.zoomTo([
    { chrom: region.chrom, pos: region.start },
    { chrom: region.chrom, pos: region.end },
  ]);
}
