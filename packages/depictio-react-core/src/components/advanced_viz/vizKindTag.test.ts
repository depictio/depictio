import { existsSync, readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { taggedVizKinds, vizKindLabel, vizKindTag } from './vizKindTag';

describe('vizKindTag', () => {
  it('names the protein kinds a linked view holds', () => {
    expect(vizKindTag('molecule_3d')).toBe('3D');
    expect(vizKindTag('hmm_logo')).toBe('HMM');
    expect(vizKindTag('msa')).toBe('MSA');
    expect(vizKindTag('sequence_track')).toBe('Track');
    expect(vizKindTag('pae_matrix')).toBe('PAE');
    expect(vizKindTag('secondary_structure')).toBe('SS');
    expect(vizKindTag('ramachandran')).toBe('Rama');
  });

  it('names the allele grid by what its cells hold', () => {
    expect(vizKindLabel('allele_grid')).toMatchObject({
      tag: 'Alleles',
      icon: 'tabler:layout-columns',
    });
    expect(vizKindLabel('allele_grid')?.description).toMatch(/haplotype/);
  });

  it('gives a legacy alias the tag of the kind it became', () => {
    expect(vizKindTag('ancombc_differentials')).toBe(vizKindTag('da_barplot'));
    expect(vizKindLabel('ancombc_differentials')).toEqual(vizKindLabel('da_barplot'));
  });

  it('has no tag for a card of fields, an unknown kind or a non-kind', () => {
    expect(vizKindTag('record_card')).toBeNull();
    expect(vizKindTag('no_such_kind')).toBeNull();
    expect(vizKindTag('')).toBeNull();
    expect(vizKindTag(undefined)).toBeNull();
    expect(vizKindTag(null)).toBeNull();
    expect(vizKindTag(42)).toBeNull();
    expect(vizKindLabel('record_card')).toBeNull();
    expect(vizKindLabel(undefined)).toBeNull();
  });

  it('does not read the prototype chain', () => {
    expect(vizKindTag('constructor')).toBeNull();
    expect(vizKindTag('toString')).toBeNull();
    expect(vizKindLabel('hasOwnProperty')).toBeNull();
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

describe('vizKindLabel', () => {
  it('pairs each tag with an icon', () => {
    expect(vizKindLabel('molecule_3d')).toMatchObject({ tag: '3D', icon: 'tabler:cube-3d-sphere' });
    for (const kind of taggedVizKinds()) {
      expect(vizKindLabel(kind)?.icon, kind).toMatch(/^[a-z][a-z0-9]*:[a-z0-9-]+$/);
    }
  });

  // The badge's tooltip: a protein tile's tag ("SS", "PAE", "Rama") is cryptic
  // to a reader who is not a structural biologist, so each says what it shows.
  const PROTEIN_KINDS = [
    'molecule_3d',
    'hmm_logo',
    'msa',
    'sequence_track',
    'pae_matrix',
    'secondary_structure',
    'ramachandran',
    'domain_architecture',
    'contact_map',
    'fusion_structure',
  ];
  it('describes every protein kind for the badge tooltip', () => {
    for (const kind of PROTEIN_KINDS) {
      const description = vizKindLabel(kind)?.description;
      expect(description, kind).toBeTruthy();
      expect(description, kind).toBe(description!.trim());
    }
  });

  it('keeps every description to one short line without em or en dashes', () => {
    for (const kind of taggedVizKinds()) {
      const description = vizKindLabel(kind)?.description;
      // A kind may go without one (its badge then falls back to the tag).
      if (description === undefined) continue;
      expect(description.length, kind).toBeGreaterThan(0);
      expect(description.length, kind).toBeLessThanOrEqual(90);
      expect(description, kind).not.toMatch(/[\u2013\u2014\n]/);
    }
  });

  it('gives a legacy alias the description of the kind it became', () => {
    expect(vizKindLabel('ancombc_differentials')?.description).toBe(
      vizKindLabel('da_barplot')?.description,
    );
  });

  // The icons are the builder picker's own (KIND_METADATA, served over the
  // wire), repeated here for the tile header: they must not drift apart.
  const schemas = new URL(
    '../../../../../depictio/models/components/advanced_viz/schemas.py',
    import.meta.url,
  );
  it.skipIf(!existsSync(schemas))("matches the builder picker's icon for every kind", () => {
    const source = readFileSync(schemas, 'utf8');
    const registry = source.slice(source.indexOf('KIND_METADATA:'));
    const picker = new Map<string, string>();
    for (const m of registry.matchAll(/^ {4}"([a-z0-9_]+)": \{\n(?:.*\n)*? {8}"icon": "([^"]+)"/gm)) {
      picker.set(m[1], m[2]);
    }
    expect(picker.size).toBeGreaterThan(30);
    for (const kind of taggedVizKinds()) {
      // `ancombc_differentials` is not a picker entry: it is `da_barplot`'s alias.
      const own = kind === 'ancombc_differentials' ? 'da_barplot' : kind;
      expect(vizKindLabel(kind)?.icon, kind).toBe(picker.get(own));
    }
  });
});
