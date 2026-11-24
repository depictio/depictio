import { describe, expect, it } from 'vitest';
import { assignColors, ordinalColors } from './palettes';
import { DIRECTION_COLORS, SEMANTIC_COLORS } from './palettes.generated';

describe('ordinal vocabularies', () => {
  it('colours SnpEff impact classes as a severity, whatever the case', () => {
    const map = assignColors(['MODIFIER', 'high', 'LOW', 'MODERATE']);
    expect(map.get('high')).toBe(DIRECTION_COLORS.up.light);
    expect(map.get('MODIFIER')).toBe(SEMANTIC_COLORS.other.light);
    expect(map.get('MODERATE')).not.toBe(map.get('LOW'));
  });
  it('keeps categorical slots when one value is not a level', () => {
    expect(ordinalColors(['HIGH', 'LOW', 'banana'])).toBeNull();
    expect(ordinalColors(['HIGH'])).toBeNull();
  });
  it('lets a pin win', () => {
    expect(assignColors(['HIGH', 'LOW'], { pinned: { HIGH: '#000001' } }).get('HIGH')).toBe('#000001');
  });
});
