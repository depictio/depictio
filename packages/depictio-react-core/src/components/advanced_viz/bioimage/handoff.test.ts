import { describe, expect, it } from 'vitest';

import {
  copyCommands,
  handoffUrl,
  HANDOFF_TARGETS,
  unsupportedReason,
  vitessceConfig,
} from './handoff';

const URL_ = 'https://depictio.example.org/depictio/api/v1/advanced_viz/bioimage/dc/t/tok/a.zarr';
const ZARR = { name: 'a.zarr', format: 'ome-zarr' as const };
const PLATE = { ...ZARR, layout: 'plate' as const, imagePath: 'B/2/0' };
const VIEW = {
  channels: [
    { index: 0, color: '#0000ff', visible: true, window: [0, 1500] as const },
    { index: 1, color: '#ffff00', visible: true, window: [10, 900] as const },
    { index: 2, color: '#ff0000', visible: false, window: [0, 1] as const },
  ],
  z: 118,
  width: 271,
  height: 275,
};

describe('handoffUrl', () => {
  it('hands vizarr and the validator the store root, encoded', () => {
    expect(handoffUrl('vizarr', URL_, PLATE)).toBe(
      `https://hms-dbmi.github.io/vizarr/?source=${encodeURIComponent(URL_)}`,
    );
    expect(handoffUrl('validator', `${URL_}/`, ZARR)).toBe(
      `https://ome.github.io/ome-ngff-validator/?source=${encodeURIComponent(URL_)}`,
    );
  });

  it('hands Neuroglancer the image drawn, in the fragment', () => {
    const url = handoffUrl('neuroglancer', URL_, PLATE);
    const [base, fragment] = url.split('#!');
    expect(base).toBe('https://neuroglancer-demo.appspot.com/');
    const state = JSON.parse(decodeURIComponent(fragment));
    expect(state.layers[0]).toEqual({
      type: 'image',
      name: 'a.zarr',
      source: `zarr://${URL_}/B/2/0`,
    });
  });

  it('hands Vitessce a config of its own, inline', () => {
    const url = handoffUrl('vitessce', URL_, ZARR);
    const config = JSON.parse(decodeURIComponent(url.split('url=data:,')[1]));
    expect(config.datasets[0].files[0]).toEqual({ fileType: 'raster.ome-zarr', url: URL_ });
  });

  it("hands Neuroglancer the tile's window for channel 0", () => {
    const url = handoffUrl('neuroglancer', URL_, { ...ZARR, view: VIEW });
    const state = JSON.parse(decodeURIComponent(url.split('#!')[1]));
    expect(state.layers[0].shaderControls).toEqual({ normalized: { range: [0, 1500] } });
  });
});

describe('unsupportedReason', () => {
  const tiff = { name: 'a.ome.tif', format: 'ome-tiff' as const };
  it('says why an OME-TIFF only opens in Vitessce', () => {
    expect(unsupportedReason('vizarr', tiff)).toMatch(/OME-Zarr/);
    expect(unsupportedReason('neuroglancer', tiff)).toMatch(/OME-Zarr/);
    expect(unsupportedReason('validator', tiff)).toMatch(/OME-Zarr/);
    expect(unsupportedReason('vitessce', tiff)).toBeNull();
    const file = (vitessceConfig('u', tiff).datasets as Array<{ files: unknown[] }>)[0].files[0];
    expect(file).toEqual({
      fileType: 'raster.json',
      options: {
        schemaVersion: '0.0.2',
        images: [{ name: 'a.ome.tif', type: 'ome-tiff', url: 'u' }],
        renderLayers: ['a.ome.tif'],
      },
    });
  });
});

describe('vitessceConfig', () => {
  const layerOf = (config: Record<string, unknown>) =>
    (config.coordinationSpace as { spatialImageLayer: { A: Array<{ channels: unknown[] }> } })
      .spatialImageLayer.A[0];

  it("draws the tile's visible channels, colours, windows and plane", () => {
    expect(layerOf(vitessceConfig('u', { ...ZARR, view: VIEW })).channels).toEqual([
      { selection: { c: 0, z: 118 }, color: [0, 0, 255], visible: true, slider: [0, 1500] },
      { selection: { c: 1, z: 118 }, color: [255, 255, 0], visible: true, slider: [10, 900] },
    ]);
  });

  it('names one channel without a view, never letting Vitessce pick three', () => {
    expect(layerOf(vitessceConfig('u', ZARR)).channels).toEqual([
      { selection: { c: 0 }, color: [255, 255, 255], visible: true },
    ]);
  });

  it('frames the whole image when its size is known', () => {
    const space = vitessceConfig('u', { ...ZARR, view: VIEW }).coordinationSpace as Record<
      string,
      { A: unknown }
    >;
    expect(space.spatialTargetX.A).toBe(135.5);
    expect(space.spatialTargetY.A).toBe(137.5);
    expect(space.spatialZoom.A).toBeCloseTo(1.35, 2);
  });
});

describe('copyCommands', () => {
  it('offers the URL, and napari for OME-Zarr', () => {
    expect(copyCommands(`${URL_}/`, ZARR).map(({ label, text }) => ({ label, text }))).toEqual([
      { label: 'Store URL', text: URL_ },
      { label: 'napari', text: `napari --plugin napari-ome-zarr ${URL_}` },
    ]);
  });

  it('shows the napari logo beside the napari command', () => {
    const napari = copyCommands(URL_, ZARR).find((c) => c.label === 'napari');
    expect(napari?.logo).toMatch(/^data:image\/svg\+xml,/);
  });
});

describe('HANDOFF_TARGETS', () => {
  it('gives every target its own logo, as an image data URI', () => {
    const logos = HANDOFF_TARGETS.map((t) => t.logo);
    expect(new Set(logos).size).toBe(HANDOFF_TARGETS.length);
    for (const logo of logos) expect(logo).toMatch(/^data:image\/(svg\+xml|png)[,;]/);
  });
});

describe('HANDOFF_LOGOS', () => {
  it('escapes # in an SVG data URI, which would otherwise end the URI as a fragment', async () => {
    const { HANDOFF_LOGOS } = await import('./handoffLogos');
    for (const uri of Object.values(HANDOFF_LOGOS)) expect(uri).not.toContain('#');
  });
});
