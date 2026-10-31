/**
 * Publishes what a `genome_view`'s genome axis shows on the view-window store,
 * so a genome browser following "other genome tiles" pans with it (the same
 * link the browser has always offered the other way).
 *
 * Only the reader's own pans and zooms go out. A zoom the tile issues itself
 * (an opening region, a followed filter, the axis following a browser) is not a
 * navigation: publishing it would send the browser to a whole chromosome the
 * moment it had put the axis there. `isCodeZoom` says when the axis is moving
 * on the tile's own account, and the events inside that stretch are dropped.
 * Echo of the tile's own window coming back from a browser that followed it is
 * handled by the store (a tile ignores windows it originated) and by
 * `approxSameWindow` in the renderer.
 */
import { useEffect, useRef } from 'react';
import type { EmbedResult } from '@genome-spy/core/types/embedApi.js';

import { usePublishViewWindow } from '../../../highlight/viewWindow';
import type { Contig } from './genomeSpySpec';
import { isGenomeSpyLive, onScaleDomainChange, readViewDomain } from './useGenomeSpy';
import {
  approxSameWindow,
  VIEW_WINDOW_DEBOUNCE_MS,
  windowFromDomain,
} from './viewWindowPublish';

export interface ViewWindowPublishOptions {
  api: EmbedResult | null;
  /** The tile's own index: the source of the windows it publishes. */
  index: string;
  contigs: readonly Contig[] | null;
  /** False when publishing is off (no window store, or the tile opted out). */
  enabled?: boolean;
  /** True while the axis moves because the tile moved it. Read at event time. */
  isCodeZoom: () => boolean;
}

/** The last window this tile published, to tell its own echo from a move. */
export function useViewWindowPublish({
  api,
  index,
  contigs,
  enabled = true,
  isCodeZoom,
}: ViewWindowPublishOptions): { lastPublished: { current: ReturnType<typeof windowFromDomain> } } {
  const publish = usePublishViewWindow(index);
  const lastPublished = useRef<ReturnType<typeof windowFromDomain>>(null);
  const isCodeZoomRef = useRef(isCodeZoom);
  isCodeZoomRef.current = isCodeZoom;
  const contigsRef = useRef(contigs);
  contigsRef.current = contigs;

  useEffect(() => {
    if (!api || !enabled) return undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onDomain = () => {
      clearTimeout(timer);
      // The tile's own zoom: not the reader's gesture, nothing to publish.
      if (isCodeZoomRef.current()) return;
      timer = setTimeout(() => {
        if (!isGenomeSpyLive(api) || isCodeZoomRef.current()) return;
        const win = windowFromDomain(readViewDomain(api), contigsRef.current);
        if (win && approxSameWindow(win, lastPublished.current)) return;
        lastPublished.current = win;
        publish(win);
      }, VIEW_WINDOW_DEBOUNCE_MS);
    };
    const off = onScaleDomainChange(api, onDomain);
    return () => {
      clearTimeout(timer);
      off();
      // Only a window this tile put up: the store's `null` publish is scoped.
      if (lastPublished.current) publish(null);
      lastPublished.current = null;
    };
  }, [api, enabled, publish]);

  return { lastPublished };
}
