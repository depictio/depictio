import { useCallback, useEffect, useRef, useState } from 'react';

import type { DragHandleProps } from './useDraggable';

/** Below this the map is a sliver with no usable tiles left. */
const MIN_DOCK_HEIGHT = 150;

/**
 * Most of the filter column the dock may ever take.
 *
 * The dock is styled `min(<dragged>px, MAX_DOCK_SHARE)` so a height dragged in
 * a tall window cannot swallow a short one, and the drag clamps to the same
 * fraction — if it did not, the pointer would keep travelling after the box had
 * stopped growing, which reads as a broken handle.
 */
export const MAX_DOCK_SHARE = 0.7;

/** How much of the filter list has to survive the drag. Without a floor, one
 *  enthusiastic pull hides every filter behind the map and the only way back is
 *  a drag from an edge the viewer can no longer see. */
const MIN_FILTERS_HEIGHT = 120;

/** `clientHeight` minus padding: percentage heights resolve against the
 *  parent's content box, and the filter panel is padded. */
function contentHeight(parent: HTMLElement | null): number {
  if (!parent) return window.innerHeight;
  const style = window.getComputedStyle(parent);
  return (
    parent.clientHeight -
    (parseFloat(style.paddingTop) || 0) -
    (parseFloat(style.paddingBottom) || 0)
  );
}

export interface DockResize {
  /** Attach to the dock element itself — measured for the drag's start height
   *  and for the space its host has to give. */
  nodeRef: React.MutableRefObject<HTMLDivElement | null>;
  /** Height while dragging; `null` once committed. Render
   *  `liveHeight ?? committedHeight`. */
  liveHeight: number | null;
  resizing: boolean;
  handleProps: DragHandleProps;
}

/**
 * Drag the dock's top edge to set its height.
 *
 * The committed height is written on release only — persisting each frame would
 * hammer localStorage — but the map has to keep up *during* the drag, and
 * Plotly only re-fits on a `window` resize (`config.responsive` installs
 * nothing but a window listener; see `plot_api.js`). So each frame that moves
 * the edge also dispatches one synthetic resize, rAF-throttled so a fast drag
 * can't queue more repaints than the browser will paint.
 */
export function useDockResize(onCommit: (height: number) => void): DockResize {
  const nodeRef = useRef<HTMLDivElement | null>(null);
  const [liveHeight, setLiveHeight] = useState<number | null>(null);
  /** Mirrors `liveHeight` for the move handler, which needs to compare against
   *  it without re-binding on every frame. */
  const heightRef = useRef<number | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    startY: number;
    startHeight: number;
    maxHeight: number;
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

  const handlePointerDown = useCallback((e: React.PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    const node = nodeRef.current;
    if (!node) return;
    const height = node.getBoundingClientRect().height;
    // The host column is the budget: whatever it can spare beyond the filter
    // list floor is how far the edge may travel. Measured as the *content* box,
    // because that is what the element's own `%` cap resolves against.
    const available = contentHeight(node.parentElement);
    dragRef.current = {
      pointerId: e.pointerId,
      startY: e.clientY,
      startHeight: height,
      maxHeight: Math.max(
        MIN_DOCK_HEIGHT,
        Math.min(available - MIN_FILTERS_HEIGHT, available * MAX_DOCK_SHARE),
      ),
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    heightRef.current = height;
    setLiveHeight(height);
    e.preventDefault();
  }, []);

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<HTMLElement>) => {
      const drag = dragRef.current;
      if (!drag || drag.pointerId !== e.pointerId) return;
      // Dragging up (a smaller clientY) makes the dock taller.
      const next = Math.min(
        drag.maxHeight,
        Math.max(MIN_DOCK_HEIGHT, drag.startHeight - (e.clientY - drag.startY)),
      );
      // A drag that is already clamped at either end keeps firing move events
      // without changing anything; only a real change is worth a repaint.
      if (next === heightRef.current) return;
      heightRef.current = next;
      setLiveHeight(next);
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
    const height = heightRef.current;
    heightRef.current = null;
    setLiveHeight(null);
    if (height != null) onCommitRef.current(height);
  }, []);

  return {
    nodeRef,
    liveHeight,
    resizing: liveHeight !== null,
    handleProps: {
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
    } satisfies DragHandleProps,
  };
}
