/**
 * A drag handle on the inner edge of a side panel. `side` is the edge it sits
 * on (the right edge of the file tree, the left edge of the workflows
 * panel); `onResize` receives the raw pointer delta and the parent applies the
 * sign for its panel.
 */
import React, { useEffect, useRef } from 'react';
import { Box } from '@mantine/core';

export const PANEL_MIN = 220;
export const PANEL_MAX = 640;
export const clampPanel = (width: number): number =>
  Math.max(PANEL_MIN, Math.min(PANEL_MAX, width));

export const ResizeHandle: React.FC<{
  side: 'left' | 'right';
  onResize: (dx: number) => void;
  label: string;
}> = ({ side, onResize, label }) => {
  const dragging = useRef(false);
  useEffect(() => {
    const move = (e: MouseEvent) => {
      if (dragging.current) onResize(e.movementX);
    };
    const stop = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', stop);
    return () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', stop);
    };
  }, [onResize]);
  return (
    <Box
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      tabIndex={0}
      onKeyDown={(e) => {
        // Keyboard resize: arrows move the edge by 16px.
        if (e.key === 'ArrowLeft') onResize(-16);
        if (e.key === 'ArrowRight') onResize(16);
      }}
      onMouseDown={() => {
        dragging.current = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
      }}
      style={{
        position: 'absolute',
        top: 0,
        bottom: 0,
        [side]: -3,
        width: 6,
        cursor: 'col-resize',
        zIndex: 2,
      }}
    />
  );
};
