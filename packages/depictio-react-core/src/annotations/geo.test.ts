import { describe, expect, it } from 'vitest';

import {
  centroidsSignature,
  GEO_HALO_OPACITY,
  geoAnnotationsToPlotly,
  geoCentroidsFromGraph,
  geoNoteAt,
  geoPointsFromSelection,
  geoRegionFromSelection,
  isGeoAnnotation,
  mapSubplotOf,
  normalizeGeoTraces,
  pixelToLonLat,
  wrapLongitude,
} from './geo';
import { annotateHint, annotateInteraction, DEFAULT_ANNOTATE_OPTIONS, kindForGeometry, toolForSurface } from './layer';
import { annotationIdFromClick, componentSupportsAnnotation, mapSupportsAnnotation } from './plotDecorate';
import { annotationSummary } from './summary';
import { OVERLAY_TRACE_PREFIX, PREVIEW_OPACITY_FACTOR } from './toPlotly';
import type { AnnotationColor, RenderableAnnotation } from './types';
import { MAX_POINT_IDS, MAX_REGION_VERTICES, PREVIEW_ANNOTATION_ID } from './types';

const resolveColor = (name: AnnotationColor, shade?: number) => `tok:${name}:${shade ?? 'd'}`;

const item = (
  id: string,
  number: number | null,
  annotation: RenderableAnnotation['annotation'],
  extra: Partial<RenderableAnnotation> = {},
): RenderableAnnotation => ({ id, number, annotation, ...extra });

describe('wrapLongitude', () => {
  it('keeps longitudes in range and wraps the rest', () => {
    expect(wrapLongitude(12.5)).toBe(12.5);
    expect(wrapLongitude(190)).toBe(-170);
    expect(wrapLongitude(-190)).toBe(170);
    expect(wrapLongitude(540)).toBe(180);
    expect(wrapLongitude(180)).toBe(180);
  });
});

describe('geoRegionFromSelection', () => {
  it('reads a map box as ordered lon/lat bounds', () => {
    // Plotly hands the north-west then the south-east corner.
    expect(geoRegionFromSelection({ range: { map: [[2, 50], [8, 45]] } })).toEqual({
      shape: 'box',
      x0: 2,
      x1: 8,
      y0: 45,
      y1: 50,
    });
  });
  it('reads a lasso on any map subplot id, wrapping longitudes', () => {
    const lassoPoints = { map2: [[1, 1], [200, 2], [3, 3]] };
    expect(geoRegionFromSelection({ lassoPoints })).toEqual({
      shape: 'lasso',
      x: [1, -160, 3],
      y: [1, 2, 3],
    });
  });
  it('thins a long lasso and ignores cartesian keys or degenerate input', () => {
    const many = Array.from({ length: MAX_REGION_VERTICES + 500 }, (_, i) => [i / 100, i / 200]);
    const out = geoRegionFromSelection({ lassoPoints: { map: many } });
    expect(out?.shape === 'lasso' && out.x.length).toBe(MAX_REGION_VERTICES);
    expect(geoRegionFromSelection({ range: { x: [0, 1], y: [0, 1] } })).toBeNull();
    expect(geoRegionFromSelection({ lassoPoints: { map: [[0, 0], [1, 1]] } })).toBeNull();
    expect(geoRegionFromSelection({ range: { map: [[1, 1], [1, 1]] } })).toBeNull();
    expect(geoRegionFromSelection(null)).toBeNull();
  });
});

describe('geoPointsFromSelection', () => {
  const points = [
    { lon: 2.35, lat: 48.85, customdata: ['s1', 'x'], curveNumber: 0 },
    { lon: 13.4, lat: 52.5, customdata: ['s2', 'y'], curveNumber: 0 },
    { lon: 2.35, lat: 48.85, customdata: ['s1', 'x'], curveNumber: 0 },
  ];

  it('keys points on the selection column, keeping the region', () => {
    const out = geoPointsFromSelection(
      { points, lassoPoints: { map: [[0, 40], [20, 40], [10, 60]] } },
      { column: 'sample', from: 'customdata', slot: 0 },
    );
    expect(out).toMatchObject({ kind: 'points', geo: true, column: 'sample', ids: ['s1', 's2'] });
    expect(out?.region).toMatchObject({ shape: 'lasso', x: [0, 20, 10] });
  });
  it('reads choropleth region ids from location', () => {
    const out = geoPointsFromSelection(
      { points: [{ location: 'FRA', lon: 2, lat: 46 }, { location: 'DEU' }] },
      { column: 'iso', from: 'location' },
    );
    expect(out).toEqual({ kind: 'points', geo: true, column: 'iso', ids: ['FRA', 'DEU'] });
  });
  it('falls back to lon/lat coords without ids', () => {
    const out = geoPointsFromSelection({ points: [{ lon: 190, lat: 95, curveNumber: 1 }, { lon: 'x' }] }, null);
    expect(out).toEqual({ kind: 'points', geo: true, coords: [{ x: -170, y: 90, trace: 1 }] });
  });
  it('caps ids and returns null for an empty selection', () => {
    const many = Array.from({ length: MAX_POINT_IDS + 3 }, (_, i) => ({ customdata: [`s${i}`] }));
    const out = geoPointsFromSelection({ points: many }, { column: 'c', from: 'customdata' });
    expect(out?.ids).toHaveLength(MAX_POINT_IDS);
    expect(geoPointsFromSelection({ points: [] }, null)).toBeNull();
  });
});

describe('notes and pixel conversion', () => {
  it('builds a geo note', () => {
    expect(geoNoteAt(2.35, 48.85)).toEqual({ kind: 'geo_note', lat: 48.85, lon: 2.35 });
    expect(geoNoteAt(null, 1)).toBeNull();
  });
  it('finds the map subplot and unprojects a click inside it', () => {
    const subplot = {
      map: { unproject: ([x, y]: [number, number]) => ({ lng: x / 10, lat: -y / 10 }) },
      div: { getBoundingClientRect: () => ({ left: 100, top: 50, width: 400, height: 300 }) },
    };
    const fullLayout = { _subplots: { map: ['map'] }, map: { _subplot: subplot } };
    expect(mapSubplotOf(fullLayout)).toBe(subplot);
    expect(pixelToLonLat(150, 70, subplot)).toEqual({ lon: 5, lat: -2 });
    expect(pixelToLonLat(90, 70, subplot)).toBeNull();
    expect(mapSubplotOf({ _subplots: { cartesian: ['xy'] } })).toBeNull();
    expect(pixelToLonLat(150, 70, null)).toBeNull();
  });
});

describe('normalizeGeoTraces / centroids', () => {
  const data = [
    { type: 'scattermap', lon: [1, 2], lat: [3, 4], customdata: [['a'], ['b']] },
    { type: 'choroplethmap', locations: ['FRA', 'DEU'], geojson: 'https://x/geo.json', featureidkey: 'id' },
    { type: 'scattermap', name: `${OVERLAY_TRACE_PREFIX}t1`, lon: [0], lat: [0] },
  ];
  it('reads ids per trace, choropleth centroids from the map given', () => {
    const traces = normalizeGeoTraces(data, 0, new Map([['FRA', [2, 46] as [number, number]]]));
    expect(traces).toHaveLength(2);
    expect(traces[0]).toMatchObject({ lon: [1, 2], lat: [3, 4], ids: ['a', 'b'] });
    expect(traces[1]).toMatchObject({
      ids: ['FRA', 'DEU'],
      lon: [2, undefined],
      lat: [46, undefined],
      regions: { geojson: 'https://x/geo.json', featureidkey: 'id' },
    });
  });
  it('reads choropleth centroids from calcdata', () => {
    const gd = {
      calcdata: [
        [{ trace: { type: 'scattermap' } }],
        [
          { trace: { type: 'choroplethmap' }, loc: 'FRA', ct: [2, 46] },
          { loc: 'DEU', ct: [10, 51] },
          { loc: 'XXX' },
        ],
      ],
    };
    const m = geoCentroidsFromGraph(gd);
    expect(m?.get('FRA')).toEqual([2, 46]);
    expect(m?.get('DEU')).toEqual([10, 51]);
    expect(m?.has('XXX')).toBe(false);
    expect(centroidsSignature(m!)).toBe(centroidsSignature(new Map(m!)));
    expect(geoCentroidsFromGraph({ calcdata: [[{ trace: { type: 'scattermap' } }]] })).toBeNull();
  });
});

describe('geoAnnotationsToPlotly', () => {
  const traces = normalizeGeoTraces(
    [
      { type: 'scattermap', lon: [1, 2, 3], lat: [10, 20, 30], customdata: [['a'], ['b'], ['c']] },
      { type: 'choroplethmap', locations: ['FRA', 'DEU'], geojson: { type: 'FeatureCollection' } },
    ],
    0,
    new Map([['DEU', [10, 51] as [number, number]]]),
  );

  it('draws marked points as a translucent halo with a numbered label', () => {
    const out = geoAnnotationsToPlotly(
      [
        item('t1', 1, {
          kind: 'points',
          geometry: { kind: 'points', geo: true, column: 'sample', ids: ['a', 'c', 'zz'] },
          label: 'Coastal',
          color: 'red',
        }),
      ],
      { resolveColor, traces },
    );
    expect(out.shapes).toEqual([]);
    expect(out.annotations).toEqual([]);
    expect(out.stats.t1).toEqual({ expected: 3, found: 2 });
    const [halo, label] = out.overlayTraces as Array<Record<string, unknown>>;
    expect(halo).toMatchObject({
      type: 'scattermap',
      mode: 'markers',
      lon: [1, 3],
      lat: [10, 30],
      name: `${OVERLAY_TRACE_PREFIX}t1`,
      opacity: GEO_HALO_OPACITY,
      marker: { color: 'tok:red:d' },
      hoverinfo: 'text',
    });
    expect(label).toMatchObject({ mode: 'markers+text', lon: [1], lat: [10], text: ['(1) Coastal'] });
    expect((label.marker as { size: number }).size).toBeGreaterThan(0);
    expect(String(label.hovertext)).toContain('2 of 3 found');
    // A click on the halo opens its thread.
    expect(annotationIdFromClick({ points: [{ data: { name: halo.name } }] })).toBe('t1');
  });

  it('outlines marked choropleth regions and labels them at their centroid', () => {
    const out = geoAnnotationsToPlotly(
      [
        item('t2', 2, {
          kind: 'points',
          geometry: { kind: 'points', geo: true, column: 'iso', ids: ['FRA', 'DEU'] },
          label: 'West',
          color: 'teal',
        }),
      ],
      { resolveColor, traces },
    );
    const [region, label] = out.overlayTraces as Array<Record<string, unknown>>;
    expect(region).toMatchObject({
      type: 'choroplethmap',
      locations: ['FRA', 'DEU'],
      z: [1, 1],
      showscale: false,
      geojson: { type: 'FeatureCollection' },
      marker: { line: { color: 'tok:teal:d' } },
    });
    expect(label).toMatchObject({ lon: [10], lat: [51] });
    expect(out.stats.t2).toEqual({ expected: 2, found: 2 });
  });

  it('shades the selected area and falls back to coords', () => {
    const out = geoAnnotationsToPlotly(
      [
        item('t3', null, {
          kind: 'points',
          geometry: {
            kind: 'points',
            geo: true,
            coords: [{ x: 5, y: 6 }],
            region: { shape: 'box', x0: 0, x1: 10, y0: 0, y1: 20 },
          },
          label: 'Area',
          style: { fill_opacity: 0.3 },
        }),
      ],
      { resolveColor, traces },
    );
    const [area, halo, label] = out.overlayTraces as Array<Record<string, unknown>>;
    expect(area).toMatchObject({
      mode: 'lines',
      fill: 'toself',
      lon: [0, 10, 10, 0, 0],
      lat: [0, 0, 20, 20, 0],
      fillcolor: 'tok:yellow:d',
      hoverinfo: 'skip',
    });
    expect(halo).toMatchObject({ lon: [5], lat: [6] });
    // Labelled at the top of the area (north-west corner of the box).
    expect(label).toMatchObject({ text: ['Area'], lon: [0], lat: [20] });
  });

  it('draws a note as a dot with its label, and fades the preview', () => {
    const out = geoAnnotationsToPlotly(
      [
        item(
          PREVIEW_ANNOTATION_ID,
          null,
          { kind: 'note', geometry: { kind: 'geo_note', lat: 48.85, lon: 2.35 }, label: 'Paris' },
          { preview: true },
        ),
      ],
      { resolveColor, traces },
    );
    const [note] = out.overlayTraces as Array<Record<string, unknown>>;
    expect(note).toMatchObject({
      mode: 'markers+text',
      lon: [2.35],
      lat: [48.85],
      text: ['Paris'],
      opacity: PREVIEW_OPACITY_FACTOR,
      hoverinfo: 'skip',
    });
    expect(annotationIdFromClick({ points: [{ data: { name: note.name } }] })).toBeNull();
  });

  it('moves labels sharing an anchor so the map does not hide one', () => {
    const note = (id: string) =>
      item(id, 1, { kind: 'note', geometry: { kind: 'geo_note', lat: 1, lon: 2 }, label: id });
    const out = geoAnnotationsToPlotly([note('a'), note('b')], { resolveColor });
    const positions = (out.overlayTraces as Array<Record<string, unknown>>).map((t) => t.textposition);
    expect(positions).toEqual(['top right', 'bottom right']);
  });

  it('skips annotations that are not geographic', () => {
    const cartesian = item('c', 1, { kind: 'note', geometry: { kind: 'arrow_note', x: 1, y: 2 }, label: 'x' });
    expect(isGeoAnnotation(cartesian)).toBe(false);
    expect(geoAnnotationsToPlotly([cartesian], { resolveColor }).overlayTraces).toEqual([]);
  });
});

describe('map surface', () => {
  it('offers only points and notes, and pans while placing a note', () => {
    expect(toolForSurface('range', 'map')).toBe('points');
    expect(toolForSurface('line', 'map')).toBe('points');
    expect(toolForSurface('note', 'map')).toBe('note');
    expect(toolForSurface('range', 'cartesian')).toBe('range');
    expect(annotateInteraction('note', DEFAULT_ANNOTATE_OPTIONS, 'map')).toEqual({ dragmode: 'pan', capture: 'click' });
    expect(annotateInteraction('range', DEFAULT_ANNOTATE_OPTIONS, 'map')).toEqual({
      dragmode: 'lasso',
      capture: 'selected',
    });
    expect(annotateInteraction('note', DEFAULT_ANNOTATE_OPTIONS)).toEqual({ dragmode: false, capture: 'click' });
    expect(annotateHint('note', DEFAULT_ANNOTATE_OPTIONS, 'map')).toMatch(/place on the map/);
  });
  it('supports scatter and choropleth maps, not density maps', () => {
    expect(componentSupportsAnnotation('map', {})).toBe(true);
    expect(componentSupportsAnnotation('map', { map_type: 'choropleth_map' })).toBe(true);
    expect(componentSupportsAnnotation('map', { map_type: 'density_map' })).toBe(false);
    expect(mapSupportsAnnotation({ map_type: 'scatter_map' })).toBe(true);
  });
  it('summarises a geo note', () => {
    const geometry = { kind: 'geo_note', lat: -33.87, lon: 151.21 } as const;
    expect(kindForGeometry(geometry)).toBe('note');
    expect(annotationSummary({ kind: 'note', geometry, label: 'x' })).toBe('Note at 33.87° S, 151.21° E');
  });
});
