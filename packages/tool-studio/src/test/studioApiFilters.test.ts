/**
 * The offline api shim applies dashboard filters the way the exported
 * serverless dashboard (and the server) do: bound by depictio-static-core's
 * `bindFilters`, masked by its engine over the fixture (`frameEngine.ts`),
 * aggregated by its kernels.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { InteractiveFilter } from 'depictio-react-core/api';
import { parseFixture } from '../catalog/parseFixture';
import { aggregate } from '../api/aggregations';
import { buildFrame } from '../api/frame';
import { frameEngine, frameTable } from '../api/frameEngine';
import {
  registerComponent,
  setActiveFixture,
  unregisterComponent,
} from '../api/fixtureRegistry';
import {
  bulkComputeCards,
  fetchAdvancedVizData,
  fetchCardHeroValue,
  fetchUniqueValues,
  previewFigure,
  renderTable,
  toBoundFilters,
} from '../api/studioApi';

// The e2e golden fixture: 8 genes over 3 samples.
const GOLDEN = [
  'gene,log2fc,pvalue,sample,coverage',
  'BRCA1,2.4,0.0001,S1,120',
  'TP53,-1.8,0.002,S1,98',
  'EGFR,0.3,0.4,S1,150',
  'MYC,3.1,0.00005,S2,80',
  'PTEN,-2.2,0.0008,S2,110',
  'KRAS,1.1,0.03,S2,95',
  'ALK,-0.2,0.6,S3,130',
  'RB1,2.9,0.0002,S3,105',
].join('\n');

const pick = (column: string, value: string[]): InteractiveFilter => ({
  index: 'flt',
  value,
  column_name: column,
  interactive_component_type: 'MultiSelect',
  metadata: { dc_id: 'studio', column_name: column, interactive_component_type: 'MultiSelect' },
});

describe('filters reach the previews', () => {
  beforeEach(() => {
    setActiveFixture(parseFixture('golden.csv', GOLDEN));
    registerComponent({
      index: 'card-1',
      component_type: 'card',
      column_name: 'coverage',
      aggregation: 'sum',
      aggregations: ['count'],
      secondary_layout: 'top_n',
      breakdown_col: 'sample',
    });
    registerComponent({ index: 'table-1', component_type: 'table' });
  });
  afterEach(() => {
    unregisterComponent('card-1');
    unregisterComponent('table-1');
    setActiveFixture(null);
  });

  it('a MultiSelect narrows a card value and its secondary strip', async () => {
    const all = await bulkComputeCards('d', [], ['card-1']);
    expect(all.values['card-1']).toBe(888);
    expect(all.filter_applied).toBe(false);

    const s2 = await bulkComputeCards('d', [pick('sample', ['S2'])], ['card-1']);
    expect(s2.values['card-1']).toBe(80 + 110 + 95);
    expect(s2.filter_applied).toBe(true);
    expect(s2.filter_count).toBe(1);
    expect(s2.secondary_values!['card-1'].count).toBe(3);
    const breakdown = s2.secondary_values!['card-1'].__breakdown__ as {
      top: { name: string }[];
      unique_values: number;
    };
    expect(breakdown.unique_values).toBe(1);
    expect(breakdown.top[0].name).toBe('S2');

    expect(await fetchCardHeroValue('dc', 'coverage', 'count', [pick('sample', ['S1', 'S3'])])).toBe(5);
  });

  it('an empty selection is no filter at all', async () => {
    const res = await bulkComputeCards('d', [pick('sample', [])], ['card-1']);
    expect(res.values['card-1']).toBe(888);
    expect(res.filter_applied).toBe(false);
  });

  it('a filter narrows a table page; total is the filtered count', async () => {
    const page = await renderTable('d', 'table-1', [pick('sample', ['S1'])], 0, 2, 'coverage', 'desc');
    expect(page.total).toBe(3);
    expect(page.rows.map((r) => r.gene)).toEqual(['EGFR', 'BRCA1']);
    const next = await renderTable('d', 'table-1', [pick('sample', ['S1'])], 2, 2, 'coverage', 'desc');
    expect(next.rows.map((r) => r.gene)).toEqual(['TP53']);
    const unfiltered = await renderTable('d', 'table-1', [], 0, 100);
    expect(unfiltered.total).toBe(8);
    expect(unfiltered.rows[0].gene).toBe('BRCA1'); // natural order without a sort
  });

  it('a RangeSlider is inclusive on both ends', async () => {
    const range: InteractiveFilter = {
      index: 'r',
      value: [95, 110],
      column_name: 'coverage',
      interactive_component_type: 'RangeSlider',
    };
    const page = await renderTable('d', 'table-1', [range], 0, 100, 'coverage', 'asc');
    expect(page.rows.map((r) => r.coverage)).toEqual([95, 98, 105, 110]);
  });

  it('figures and advanced-viz rows see only the kept rows', async () => {
    const fig = await previewFigure({
      metadata: { visu_type: 'scatter', dict_kwargs: { x: 'log2fc', y: 'coverage' } },
      filters: [pick('sample', ['S3'])],
    });
    const points = (fig.figure.data as { x?: unknown[] }[]).reduce((n, t) => n + (t.x?.length ?? 0), 0);
    expect(points).toBe(2);
    expect(fig.metadata.filter_applied).toBe(true);

    const viz = await fetchAdvancedVizData({
      wfId: 'w',
      dcId: 'dc',
      columns: ['gene', 'pvalue'],
      filters: [pick('sample', ['S2'])],
    });
    expect(viz.rows.gene).toEqual(['MYC', 'PTEN', 'KRAS']);
    expect(viz.total_rows).toBe(3);
    expect(viz.filter_applied).toBe(true);
  });

  it('control options stay the whole collection', async () => {
    expect(await fetchUniqueValues('dc', 'sample')).toEqual(['S1', 'S2', 'S3']);
  });
});

describe('aggregation parity with depictio-static-core', () => {
  // Nulls on purpose: the unfiltered (precomputed spec) and filtered
  // (`_agg_value`) server paths disagree on exactly those.
  const fixture = parseFixture(
    'parity.csv',
    ['grp,x,label', 'a,1,p', 'a,2,q', 'a,,', 'a,10,q', 'b,7,r', 'b,,r'].join('\n'),
  );
  const frame = buildFrame(fixture);
  const mask = async (value: string[]) =>
    (await frameEngine.mask(frameEngine.openFrame(frame), [{ kind: 'in', column: 'grp', values: value }])).mask;

  it('types columns the way hyparquet decodes them', () => {
    const { columns } = frameTable(frame);
    expect(Array.isArray(columns.x)).toBe(true); // has nulls → plain array
    expect(columns.x[2]).toBeNull();
    expect(columns.grp).toEqual(['a', 'a', 'a', 'a', 'b', 'b']);
  });

  it('median interpolates, std is the sample statistic', async () => {
    const a = await mask(['a']);
    expect(aggregate(frame, 'x', 'median', a)).toBe(2); // [1, 2, 10]
    expect(aggregate(frame, 'x', 'median')).toBe(4.5); // [1, 2, 7, 10]
    expect(aggregate(frame, 'x', 'std_dev', a)).toBeCloseTo(4.9328828623, 9);
    expect(aggregate(frame, 'x', 'std_dev', await mask(['b']))).toBeNull(); // one value
    expect(aggregate(frame, 'x', 'variance')).toBeCloseTo(18, 9); // mean 5, ssd 54, n-1 = 3
  });

  it('nunique: the precomputed spec drops nulls, the filtered path counts one', async () => {
    expect(aggregate(frame, 'label', 'nunique')).toBe(3);
    // `_agg_value` → `n_unique()`: null is a distinct value.
    expect(aggregate(frame, 'label', 'nunique', await mask(['a']))).toBe(3); // p, q, null
    expect(aggregate(frame, 'label', 'nunique', await mask(['a', 'b']))).toBe(4);
    expect(aggregate(frame, 'x', 'count', await mask(['a']))).toBe(3);
    expect(aggregate(frame, 'x', 'sum', await mask(['zz']))).toBe(0); // empty numeric sum
  });
});

describe('companions the bundle producer writes', () => {
  const parsed = parseFixture(
    'typed.csv',
    ['day,ok,v', '2024-01-01,true,1', '2024-01-05,false,2', '2024-01-09,true,3', ',,4'].join('\n'),
  );
  // Declared, not inferred: inference keeps ISO dates as String like polars.
  const frame = buildFrame({
    ...parsed,
    columns: parsed.columns.map((c) =>
      c.name === 'day' ? { ...c, dtype: 'Datetime' as const } : c.name === 'ok' ? { ...c, dtype: 'Boolean' as const } : c,
    ),
  });
  const h = frameEngine.openFrame(frame);
  const kept = async (filters: InteractiveFilter[]) => {
    const { mask } = await frameEngine.mask(h, toBoundFilters(filters));
    return [...mask];
  };

  it('a DateRangePicker compares the __ts__ companion, both ends inclusive', async () => {
    expect(
      await kept([{ index: 'd', value: ['2024-01-05', '2024-01-09'], column_name: 'day', interactive_component_type: 'DateRangePicker' }]),
    ).toEqual([0, 1, 1, 0]);
  });

  it('a Select on a Boolean column goes through its codebook', async () => {
    expect(
      await kept([{ index: 'b', value: ['true'], column_name: 'ok', interactive_component_type: 'Select' }]),
    ).toEqual([1, 0, 1, 0]);
  });
});
