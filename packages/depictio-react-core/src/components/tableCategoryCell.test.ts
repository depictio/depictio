import { describe, expect, it } from 'vitest';

import { pinnedColourColumns } from './tableCategoryCell';

describe('pinnedColourColumns', () => {
  const source = {
    category_colors: { genome: { A: '#111111' } },
    inherited_category_colors: { group: { x: '#222222' } },
  };

  it('keeps only the columns the dashboard gives colours to', () => {
    expect([...pinnedColourColumns(source, ['genome', 'group', 'size'])].sort()).toEqual([
      'genome',
      'group',
    ]);
  });

  it('is empty without a colour source', () => {
    expect(pinnedColourColumns(null, ['genome']).size).toBe(0);
  });
});
