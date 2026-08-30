import { describe, expect, it } from 'vitest';

import { computeMapFit, mapSubplotKey, parseMapFit, sameFit } from './fit';

/** The Ammer catchment box the ampliseq reference project ships. */
const AMMER = {
  min_lat: 48.5325,
  max_lat: 48.5787,
  min_lon: 8.8919,
  max_lon: 9.015,
  padding: 0.5,
  max_zoom: 12,
  single_point_zoom: 9,
};

describe('mapSubplotKey', () => {
  it('prefers `map` when plotly.py also serialises an empty `mapbox`', () => {
    // The regression this guards: `mapbox: {}` is truthy, so testing it first
    // sent the fit to a subplot nothing draws and the map silently kept the
    // server's framing.
    expect(mapSubplotKey({ map: { zoom: 11 }, mapbox: {} })).toBe('map');
  });

  it('falls back to `mapbox` for a figure that only carries the legacy key', () => {
    expect(mapSubplotKey({ mapbox: { zoom: 11 } })).toBe('mapbox');
  });

  it('defaults to `map` when the layout carries neither', () => {
    expect(mapSubplotKey({})).toBe('map');
    expect(mapSubplotKey(undefined)).toBe('map');
  });
});

describe('parseMapFit', () => {
  it('returns null when the server sent no fit', () => {
    expect(parseMapFit(undefined)).toBeNull();
    expect(parseMapFit({})).toBeNull();
  });

  it('returns null when a bound is missing or not a number', () => {
    expect(parseMapFit({ fit: { ...AMMER, max_lon: 'nine' } })).toBeNull();
  });

  it('reads the bounds and the constants the server fitted with', () => {
    expect(parseMapFit({ fit: AMMER })).toEqual({
      minLat: 48.5325,
      maxLat: 48.5787,
      minLon: 8.8919,
      maxLon: 9.015,
      padding: 0.5,
      maxZoom: 12,
      singlePointZoom: 9,
    });
  });

  it('falls back to the server defaults for absent constants', () => {
    const spec = parseMapFit({
      fit: { min_lat: 0, max_lat: 1, min_lon: 0, max_lon: 1 },
    });
    expect(spec).toMatchObject({ padding: 0.5, maxZoom: 12, singlePointZoom: 9 });
  });
});

describe('computeMapFit', () => {
  const spec = parseMapFit({ fit: AMMER })!;

  it('zooms out in a docked panel relative to the 600x400 the server assumes', () => {
    const grid = computeMapFit(spec, 600, 400);
    const docked = computeMapFit(spec, 307, 311);
    expect(docked.zoom).toBeLessThan(grid.zoom);
  });

  it('centres on the projected midpoint rather than the mean of the degrees', () => {
    // Mercator stretches towards the poles, so the two differ — by little at
    // this latitude, but the sign is what matters.
    const { center } = computeMapFit(spec, 307, 311);
    expect(center.lon).toBeCloseTo((AMMER.min_lon + AMMER.max_lon) / 2, 10);
    expect(center.lat).toBeGreaterThan((AMMER.min_lat + AMMER.max_lat) / 2);
  });

  it('keeps the zoom fraction the server floors away', () => {
    expect(computeMapFit(spec, 307, 311).zoom % 1).not.toBe(0);
  });

  it('uses the single-point zoom for a degenerate box', () => {
    const point = parseMapFit({
      fit: { ...AMMER, min_lat: 48.5, max_lat: 48.5, min_lon: 9, max_lon: 9 },
    })!;
    const fit = computeMapFit(point, 307, 311);
    expect(fit.zoom).toBe(9);
    expect(fit.center.lat).toBeCloseTo(48.5, 10);
    expect(fit.center.lon).toBeCloseTo(9, 10);
  });

  it('never exceeds the server’s max zoom', () => {
    const tiny = parseMapFit({
      fit: { ...AMMER, max_lat: 48.53251, max_lon: 8.89191 },
    })!;
    expect(computeMapFit(tiny, 307, 311).zoom).toBe(12);
  });
});

describe('sameFit', () => {
  const applied = { center: { lat: 48.5, lon: 9 }, zoom: 10.276, revision: 'fit-1' };

  it('treats a sub-threshold difference as the same framing', () => {
    expect(sameFit(applied, { center: { lat: 48.5, lon: 9 }, zoom: 10.28 })).toBe(true);
  });

  it('separates a framing the viewer would actually see move', () => {
    expect(sameFit(applied, { center: { lat: 48.5, lon: 9 }, zoom: 10.6 })).toBe(false);
    expect(sameFit(applied, { center: { lat: 48.6, lon: 9 }, zoom: 10.276 })).toBe(false);
  });
});
