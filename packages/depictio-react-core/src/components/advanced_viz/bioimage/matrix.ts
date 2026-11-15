/**
 * A scale-only model matrix that viv's tiled image layer accepts.
 *
 * deck.gl takes a model matrix as 16 numbers (column-major), but viv's
 * MultiscaleImageLayer also calls three math.gl `Matrix4` methods on it:
 * `getScale()` (to pick the tile level), `clone()` and `scale(n)` (for its
 * low-resolution backdrop). A plain array makes it throw. math.gl is not a
 * dependency of this package, and a diagonal matrix needs only those three.
 */
export class ScaleMatrix extends Array<number> {
  static of2d(sx: number, sy: number): ScaleMatrix {
    const m = new ScaleMatrix();
    m.push(sx, 0, 0, 0, 0, sy, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1);
    return m;
  }

  getScale(): [number, number, number] {
    return [this[0], this[5], this[10]];
  }

  clone(): ScaleMatrix {
    const m = new ScaleMatrix();
    m.push(...this);
    return m;
  }

  /** Scale by `factor` (one number, or per axis), in place, like Matrix4. */
  scale(factor: number | readonly number[]): ScaleMatrix {
    const [fx, fy, fz] = typeof factor === 'number' ? [factor, factor, factor] : factor;
    this[0] *= fx;
    this[5] *= fy ?? fx;
    this[10] *= fz ?? 1;
    return this;
  }
}
