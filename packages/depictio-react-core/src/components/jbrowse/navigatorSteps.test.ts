import { describe, expect, it } from 'vitest';

import type { JBrowseCall } from '../../api';
import type { NamedLocusSource } from './locusSources';
import {
  cellValue,
  formatCount,
  gridFiltersToBody,
  gridSortToBody,
  navigatorCaption,
  nearQuery,
  normalizeEnabledSources,
  parseStoredSources,
  pickerColumns,
  pickerRequest,
  regionCountLabel,
  regionNoun,
  sourceColorVar,
  sourcesBody,
  sourcesStorageKey,
  versionFields,
  withNumericExtras,
  type PickerColumn,
} from './navigatorSteps';

const order = ['chr1', 'chr2', 'chrX'];
const src = (over: Partial<NamedLocusSource> = {}): NamedLocusSource => ({
  name: 'peaks',
  data_collection_tag: 'peaks',
  ...over,
});

describe('nearQuery', () => {
  it('anchors next on the right edge and previous on the left edge of the view', () => {
    const visible = [{ refName: 'chr2', start: 999, end: 2000 }];
    expect(nearQuery(1, visible, order)).toEqual({
      chrom: 'chr2',
      pos: 2000,
      direction: 1,
      chrom_order: order,
    });
    // 0-based start 999 is the 1-based base 1000
    expect(nearQuery(-1, visible, order)).toEqual({
      chrom: 'chr2',
      pos: 1000,
      direction: -1,
      chrom_order: order,
    });
  });

  it('takes the last visible region for next and the first for previous', () => {
    const visible = [
      { refName: 'chr1', start: 0, end: 100 },
      { refName: 'chr2', start: 50, end: 150 },
    ];
    expect(nearQuery(1, visible, order)?.chrom).toBe('chr2');
    expect(nearQuery(-1, visible, order)?.chrom).toBe('chr1');
  });

  it('is null when nothing is visible or the span is unreadable', () => {
    expect(nearQuery(1, [], order)).toBeNull();
    expect(nearQuery(1, [{ refName: '', start: 0, end: 5 }], order)).toBeNull();
    expect(nearQuery(1, [{ refName: 'chr1', start: NaN, end: 5 }], order)).toBeNull();
  });

  it('does not alias the caller chromosome order', () => {
    const q = nearQuery(1, [{ refName: 'chr1', start: 0, end: 5 }], order);
    expect(q?.chrom_order).not.toBe(order);
  });
});

describe('labels', () => {
  it('formats the count and pluralises the badge', () => {
    expect(formatCount(224312)).toBe('224,312');
    expect(formatCount(-4)).toBe('0');
    expect(regionCountLabel(224312)).toBe('224,312 regions');
    expect(regionCountLabel(1)).toBe('1 region');
    expect(regionCountLabel(209314, 'peak')).toBe('209,314 peaks');
    expect(regionCountLabel(3, 'consensus')).toBe('3 consensus');
  });

  it('names a region after its source', () => {
    expect(regionNoun(['Peaks'])).toBe('peak');
    expect(regionNoun(['Consensus'])).toBe('consensus');
    expect(regionNoun(['Genes', 'Peaks'])).toBe('region');
    expect(regionNoun([])).toBe('region');
    expect(regionNoun(['variants_long'])).toBe('region');
  });

  it('captions a region with its label, else its locus, and the merged sample count', () => {
    const base: JBrowseCall = { locus: 'chr1:5-9', mate_locus: null, label: null };
    expect(navigatorCaption(null)).toBeNull();
    expect(navigatorCaption(base)).toBe('chr1:5-9');
    expect(navigatorCaption({ ...base, label: ' BRCA1 ' })).toBe('BRCA1');
    expect(navigatorCaption({ ...base, n_samples: 1 })).toBe('chr1:5-9');
    expect(navigatorCaption({ ...base, label: 'BRCA1', n_samples: 6 })).toBe('BRCA1 · 6 samples');
    expect(navigatorCaption({ ...base, locus: null })).toBeNull();
  });
});

describe('sources', () => {
  const names = ['peaks', 'de', 'snv'];

  it('steps through one source: the stored one the tile still has, else its first', () => {
    expect(normalizeEnabledSources(['de', 'gone'], names)).toEqual(['de']);
    expect(normalizeEnabledSources(['gone'], names)).toEqual(['peaks']);
    expect(normalizeEnabledSources([], names)).toEqual(['peaks']);
    expect(normalizeEnabledSources(null, names)).toEqual(['peaks']);
    expect(normalizeEnabledSources(null, [])).toEqual([]);
  });

  it('keeps one of several stored names, in the tile order', () => {
    expect(normalizeEnabledSources(['snv', 'peaks'], names)).toEqual(['peaks']);
  });

  it('parses the stored JSON defensively', () => {
    expect(parseStoredSources('["a","b"]')).toEqual(['a', 'b']);
    expect(parseStoredSources('["a",3]')).toEqual(['a']);
    expect(parseStoredSources('{"a":1}')).toBeNull();
    expect(parseStoredSources('not json')).toBeNull();
    expect(parseStoredSources(null)).toBeNull();
  });

  it('asks the backend for all sources with null', () => {
    expect(sourcesBody(names, names)).toBeNull();
    expect(sourcesBody(['de'], names)).toEqual(['de']);
  });

  it('keys the storage per tile and reads the palette as a Mantine variable', () => {
    expect(sourcesStorageKey('abc')).toBe('depictio.jbrowse.abc.sources');
    expect(sourceColorVar('teal')).toBe('var(--mantine-color-teal-6)');
    expect(sourceColorVar(' ')).toBeNull();
    expect(sourceColorVar(null)).toBeNull();
  });

  it('forwards only the pins of the version body', () => {
    expect(versionFields({})).toEqual({});
    expect(versionFields({ as_of_version: 'v1', other: 1 })).toEqual({ as_of_version: 'v1' });
    expect(versionFields({ data_versions: { a: 2 } })).toEqual({ data_versions: { a: 2 } });
  });
});

describe('pickerColumns', () => {
  const single = [src({ sort_by: 'score', sample_column: 'sample', label_column: 'gene' })];
  const ids = (cols: ReturnType<typeof pickerColumns>) => cols.map((c) => c.id);

  it('lists the rows columns of one source, headed by the sort_by name', () => {
    const cols = pickerColumns({ sources: single, merged: false });
    expect(ids(cols)).toEqual(['label', 'locus', 'score', 'sample']);
    expect(cols.find((c) => c.id === 'score')?.header).toBe('score');
    expect(cols.find((c) => c.id === 'score')?.sortColumn).toBe('score');
    expect(cols.find((c) => c.id === 'label')?.sortColumn).toBe('gene');
  });

  it('adds source and the extras when there are several sources', () => {
    const sources = [
      src({ columns: ['gene'], run_column: 'run', sort_by: 'fc' }),
      src({ name: 'de', color: 'red', columns: ['gene', 'padj'] }),
    ] as NamedLocusSource[];
    const cols = pickerColumns({ sources, merged: false, scoreLabel: 'log2FC' });
    expect(ids(cols)).toEqual([
      'label',
      'locus',
      'score',
      'run',
      'source',
      'extra:gene',
      'extra:padj',
    ]);
    expect(cols.find((c) => c.id === 'score')?.header).toBe('log2FC');
    expect(cols.find((c) => c.id === 'source')?.sortColumn).toBeNull();
  });

  it('merged mode sorts only chrom, score and n_samples', () => {
    const cols = pickerColumns({ sources: single, merged: true });
    expect(ids(cols)).toEqual(['label', 'locus', 'score', 'n_samples', 'samples']);
    const sortable = Object.fromEntries(cols.map((c) => [c.id, c.sortColumn]));
    expect(sortable).toEqual({
      label: null,
      locus: 'chrom',
      score: 'score',
      n_samples: 'n_samples',
      samples: null,
    });
    const multi = pickerColumns({ sources: [src(), src({ name: 'de' })], merged: true });
    expect(ids(multi)).toContain('sources');
  });

  it('has no columns without a source and no score column without sort_by', () => {
    expect(pickerColumns({ sources: [], merged: true })).toEqual([]);
    expect(ids(pickerColumns({ sources: [src()], merged: false }))).toEqual(['label', 'locus']);
  });
});

describe('grid sort and requests', () => {
  const cols = pickerColumns({
    sources: [src({ sort_by: 'score', sample_column: 'sample' })],
    merged: false,
  });

  it('maps the sort model to the backend column and direction', () => {
    expect(gridSortToBody([{ colId: 'score', sort: 'desc' }], cols)).toEqual({
      column: 'score',
      descending: true,
    });
    expect(gridSortToBody([{ colId: 'locus', sort: 'asc' }], cols)).toEqual({
      column: 'chrom',
      descending: false,
    });
  });

  it('leaves the order to the backend when nothing sortable is sorted', () => {
    expect(gridSortToBody([], cols)).toBeNull();
    expect(gridSortToBody([{ colId: 'score', sort: null }], cols)).toBeNull();
    expect(gridSortToBody([{ colId: 'nope', sort: 'asc' }], cols)).toBeNull();
    const merged = pickerColumns({ sources: [src()], merged: true });
    expect(gridSortToBody([{ colId: 'samples', sort: 'asc' }], merged)).toBeNull();
  });

  it('builds one block request', () => {
    const body = pickerRequest({
      filters: [],
      versionBody: { as_of_version: 'v2' },
      startRow: 100,
      endRow: 150,
      sortModel: [{ colId: 'score', sort: 'asc' }],
      columns: cols,
      search: '  brca ',
      sources: ['de'],
      merged: true,
    });
    expect(body).toEqual({
      filters: [],
      start: 100,
      limit: 50,
      sort: { column: 'score', descending: false },
      search: 'brca',
      sources: ['de'],
      merge: true,
      as_of_version: 'v2',
    });
  });

  it('caps the block at the endpoint limit and drops an empty search', () => {
    const body = pickerRequest({
      filters: [],
      versionBody: {},
      startRow: 0,
      endRow: 1000,
      sortModel: [],
      columns: cols,
      search: '   ',
      sources: null,
      merged: false,
    });
    expect(body.limit).toBe(200);
    expect(body.search).toBeNull();
    expect(body.sort).toBeNull();
    expect(body.sources).toBeNull();
    expect(body.merge).toBe(false);
  });
});

describe('cellValue', () => {
  const call: JBrowseCall = {
    locus: 'chr1:5-9',
    mate_locus: null,
    label: null,
    score: 3.2,
    source: 'peaks',
    sample: 's1',
    run: 'r1',
    extra: { gene: 'TP53' },
    n_samples: 12,
    samples: ['a', 'b'],
    sources: ['peaks', 'de'],
  };

  it('reads each column', () => {
    expect(cellValue(call, 'label')).toBe('peaks');
    expect(cellValue({ ...call, label: 'X' }, 'label')).toBe('X');
    expect(cellValue(call, 'locus')).toBe('chr1:5-9');
    expect(cellValue(call, 'score')).toBe(3.2);
    expect(cellValue(call, 'sample')).toBe('s1');
    expect(cellValue(call, 'run')).toBe('r1');
    expect(cellValue(call, 'source')).toBe('peaks');
    expect(cellValue(call, 'n_samples')).toBe(12);
    expect(cellValue(call, 'samples')).toBe('a, b +10');
    expect(cellValue(call, 'sources')).toBe('peaks, de');
    expect(cellValue(call, 'extra:gene')).toBe('TP53');
    expect(cellValue(call, 'extra:missing')).toBe('');
  });

  it('is empty for a row that has not loaded', () => {
    expect(cellValue(undefined, 'locus')).toBe('');
  });
});

describe('picker column filters', () => {
  const cols = [
    { id: 'label', header: 'Region', sortColumn: null, filter: { column: 'label', kind: 'text' }, width: 1 },
    { id: 'score', header: 'q', sortColumn: 'score', filter: { column: 'score', kind: 'number' }, width: 1 },
    { id: 'samples', header: 'Samples', sortColumn: null, width: 1 },
    { id: 'extra:width', header: 'width', sortColumn: 'width', filter: { column: 'width', kind: 'text' }, width: 1 },
  ] as PickerColumn[];

  it('maps AG Grid conditions onto the backend filters', () => {
    expect(
      gridFiltersToBody(
        {
          label: { filterType: 'text', type: 'contains', filter: 'Peak_1' },
          score: { filterType: 'number', type: 'inRange', filter: 2, filterTo: 5 },
          samples: { filterType: 'text', type: 'contains', filter: 'x' },
        },
        cols,
      ),
    ).toEqual([
      { column: 'label', kind: 'text', op: 'contains', value: 'Peak_1' },
      { column: 'score', kind: 'number', op: 'inRange', value: 2, value_to: 5 },
    ]);
  });

  it('leaves out an emptied box and a range without its end', () => {
    expect(
      gridFiltersToBody(
        {
          label: { filterType: 'text', type: 'contains', filter: '' },
          score: { filterType: 'number', type: 'inRange', filter: 2 },
        },
        cols,
      ),
    ).toEqual([]);
    expect(gridFiltersToBody(null, cols)).toEqual([]);
  });

  it('filters an extra column as numbers when its loaded cells are numbers', () => {
    const row = (width: unknown) => ({ extra: { width } }) as unknown as JBrowseCall;
    const numeric = withNumericExtras(cols, [row(120), row('85'), row(null)]);
    expect(numeric.find((c) => c.id === 'extra:width')?.filter?.kind).toBe('number');
    const text = withNumericExtras(cols, [row(120), row('wide')]);
    expect(text.find((c) => c.id === 'extra:width')?.filter?.kind).toBe('text');
  });
});
