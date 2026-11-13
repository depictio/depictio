import { describe, expect, it } from 'vitest';

import { copyCommands, handoffUrl, unsupportedReason, vitessceConfig } from './handoff';

const URL_ = 'https://depictio.example.org/depictio/api/v1/advanced_viz/bioimage/dc/t/tok/a.zarr';
const ZARR = { name: 'a.zarr', format: 'ome-zarr' as const };
const PLATE = { ...ZARR, layout: 'plate' as const, imagePath: 'B/2/0' };

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
    expect(config.datasets[0].files[0]).toEqual({ fileType: 'image.ome-zarr', url: URL_ });
  });
});

describe('unsupportedReason', () => {
  const tiff = { name: 'a.ome.tif', format: 'ome-tiff' as const };
  it('says why an OME-TIFF only opens in Vitessce', () => {
    expect(unsupportedReason('vizarr', tiff)).toMatch(/OME-Zarr/);
    expect(unsupportedReason('neuroglancer', tiff)).toMatch(/OME-Zarr/);
    expect(unsupportedReason('validator', tiff)).toMatch(/OME-Zarr/);
    expect(unsupportedReason('vitessce', tiff)).toBeNull();
    expect(vitessceConfig('u', tiff).datasets).toEqual([
      { uid: 'image', name: 'a.ome.tif', files: [{ fileType: 'image.ome-tiff', url: 'u' }] },
    ]);
  });
});

describe('copyCommands', () => {
  it('offers the URL, and napari for OME-Zarr', () => {
    expect(copyCommands(`${URL_}/`, ZARR)).toEqual([
      { label: 'Store URL', text: URL_ },
      { label: 'napari', text: `napari --plugin napari-ome-zarr ${URL_}` },
    ]);
  });
});
