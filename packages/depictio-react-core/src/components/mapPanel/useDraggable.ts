import { useCallback, useEffect, useRef, useState } from 'react';

/** Keep at least this much of the card reachable when clamping to the viewport,
 *  so a card dragged off-screen can always be grabbed by its header again. */
const MIN_VISIBLE_X = 120;
const MIN_VISIBLE_Y = 8;

export interface Position {
  x: number;
  y: number;
}

/** Spread onto the element that should act as the drag handle. */
export interface DragHandleProps {
  onPointerDown: (e: React.PointerEvent<HTMLElement>) => void;
  onPointerMove: (e: React.PointerEvent<HTMLElement>) => void;
  onPointerUp: (e: React.PointerEvent<HTMLElement>) => void;
  onPointerCancel: (e: React.PointerEvent<HTMLElement>) => void;
}

/** Clamp a top-left corner so the card's header stays grabbable. */
export function clampToViewport(pos: Position, width: number, height: number): Position {
  const maxX = Math.max(MIN_VISIBLE_X - width, window.innerWidth - MIN_VISIBLE_X);
  const maxY = Math.max(MIN_VISIBLE_Y, window.innerHeight - height);
  return {
    x: Math.min(Math.max(pos.x, MIN_VISIBLE_X - width), maxX),
    y: Math.min(Math.max(pos.y, MIN_VISIBLE_Y), maxY),
  };
}

/**
 * Pointer-drag for a `position: fixed` card, driven from its header.
 *
 * Uses pointer capture rather than window listeners so the drag survives the
 * pointer leaving the header (and, importantly, crossing the Plotly canvas
 * below it, which swallows mouse events of its own).
 *
 * The live position is returned separately from the committed one: the caller
 * renders `livePosition ?? committedPosition` and only persists on drop, so a
 * drag does not write to storage on every frame.
 */
export function useDraggable(onDrop: (pos: Position) => void) {
  const nodeRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ pointerId: number; offsetX: number; offsetY: number } | null>(null);
  const [livePosition, setLivePosition] = useState<Position | null>(null);

  // Keep the drop callback current without re-binding handlers mid-drag.
  const onDropRef = useRef(onDrop);
  useEffect(() => {
    onDropRef.current = onDrop;
  }, [onDrop]);

  const handlePointerDown = useCallback((e: React.PointerEvent<HTMLElement>) => {
    // Left button only, and never start a drag from a control in the header.
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest('button, a, input, [data-no-drag]')) return;
    const node = nodeRef.current;
    if (!node) return;

    const rect = node.getBoundingClientRect();
    dragRef.current = {
      pointerId: e.pointerId,
      offsetX: e.clientX - rect.left,
      offsetY: e.clientY - rect.top,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    setLivePosition({ x: rect.left, y: rect.top });
    e.preventDefault();
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    const node = nodeRef.current;
    if (!drag || !node || drag.pointerId !== e.pointerId) return;
    const rect = node.getBoundingClientRect();
    setLivePosition(
      clampToViewport(
        { x: e.clientX - drag.offsetX, y: e.clientY - drag.offsetY },
        rect.width,
        rect.height,
      ),
    );
  }, []);

  const endDrag = useCallback((e: React.PointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    dragRef.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    setLivePosition((pos) => {
      if (pos) onDropRef.current(pos);
      return null;
    });
  }, []);

  return {
    nodeRef,
    livePosition,
    dragging: livePosition !== null,
    handleProps: {
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
    } satisfies DragHandleProps,
  };
}
