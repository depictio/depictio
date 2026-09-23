/**
 * Rotate a symmetric contact matrix 45 degrees, the HiCExplorer /
 * pyGenomeTracks reading.
 *
 * A square matrix puts genomic position on both axes, so a `genome_view`
 * track stacked above it lines up with neither. Rotating it so the diagonal
 * becomes the horizontal axis fixes that: x is then genomic position on the
 * same scale as the tracks, and y is the separation between the two bins
 * ("how far apart do these loci contact from"). That is why every Hi-C figure
 * with tracks under it is a triangle.
 *
 * The rotation is exact, not resampled. Cell `(i, j)` of the square matrix
 * lands at `x = i + j`, `y = j - i` on a lattice of half-steps, which is why
 * the output grid is `2 * size - 1` wide. Positions whose `x + y` is odd have
 * no cell of their own (they are the gaps of the rotated lattice), so each is
 * filled with the mean of its two horizontal neighbours. Without that fill the
 * image is a visible checkerboard.
 */

/** `null` marks a cell with no data, which Plotly leaves blank. */
export type TriangleZ = (number | null)[][];

export interface TriangleMatrix {
  /** Row `y` = bin separation, column `x` = doubled genomic index. */
  z: TriangleZ;
  /** Bucket index (possibly fractional by a half) for each output column. */
  positionIndex: number[];
  /** Bin separation for each output row, in bins. */
  separations: number[];
}

/**
 * @param matrix square, symmetric, `size x size`; `null` cells are treated as
 *   absent rather than zero.
 * @param maxSeparation cap on the drawn rows. Hi-C signal decays with
 *   distance, so the far corner of the triangle is noise that would flatten
 *   the colour scale; `0` or a value past the matrix keeps every row.
 */
export function rotateToTriangle(
  matrix: readonly (readonly (number | null)[])[],
  maxSeparation = 0,
): TriangleMatrix {
  const size = matrix.length;
  if (size === 0) return { z: [], positionIndex: [], separations: [] };

  const rows = maxSeparation > 0 ? Math.min(size, maxSeparation) : size;
  const width = 2 * size - 1;
  const z: TriangleZ = Array.from({ length: rows }, () => new Array(width).fill(null));

  for (let i = 0; i < size; i += 1) {
    for (let j = i; j < size; j += 1) {
      const sep = j - i;
      if (sep >= rows) continue;
      const v = matrix[i][j] ?? matrix[j][i] ?? null;
      if (v === null) continue;
      z[sep][i + j] = v;
    }
  }

  // Fill the odd-parity gaps of the rotated lattice from their two horizontal
  // neighbours, which are always on the even lattice.
  for (let y = 0; y < rows; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if ((x + y) % 2 === 0) continue;
      const left = x > 0 ? z[y][x - 1] : null;
      const right = x < width - 1 ? z[y][x + 1] : null;
      if (left !== null && right !== null) z[y][x] = (left + right) / 2;
      else if (left !== null) z[y][x] = left;
      else if (right !== null) z[y][x] = right;
    }
  }

  return {
    z,
    positionIndex: Array.from({ length: width }, (_, x) => x / 2),
    separations: Array.from({ length: rows }, (_, y) => y),
  };
}

/** The two readings of a contact matrix. Mirrors `ContactMapConfig.display`. */
export type ContactMapDisplay = 'square' | 'triangle';

/**
 * Which reading to draw, given what the author wrote and where the dashboard
 * is.
 *
 * A square matrix is the right default on its own: it is the familiar Hi-C
 * figure and it needs no axis to align with. The moment a region filter
 * reaches the tile, though, the tile is part of a locus view, and only the
 * triangle puts genomic position on x where the tracks stacked under it put
 * it. So the region flips the default, and nothing else does.
 *
 * `pinned` is what stops that from being a hijack: an author who wrote
 * `display` in the YAML, and a reader who has touched the control, both mean
 * it, and a region must not silently overrule either.
 */
export function displayForRegion(
  current: ContactMapDisplay,
  opts: { pinned: boolean; hasRegion: boolean },
): ContactMapDisplay {
  if (opts.pinned) return current;
  return opts.hasRegion ? 'triangle' : current;
}
