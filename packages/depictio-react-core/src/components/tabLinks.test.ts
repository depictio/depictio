import { describe, expect, it } from 'vitest';

import { parseTabTile, tabLinkKey } from './tabLinks';

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
