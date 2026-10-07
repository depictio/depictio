import { describe, expect, it } from 'vitest';

import type { GroupRenderDef } from '../../../selectionGroups';
import {
  configuredGroupPair,
  defaultGroupPair,
  groupCompareOptions,
  LABEL_VALUE_SOURCE,
  resolveGroupDefault,
  SAVED_GROUP_SOURCE,
  selectorFor,
} from './groupOptions';

const saved: GroupRenderDef[] = [
  { name: 'Lasso A', column_name: 'cell_id', values: ['c1', 'c2'], color: '#000' },
  { name: 'Lasso B', column_name: 'cell_id', values: ['c3'], color: '#111' },
];

describe('groupCompareOptions', () => {
  it('collapses a saved group into a row selector', () => {
    const [first] = groupCompareOptions(saved, null, []);
    expect(first.source).toBe(SAVED_GROUP_SOURCE);
    expect(first.selector).toEqual({
      label: 'Lasso A',
      column: 'cell_id',
      values: ['c1', 'c2'],
    });
  });

  it('collapses one value of the label column into the same shape', () => {
    const options = groupCompareOptions([], 'cluster', ['cluster_1', 'cluster_2']);
    expect(options.map((o) => o.source)).toEqual([LABEL_VALUE_SOURCE, LABEL_VALUE_SOURCE]);
    expect(options[1].selector).toEqual({
      label: 'cluster_2',
      column: 'cluster',
      values: ['cluster_2'],
    });
  });

  it('offers saved groups before label values', () => {
    const options = groupCompareOptions(saved, 'cluster', ['cluster_1']);
    expect(options.map((o) => o.label)).toEqual(['Lasso A', 'Lasso B', 'cluster_1']);
  });

  it('drops a group that captured nothing, which the server would refuse', () => {
    const empty: GroupRenderDef[] = [
      { name: 'Empty', column_name: 'cell_id', values: [], color: '#000' },
    ];
    expect(groupCompareOptions(empty, null, [])).toEqual([]);
  });

  it('ignores label values with no column to belong to', () => {
    expect(groupCompareOptions([], null, ['cluster_1', 'cluster_2'])).toEqual([]);
  });
});

describe('defaultGroupPair', () => {
  it('opens on two saved groups when there are two', () => {
    const options = groupCompareOptions(saved, 'cluster', ['cluster_1', 'cluster_2']);
    expect(defaultGroupPair(options)).toEqual(['saved:Lasso A', 'saved:Lasso B']);
  });

  it('falls back to the label column when only one lasso exists', () => {
    const options = groupCompareOptions(saved.slice(0, 1), 'cluster', ['cluster_1', 'cluster_2']);
    expect(defaultGroupPair(options)).toEqual(['col:cluster_1', 'col:cluster_2']);
  });

  it('never pairs a lasso against a label, which would overlap', () => {
    const options = groupCompareOptions(saved.slice(0, 1), 'cluster', ['cluster_1']);
    expect(defaultGroupPair(options)).toEqual([null, null]);
  });
});

describe('selectorFor', () => {
  const options = groupCompareOptions(saved, 'cluster', ['cluster_1']);

  it('resolves a picked value', () => {
    expect(selectorFor(options, 'col:cluster_1')?.column).toBe('cluster');
  });

  it('returns null for a group that no longer exists', () => {
    expect(selectorFor(options, 'saved:Deleted')).toBeNull();
    expect(selectorFor(options, null)).toBeNull();
  });
});

describe('configuredGroupPair', () => {
  const options = groupCompareOptions(saved, 'cluster', ['cluster_1', 'cluster_2', 'cluster_3']);

  it('opens on the two groups the config names', () => {
    expect(configuredGroupPair(options, 'cluster_2', 'cluster_3')).toEqual([
      'col:cluster_2',
      'col:cluster_3',
    ]);
  });

  it('prefers a saved group over a label value of the same name', () => {
    const clash = groupCompareOptions(
      [{ name: 'cluster_1', column_name: 'cell_id', values: ['c1'], color: '#000' }],
      'cluster',
      ['cluster_1', 'cluster_2'],
    );
    expect(resolveGroupDefault(clash, 'cluster_1')).toBe('saved:cluster_1');
  });

  it('falls back to the automatic pair when a default does not resolve', () => {
    expect(configuredGroupPair(options, 'cluster_1', 'missing')).toEqual(
      defaultGroupPair(options),
    );
    expect(configuredGroupPair(options, null, null)).toEqual(defaultGroupPair(options));
  });
});
