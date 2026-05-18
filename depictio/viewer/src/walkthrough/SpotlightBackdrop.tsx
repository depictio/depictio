import React, { useEffect, useLayoutEffect, useState } from 'react';

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface SpotlightBackdropProps {
  /** Target element. When null, the backdrop renders as a uniform dim layer
   *  (no cutout) — used for welcome/end cards that don't anchor to anything. */
  target: HTMLElement | null;
  /** When true, clicks on the spotlight area pass through to the target (e.g.
   *  the user is meant to click the highlighted button to advance). Otherwise
   *  the entire viewport is click-blocked. */
  allowTargetClick: boolean;
  /** Optional padding around the target in px so the cutout breathes a bit. */
  padding?: number;
}

/** Full-viewport dim overlay with a transparent cutout around `target`.
 *  Implemented as a single absolutely-positioned div whose huge box-shadow
 *  paints everything outside the cutout — no SVG mask required. Tracks
 *  layout changes via ResizeObserver + scroll/resize listeners.
 */
const SpotlightBackdrop: React.FC<SpotlightBackdropProps> = ({
  target,
  allowTargetClick,
  padding = 8,
}) => {
  const [rect, setRect] = useState<Rect | null>(null);

  useLayoutEffect(() => {
    if (!target) {
      setRect(null);
      return;
    }
    const measure = () => {
      const r = target.getBoundingClientRect();
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
    };
    measure();
    const onScroll = () => measure();
    const onResize = () => measure();
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onResize);
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    if (ro) ro.observe(target);
    // Cheap fallback for sub-pixel transitions that ResizeObserver doesn't
    // always catch (e.g. opening accordions). Re-measure on the next frame.
    const raf = requestAnimationFrame(measure);
    return () => {
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onResize);
      if (ro) ro.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [target]);

  // Re-measure whenever Mantine portals or images finish loading.
  useEffect(() => {
    if (!target) return;
    const id = window.setInterval(() => {
      const r = target.getBoundingClientRect();
      setRect((prev) =>
        prev &&
        prev.top === r.top &&
        prev.left === r.left &&
        prev.width === r.width &&
        prev.height === r.height
          ? prev
          : { top: r.top, left: r.left, width: r.width, height: r.height },
      );
    }, 400);
    return () => window.clearInterval(id);
  }, [target]);

  if (!target || !rect) {
    return (
      <div
        aria-hidden
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0, 0, 0, 0.55)',
          zIndex: 1000,
          pointerEvents: 'auto',
        }}
      />
    );
  }

  // The cutout div is the same size as the target (with padding). Its huge
  // outward box-shadow paints the dim layer over the rest of the viewport.
  return (
    <div
      aria-hidden
      style={{
        position: 'fixed',
        top: rect.top - padding,
        left: rect.left - padding,
        width: rect.width + padding * 2,
        height: rect.height + padding * 2,
        borderRadius: 8,
        boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.55)',
        zIndex: 1000,
        // When the user is meant to click the target itself, the cutout has
        // to be click-transparent. Otherwise we block all viewport clicks so
        // the popover Next/Back/Skip are the only way forward.
        pointerEvents: allowTargetClick ? 'none' : 'auto',
        transition: 'top 120ms ease, left 120ms ease, width 120ms ease, height 120ms ease',
      }}
    />
  );
};

export default SpotlightBackdrop;
