import { describe, expect, it } from 'vitest';

import {
  buildLabelLut,
  cellColouring,
  colorizeLabels,
  labelAt,
  labelOf,
  labelTileKey,
  pairLabelsStore,
  rampColor,
  type LabelStyle,
  type LabelTile,
} from './labels';

const RED: [number, number, number] = [255, 0, 0];
const BLUE: [number, number, number] = [0, 0, 255];
const ACCENT: [number, number, number] = [9, 9, 9];

describe('pairLabelsStore', () => {
  const labels = [
    { name: 's1_mask.tif', sample: 's1' },
    { name: 's2_mask.tif', sample: 's2' },
  ];

  it('pairs by sample name', () => {
    expect(pairLabelsStore(labels, { name: 's2.ome.tif', sample: 's2' }, 2)?.name).toBe(
      's2_mask.tif',
    );
  });

  it('finds nothing for a sample without a mask', () => {
    expect(pairLabelsStore(labels, { name: 's3.zarr', sample: 's3' }, 3)).toBeNull();
  });

  it('pairs a lone mask with a lone image whatever their names', () => {
    const lone = [{ name: 'mask.tif', sample: 'mask' }];
    expect(pairLabelsStore(lone, { name: 'image.zarr', sample: 'image' }, 1)?.name).toBe(
      'mask.tif',
    );
    expect(pairLabelsStore(lone, { name: 'image.zarr', sample: 'image' }, 2)).toBeNull();
  });

  it('handles missing inputs', () => {
    expect(pairLabelsStore(null, { name: 'a', sample: 'a' }, 1)).toBeNull();
    expect(pairLabelsStore(labels, null, 0)).toBeNull();
  });
});

describe('labelOf', () => {
  it.each([
    ['12', 12],
    [7, 7],
    ['12.0', 12],
    ['0', null],
    ['-3', null],
    ['1.5', null],
    ['cell_1', null],
    ['', null],
    [null, null],
  ])('%s -> %s', (id, expected) => {
    expect(labelOf(id)).toBe(expected);
  });
});

describe('buildLabelLut', () => {
  it('keys cells by label, keeps their table id and marks the selection', () => {
    const lut = buildLabelLut(
      [
        { id: '3', color: RED, faded: false },
        { id: '5', color: BLUE, faded: true },
        { id: 'x', color: BLUE, faded: false },
      ],
      new Set(['5']),
      null,
    );
    expect([...lut.styles.keys()]).toEqual([3, 5]);
    expect(lut.styles.get(3)).toEqual({ color: RED, faded: false, selected: false });
    expect(lut.styles.get(5)).toEqual({ color: BLUE, faded: true, selected: true });
    expect(lut.ids.get(5)).toBe('5');
  });

  it('keys by the mask label but selects by the id when they differ', () => {
    const lut = buildLabelLut(
      [{ id: 's1:7', label: '7', color: RED, faded: false }],
      new Set(['s1:7']),
      null,
    );
    expect(lut.styles.get(7)).toEqual({ color: RED, faded: false, selected: true });
    expect(lut.ids.get(7)).toBe('s1:7');
  });
});

describe('colorizeLabels', () => {
  // 4 x 3 tile: cell 1 on the left two columns, cell 2 on the right, background row.
  const data = [1, 1, 2, 2, 1, 1, 2, 2, 0, 0, 0, 0];
  const paint = { opacity: 0.5, outline: false, accent: ACCENT };
  const px = (rgba: Uint8ClampedArray, i: number) => Array.from(rgba.slice(i * 4, i * 4 + 4));

  it('fills cells at the opacity and leaves the background transparent', () => {
    const lut = buildLabelLut(
      [
        { id: '1', color: RED, faded: false },
        { id: '2', color: BLUE, faded: false },
      ],
      new Set(),
      null,
    );
    const rgba = colorizeLabels(data, 4, 3, lut, paint);
    expect(px(rgba, 0)).toEqual([255, 0, 0, 128]);
    expect(px(rgba, 3)).toEqual([0, 0, 255, 128]);
    expect(px(rgba, 8)[3]).toBe(0);
  });

  it('draws edges opaque with outline on', () => {
    const lut = buildLabelLut([{ id: '1', color: RED, faded: false }], new Set(), null);
    const rgba = colorizeLabels(data, 4, 3, lut, { ...paint, outline: true });
    // (1, 0) touches cell 2 on its right: an edge.
    expect(px(rgba, 1)).toEqual([255, 0, 0, 255]);
    // (0, 0) has only cell 1 inside the tile around it.
    expect(px(rgba, 0)[3]).toBe(128);
    // (0, 1) sits on the background row below: an edge.
    expect(px(rgba, 4)[3]).toBe(255);
  });

  it('fades excluded cells and rings selected ones in the accent', () => {
    const lut = buildLabelLut(
      [
        { id: '1', color: RED, faded: true },
        { id: '2', color: BLUE, faded: false },
      ],
      new Set(['2']),
      null,
    );
    const rgba = colorizeLabels(data, 4, 3, lut, paint);
    expect(px(rgba, 0)[3]).toBeLessThan(40);
    // Selected cell 2: its edge next to cell 1 is the accent, even with outline off.
    expect(px(rgba, 2)).toEqual([...ACCENT, 255]);
    // Its inside stays its colour, filled more strongly.
    expect(px(rgba, 3).slice(0, 3)).toEqual(BLUE);
  });

  it('draws unknown labels with the fallback style, or not at all', () => {
    const unknown: LabelStyle = { color: BLUE, faded: false, selected: false };
    const empty = buildLabelLut([], new Set(), unknown);
    expect(px(colorizeLabels(data, 4, 3, empty, paint), 0)).toEqual([0, 0, 255, 128]);
    const none = buildLabelLut([], new Set(), null);
    expect(px(colorizeLabels(data, 4, 3, none, paint), 0)[3]).toBe(0);
  });
});

describe('labelAt', () => {
  const tile = (value: number, width = 4, height = 4): LabelTile => ({
    data: new Uint32Array(width * height).fill(value),
    width,
    height,
  });

  it('reads the finest loaded level covering the point', () => {
    const tiles = new Map<string, LabelTile>([
      [labelTileKey(1, 0, 0), tile(7)],
      [labelTileKey(0, 1, 0), tile(9)],
    ]);
    // Level 0, tile size 4: x 5 is in tile column 1.
    expect(labelAt(tiles, 5, 1, 4, 2)).toBe(9);
    // x 1 has no level-0 tile loaded: level 1 answers.
    expect(labelAt(tiles, 1, 1, 4, 2)).toBe(7);
  });

  it('indexes inside the tile', () => {
    const data = new Uint32Array(16);
    data[2 * 4 + 3] = 42;
    const tiles = new Map([[labelTileKey(0, 0, 0), { data, width: 4, height: 4 }]]);
    expect(labelAt(tiles, 3.7, 2.2, 4, 1)).toBe(42);
  });

  it('is null off the image or with nothing loaded', () => {
    expect(labelAt(new Map(), 1, 1, 4, 3)).toBeNull();
    expect(labelAt(new Map([[labelTileKey(0, 0, 0), tile(1, 2, 2)]]), 3, 0, 4, 1)).toBeNull();
    expect(labelAt(new Map([[labelTileKey(0, 0, 0), tile(1)]]), -1, 0, 4, 1)).toBeNull();
  });
});

describe('cellColouring', () => {
  it('reads ids and categories as categorical', () => {
    expect(cellColouring(['a', 'b']).kind).toBe('categorical');
    expect(cellColouring([1, 2, 3]).kind).toBe('categorical');
  });

  it('ramps a measurement over its range', () => {
    const c = cellColouring([0.5, 1.5, 2.5]);
    expect(c).toEqual({ kind: 'continuous', min: 0.5, max: 2.5, scale: 'Viridis' });
    if (c.kind !== 'continuous') throw new Error('unreachable');
    expect(rampColor(c, 0.5)).not.toEqual(rampColor(c, 2.5));
    expect(rampColor(c, null)).toBeNull();
    expect(rampColor(c, 'x')).toBeNull();
  });
});
