import { describe, expect, it } from 'vitest';

import { resolveChannels } from './channels';
import { normaliseOmeTiffMetadata, omeColorToRgb, type OmeXmlImage } from './omeTiff';

function image(pixels: Partial<OmeXmlImage['Pixels']>): OmeXmlImage {
  return { Pixels: { SizeC: 1, ...pixels } };
}

describe('omeColorToRgb', () => {
  it("reads OME's signed 32-bit RGBA integer", () => {
    // 0xFF0000FF: opaque red, written signed.
    expect(omeColorToRgb(-16776961)).toEqual([255, 0, 0]);
    // 0x00FF00FF: opaque green, positive.
    expect(omeColorToRgb(16711935)).toEqual([0, 255, 0]);
    // -1 is OME's default: opaque white.
    expect(omeColorToRgb(-1)).toEqual([255, 255, 255]);
  });

  it("reads viv's already-split RGBA array, ignoring alpha", () => {
    expect(omeColorToRgb([0, 0, 255, 255])).toEqual([0, 0, 255]);
    expect(omeColorToRgb([0, 0, 300, 255])).toBeNull();
  });

  it('rejects anything else', () => {
    expect(omeColorToRgb(undefined)).toBeNull();
    expect(omeColorToRgb(1.5)).toBeNull();
  });
});

describe('normaliseOmeTiffMetadata', () => {
  it('maps channel names and colours to the omero shape, one per SizeC', () => {
    const meta = normaliseOmeTiffMetadata(
      image({
        SizeC: 3,
        Channels: [
          { Name: 'DAPI', Color: [0, 0, 255, 255] },
          { Name: '  ', Color: -16776961 },
        ],
      }),
    );
    expect(meta.omero.channels).toEqual([
      { label: 'DAPI', color: '#0000ff' },
      { label: undefined, color: '#ff0000' },
      { label: undefined, color: undefined },
    ]);
  });

  it("drops OME's default white so the fluorescence defaults apply", () => {
    const meta = normaliseOmeTiffMetadata(
      image({ SizeC: 2, Channels: [{ Color: -1 }, { Color: [255, 255, 255, 255] }] }),
    );
    expect(meta.omero.channels.map((c) => c.color)).toEqual([undefined, undefined]);
    const channels = resolveChannels({ sizeC: 2, dtype: 'Uint16', omero: meta.omero });
    expect(channels.map((c) => c.color)).toEqual(['#0000ff', '#00ff00']);
    expect(channels.map((c) => c.name)).toEqual(['Channel 0', 'Channel 1']);
  });

  it('feeds resolveChannels like omero, with config still winning', () => {
    const meta = normaliseOmeTiffMetadata(
      image({ SizeC: 2, Channels: [{ Name: 'DAPI', Color: -16776961 }, { Name: 'GFP' }] }),
    );
    const channels = resolveChannels({
      sizeC: 2,
      dtype: 'Uint8',
      omero: meta.omero,
      config: [{ index: 0, color: '#00ffff' }],
      stats: [null, { domain: [0, 200], contrastLimits: [5, 150] }],
    });
    expect(channels[0]).toMatchObject({ name: 'DAPI', color: '#00ffff', contrastLimits: [0, 255] });
    expect(channels[1]).toMatchObject({ name: 'GFP', color: '#00ff00', contrastLimits: [5, 150] });
  });

  it('reads the level-0 pixel size along x, abbreviating the unit', () => {
    expect(
      normaliseOmeTiffMetadata(image({ PhysicalSizeX: 0.325, PhysicalSizeXUnit: 'µm' })).physicalSize,
    ).toEqual({ value: 0.325, unit: 'µm' });
    expect(
      normaliseOmeTiffMetadata(image({ PhysicalSizeX: 2, PhysicalSizeXUnit: 'nanometer' }))
        .physicalSize,
    ).toEqual({ value: 2, unit: 'nm' });
  });

  it('has no physical size without a positive length in a length unit', () => {
    const size = (px: Partial<OmeXmlImage['Pixels']>) =>
      normaliseOmeTiffMetadata(image(px)).physicalSize;
    expect(size({})).toBeNull();
    expect(size({ PhysicalSizeXUnit: 'µm' })).toBeNull();
    expect(size({ PhysicalSizeX: 0, PhysicalSizeXUnit: 'µm' })).toBeNull();
    expect(size({ PhysicalSizeX: 1, PhysicalSizeXUnit: 'pixel' })).toBeNull();
    expect(size({ PhysicalSizeX: 1 })).toBeNull();
  });

  it('treats a missing or bad SizeC as one channel', () => {
    expect(normaliseOmeTiffMetadata(image({ SizeC: 0 })).omero.channels).toHaveLength(1);
  });
});
