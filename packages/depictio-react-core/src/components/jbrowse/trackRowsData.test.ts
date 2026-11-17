import { describe, expect, it } from 'vitest';

import type { JBrowseTrackRow } from '../../api';
import { trackRowsToColumns } from './trackRowsData';

const row = (over: Partial<JBrowseTrackRow>): JBrowseTrackRow => ({
  track_id: 't',
  name: 'T',
  format: 'bam',
  sample: null,
  selection_value: null,
  ...over,
});

describe('trackRowsToColumns', () => {
  it('transposes the tracks into one array per column', () => {
    const { rows, columns } = trackRowsToColumns([
      row({ track_id: 'a', name: 'A', sample: 'S1', category: 'RNA' }),
      row({ track_id: 'b', name: 'B', sample: 'S2', category: null }),
    ]);
    expect(columns).toEqual(['Track', 'Format', 'Sample', 'Category', 'Track id']);
    expect(rows.Track).toEqual(['A', 'B']);
    expect(rows.Sample).toEqual(['S1', 'S2']);
    expect(rows.Category).toEqual(['RNA', null]);
  });
  it('leaves out a column no track fills', () => {
    const { columns } = trackRowsToColumns([row({}), row({ track_id: 'u' })]);
    expect(columns).not.toContain('Sample');
    expect(columns).not.toContain('File');
  });
  it('is empty for no tracks', () => {
    expect(trackRowsToColumns([])).toEqual({ rows: {}, columns: [] });
  });
});
