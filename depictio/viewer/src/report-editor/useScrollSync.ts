import { useCallback, useEffect, useRef } from 'react';
import type { RefObject } from 'react';

import { tileKey } from './previewProtocol';

/** A scroll one side was asked for is not mirrored back for this long. */
const DRIVEN_MS = 800;
/** How long a scroll must rest before the other side follows. */
const SETTLE_MS = 120;
/** A tile counts as "at the top" once its bottom is this far into the view. */
const TOP_BAND = 72;

/**
 * Keeps the structure column and the preview frame on the same component.
 *
 * The column reports the first tile card at its top; the frame is scrolled to
 * it. The frame reports the first tile at the top of its own viewport (the
 * `visible` message); the column scrolls to that card, or to its tab's header
 * when the tab is folded. Each side ignores scroll events it caused itself, so
 * the two never chase each other.
 */
export function useScrollSync(
  columnRef: RefObject<HTMLElement>,
  enabled: boolean,
  frameReady: boolean,
  scrollFrameTo: (tabId: string, componentId: string) => void,
) {
  const drivenUntil = useRef(0);
  const lastKey = useRef<string | null>(null);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  // Column -> frame.
  useEffect(() => {
    const column = columnRef.current;
    if (!column || !enabled || !frameReady) return;
    let timer: number | null = null;
    const settle = () => {
      timer = null;
      if (Date.now() < drivenUntil.current) return;
      const top = column.getBoundingClientRect().top + TOP_BAND;
      const cards = column.querySelectorAll<HTMLElement>('[data-tile-key]');
      for (const card of Array.from(cards)) {
        if (card.getBoundingClientRect().bottom <= top) continue;
        const key = card.dataset.tileKey ?? '';
        const at = key.indexOf(':');
        if (at <= 0 || key === lastKey.current) return;
        lastKey.current = key;
        scrollFrameTo(key.slice(0, at), key.slice(at + 1));
        return;
      }
    };
    const onScroll = () => {
      // A smooth scroll the frame caused holds the window while it moves.
      if (Date.now() < drivenUntil.current) {
        drivenUntil.current = Date.now() + 250;
        return;
      }
      if (timer != null) window.clearTimeout(timer);
      timer = window.setTimeout(settle, SETTLE_MS);
    };
    column.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      column.removeEventListener('scroll', onScroll);
      if (timer != null) window.clearTimeout(timer);
    };
  }, [columnRef, enabled, frameReady, scrollFrameTo]);

  // Frame -> column.
  return useCallback(
    (tabId: string, componentId: string) => {
      const column = columnRef.current;
      if (!column || !enabledRef.current) return;
      const key = tileKey(tabId, componentId);
      if (key === lastKey.current) return;
      lastKey.current = key;
      const target =
        column.querySelector<HTMLElement>(`[data-tile-key="${CSS.escape(key)}"]`) ??
        column.querySelector<HTMLElement>(
          `[data-testid="report-outline-tab"][data-tab-id="${CSS.escape(tabId)}"]`,
        );
      if (!target) return;
      drivenUntil.current = Date.now() + DRIVEN_MS;
      const gap = () => target.getBoundingClientRect().top - column.getBoundingClientRect().top - 12;
      column.scrollTo({ top: column.scrollTop + gap(), behavior: 'smooth' });
      // Live tiles drawn on the way change the heights above the target:
      // once the smooth scroll is done, land exactly.
      window.setTimeout(() => {
        if (Math.abs(gap()) <= 24) return;
        drivenUntil.current = Date.now() + 400;
        column.scrollTo({ top: column.scrollTop + gap() });
      }, DRIVEN_MS);
    },
    [columnRef],
  );
}
