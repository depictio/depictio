import { useEffect, type RefObject } from 'react';
import { comparer, reaction } from 'mobx';
import { isAlive } from '@jbrowse/mobx-state-tree';

import { fitTrackHeights, isFittableDisplay } from './fitTracks';

interface Display {
  type?: string;
  height: number;
  setHeight: (px: number) => unknown;
}

/** ``isAlive`` throws on anything that is not a state-tree node. */
const alive = (node: unknown): boolean => {
  try {
    return !!node && isAlive(node as Parameters<typeof isAlive>[0]);
  } catch {
    return false;
  }
};

const displaysOf = (view: unknown): Display[] => {
  if (!alive(view)) return [];
  const tracks = (view as { tracks: Array<{ displays?: unknown[] }> }).tracks;
  return tracks
    .map((t) => t.displays?.[0] as Display | undefined)
    .filter((d): d is Display => !!d && typeof d.setHeight === 'function');
};

/**
 * While `enabled`, stretch the signal tracks of `view` so the tracks fill the
 * `host` box (see `fitTracks.ts`). Re-fits on a resize of the box or of the
 * view (header toggled) and when a track opens or closes; turning it off puts
 * every track back to the height it had before.
 */
export function useFitTracks(
  view: unknown,
  host: RefObject<HTMLElement | null>,
  enabled: boolean,
): void {
  useEffect(() => {
    const box = host.current;
    if (!enabled || !view || !box || typeof ResizeObserver === 'undefined') return undefined;
    const original = new Map<Display, number>();
    let frame = 0;
    const fit = () => {
      frame = 0;
      const content = box.firstElementChild as HTMLElement | null;
      const displays = displaysOf(view);
      if (!content || !displays.length) return;
      const tracks = displays.map((d) => ({ height: d.height, fittable: isFittableDisplay(d.type) }));
      const target = fitTrackHeights(tracks, content.offsetHeight, box.clientHeight);
      if (target == null) return;
      for (const d of displays) {
        if (!isFittableDisplay(d.type) || Math.abs(d.height - target) <= 1) continue;
        if (!original.has(d)) original.set(d, d.height);
        d.setHeight(target);
      }
    };
    const schedule = () => {
      if (!frame) frame = window.requestAnimationFrame(fit);
    };
    const ro = new ResizeObserver(schedule);
    ro.observe(box);
    if (box.firstElementChild) ro.observe(box.firstElementChild);
    const dispose = reaction(() => displaysOf(view), schedule, {
      equals: comparer.shallow,
      fireImmediately: true,
    });
    return () => {
      dispose();
      ro.disconnect();
      if (frame) window.cancelAnimationFrame(frame);
      for (const [d, px] of original) if (alive(d)) d.setHeight(px);
    };
  }, [view, host, enabled]);
}
