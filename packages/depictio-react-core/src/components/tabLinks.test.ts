import { describe, expect, it } from 'vitest';

import { balancedColumns, parseTabTile, tabLinkKey } from './tabLinks';

describe('parseTabTile', () => {
  it('reads a bare tab link', () => {
    expect(parseTabTile('[Alpha](tab:Alpha Diversity)')).toEqual({
      label: 'Alpha',
      tab: 'Alpha Diversity',
      text: null,
    });
  });

  it('reads the text after a colon or a dash', () => {
    expect(parseTabTile('[QC](tab:Sequencing QC): did the run work')?.text).toBe(
      'did the run work',
    );
    expect(parseTabTile('[QC](tab:Sequencing QC) — did the run work')?.text).toBe(
      'did the run work',
    );
  });

  it('keeps parentheses in the tab name', () => {
    expect(parseTabTile('[CTD](tab:Environment (CTD))')?.tab).toBe('Environment (CTD)');
  });

  it('refuses prose that only mentions a tab', () => {
    expect(parseTabTile('see [Alpha](tab:Alpha Diversity) for more')).toBeNull();
    expect(parseTabTile('[docs](https://example.org)')).toBeNull();
  });
});

describe('tabLinkKey', () => {
  it('ignores case and repeated spaces', () => {
    expect(tabLinkKey('  Community  &  Diversity ')).toBe(tabLinkKey('community & diversity'));
  });
});

describe('balancedColumns', () => {
  it('evens out a last row that would hold one tile', () => {
    // 4 fit in 940px at 220 + 12; five go 3 + 2.
    expect(balancedColumns(5, 940, 220, 12)).toBe(3);
    expect(balancedColumns(4, 940, 220, 12)).toBe(4);
    expect(balancedColumns(3, 940, 220, 12)).toBe(3);
  });

  it('falls back to one column when nothing fits', () => {
    expect(balancedColumns(4, 150, 220, 12)).toBe(1);
  });
});
