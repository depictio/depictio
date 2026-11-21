import { describe, expect, it } from 'vitest';

import { semanticColor } from '../../../palettes';
import { phyloColorScale } from './palette';
import { canonicalTaxon, pinnedColourFor } from './taxonAliases';

const PALETTE = ['#111111', '#222222', '#333333', '#444444', '#555555', '#666666', '#777777', '#888888'];
const OTHER = semanticColor('other', 'light');

describe('taxonAliases', () => {
  it('maps legacy and current names to one key, case-insensitively', () => {
    expect(canonicalTaxon('Proteobacteria')).toBe(canonicalTaxon('pseudomonadota'));
    expect(canonicalTaxon('Crenarchaeota')).toBe(canonicalTaxon('Thermoproteota'));
    expect(canonicalTaxon('Actinobacteriota')).toBe(canonicalTaxon('Actinomycetota'));
    expect(canonicalTaxon('Unknownia')).toBe('unknownia');
  });

  it('finds a pin under the alias, in either direction', () => {
    expect(pinnedColourFor('Proteobacteria', { Pseudomonadota: '#abcdef' })).toBe('#abcdef');
    expect(pinnedColourFor('Pseudomonadota', { Proteobacteria: '#123456' })).toBe('#123456');
    expect(pinnedColourFor('Firmicutes', { Pseudomonadota: '#abcdef' })).toBeUndefined();
    expect(pinnedColourFor('Firmicutes', null)).toBeUndefined();
  });

  it('prefers the own pin over an alias pin', () => {
    expect(
      pinnedColourFor('Proteobacteria', { Proteobacteria: '#000001', Pseudomonadota: '#000002' }),
    ).toBe('#000001');
  });
});

describe('phyloColorScale', () => {
  const tips = (spec: Record<string, number>) =>
    Object.entries(spec).flatMap(([v, n]) => Array.from({ length: n }, () => v));

  it('ranks by tip count, ties by name, so the largest lineages take the first slots', () => {
    const scale = phyloColorScale(tips({ B: 3, A: 3, C: 10, D: 1 }), null, PALETTE, null, 'light');
    expect(scale.get('C')).toBe(PALETTE[0]);
    expect(scale.get('A')).toBe(PALETTE[1]);
    expect(scale.get('B')).toBe(PALETTE[2]);
    expect(scale.get('D')).toBe(PALETTE[3]);
  });

  it('colours a SILVA tip name with the pin of its GTDB name, labels untouched', () => {
    const scale = phyloColorScale(
      tips({ Proteobacteria: 5, Bacteroidetes: 4, Other_x: 1 }),
      null,
      PALETTE,
      { Pseudomonadota: '#aa0000', Bacteroidota: '#00aa00' },
      'light',
    );
    expect(scale.get('Proteobacteria')).toBe('#aa0000');
    expect(scale.get('Bacteroidetes')).toBe('#00aa00');
    // the free value takes a slot, never a pinned colour
    expect(['#aa0000', '#00aa00']).not.toContain(scale.get('Other_x'));
  });

  it('never repeats a hue past the palette: the tail is the Other grey', () => {
    const names = Array.from({ length: 12 }, (_, i) => `P${String(i).padStart(2, '0')}`);
    const spec = Object.fromEntries(names.map((n, i) => [n, 100 - i]));
    const scale = phyloColorScale(tips(spec), null, PALETTE, null, 'light');
    const colours = names.map((n) => scale.get(n));
    const real = colours.filter((c) => c !== OTHER);
    expect(real).toHaveLength(8);
    expect(new Set(real).size).toBe(8);
    expect(colours.slice(8).every((c) => c === OTHER)).toBe(true);
    // the largest eight kept the slots
    expect(colours.slice(0, 8)).toEqual(PALETTE);
  });

  it('keeps universe values with no tip, ranked last', () => {
    const scale = phyloColorScale(tips({ A: 2 }), ['Z', 'A'], PALETTE, null, 'light');
    expect(scale.get('A')).toBe(PALETTE[0]);
    expect(scale.get('Z')).toBe(PALETTE[1]);
  });
});
