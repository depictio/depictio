import { useCallback, useEffect, useRef, useState } from 'react';

import type { DragHandleProps } from './useDraggable';

/** Below this the map is a sliver with no usable tiles left — same floor logic
 *  as the dock's `MIN_DOCK_HEIGHT`, plus room for the header row. */
const MIN_CARD_WIDTH = 280;
const MIN_CARD_HEIGHT = 200;

/** The card may grow to almost the whole viewport but never edge to edge, so
 *  the dashboard behind it stays reachable. */
const MAX_VIEWPORT_SHARE = { width: 0.95, height: 0.9 };

export interface CardSize {
  width: number;
  height: number;
}

export interface CardResize {
  /** Size while dragging; `null` once committed. Render
   *  `liveSize ?? committedSize`. */
  liveSize: CardSize | null;
  resizing: boolean;
  /** Spread onto the corner handle. */
  handleProps: DragHandleProps;
}

/**
 * Drag the floating card's bottom-right corner to set its size freely.
 *
 * Two-axis sibling of `useDockResize`, with the same commit discipline: the
 * committed size is written on release only, but the map has to keep up
 * *during* the drag, and Plotly only re-fits on a `window` resize
 * (`config.responsive` installs nothing but a window listener). So each frame
 * that changes the box also dispatches one synthetic resize, rAF-throttled so
 * a fast drag can't queue more repaints than the browser will paint.
 *
 * The measured element is passed by ref from the card itself (`nodeRef` is
 * shared with `useDraggable`) rather than owned here — the corner handle is a
 * child, and the drag needs the card's rect, not the handle's.
 */
export function useCardResize(
  nodeRef: React.MutableRefObject<HTMLDivElement | null>,
  onCommit: (size: CardSize) => void,
): CardResize {
  const [liveSize, setLiveSize] = useState<CardSize | null>(null);
  /** Mirrors `liveSize` for the move handler, which needs to compare against
   *  it without re-binding on every frame. */
  const sizeRef = useRef<CardSize | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    startSize: CardSize;
    maxSize: CardSize;
  } | null>(null);
  const frameRef = useRef<number | null>(null);

  const onCommitRef = useRef(onCommit);
  useEffect(() => {
    onCommitRef.current = onCommit;
  }, [onCommit]);

  useEffect(
    () => () => {
      if (frameRef.current != null) cancelAnimationFrame(frameRef.current);
    },
    [],
  );

  const nudgePlotly = useCallback(() => {
    if (frameRef.current != null) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = null;
      window.dispatchEvent(new Event('resize'));
    });
  }, []);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      if (e.button !== 0) return;
      const node = nodeRef.current;
      if (!node) return;
      const rect = node.getBoundingClientRect();
      dragRef.current = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        startSize: { width: rect.width, height: rect.height },
        // The viewport share is the ceiling, not the room right of the card:
        // growing past the right edge is fine, the position clamp pulls the
        // card back into view on the next render.
        maxSize: {
          width: Math.round(window.innerWidth * MAX_VIEWPORT_SHARE.width),
          height: Math.round(window.innerHeight * MAX_VIEWPORT_SHARE.height),
        },
      };
      e.currentTarget.setPointerCapture(e.pointerId);
      sizeRef.current = { width: rect.width, height: rect.height };
      setLiveSize(sizeRef.current);
      // Without this the drag also selects text across the dashboard below.
      e.preventDefault();
      e.stopPropagation();
    },
    [nodeRef],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      const drag = dragRef.current;
      if (!drag || drag.pointerId !== e.pointerId) return;
      const next = {
        width: Math.min(
          drag.maxSize.width,
          Math.max(MIN_CARD_WIDTH, Math.round(drag.startSize.width + (e.clientX - drag.startX))),
        ),
        height: Math.min(
          drag.maxSize.height,
          Math.max(
            MIN_CARD_HEIGHT,
            Math.round(drag.startSize.height + (e.clientY - drag.startY)),
          ),
        ),
      };
      // A drag pinned at a clamp keeps firing move events without changing
      // anything; only a real change is worth a repaint.
      const prev = sizeRef.current;
      if (prev && prev.width === next.width && prev.height === next.height) return;
      sizeRef.current = next;
      setLiveSize(next);
      nudgePlotly();
    },
    [nudgePlotly],
  );

  const endDrag = useCallback((e: React.PointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    dragRef.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    const size = sizeRef.current;
    sizeRef.current = null;
    setLiveSize(null);
    if (size) onCommitRef.current(size);
  }, []);

  return {
    liveSize,
    resizing: liveSize !== null,
    handleProps: {
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
    } satisfies DragHandleProps,
  };
}
