import { describe, expect, it } from 'vitest';

import {
  canonicalRefName,
  createAliasLookup,
  cursorLocus,
  visibleWindow,
  type CursorView,
} from './viewCursor';

/** A one-region view at 10 bp per pixel: pixel p is base p * 10 + 1. */
const view = (over: Partial<CursorView> = {}): CursorView => ({
  displayedRegions: [{}],
  pxToBp: (px) => ({ refName: 'chr1', coord: Math.floor(px * 10) + 1 }),
  ...over,
});

describe('cursorLocus', () => {
  it('converts the offset into the tracks area through the view', () => {
    expect(cursorLocus(view(), 150, 100)).toEqual({ refName: 'chr1', coord: 501 });
  });

  it('is null left of the tracks area, before regions load and outside the genome', () => {
    expect(cursorLocus(view(), 90, 100)).toBeNull();
    expect(cursorLocus(view({ displayedRegions: [] }), 150, 100)).toBeNull();
    expect(
      cursorLocus(view({ pxToBp: () => ({ refName: 'chr1', coord: 5, oob: true }) }), 150, 100),
    ).toBeNull();
    expect(cursorLocus(view({ pxToBp: () => ({ refName: '', coord: 5 }) }), 150, 100)).toBeNull();
  });
});

describe('visibleWindow', () => {
  it('is the first block as a 1-based inclusive window', () => {
    expect(visibleWindow([{ refName: 'chr8', start: 999.4, end: 5000.2 }])).toEqual({
      entity: 'chr8',
      start: 1000,
      end: 5001,
    });
  });

  it('reports the first contig of a multi-contig view', () => {
    const out = visibleWindow([
      { refName: 'a', start: 0, end: 10 },
      { refName: 'b', start: 0, end: 10 },
    ]);
    expect(out?.entity).toBe('a');
  });

  it('is null without blocks', () => {
    expect(visibleWindow([])).toBeNull();
    expect(visibleWindow(undefined)).toBeNull();
  });
});

describe('createAliasLookup', () => {
  const aliases = {
    NC_045512v2: 'NC_045512v2',
    'MN908947.3': 'NC_045512v2',
    'NC_045512.2': 'NC_045512v2',
    chr1: 'chr1',
  };

  it('lists the other names of a canonical reference name', () => {
    const lookup = createAliasLookup(() => aliases);
    expect(lookup('NC_045512v2')).toEqual(['MN908947.3', 'NC_045512.2']);
  });

  it('is undefined for a contig without aliases, an unknown one, or unloaded aliases', () => {
    const lookup = createAliasLookup(() => aliases);
    expect(lookup('chr1')).toBeUndefined();
    expect(lookup('nope')).toBeUndefined();
    expect(createAliasLookup(() => undefined)('chr1')).toBeUndefined();
  });

  it('follows the alias map once it loads', () => {
    let current: Record<string, string> | undefined;
    const lookup = createAliasLookup(() => current);
    expect(lookup('NC_045512v2')).toBeUndefined();
    current = aliases;
    expect(lookup('NC_045512v2')).toEqual(['MN908947.3', 'NC_045512.2']);
  });
});

describe('canonicalRefName', () => {
  it('asks the assembly, and says nothing while its aliases are not loaded', () => {
    expect(canonicalRefName({ getCanonicalRefName: () => 'chr20' }, '20')).toBe('chr20');
    const loading = {
      getCanonicalRefName: () => {
        throw new Error('aliases not loaded');
      },
    };
    expect(canonicalRefName(loading, '20')).toBeUndefined();
    expect(canonicalRefName(undefined, '20')).toBeUndefined();
  });
});
