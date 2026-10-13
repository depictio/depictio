import { describe, expect, it } from 'vitest';

import { namedColumns } from './namedColumns';

const schema = {
  region: 'String',
  'T15_R1.mLb.clN': 'Float64',
  'T0.mRp.clN': 'Float64',
  'T0_R1.mLb.clN': 'Float64',
};

describe('namedColumns', () => {
  it('returns the listed columns as given', () => {
    expect(namedColumns(['T0.mRp.clN'], '\\.mLb\\.clN$', schema)).toEqual(['T0.mRp.clN']);
  });

  it('matches the pattern against the schema, in schema order', () => {
    expect(namedColumns(null, '\\.mLb\\.clN$', schema)).toEqual(['T15_R1.mLb.clN', 'T0_R1.mLb.clN']);
  });

  it('names nothing before the schema arrives', () => {
    expect(namedColumns(null, '\\.mLb\\.clN$', null)).toEqual([]);
  });

  it('names nothing for a pattern the browser cannot compile', () => {
    expect(namedColumns(undefined, '(unclosed', schema)).toEqual([]);
  });

  it('names nothing without a list or a pattern', () => {
    expect(namedColumns(null, null, schema)).toEqual([]);
  });
});
