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

describe('following a GenomeSpy window', () => {
  // GenomeSpy names the contig the way its data does, and sends the other
  // chr spelling as an alias; the assembly resolves either.
  it('resolves the contig through the alias GenomeSpy sends', () => {
    expect(
      followTarget({ entity: 'chr8', entityAliases: ['8'], start: 120, end: 4800 }, null, canonical),
    ).toBe('chr8:120-4800');
    expect(
      followTarget({ entity: 'MN908947.3', entityAliases: ['chrMN908947.3'], start: 1, end: 90 }, null, canonical),
    ).toBe('NC_045512v2:1-90');
  });
  it('does not move for the window the browser itself reported back', () => {
    const current = { entity: 'chr8', start: 1000, end: 5000 };
    expect(followTarget({ entity: 'chr8', entityAliases: ['8'], start: 1002, end: 4998 }, current, canonical)).toBeNull();
  });
  // A navigator zoomed out on a whole contig publishes tens of megabases; the
  // alignment tracks refuse anything over 1 Mb, so the browser takes the centre.
  it('follows a whole-contig window on its centre, at most 1 Mb wide', () => {
    expect(followTarget({ entity: 'chr8', entityAliases: ['8'], start: 0, end: 30_000_000 }, null, canonical)).toBe(
      'chr8:14500000-15500000',
    );
    const current = { entity: 'chr8', start: 14_500_000, end: 15_500_000 };
    expect(followTarget({ entity: 'chr8', start: 0, end: 30_000_000 }, current, canonical)).toBeNull();
  });
});
