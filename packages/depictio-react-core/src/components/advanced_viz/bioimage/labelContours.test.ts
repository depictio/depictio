import { describe, expect, it } from 'vitest';

import { labelColour, labelContourRgba } from './labelContours';

const alpha = (out: Uint8ClampedArray, i: number) => out[i * 4 + 3];

describe('labelContourRgba', () => {
  it('draws only the boundary of a filled block, on the label side', () => {
    // 4x4 block of label 1 inside a 6x6 plane of background.
    const w = 6;
    const h = 6;
    const labels = new Float32Array(w * h);
    for (let y = 1; y <= 4; y += 1) for (let x = 1; x <= 4; x += 1) labels[y * w + x] = 1;
    const out = labelContourRgba(labels, w, h);
    // Interior pixel (2,2) has four neighbours of the same label: no line.
    expect(alpha(out, 2 * w + 2)).toBe(0);
    // Edge pixel (1,1) touches background: drawn.
    expect(alpha(out, 1 * w + 1)).toBe(255);
    // Background is never drawn, even next to the block.
    expect(alpha(out, 0 * w + 0)).toBe(0);
    expect(alpha(out, 5 * w + 5)).toBe(0);
  });

  it('separates two touching labels with an outline on each side', () => {
    const w = 4;
    const h = 1;
    const labels = Float32Array.from([1, 1, 2, 2]);
    const out = labelContourRgba(labels, w, h);
    expect(alpha(out, 0)).toBe(0); // label 1 with label 1 on its only neighbour: no edge
    expect(alpha(out, 1)).toBe(255); // label 1 meets label 2
    expect(alpha(out, 2)).toBe(255); // label 2 meets label 1
    expect(alpha(out, 3)).toBe(0);
  });

  it('colours each label by its id', () => {
    expect(labelColour(1)).not.toEqual(labelColour(2));
    expect(labelColour(7)).toEqual(labelColour(7));
  });
});
