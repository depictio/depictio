/**
 * Viewer filter payloads → BoundFilters → mask, against the rows the SERVER
 * keeps for the same payload (generate_fixture.py `binding` cases:
 * clean_filter_payload → process_metadata_and_filter over the fixture).
 *
 * Pins the add_filter semantics the hand-written translation used to miss:
 * TextInput case-insensitive regex / match_mode / case_sensitive, Slider `>=`
 * default + slider_mode, and component filter_expr ANDed in through the
 * `__fe__` companions the Python builder evaluated.
 */

import { describe, expect, it } from 'vitest';

import {
  bindFilters,
  chromNameVariants,
  escapeRegex,
  scopeRegionFilters,
  scopeResidueFilters,
  textFilterPattern,
  type FilterLike,
} from '../../src/filterBinding';
import { expectClose, expected, openFixture } from './helpers';

const binding = (expected as unknown as {
  binding: Record<string, { matched: number; value_f64_sum: number; filters: FilterLike[] }>;
}).binding;

const feCompanions = new Map(
  Object.entries(expected.companions)
    .filter(([name]) => name.startsWith('__fe__'))
    .map(([name, expr]) => [expr, name] as [string, string]),
);

describe('bindFilters vs the server (process_metadata_and_filter)', () => {
  it('has the filter_expr companions the Python builder wrote', () => {
    expect(feCompanions.size).toBe(3);
  });

  for (const [name, exp] of Object.entries(binding)) {
    it(name, async () => {
      const { engine, handle } = await openFixture();
      const bound = bindFilters(exp.filters, { filterExprCompanions: feCompanions });
      const { mask, matched } = await engine.mask(handle, bound);
      const [sum] = (await engine.aggregate(handle, mask, [{ col: 'value_f64', fn: 'sum' }])) as [
        number,
      ];
      expect(matched, `${name} matched`).toBe(exp.matched);
      expectClose(sum, exp.value_f64_sum);
    });
  }
});

describe('textFilterPattern', () => {
  it('is a case-insensitive regex by default', () => {
    expect(textFilterPattern('ab', null, null)).toEqual({ pattern: 'ab', literal: false, flags: 'i' });
  });
  it('escapes a literal in case-insensitive contains mode', () => {
    expect(textFilterPattern('a.b', false, 'contains')).toEqual({
      pattern: 'a\\.b',
      literal: false,
      flags: 'i',
    });
  });
  it('keeps a case-sensitive literal literal', () => {
    expect(textFilterPattern('a.b', true, 'contains')).toEqual({ pattern: 'a.b', literal: true, flags: '' });
  });
  it('is no filter for blanks, over-long and invalid patterns', () => {
    expect(textFilterPattern('   ', null, null)).toBeNull();
    expect(textFilterPattern('a'.repeat(513), null, null)).toBeNull();
    expect(textFilterPattern('(', null, null)).toBeNull();
    expect(textFilterPattern(['a'], null, null)).toBeNull();
  });
  it('escape_regex covers the Rust metacharacters', () => {
    expect(escapeRegex('a-b#c&d~e')).toBe('a\\-b\\#c\\&d\\~e');
  });
});

describe('genome_selection chromosome spellings (chrom_name_variants)', () => {
  it('adds the chr / no-chr spellings and the MT aliases', () => {
    expect(chromNameVariants(['chr1'])).toEqual(['chr1', '1']);
    expect(chromNameVariants('M')).toEqual(['M', 'MT', 'chrMT', 'chrM']);
  });
  it('widens a region MultiSelect, never a plain one', () => {
    const region = bindFilters([
      { value: ['chr2'], column_name: 'chrom', interactive_component_type: 'MultiSelect', source: 'genome_selection' },
    ]);
    expect(region).toEqual([{ kind: 'in', column: 'chrom', values: ['chr2', '2'] }]);
    const plain = bindFilters([{ value: ['chr2'], column_name: 'chrom', interactive_component_type: 'MultiSelect' }]);
    expect(plain).toEqual([{ kind: 'in', column: 'chrom', values: ['chr2'] }]);
  });
});

describe('region scoping (region_scope.py)', () => {
  const sample: FilterLike = { value: ['a'], column_name: 'sample', interactive_component_type: 'MultiSelect' };
  const chrom: FilterLike = {
    value: ['chr1'],
    column_name: 'chrom',
    interactive_component_type: 'MultiSelect',
    source: 'genome_selection',
  };
  const pos: FilterLike = {
    value: [1, 10],
    column_name: 'pos',
    interactive_component_type: 'RangeSlider',
    metadata: { source: 'genome_selection' },
  };
  it('cards and interactive components drop the region unless they opt in', () => {
    expect(scopeRegionFilters([sample, chrom, pos], 'card', {})).toEqual([sample]);
    expect(scopeRegionFilters([sample, chrom, pos], 'interactive', {})).toEqual([sample]);
    expect(scopeRegionFilters([sample, chrom], 'card', { follow_region_filter: true })).toHaveLength(2);
    expect(scopeRegionFilters([sample, chrom], 'card', { config: { follow_region_filter: true } })).toHaveLength(2);
  });
  it('a figure keeps the region only when its encodings name a region column', () => {
    expect(scopeRegionFilters([sample, chrom, pos], 'figure', { dict_kwargs: { x: 'depth' } })).toEqual([sample]);
    expect(scopeRegionFilters([sample, chrom, pos], 'figure', { dict_kwargs: { x: 'pos' } })).toHaveLength(3);
  });
  it('other component types are never scoped', () => {
    expect(scopeRegionFilters([sample, chrom, pos], 'table', {})).toHaveLength(3);
  });
  it('heatmap and UpSet ignore the residue gesture', () => {
    const residue: FilterLike = { value: ['P1'], column_name: 'protein', interactive_component_type: 'MultiSelect', source: 'residue_selection' };
    const paired: FilterLike = { value: ['d'], column_name: 'domain', interactive_component_type: 'MultiSelect', paired_with: 'residue_selection' };
    expect(scopeResidueFilters([sample, residue, paired], 'complex_heatmap')).toEqual([sample]);
    expect(scopeResidueFilters([sample, residue, paired], 'msa')).toHaveLength(3);
  });
});
