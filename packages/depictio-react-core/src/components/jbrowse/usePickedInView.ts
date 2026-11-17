import { useEffect } from 'react';
import { reaction } from 'mobx';
import { isAlive } from '@jbrowse/mobx-state-tree';

import type { JBrowsePicked } from '../../api';
import {
  heightToShowPicked,
  layoutRecordIsPicked,
  pickMatchOf,
  scrollToShowPicked,
} from './pickedColour';

interface Display {
  height: number;
  setHeight: (px: number) => unknown;
  layoutFeatures?: { values: () => Iterable<unknown> };
}

interface Track {
  configuration?: { trackId?: string; type?: string };
  displays?: unknown[];
}

interface Placement {
  display: Display;
  trackId: string;
  /** The height to grow to, or null when the track is tall enough. */
  grow: number | null;
  /** The topmost picked feature, pixels from the track's top. */
  top: number;
  bottom: number;
}

const alive = (node: unknown): boolean => {
  try {
    return !!node && isAlive(node as Parameters<typeof isAlive>[0]);
  } catch {
    return false;
  }
};

/** Rectangles [top, bottom] (px) of the picked features laid out in `display`. */
function pickedRects(display: Display): Array<[number, number]> {
  const rects: Array<[number, number]> = [];
  if (!display.layoutFeatures) return rects;
  // A layout record is [left, top, right, bottom, data].
  for (const record of display.layoutFeatures.values()) {
    if (!layoutRecordIsPicked(record)) continue;
    const [, top, , bottom] = record as number[];
    if (typeof top === 'number' && typeof bottom === 'number') rects.push([top, bottom]);
  }
  return rects;
}

/**
 * Brings an annotation track's picked gene into view when it is laid out
 * below the track's height (a gene with many isoforms, or under overlapping
 * genes): the track grows, up to `PICK_TRACK_MAX_PX`, and a pick lower still
 * is scrolled to inside the track. Each track scrolls once per pick, so the
 * reader's own scrolling and resizing afterwards stand. Re-runs as blocks
 * lay out.
 */
export function usePickedInView(view: unknown, picked: JBrowsePicked | null | undefined): void {
  const key = (picked?.names ?? []).join('\u0000');
  useEffect(() => {
    if (!view || !key) return undefined;
    const scrolled = new Set<string>();
    let frame = 0;
    const dispose = reaction(
      () => {
        if (!alive(view)) return [] as Placement[];
        const out: Placement[] = [];
        for (const track of (view as { tracks: Track[] }).tracks) {
          const conf = track.configuration;
          const trackId = String(conf?.trackId ?? '');
          if (pickMatchOf(trackId, String(conf?.type ?? '')) !== 'names') continue;
          const display = track.displays?.[0] as Display | undefined;
          if (!display || typeof display.setHeight !== 'function') continue;
          const rects = pickedRects(display);
          if (!rects.length) continue;
          const first = rects.reduce((a, b) => (b[0] < a[0] ? b : a));
          out.push({
            display,
            trackId,
            grow: heightToShowPicked(
              rects.map((r) => r[1]),
              display.height,
            ),
            top: first[0],
            bottom: first[1],
          });
        }
        return out;
      },
      (placements) => {
        for (const p of placements) if (p.grow != null && alive(p.display)) p.display.setHeight(p.grow);
        // The track's scroll position lives in the DOM (JBrowse only reads it
        // back), so the pick is scrolled to there, once the new height is drawn.
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          const viewId = alive(view) ? String((view as { id?: string }).id ?? '') : '';
          for (const p of placements) {
            if (scrolled.has(p.trackId) || !alive(p.display)) continue;
            const el = document.querySelector<HTMLElement>(
              `[data-testid="trackRenderingContainer-${CSS.escape(viewId)}-${CSS.escape(p.trackId)}"]`,
            );
            if (!el) continue;
            scrolled.add(p.trackId);
            const to = scrollToShowPicked(p.top, p.bottom, el.scrollTop, el.clientHeight);
            if (to != null) el.scrollTop = to;
          }
        });
      },
      { fireImmediately: true, delay: 50 },
    );
    return () => {
      cancelAnimationFrame(frame);
      dispose();
    };
  }, [view, key]);
}
