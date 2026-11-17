import { describe, expect, it } from 'vitest';

import {
  axisRanges,
  cellDiameters,
  cellExtent,
  clipRange,
  facetDomains,
  fillUrlTemplate,
  formatHoverNumber,
  groupRowsBySample,
  heightForFrames,
  imageFrame,
  imageServeUrl,
  isNumericDtype,
  padFrame,
  percentile,
  pickMarker,
  pickSample,
  pixelsPerUnit,
  resolveMarkerColumns,
  thinIndices,
  toNumber,
  transformValue,
  underlayImage,
  unionFrame,
} from './spatialLayout';

// The shape of an mcquant table: id, morphology, coordinates, one column per marker.
const MCQUANT: Record<string, string> = {
  CellID: 'Int64',
  cell_id: 'String',
  sample: 'String',
  DNA_1: 'Float64',
  CD3: 'Float64',
  CD20: 'Float64',
  PanCK: 'Float64',
  Ki67: 'Float64',
  X_centroid: 'Float64',
  Y_centroid: 'Float64',
  Area: 'Int64',
  Eccentricity: 'Float64',
  cell_type: 'String',
};

describe('resolveMarkerColumns', () => {
  it('keeps an explicit list in its order and puts value_col first when missing', () => {
    expect(resolveMarkerColumns({ schema: null, valueColumns: ['CD3', 'CD20'] })).toEqual(['CD3', 'CD20']);
    expect(resolveMarkerColumns({ schema: null, valueColumns: ['CD3', 'CD20'], valueCol: 'Ki67' })).toEqual([
      'Ki67',
      'CD3',
      'CD20',
    ]);
    expect(resolveMarkerColumns({ schema: null, valueColumns: ['CD3', 'CD3'], valueCol: 'CD3' })).toEqual(['CD3']);
  });

  it('matches a pattern against the numeric columns only, less the bound ones', () => {
    const markers = resolveMarkerColumns({
      schema: MCQUANT,
      pattern: '^(?!X_|Y_|Area|Eccentricity|CellID)',
      exclude: ['cell_id', 'sample'],
    });
    expect(markers).toEqual(['DNA_1', 'CD3', 'CD20', 'PanCK', 'Ki67']);
    expect(resolveMarkerColumns({ schema: MCQUANT, pattern: '^CD' })).toEqual(['CD3', 'CD20']);
  });

  it('matches nothing on an invalid pattern or before the schema arrives', () => {
    expect(resolveMarkerColumns({ schema: MCQUANT, pattern: '(' })).toEqual([]);
    expect(resolveMarkerColumns({ schema: null, pattern: '^CD', valueCol: 'CD3' })).toEqual(['CD3']);
  });

  it('falls back to value_col alone, and to nothing', () => {
    expect(resolveMarkerColumns({ schema: MCQUANT, valueCol: 'Ki67' })).toEqual(['Ki67']);
    expect(resolveMarkerColumns({ schema: MCQUANT })).toEqual([]);
  });

  it('picks the marker still on offer, else the first', () => {
    expect(pickMarker(['CD3', 'CD20'], 'CD20')).toBe('CD20');
    expect(pickMarker(['CD3', 'CD20'], 'gone')).toBe('CD3');
    expect(pickMarker([], 'CD3')).toBeNull();
  });

  it('reads polars numeric dtypes', () => {
    expect(isNumericDtype('Float32')).toBe(true);
    expect(isNumericDtype('UInt16')).toBe(true);
    expect(isNumericDtype('String')).toBe(false);
    expect(isNumericDtype(undefined)).toBe(false);
  });
});

describe('colour transform and clipping', () => {
  it('applies asinh with its cofactor and log1p', () => {
    expect(transformValue(150, 'asinh', 150)).toBeCloseTo(Math.asinh(1));
    expect(transformValue(5, 'asinh', 5)).toBeCloseTo(0.8814, 4);
    expect(transformValue(0, 'asinh', 5)).toBe(0);
    expect(transformValue(Math.E - 1, 'log1p')).toBeCloseTo(1);
    expect(Number.isNaN(transformValue(-2, 'log1p'))).toBe(true);
    expect(transformValue(42, 'none')).toBe(42);
    // A cofactor of zero would divide by zero; it is read as one.
    expect(transformValue(2, 'asinh', 0)).toBeCloseTo(Math.asinh(2));
  });

  it('interpolates percentiles between ranks', () => {
    expect(percentile([0, 10, 20, 30, 40], 50)).toBe(20);
    expect(percentile([0, 10], 25)).toBe(2.5);
    expect(percentile([5], 99)).toBe(5);
    expect(Number.isNaN(percentile([], 50))).toBe(true);
  });

  it('clips the range to the percentiles so one bright cell cannot flatten the rest', () => {
    const values = Array.from({ length: 101 }, (_, i) => i);
    values.push(100_000);
    const range = clipRange(values, 1, 99)!;
    expect(range.min).toBeCloseTo(1.01, 2);
    expect(range.max).toBeLessThan(101);
    expect(clipRange(values, 0, 100)).toEqual({ min: 0, max: 100_000 });
  });

  it('ignores nulls and widens a collapsed range', () => {
    expect(clipRange([null, 3, 3, null], 1, 99)).toEqual({ min: 2, max: 4 });
    expect(clipRange([null, Number.NaN], 1, 99)).toBeNull();
  });

  it('reads numbers strictly', () => {
    expect(toNumber('3.5')).toBe(3.5);
    expect(toNumber('')).toBeNull();
    expect(toNumber(null)).toBeNull();
    expect(toNumber(true)).toBeNull();
    expect(toNumber('x')).toBeNull();
  });
});

describe('the coordinate frame', () => {
  it('bounds the cells, skipping missing coordinates', () => {
    expect(cellExtent([10, null, 30], [5, 7, 50])).toEqual({ x0: 10, x1: 30, y0: 5, y1: 50 });
    expect(cellExtent([null], [null])).toBeNull();
  });

  it('runs y downwards in image mode and upwards in cartesian mode', () => {
    const frame = { x0: 0, x1: 100, y0: 0, y1: 80 };
    expect(axisRanges(frame, 'image')).toEqual({ x: [0, 100], y: [80, 0] });
    expect(axisRanges(frame, 'cartesian')).toEqual({ x: [0, 100], y: [0, 80] });
  });

  it('covers the whole image when there is one, and pads the edge cells', () => {
    const image = imageFrame(512, 256, 2);
    expect(image).toEqual({ x0: 0, x1: 1024, y0: 0, y1: 512 });
    expect(unionFrame(image, { x0: -10, x1: 100, y0: 20, y1: 600 })).toEqual({
      x0: -10,
      x1: 1024,
      y0: 0,
      y1: 600,
    });
    expect(unionFrame(null, image)).toBe(image);
    expect(padFrame({ x0: 0, x1: 100, y0: 0, y1: 50 }, 0.1)).toEqual({ x0: -10, x1: 110, y0: -10, y1: 60 });
    expect(padFrame({ x0: 5, x1: 5, y0: 5, y1: 5 })).toEqual({ x0: 4, x1: 6, y0: 4, y1: 6 });
  });

  it('anchors the image at its top-left pixel on either axis direction', () => {
    const down = underlayImage({ source: 'a.png', width: 400, height: 300, scale: 0.5, yAxis: 'image' });
    expect(down).toMatchObject({ x: 0, y: 0, sizex: 200, sizey: 150, xanchor: 'left', yanchor: 'top' });
    expect(down).toMatchObject({ xref: 'x', yref: 'y', layer: 'below', sizing: 'stretch' });
    const up = underlayImage({
      source: 'a.png',
      width: 400,
      height: 300,
      yAxis: 'cartesian',
      xref: 'x2',
      yref: 'y2',
      opacity: 0.3,
    });
    expect(up).toMatchObject({ y: 300, sizey: 300, xref: 'x2', yref: 'y2', opacity: 0.3 });
  });
});

describe('cell size on screen', () => {
  it('takes the tighter axis of an equal-aspect frame', () => {
    expect(pixelsPerUnit({ x0: 0, x1: 1000, y0: 0, y1: 500 }, 500, 500)).toBe(0.5);
    expect(pixelsPerUnit({ x0: 0, x1: 100, y0: 0, y1: 400 }, 500, 200)).toBe(0.5);
    expect(pixelsPerUnit({ x0: 0, x1: 0, y0: 0, y1: 0 }, 500, 200)).toBe(0);
  });

  it('draws a cell at the diameter of its area, clamped, and grows with the zoom', () => {
    const area = Math.PI * 25; // a disc of radius 5 units
    expect(cellDiameters([area], 1, 1, 100)).toEqual([10]);
    expect(cellDiameters([area], 3, 1, 100)).toEqual([30]);
    expect(cellDiameters([area], 10, 1, 40)).toEqual([40]);
    expect(cellDiameters([area], 0.01, 2, 40)).toEqual([2]);
    expect(cellDiameters([null, 0, -4], 1, 3, 40)).toEqual([3, 3, 3]);
  });
});

describe('thinning and samples', () => {
  it('keeps every row under the cap, else an even stride that starts at the first', () => {
    expect(thinIndices(10, 20)).toBeNull();
    expect(thinIndices(10, 5)).toEqual([0, 2, 4, 6, 8]);
    expect(thinIndices(7, 3)).toEqual([0, 2, 4]);
    expect(thinIndices(0, 3)).toBeNull();
  });

  it('files rows by sample in natural order', () => {
    const groups = groupRowsBySample(['S10', 'S2', 'S10', null], 4);
    expect(Array.from(groups.keys())).toEqual(['', 'S2', 'S10']);
    expect(groups.get('S10')).toEqual([0, 2]);
    expect(groupRowsBySample(null, 2).get('')).toEqual([0, 1]);
  });

  it('opens on the configured sample when it exists', () => {
    expect(pickSample(['A', 'B'], 'B')).toBe('B');
    expect(pickSample(['A', 'B'], 'C')).toBe('A');
    expect(pickSample([], 'C')).toBeNull();
  });

  it('lays facets side by side with a gap', () => {
    expect(facetDomains(1)).toEqual([[0, 1]]);
    const [a, b] = facetDomains(2, 0.1);
    expect(a[0]).toBe(0);
    expect(a[1]).toBeCloseTo(0.45);
    expect(b[0]).toBeCloseTo(0.55);
    expect(b[1]).toBeCloseTo(1);
  });
});

describe('the height the frames need', () => {
  it('is the width times the aspect, for the tallest facet', () => {
    expect(heightForFrames([{ x0: 0, x1: 1000, y0: 0, y1: 800 }], 500)).toBe(400);
    const two = heightForFrames(
      [
        { x0: 0, x1: 100, y0: 0, y1: 100 },
        { x0: 0, x1: 100, y0: 0, y1: 200 },
      ],
      1000,
      0,
    );
    expect(two).toBe(1000);
  });

  it('is unknown without a width or a frame', () => {
    expect(heightForFrames([], 500)).toBe(0);
    expect(heightForFrames([{ x0: 0, x1: 10, y0: 0, y1: 10 }], 0)).toBe(0);
    expect(heightForFrames([{ x0: 0, x1: 0, y0: 0, y1: 10 }], 300)).toBe(0);
  });
});

describe('underlay URLs', () => {
  it('fills the sample into a template', () => {
    expect(fillUrlTemplate('/previews/{sample}.png', 'tonsil 1')).toBe('/previews/tonsil%201.png');
    expect(fillUrlTemplate('/one.png', 'x')).toBe('/one.png');
  });

  it('builds the serve URL as the image grid does', () => {
    expect(imageServeUrl('s3://bucket/previews/', 'previews/s1.png')).toBe(
      `/depictio/api/v1/files/serve/image?s3_path=${encodeURIComponent('s3://bucket/previews/s1.png')}`,
    );
    expect(imageServeUrl('s3://bucket/previews', 's1.png')).toContain(encodeURIComponent('previews/s1.png'));
    expect(imageServeUrl('s3://bucket/x', 'https://example.org/a.png')).toBe('https://example.org/a.png');
    expect(imageServeUrl('', 'a.png')).toBe('a.png');
  });
});

describe('hover numbers', () => {
  it('prints integers whole and the rest to four significant digits', () => {
    expect(formatHoverNumber(212)).toBe('212');
    expect(formatHoverNumber(1234.5678)).toBe('1235');
    expect(formatHoverNumber(0.012345)).toBe('0.01235');
    expect(formatHoverNumber(null)).toBe('NA');
  });
});
