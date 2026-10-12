/**
 * Prepare a chosen picture before it is uploaded: centre-crop to a square and
 * downscale to at most `MAX_EDGE` pixels on a canvas.
 *
 * This keeps uploads small (a phone photo is several MB) and fits the 5 MB
 * limit by construction. It is a convenience, not the security boundary: the
 * server decodes and re-encodes whatever it receives.
 */

const MAX_EDGE = 512;

export async function squareDownscale(file: Blob): Promise<Blob> {
  let bitmap: ImageBitmap;
  try {
    // `from-image` applies the photo's EXIF orientation while decoding, so the
    // crop below is taken from the picture as the user sees it.
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
  } catch {
    throw new Error('That file could not be read as an image.');
  }
  try {
    const side = Math.min(bitmap.width, bitmap.height);
    const edge = Math.min(side, MAX_EDGE);
    const canvas = document.createElement('canvas');
    canvas.width = edge;
    canvas.height = edge;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('Your browser cannot prepare the picture.');
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(
      bitmap,
      (bitmap.width - side) / 2,
      (bitmap.height - side) / 2,
      side,
      side,
      0,
      0,
      edge,
      edge,
    );
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/webp', 0.9),
    );
    if (!blob) throw new Error('Your browser cannot prepare the picture.');
    return blob;
  } finally {
    bitmap.close();
  }
}
