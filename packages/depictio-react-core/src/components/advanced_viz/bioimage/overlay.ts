// An overlay is a second image laid over the shown one, with its own channels:
// light microscopy registered into an EM volume, say. It covers the same field
// as the image, so a coarser overlay is stretched to the image's extent, and a
// plane of the image shows the overlay plane at the same depth.

/** The overlay plane at the depth of image plane `z`. */
export function overlayPlane(z: number, imageDepth: number, overlayDepth: number): number {
  if (overlayDepth <= 1 || imageDepth <= 1) return 0;
  const plane = Math.floor(((z + 0.5) * overlayDepth) / imageDepth);
  return Math.min(Math.max(plane, 0), overlayDepth - 1);
}

interface Size {
  width: number;
  height: number;
}

/** The deck.gl model matrix (column-major) stretching the overlay over the
 *  image, or null when they are the same size. */
export function overlayMatrix(image: Size, overlay: Size): number[] | null {
  if (!(overlay.width > 0 && overlay.height > 0)) return null;
  const sx = image.width / overlay.width;
  const sy = image.height / overlay.height;
  if (sx === 1 && sy === 1) return null;
  return [sx, 0, 0, 0, 0, sy, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
}
