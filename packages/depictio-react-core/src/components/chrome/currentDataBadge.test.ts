/**
 * Which tiles say "Current data" while a past version is on screen.
 *
 * MultiQC, JBrowse, advanced visualisations (record cards included) and the
 * filter funnel never read a data pin. Under a data version or a `?version=`
 * preview they keep drawing today's data, so they are badged; with nothing
 * pinned, a live dashboard shows no badge at all.
 */
import { describe, expect, it } from 'vitest';

import { isCurrentDataOnlyType, showsCurrentDataOnly } from './CurrentDataBadge';

const DC = '646b0f3c1e4a2d7f8e5b9003';

describe('the Current data badge', () => {
  it('covers exactly the types that ignore pins', () => {
    for (const type of ['multiqc', 'jbrowse', 'advanced_viz', 'funnel']) {
      expect(isCurrentDataOnlyType(type)).toBe(true);
    }
    for (const type of ['figure', 'card', 'table', 'interactive', 'image', 'map', 'text', '']) {
      expect(isCurrentDataOnlyType(type)).toBe(false);
    }
    expect(isCurrentDataOnlyType(null)).toBe(false);
    expect(isCurrentDataOnlyType(undefined)).toBe(false);
  });

  it('shows under a preview or an editor as-of', () => {
    expect(showsCurrentDataOnly('multiqc', { asOfVersionId: 'v1', definitionVersionId: 'v1' })).toBe(true);
    expect(showsCurrentDataOnly('advanced_viz', { asOfVersionId: 'v1' })).toBe(true);
  });

  it('shows under a single numeric pin, commit 0 included', () => {
    expect(showsCurrentDataOnly('jbrowse', { pins: { [DC]: 0 } })).toBe(true);
  });

  it('stays hidden on a live dashboard', () => {
    expect(showsCurrentDataOnly('multiqc', {})).toBe(false);
    expect(showsCurrentDataOnly('funnel', { pins: { [DC]: null } })).toBe(false);
  });

  it('never badges a tile that does read the pin', () => {
    expect(showsCurrentDataOnly('figure', { asOfVersionId: 'v1' })).toBe(false);
  });
});
