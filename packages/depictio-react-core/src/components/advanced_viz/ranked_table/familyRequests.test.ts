import { describe, expect, it } from 'vitest';

import type { StoredMetadata } from '../../../api';
import { familyFetchFilters } from './familyRequests';

const metadata = { index: 'rk-top', dc_id: 'dc-ranked' } as unknown as StoredMetadata;
const config = {
  family_dc_id: 'dc-family',
  family_family_col: 'family_id',
  genotypes_dc_id: 'dc-genotypes',
  genotypes_key_col: 'variant_key',
};

describe('familyFetchFilters', () => {
  it('carries the pinned row’s family and variant, and nothing else', () => {
    const { pedigree, genotypes } = familyFetchFilters(config, metadata, {
      family: 'fam1',
      key: '1:100:A:T',
    });
    expect(pedigree).toHaveLength(1);
    expect(pedigree[0].column_name).toBe('family_id');
    expect(pedigree[0].value).toEqual(['fam1']);
    expect(pedigree[0].metadata?.dc_id).toBe('dc-family');
    expect(genotypes).toHaveLength(1);
    expect(genotypes[0].column_name).toBe('variant_key');
    expect(genotypes[0].value).toEqual(['1:100:A:T']);
    expect(genotypes[0].metadata?.dc_id).toBe('dc-genotypes');
  });

  it('sends no filter at all for a table without a family column (every individual)', () => {
    const { pedigree } = familyFetchFilters(
      { ...config, family_family_col: null },
      metadata,
      { family: 'fam1', key: 'k' },
    );
    // A sample picked in the left panel is never in here: the whole pedigree
    // table is read, so the family is not cut down to one person.
    expect(pedigree).toEqual([]);
  });

  it('sends none without a row value to match', () => {
    const out = familyFetchFilters(config, metadata, { family: null, key: null });
    expect(out.pedigree).toEqual([]);
    expect(out.genotypes).toEqual([]);
  });
});
