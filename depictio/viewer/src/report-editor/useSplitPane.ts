import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';

const KEY = 'depictio.reportEditor.split';
const MIN = 0.28;
const MAX = 0.72;
const STEP = 0.02;

const clamp = (v: number) => Math.min(MAX, Math.max(MIN, v));

function readStored(): number {
  try {
    const v = Number(localStorage.getItem(KEY));
    return Number.isFinite(v) && v > 0 ? clamp(v) : 0.5;
  } catch {
    return 0.5;
  }
}

/**
 * The share of the width the structure column takes, dragged on the handle
 * between the two panes, kept in this browser. The preview is an iframe: it
 * would swallow the pointer mid-drag, so the page is flagged `re-resizing`
 * while dragging (the CSS turns the frame's pointer events off).
 */
export function useSplitPane(bodyRef: RefObject<HTMLElement>) {
  const [ratio, setRatio] = useState(readStored);
  const dragging = useRef(false);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, String(ratio));
    } catch {
      // Storage blocked: the width lasts for this page only.
    }
  }, [ratio]);

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      const body = bodyRef.current;
      if (!body || event.button !== 0) return;
      event.preventDefault();
      dragging.current = true;
      document.documentElement.classList.add('re-resizing');
      const rect = body.getBoundingClientRect();
      const move = (e: PointerEvent) => {
        if (dragging.current) setRatio(clamp((e.clientX - rect.left) / rect.width));
      };
      const up = () => {
        dragging.current = false;
        document.documentElement.classList.remove('re-resizing');
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    },
    [bodyRef],
  );

  const onKeyDown = useCallback((event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === 'ArrowLeft') setRatio((r) => clamp(r - STEP));
    else if (event.key === 'ArrowRight') setRatio((r) => clamp(r + STEP));
    else if (event.key === 'Home') setRatio(MIN);
    else if (event.key === 'End') setRatio(MAX);
    else return;
    event.preventDefault();
  }, []);

  const reset = useCallback(() => setRatio(0.5), []);

  return { ratio, onPointerDown, onKeyDown, reset, min: MIN, max: MAX };
}
