import { describe, expect, it } from 'vitest';

import {
  abundanceRankCoverage,
  phyloSourcePatch,
  preferredTipMetadata,
  tipLabelColumn,
  type PhyloDcRef,
} from './sources';

const tree: PhyloDcRef = {
  wfId: 'wf1',
  dcId: 'tree',
  tag: 'phylogenetic_tree_canonical',
  type: 'phylogeny',
  metadataTag: 'tree_metadata',
  metadataTaxonColumn: 'taxon',
};
const tables: PhyloDcRef[] = [
  { wfId: 'wf1', dcId: 'samples', tag: 'metadata', type: 'table' },
  { wfId: 'wf2', dcId: 'tips-elsewhere', tag: 'tree_metadata', type: 'table' },
  { wfId: 'wf1', dcId: 'tips', tag: 'tree_metadata', type: 'table' },
  { wfId: 'wf1', dcId: 'reads', tag: 'taxonomy_rel_abundance', type: 'table' },
];

describe('phyloSourcePatch', () => {
  it('writes the ids and the tag under the keys a YAML uses', () => {
    expect(phyloSourcePatch('abundance', tables[3], 'wf1')).toEqual({
      abundance_wf_id: 'wf1',
      abundance_dc_id: 'reads',
      abundance_dc_tag: 'taxonomy_rel_abundance',
    });
  });

  it('binds a DC of another workflow by id alone', () => {
    // The import resolves a tag in the component's own workflow only.
    expect(phyloSourcePatch('metadata', tables[1], 'wf1')).toEqual({
      metadata_wf_id: 'wf2',
      metadata_dc_id: 'tips-elsewhere',
      metadata_dc_tag: null,
    });
  });

  it('unbinds all three keys, the tag included', () => {
    expect(phyloSourcePatch('abundance', null, 'wf1')).toEqual({
      abundance_wf_id: null,
      abundance_dc_id: null,
      abundance_dc_tag: null,
    });
  });
});

describe('tipLabelColumn', () => {
  it('takes the column the tree declares', () => {
    expect(tipLabelColumn(['label', 'asv_id'], 'asv_id')).toBe('asv_id');
  });

  it('falls back on the usual names, taxon first', () => {
    expect(tipLabelColumn(['name', 'Kingdom', 'Taxon'], 'missing')).toBe('Taxon');
    expect(tipLabelColumn(['sample', 'rel_abundance'])).toBeNull();
  });
});

describe('preferredTipMetadata', () => {
  it('takes the table the tree names, in its own workflow', () => {
    expect(preferredTipMetadata(tables, { tree })).toBe('tips');
  });

  it('else the component’s own table', () => {
    expect(preferredTipMetadata(tables, { tree: { ...tree, metadataTag: null }, bound: tables[0] })).toBe(
      'samples',
    );
  });

  it('else the first table with a tip-label column', () => {
    const columns = {
      samples: ['sample', 'site'],
      'tips-elsewhere': ['taxon', 'Phylum'],
      tips: ['taxon', 'Phylum'],
    };
    expect(preferredTipMetadata(tables, { columns })).toBe('tips-elsewhere');
    expect(preferredTipMetadata(tables, {})).toBeNull();
  });
});

describe('abundanceRankCoverage', () => {
  it('splits the ranks by whether the table has a column of that name', () => {
    expect(
      abundanceRankCoverage(['Kingdom', 'Phylum', 'Class'], ['sample', 'Kingdom', 'Phylum']),
    ).toEqual({ joined: ['Kingdom', 'Phylum'], missing: ['Class'] });
  });
});
