import { describe, expect, it } from 'vitest';

import { tabDisplayName, tabFamilyOf } from './tabFamily';

const main = { dashboard_id: 'm', title: 'TREC study', main_tab_name: 'Overview', tab_order: 0 };
const qc = { dashboard_id: 'q', title: 'Sequencing QC', parent_dashboard_id: 'm', tab_order: 2 };
const alpha = { dashboard_id: 'a', title: 'Alpha Diversity', parent_dashboard_id: 'm', tab_order: 1 };
const other = { dashboard_id: 'o', title: 'Another study' };

describe('tabDisplayName', () => {
  it('names the main tab by its main_tab_name', () => {
    expect(tabDisplayName(main)).toBe('Overview');
    expect(tabDisplayName({ ...main, main_tab_name: undefined })).toBe('TREC study');
  });

  it('names a child tab by its title, never by main_tab_name', () => {
    expect(tabDisplayName({ ...qc, main_tab_name: 'ignored' })).toBe('Sequencing QC');
  });
});

describe('tabFamilyOf', () => {
  const all = [qc, other, alpha, main];

  it('returns the main tab and its children in tab order', () => {
    expect(tabFamilyOf(all, 'q').map((d) => d.dashboard_id)).toEqual(['m', 'a', 'q']);
    expect(tabFamilyOf(all, 'm').map((d) => d.dashboard_id)).toEqual(['m', 'a', 'q']);
  });

  it('is the dashboard alone when it has no tabs', () => {
    expect(tabFamilyOf(all, 'o').map((d) => d.dashboard_id)).toEqual(['o']);
  });

  it('is empty for a dashboard the list does not hold', () => {
    expect(tabFamilyOf(all, 'missing')).toEqual([]);
  });
});
