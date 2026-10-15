import { describe, expect, it } from 'vitest';

import { taggedVizKinds, vizKindTag } from './vizKindTag';

describe('vizKindTag', () => {
  it('names the protein kinds a workbench holds', () => {
    expect(vizKindTag('molecule_3d')).toBe('3D');
    expect(vizKindTag('hmm_logo')).toBe('HMM');
    expect(vizKindTag('msa')).toBe('MSA');
    expect(vizKindTag('sequence_track')).toBe('Track');
    expect(vizKindTag('pae_matrix')).toBe('PAE');
    expect(vizKindTag('secondary_structure')).toBe('SS');
    expect(vizKindTag('ramachandran')).toBe('Rama');
  });

  it('gives a legacy alias the tag of the kind it became', () => {
    expect(vizKindTag('ancombc_differentials')).toBe(vizKindTag('da_barplot'));
  });

  it('has no tag for a card of fields, an unknown kind or a non-kind', () => {
    expect(vizKindTag('record_card')).toBeNull();
    expect(vizKindTag('no_such_kind')).toBeNull();
    expect(vizKindTag('')).toBeNull();
    expect(vizKindTag(undefined)).toBeNull();
    expect(vizKindTag(null)).toBeNull();
    expect(vizKindTag(42)).toBeNull();
  });

  it('does not read the prototype chain', () => {
    expect(vizKindTag('constructor')).toBeNull();
    expect(vizKindTag('toString')).toBeNull();
  });

  it('keeps every tag short enough for the one-line compact header', () => {
    for (const kind of taggedVizKinds()) {
      const tag = vizKindTag(kind);
      expect(tag, kind).toBeTruthy();
      expect(tag!.length, kind).toBeLessThanOrEqual(12);
      expect(tag, kind).toBe(tag!.trim());
    }
  });
});
