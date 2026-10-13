import { describe, expect, it } from 'vitest';
import { textLogoSrc } from './textLogo';

describe('textLogoSrc', () => {
  it('draws the logo on a light page', () => {
    expect(textLogoSrc('/assets/a.png', null, false)).toBe('/assets/a.png');
  });

  it('draws the dark variant on a dark page', () => {
    expect(textLogoSrc('/assets/a.png', '/assets/a_dark.png', true)).toBe('/assets/a_dark.png');
  });

  it('falls back to the title on a dark page without a dark variant', () => {
    expect(textLogoSrc('/assets/a.png', '', true)).toBeNull();
  });

  it('has no logo without one', () => {
    expect(textLogoSrc(undefined, '/assets/a_dark.png', true)).toBeNull();
    expect(textLogoSrc('  ', null, false)).toBeNull();
  });
});
