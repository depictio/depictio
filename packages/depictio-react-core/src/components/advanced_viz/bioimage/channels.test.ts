import { describe, expect, it } from 'vitest';

import {
  axisSizes,
  formatLength,
  hexToRgb,
  normaliseHex,
  physicalPixelSize,
  renderedChannels,
  resolveChannels,
  selectionFor,
} from './channels';

describe('hex colours', () => {
  it('reads the OMERO spelling without a hash, and short forms', () => {
    expect(hexToRgb('FF0080')).toEqual([255, 0, 128]);
    expect(hexToRgb('#0f0')).toEqual([0, 255, 0]);
    expect(hexToRgb('red')).toBeNull();
    expect(normaliseHex('00FF00')).toBe('#00ff00');
  });
});

describe('axes', () => {
  it('counts absent axes as size 1', () => {
    expect(axisSizes(['c', 'y', 'x'], [3, 512, 512])).toEqual({ c: 3, z: 1, t: 1 });
    expect(axisSizes(['t', 'c', 'z', 'y', 'x'], [4, 2, 30, 64, 64])).toEqual({ c: 2, z: 30, t: 4 });
  });

  it('names only the axes the array has in a selection', () => {
    expect(selectionFor(['c', 'y', 'x'], { c: 1, z: 5, t: 2 })).toEqual({ c: 1 });
    expect(selectionFor(['t', 'c', 'z', 'y', 'x'], { c: 1, z: 5, t: 2 })).toEqual({
      c: 1,
      z: 5,
      t: 2,
    });
  });
});

describe('resolveChannels', () => {
  const omero = {
    channels: [
      { label: 'DAPI', color: '0000FF', active: true, window: { start: 10, end: 900, min: 0, max: 4095 } },
      { label: 'GFP', color: '00FF00', active: false, window: { start: 0, end: 2000, min: 0, max: 4095 } },
    ],
  };

  it('takes names, colours, visibility and windows from omero', () => {
    const ch = resolveChannels({ sizeC: 2, dtype: 'Uint16', omero });
    expect(ch.map((c) => c.name)).toEqual(['DAPI', 'GFP']);
    expect(ch.map((c) => c.color)).toEqual(['#0000ff', '#00ff00']);
    expect(ch.map((c) => c.visible)).toEqual([true, false]);
    expect(ch[0].contrastLimits).toEqual([10, 900]);
    expect(ch[0].domain).toEqual([0, 4095]);
  });

  it('lets the component config win over omero, field by field', () => {
    const ch = resolveChannels({
      sizeC: 2,
      dtype: 'Uint16',
      omero,
      config: [{ index: 1, visible: true, color: '#ff00ff', contrast_limits: [5, 50] }],
    });
    expect(ch[1]).toMatchObject({
      name: 'GFP',
      color: '#ff00ff',
      visible: true,
      contrastLimits: [5, 50],
    });
    // Untouched channel keeps its omero settings.
    expect(ch[0].contrastLimits).toEqual([10, 900]);
  });

  it('falls back to data statistics, then the dtype range', () => {
    const fromStats = resolveChannels({
      sizeC: 1,
      dtype: 'Uint8',
      stats: [{ domain: [3, 200], contrastLimits: [12, 180] }],
    });
    expect(fromStats[0]).toMatchObject({
      name: 'Channel 0',
      color: '#ffffff',
      contrastLimits: [12, 180],
      domain: [3, 200],
    });
    const fromDtype = resolveChannels({ sizeC: 1, dtype: 'Uint8' });
    expect(fromDtype[0].contrastLimits).toEqual([0, 255]);
  });

  it('widens the slider domain to a pinned window outside the data', () => {
    const ch = resolveChannels({
      sizeC: 1,
      dtype: 'Float32',
      stats: [{ domain: [0, 1], contrastLimits: [0.1, 0.9] }],
      config: [{ index: 0, contrast_limits: [-1, 2] }],
    });
    expect(ch[0].domain).toEqual([-1, 2]);
  });

  it('starts only as many channels visible as viv can shade', () => {
    const ch = resolveChannels({ sizeC: 8, dtype: 'Uint16' });
    expect(ch.filter((c) => c.visible)).toHaveLength(6);
    expect(renderedChannels(ch)).toHaveLength(6);
  });

  it('keeps one invisible channel when all are hidden', () => {
    const ch = resolveChannels({ sizeC: 2, dtype: 'Uint16' }).map((c) => ({ ...c, visible: false }));
    const rendered = renderedChannels(ch);
    expect(rendered).toHaveLength(1);
    expect(rendered[0].visible).toBe(false);
  });
});

describe('physicalPixelSize', () => {
  it('reads the x unit and the first dataset scale', () => {
    const attrs = {
      multiscales: [
        {
          axes: [
            { name: 'c', type: 'channel' },
            { name: 'y', type: 'space', unit: 'micrometer' },
            { name: 'x', type: 'space', unit: 'micrometer' },
          ],
          datasets: [
            { path: '0', coordinateTransformations: [{ type: 'scale', scale: [1, 0.325, 0.325] }] },
            { path: '1', coordinateTransformations: [{ type: 'scale', scale: [1, 0.65, 0.65] }] },
          ],
        },
      ],
    };
    expect(physicalPixelSize(attrs)).toEqual({ value: 0.325, unit: 'µm' });
  });

  it('is null without a unit on x', () => {
    expect(physicalPixelSize({ multiscales: [{ axes: [{ name: 'y' }, { name: 'x' }] }] })).toBeNull();
    expect(physicalPixelSize(null)).toBeNull();
  });

  it('formats lengths without float noise', () => {
    expect(formatLength(0.30000000000000004, 'µm')).toBe('0.3 µm');
    expect(formatLength(50, 'µm')).toBe('50 µm');
  });
});
