/**
 * Two panes with a draggable divider: the structure and its sequence strip or
 * alignment. `fraction` is the first pane's share of the main axis.
 */

import React, { useCallback, useRef } from 'react';

export const MIN_FRACTION = 0.2;
export const MAX_FRACTION = 0.85;

/** Keep a dragged fraction inside the bounds both panes stay usable at. */
export function clampFraction(f: number): number {
  if (!Number.isFinite(f)) return 0.6;
  return Math.max(MIN_FRACTION, Math.min(MAX_FRACTION, f));
}

/** Row (side by side) when the tile is clearly wider than tall, else column. */
export function splitOrientation(width: number, height: number): 'row' | 'column' {
  return width > 0 && height > 0 && width >= height * 1.3 ? 'row' : 'column';
}

const DIVIDER_PX = 6;

export const SplitView: React.FC<{
  orientation: 'row' | 'column';
  fraction: number;
  onFraction: (f: number) => void;
  first: React.ReactNode;
  /** Null draws the first pane alone. The first pane keeps its place in the
   *  tree either way, so a WebGL canvas inside it survives a layout switch. */
  second: React.ReactNode | null;
}> = ({ orientation, fraction, onFraction, first, second }) => {
  const box = useRef<HTMLDivElement | null>(null);
  const row = orientation === 'row';

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const el = box.current;
      if (!el) return;
      event.preventDefault();
      const target = event.currentTarget;
      target.setPointerCapture(event.pointerId);
      const rect = el.getBoundingClientRect();
      const move = (e: PointerEvent) => {
        const f = row
          ? (e.clientX - rect.left) / Math.max(1, rect.width)
          : (e.clientY - rect.top) / Math.max(1, rect.height);
        onFraction(clampFraction(f));
      };
      const up = (e: PointerEvent) => {
        target.releasePointerCapture(e.pointerId);
        target.removeEventListener('pointermove', move);
        target.removeEventListener('pointerup', up);
      };
      target.addEventListener('pointermove', move);
      target.addEventListener('pointerup', up);
    },
    [row, onFraction],
  );

  const f = clampFraction(fraction);
  return (
    <div
      ref={box}
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: orientation,
        minWidth: 0,
        minHeight: 0,
      }}
    >
      <div
        style={{
          flex: second === null ? '1 1 0' : `${f} 1 0`,
          position: 'relative',
          minWidth: 0,
          minHeight: 0,
        }}
      >
        {first}
      </div>
      {second === null ? null : (
        <>
          <div
            role="separator"
            aria-orientation={row ? 'vertical' : 'horizontal'}
            onPointerDown={onPointerDown}
            style={{
              flex: `0 0 ${DIVIDER_PX}px`,
              cursor: row ? 'col-resize' : 'row-resize',
              background: 'var(--mantine-color-default-border)',
              opacity: 0.6,
              touchAction: 'none',
            }}
          />
          <div
            style={{
              flex: `${1 - f} 1 0`,
              position: 'relative',
              minWidth: 0,
              minHeight: 0,
              overflow: 'hidden',
            }}
          >
            {second}
          </div>
        </>
      )}
    </div>
  );
};
