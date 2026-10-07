import { describe, expect, it } from 'vitest';

import { DEFAULT_SECTION_PALETTE, resolveSectionColor } from './SectionIcon';

describe('resolveSectionColor', () => {
  it('keeps a declared colour', () => {
    expect(resolveSectionColor('grape', 'QC')).toBe('grape');
  });

  it('picks a stable default from the small palette by name', () => {
    const first = resolveSectionColor(null, 'Run QC');
    expect(DEFAULT_SECTION_PALETTE).toContain(first);
    expect(resolveSectionColor(undefined, 'Run QC')).toBe(first);
  });

  it('stays neutral without a colour or a name', () => {
    expect(resolveSectionColor(null, null)).toBeNull();
  });
});
