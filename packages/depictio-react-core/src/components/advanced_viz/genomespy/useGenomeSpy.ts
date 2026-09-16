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
 * genomespy_track tile ever downloads it. `./minimal` skips the BAM / VCF /
 * BigWig / parquet parsers; the chosen renderer backend is registered by its
 * side-effect module.
 */
import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

import type { EmbedResult } from '@genome-spy/core/types/embedApi.js';
import type { IntervalSelection } from '@genome-spy/core/types/selectionTypes.js';
import type { RootSpec } from '@genome-spy/core/spec/root.js';
import { BRUSH_PARAM, DATASET_NAME } from './genomeSpySpec';

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
        // The spec may legitimately declare no brush param.
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
