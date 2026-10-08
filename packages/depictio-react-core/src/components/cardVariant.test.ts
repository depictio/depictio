import { describe, expect, it } from 'vitest';

import type { StoredMetadata } from '../api';
import {
  CARD_VARIANTS,
  compactKeepsStrip,
  normalizeCardVariant,
  resolveCardVariant,
  stripIsMinimal,
  variantForPick,
  withSectionCardVariant,
} from './cardVariant';

const card = (extra: Partial<StoredMetadata> = {}): StoredMetadata =>
  ({ index: 'c1', component_type: 'card', ...extra }) as StoredMetadata;

describe('normalizeCardVariant', () => {
  it('keeps the six known styles', () => {
    for (const v of ['default', 'headline', 'compact', 'minimal', 'accent', 'split']) {
      expect(normalizeCardVariant(v)).toBe(v);
    }
  });

  it('reads anything else as unset', () => {
    expect(normalizeCardVariant(undefined)).toBeNull();
    expect(normalizeCardVariant(null)).toBeNull();
    expect(normalizeCardVariant('')).toBeNull();
    expect(normalizeCardVariant('fancy')).toBeNull();
    expect(normalizeCardVariant(3)).toBeNull();
  });
});

describe('resolveCardVariant', () => {
  it('falls back to default when neither side sets a style', () => {
    expect(resolveCardVariant(undefined, undefined)).toBe('default');
  });

  it("takes the section's style when the card sets none", () => {
    expect(resolveCardVariant(undefined, 'headline')).toBe('headline');
    expect(resolveCardVariant(null, 'compact')).toBe('compact');
  });

  it("keeps the card's own style over the section's", () => {
    expect(resolveCardVariant('minimal', 'headline')).toBe('minimal');
  });

  it('lets an explicit default opt a card out of its section', () => {
    expect(resolveCardVariant('default', 'headline')).toBe('default');
  });

  it('ignores unknown values on either side', () => {
    expect(resolveCardVariant('fancy', 'compact')).toBe('compact');
    expect(resolveCardVariant(undefined, 'fancy')).toBe('default');
  });
});

describe('withSectionCardVariant', () => {
  it("fills in the section's style on a card that sets none", () => {
    expect(withSectionCardVariant(card(), { card_variant: 'headline' }).variant).toBe('headline');
  });

  it('returns the same object when nothing changes', () => {
    const own = card({ variant: 'compact' });
    expect(withSectionCardVariant(own, { card_variant: 'headline' })).toBe(own);
    const bare = card();
    expect(withSectionCardVariant(bare, null)).toBe(bare);
    expect(withSectionCardVariant(bare, { card_variant: null })).toBe(bare);
  });

  it('replaces an unknown card value with the section style', () => {
    expect(
      withSectionCardVariant(card({ variant: 'fancy' }), { card_variant: 'minimal' }).variant,
    ).toBe('minimal');
  });

  it('leaves other component types alone', () => {
    const fig = { index: 'f1', component_type: 'figure' } as StoredMetadata;
    expect(withSectionCardVariant(fig, { card_variant: 'headline' })).toBe(fig);
  });
});

describe('variantForPick', () => {
  it('stores default as unset when the section sets no style', () => {
    expect(variantForPick('default', null)).toBeNull();
    expect(variantForPick('headline', null)).toBe('headline');
  });

  it("stores the section's own style as unset, so the card keeps following it", () => {
    expect(variantForPick('headline', 'headline')).toBeNull();
  });

  it('stores default explicitly to opt out of a styled section', () => {
    expect(variantForPick('default', 'headline')).toBe('default');
    expect(variantForPick('compact', 'headline')).toBe('compact');
  });

  it('reads an unknown pick as default', () => {
    expect(variantForPick('fancy', null)).toBeNull();
  });
});

describe('compactKeepsStrip', () => {
  it('keeps only the single-bar strips', () => {
    expect(compactKeepsStrip('coverage')).toBe(true);
    expect(compactKeepsStrip('composition')).toBe(true);
    expect(compactKeepsStrip('box_plot')).toBe(false);
    expect(compactKeepsStrip(undefined)).toBe(false);
  });
});

describe('stripIsMinimal', () => {
  it('keeps the full strip on default and accent cards only', () => {
    const full = CARD_VARIANTS.filter((v) => !stripIsMinimal(v));
    expect(full).toEqual(['default', 'accent']);
  });
});

describe('the new styles', () => {
  it('resolve from a section like the others', () => {
    expect(resolveCardVariant(undefined, 'accent')).toBe('accent');
    expect(resolveCardVariant('split', 'accent')).toBe('split');
    expect(withSectionCardVariant(card(), { card_variant: 'split' }).variant).toBe('split');
  });
});
