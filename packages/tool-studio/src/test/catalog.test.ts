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

// A catalog where an id/name collision sits on a *different* tool than the real
// nf-core module match — proves the module-first priority.
const twoToolCatalog: CatalogManifest = {
  tools: [
    { id: 'samtools', name: 'samtools', outputs: [] }, // id collides with the draft below
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
  it('prefers an nf-core module match over an id/name collision on another tool', () => {
    const match = findDuplicateTool(twoToolCatalog, {
      id: 'samtools', // collides with the first tool by id
      nf_core_url:
        'https://github.com/nf-core/modules/tree/master/modules/nf-core/mosdepth',
    });
    expect(match?.reason).toBe('nf-core module');
    expect(match?.tool.id).toBe('mosdepth');
  });
});
