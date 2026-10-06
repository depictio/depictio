import { describe, expect, it } from 'vitest';

import type { TabLinkTarget } from '../tabLinks';
import { advancedVizShowcase, tabLinkName } from './advancedVizShowcase';

const target: TabLinkTarget = { href: '/dashboard/t1', label: 'Phylogeny', icon: 'mdi:family-tree' };

describe('advancedVizShowcase', () => {
  it('is null unless the tile is drawn minimal', () => {
    expect(advancedVizShowcase({}, null)).toBeNull();
    expect(advancedVizShowcase({ figure_style: 'default', subtitle: 'x' }, null)).toBeNull();
  });

  it('carries the header of a minimal tile, trimmed', () => {
    expect(
      advancedVizShowcase(
        {
          figure_style: 'minimal',
          subtitle: ' top phyla ',
          icon_name: 'mdi:family-tree',
          icon_color: '#82c91e',
        },
        target,
      ),
    ).toEqual({ subtitle: 'top phyla', icon: 'mdi:family-tree', iconColor: '#82c91e', source: target });
  });

  it('reads missing header fields as empty', () => {
    expect(advancedVizShowcase({ figure_style: 'minimal' }, null)).toEqual({
      subtitle: '',
      icon: '',
      iconColor: '',
      source: null,
    });
  });
});

describe('tabLinkName', () => {
  it('names the tab of a tab link only', () => {
    expect(tabLinkName('tab:Phylogeny')).toBe('Phylogeny');
    expect(tabLinkName('https://example.org')).toBeNull();
    expect(tabLinkName(undefined)).toBeNull();
  });
});
