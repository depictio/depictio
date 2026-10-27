import { describe, expect, it } from 'vitest';

import { followTarget } from './followWindow';

const canonical = (name: string) =>
  ({ chr8: 'chr8', '8': 'chr8', NC_045512v2: 'NC_045512v2', 'MN908947.3': 'NC_045512v2' })[name];

describe('followTarget', () => {
  it('navigates to the published window', () => {
    expect(followTarget({ entity: 'chr8', start: 1000, end: 5000 }, null, canonical)).toBe(
      'chr8:1000-5000',
    );
  });
  it('resolves the contig through its aliases', () => {
    expect(
      followTarget(
        { entity: 'unknown', entityAliases: ['MN908947.3'], start: 10, end: 90 },
        null,
        canonical,
      ),
    ).toBe('NC_045512v2:10-90');
  });
  it('does nothing for a contig the assembly does not know', () => {
    expect(followTarget({ entity: 'chrZ', start: 1, end: 9 }, null, canonical)).toBeNull();
  });
  it('ignores the echo of the window already on screen (a base or two off)', () => {
    const current = { entity: 'chr8', start: 1000, end: 5000 };
    expect(followTarget({ entity: '8', start: 1001, end: 4999 }, current, canonical)).toBeNull();
  });
  it('follows a real move, and a move to another contig', () => {
    const current = { entity: 'chr8', start: 1000, end: 5000 };
    expect(followTarget({ entity: 'chr8', start: 2000, end: 6000 }, current, canonical)).toBe(
      'chr8:2000-6000',
    );
    expect(
      followTarget({ entity: 'NC_045512v2', start: 1000, end: 5000 }, current, canonical),
    ).toBe('NC_045512v2:1000-5000');
  });
  it('rejects a malformed window', () => {
    expect(followTarget({ entity: 'chr8', start: 50, end: 10 }, null, canonical)).toBeNull();
    expect(followTarget({ entity: 'chr8', start: NaN, end: 10 }, null, canonical)).toBeNull();
  });
});
