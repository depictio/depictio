import { describe, expect, it } from 'vitest';

import { echoWithoutScope } from './scopeChip';

describe('echoWithoutScope', () => {
  it('drops a leading unit', () => {
    expect(echoWithoutScope('P12345 · 412 residues', 'P12345')).toBe('412 residues');
  });

  it('drops every segment equal to the unit, keeps the rest in order', () => {
    expect(echoWithoutScope('a · P1 · b · P1', 'P1')).toBe('a · b');
  });

  it('is null when only the unit was said', () => {
    expect(echoWithoutScope('P1', 'P1')).toBeNull();
    expect(echoWithoutScope(null, 'P1')).toBeNull();
  });

  it('leaves the echo alone without a unit or a match', () => {
    expect(echoWithoutScope('412 residues', undefined)).toBe('412 residues');
    expect(echoWithoutScope('P12 · x', 'P1')).toBe('P12 · x');
  });
});
