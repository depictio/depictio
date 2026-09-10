import { describe, expect, it } from 'vitest';

import {
  asEnum,
  asList,
  asScalar,
  decodeListingParams,
  encodeListingParams,
} from './listingUrlState';

describe('decodeListingParams', () => {
  it('collects repeated params into one entry', () => {
    expect(decodeListingParams('?owner=a&owner=b')).toEqual({ owner: ['a', 'b'] });
  });

  it('tolerates the leading question mark being absent', () => {
    expect(decodeListingParams('template=rnaseq')).toEqual({ template: ['rnaseq'] });
  });

  it('returns an empty map for an empty query string', () => {
    expect(decodeListingParams('')).toEqual({});
    expect(decodeListingParams('?')).toEqual({});
  });

  it('decodes percent-escaped values', () => {
    expect(decodeListingParams('?template=nf-core%2Frnaseq')).toEqual({
      template: ['nf-core/rnaseq'],
    });
  });
});

describe('asList', () => {
  it('reads repeats and comma-joined values the same way', () => {
    expect(asList(['a', 'b'])).toEqual(['a', 'b']);
    expect(asList(['a,b'])).toEqual(['a', 'b']);
  });

  it('drops blanks and collapses duplicates', () => {
    expect(asList([',a, ,a,b '])).toEqual(['a', 'b']);
  });

  it('reads a missing param as no filter', () => {
    expect(asList(undefined)).toEqual([]);
  });
});

describe('asScalar', () => {
  it('takes the value verbatim, commas included', () => {
    expect(asScalar(['rnaseq, salmon'])).toBe('rnaseq, salmon');
  });

  it('keeps the first occurrence and ignores blanks', () => {
    expect(asScalar(['first', 'second'])).toBe('first');
    expect(asScalar(['   '])).toBeUndefined();
    expect(asScalar(undefined)).toBeUndefined();
  });
});

describe('asEnum', () => {
  const VIEWS = ['thumbnails', 'list', 'table'] as const;

  it('accepts a known value', () => {
    expect(asEnum(['table'], VIEWS)).toBe('table');
  });

  it('falls through on anything else, so the stored preference wins', () => {
    expect(asEnum(['grid'], VIEWS)).toBeUndefined();
    expect(asEnum(undefined, VIEWS)).toBeUndefined();
  });
});

describe('encodeListingParams', () => {
  it('joins lists with commas and preserves key order', () => {
    expect(
      encodeListingParams({ template: ['nf-core/rnaseq'], owner: ['a', 'b'] }),
    ).toBe('template=nf-core%2Frnaseq&owner=a%2Cb');
  });

  it('omits everything empty so a cleared filter leaves no trace', () => {
    expect(
      encodeListingParams({
        template: [],
        q: '',
        owner: null,
        view: undefined,
        pinned: false,
      }),
    ).toBe('');
  });

  it('writes a true flag as 1', () => {
    expect(encodeListingParams({ pinned: true })).toBe('pinned=1');
  });

  it('round-trips through decode', () => {
    const encoded = encodeListingParams({ template: ['a', 'b'], q: 'x, y' });
    const decoded = decodeListingParams(`?${encoded}`);
    expect(asList(decoded.template)).toEqual(['a', 'b']);
    expect(asScalar(decoded.q)).toBe('x, y');
  });
});
