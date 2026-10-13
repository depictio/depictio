import { describe, expect, it } from 'vitest';

import type { StoredMetadata } from './api';
import { multiqcDcIds, normaliseSpecs, specsHaveColumn } from './dcSpecs';

describe('normaliseSpecs', () => {
  it('keeps the list shape', () => {
    const specs = [{ name: 'sample', type: 'object', specs: { nunique: 3 } }];
    expect(normaliseSpecs(specs)).toEqual(specs);
  });

  it('turns the legacy dict shape into a list', () => {
    expect(normaliseSpecs({ reads: { type: 'int64', min: 1 } })).toEqual([
      { name: 'reads', type: 'int64', specs: { type: 'int64', min: 1 } },
    ]);
  });

  it('yields nothing for junk', () => {
    expect(normaliseSpecs(null)).toEqual([]);
    expect(normaliseSpecs('x')).toEqual([]);
  });
});

describe('specsHaveColumn', () => {
  const specs = [{ name: 'sample' }, { name: 'reads' }];
  it('matches listed columns only', () => {
    expect(specsHaveColumn(specs, 'sample')).toBe(true);
    expect(specsHaveColumn(specs, 'condition')).toBe(false);
  });
  it('treats unavailable specs as "column absent"', () => {
    expect(specsHaveColumn(null, 'sample')).toBe(false);
  });
});

describe('multiqcDcIds', () => {
  it('flags a DC bound to any multiqc component', () => {
    const md = [
      { index: '1', component_type: 'card', dc_id: 'mq' },
      { index: '2', component_type: 'multiqc', dc_id: 'mq' },
      { index: '3', component_type: 'table', dc_id: 'tbl' },
      { index: '4', component_type: 'multiqc' },
    ] as StoredMetadata[];
    expect(Array.from(multiqcDcIds(md))).toEqual(['mq']);
    expect(multiqcDcIds(undefined).size).toBe(0);
  });
});
