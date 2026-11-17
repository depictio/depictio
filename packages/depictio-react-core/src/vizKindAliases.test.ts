import { describe, expect, it } from 'vitest';
import { canonicalVizKind, canonicalizeVizKinds } from './vizKindAliases';

describe('canonicalVizKind', () => {
  it('maps a renamed kind to its current name and leaves others alone', () => {
    expect(canonicalVizKind('stacked_taxonomy')).toBe('stacked_bar');
    expect(canonicalVizKind('stacked_bar')).toBe('stacked_bar');
    expect(canonicalVizKind('volcano')).toBe('volcano');
  });
});

describe('canonicalizeVizKinds', () => {
  it('rewrites a tile and its config wherever they sit in a response', () => {
    const response = {
      stored_metadata: [
        { component_type: 'advanced_viz', viz_kind: 'stacked_taxonomy', config: { viz_kind: 'stacked_taxonomy', taxon_col: 't' } },
        { component_type: 'advanced_viz', viz_kind: 'volcano', config: { viz_kind: 'volcano' } },
      ],
      floating: [{ metadata: { viz_kind: 'stacked_taxonomy' } }],
    };
    const out = canonicalizeVizKinds(response);
    expect(out).toBe(response);
    expect(response.stored_metadata[0].viz_kind).toBe('stacked_bar');
    expect(response.stored_metadata[0].config.viz_kind).toBe('stacked_bar');
    expect(response.stored_metadata[0].config.taxon_col).toBe('t');
    expect(response.stored_metadata[1].viz_kind).toBe('volcano');
    expect(response.floating[0].metadata.viz_kind).toBe('stacked_bar');
  });

  it('passes scalars and null through', () => {
    expect(canonicalizeVizKinds(null)).toBeNull();
    expect(canonicalizeVizKinds('stacked_taxonomy')).toBe('stacked_taxonomy');
  });
});
