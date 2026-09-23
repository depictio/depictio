import React, { useEffect, useRef, useState } from 'react';

import DepictioRose from '../components/rose/DepictioRose';

const WORDMARK_SRC = '/dashboard/logos/logo_black.svg';

// Geometry of the mark inside the wordmark raster (1200x269), measured on the
// asset and expressed as fractions of its height: the rose's centre and outer
// radius. The mark ends at x≈270 and the lettering starts at x≈335, so hiding
// the left quarter hides the mark and nothing else.
const RASTER_W = 1200;
const RASTER_H = 269;
const MARK_CX = 0.582;
const MARK_CY = 0.58;
const MARK_R = 0.58;
const MARK_CLIP = 'inset(0 0 0 25%)';
// `<depictio-rose>` draws its circle (r = 300) in a 640-wide viewBox.
const ROSE_BOX_PER_RADIUS = 640 / 300;
// Long enough that sweeping the pointer across the logo doesn't set it off.
const HOVER_DELAY_MS = 400;

interface Overlay {
  side: number;
  left: number;
  top: number;
}

/** Where the rose goes over the rendered `<img>`, allowing for the letterbox
 *  `object-fit: contain` adds when the box's aspect differs from the raster's. */
function overlayFor(img: HTMLImageElement): Overlay | null {
  const { clientWidth: w, clientHeight: h } = img;
  if (!w || !h) return null;
  const scale = Math.min(w / RASTER_W, h / RASTER_H);
  const drawnW = RASTER_W * scale;
  const drawnH = RASTER_H * scale;
  const side = MARK_R * ROSE_BOX_PER_RADIUS * drawnH;
  return {
    side: Math.round(side),
    left: (w - drawnW) / 2 + MARK_CX * drawnH - side / 2,
    top: (h - drawnH) / 2 + MARK_CY * drawnH - side / 2,
  };
}

interface DepictioWordmarkProps {
  width?: number | string;
  height?: number | string;
  alt: string;
  /** Dark scheme: the raster is inverted and hue-rotated back, see below. */
  dark: boolean;
  style?: React.CSSProperties;
  testId?: string;
}

/**
 * The depictio wordmark: the raster's lettering, with its mark replaced by the
 * live `<depictio-rose>` drawn exactly over it (the raster's own mark is
 * clipped away). At rest the element's `logo` mode paints the same static
 * mark, so nothing moves and nothing animates; resting the pointer on it for a
 * moment plays the fan, and leaving settles it back.
 *
 * The docs header does the same thing with the same element, so the mark
 * behaves alike wherever it appears.
 *
 * `logo_black.svg` and `logo_white.svg` are byte-identical (a base64 raster
 * inside an SVG wrapper), so dark mode inverts the raster with a filter and
 * rotates the hue back to keep the brand colours. The rose is drawn in the
 * brand colours directly, so it needs no filter.
 */
const DepictioWordmark: React.FC<DepictioWordmarkProps> = ({
  width,
  height,
  alt,
  dark,
  style,
  testId,
}) => {
  const imgRef = useRef<HTMLImageElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [hovered, setHovered] = useState(false);

  // The mark is the live element at all times, so it has to be measured as
  // soon as the raster gives it a box, and again whenever that box changes
  // (a collapsing sidebar, a window resize, a late-loading font).
  useEffect(() => {
    const img = imgRef.current;
    if (!img) return;
    const measure = () => setOverlay(overlayFor(img));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(img);
    img.addEventListener('load', measure);
    return () => {
      observer.disconnect();
      img.removeEventListener('load', measure);
    };
  }, []);

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  const handleEnter = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      setHovered(true);
    }, HOVER_DELAY_MS);
  };

  const handleLeave = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    setHovered(false);
  };

  return (
    <span
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      style={{ position: 'relative', display: 'inline-block', maxWidth: '100%', lineHeight: 0 }}
    >
      <img
        ref={imgRef}
        src={WORDMARK_SRC}
        alt={alt}
        data-testid={testId}
        style={{
          width,
          height,
          maxWidth: '100%',
          objectFit: 'contain',
          display: 'block',
          filter: dark ? 'invert(1) hue-rotate(180deg)' : undefined,
          clipPath: overlay ? MARK_CLIP : undefined,
          ...style,
        }}
      />
      {overlay && (
        <DepictioRose
          mode={hovered ? 'fan' : 'logo'}
          size={overlay.side}
          label=""
          style={{
            position: 'absolute',
            left: overlay.left,
            top: overlay.top,
            pointerEvents: 'none',
          }}
        />
      )}
    </span>
  );
};

export default DepictioWordmark;
