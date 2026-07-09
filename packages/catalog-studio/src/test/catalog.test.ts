import { describe, it, expect } from 'vitest';
import { findDuplicateTool, type CatalogManifest } from '../catalog/catalog';

const catalog: CatalogManifest = {
  tools: [
    {
      id: 'mosdepth',
      name: 'mosdepth',
      nf_core_url: 'https://github.com/nf-core/modules/tree/master/modules/nf-core/mosdepth',
      outputs: [],
    },
  ],
};

describe('findDuplicateTool', () => {
  it('matches by id', () => {
    expect(findDuplicateTool(catalog, { id: 'mosdepth' })?.reason).toBe('id');
  });
  it('matches by name (case-insensitive)', () => {
    expect(findDuplicateTool(catalog, { name: 'MOSDEPTH' })?.reason).toBe('name');
  });
  it('matches by nf-core module even when the draft URL points at meta.yml', () => {
    const match = findDuplicateTool(catalog, {
      id: 'mos',
      nf_core_url:
        'https://github.com/nf-core/modules/blob/master/modules/nf-core/mosdepth/meta.yml',
    });
    expect(match?.reason).toBe('nf-core module');
  });
  it('returns null for a genuinely new tool', () => {
    expect(findDuplicateTool(catalog, { id: 'novel', name: 'Novel' })).toBeNull();
  });
});
