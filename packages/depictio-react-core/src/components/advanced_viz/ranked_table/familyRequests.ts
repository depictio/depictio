/**
 * The filters the Family section's two reads carry.
 *
 * Only the pinned row's own key: its family on the pedigree table, its variant
 * on the long genotype table. The dashboard's filters are never sent, so a
 * sample picked in the left panel (or a funnel narrowing the ranking) cannot
 * shrink the pedigree to that one person: the family is the family whatever
 * the page is filtered to, and the section says who of it carries the variant.
 * The server adds only the links that resolve *these* filters.
 */
import type { InteractiveFilter, StoredMetadata } from '../../../api';
import { advancedVizSelectionFilter } from '../../../selection';

/** The part of the section's config these filters read. */
export interface FamilyFilterConfig {
  family_dc_id?: string | null;
  family_family_col?: string | null;
  genotypes_dc_id?: string | null;
  genotypes_key_col: string;
}

/** The pinned row's values the filters match against. */
export interface FamilyFilterRow {
  family: string | null;
  key: string | null;
}

function valueFilter(
  metadata: StoredMetadata,
  dcId: string,
  column: string,
  value: string,
  tag: string,
): InteractiveFilter {
  const base = advancedVizSelectionFilter(metadata, column, [value]);
  return {
    ...base,
    index: `${String(metadata.index)}::${tag}`,
    metadata: { ...base.metadata, dc_id: dcId },
  };
}

export function familyFetchFilters(
  config: FamilyFilterConfig,
  metadata: StoredMetadata,
  row: FamilyFilterRow,
): { pedigree: InteractiveFilter[]; genotypes: InteractiveFilter[] } {
  return {
    pedigree:
      config.family_dc_id && config.family_family_col && row.family
        ? [valueFilter(metadata, config.family_dc_id, config.family_family_col, row.family, 'family')]
        : [],
    genotypes:
      config.genotypes_dc_id && row.key
        ? [valueFilter(metadata, config.genotypes_dc_id, config.genotypes_key_col, row.key, 'genotypes')]
        : [],
  };
}
