import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../../api';
import {
  defaultRecordFilter,
  recordEcho,
  resolveRecordTarget,
  targetMatch,
} from './recordDefault';
import { readRecordSelection } from './recordSelection';

const scatter = (values: unknown[]): InteractiveFilter => ({
  index: 'tile-a',
  value: values,
  source: 'scatter_selection',
  column_name: 'feature_id',
  interactive_component_type: 'MultiSelect',
  metadata: { dc_id: 'dc-1', column_name: 'feature_id', selection_column: 'feature_id' },
});

const target = (filters: InteractiveFilter[], defaultRecord?: string | null) =>
  resolveRecordTarget(readRecordSelection(filters, { dcId: 'dc-1' }), {
    idCol: 'feature_id',
    defaultRecord,
  });

describe('resolveRecordTarget', () => {
  it('shows the default when nothing is selected', () => {
    expect(target([], 'GENE072')).toEqual({
      kind: 'default',
      column: 'feature_id',
      value: 'GENE072',
    });
  });

  it('lets a real selection win over the default', () => {
    const t = target([scatter(['GENE001', 'GENE002'])], 'GENE072');
    expect(t?.kind).toBe('selection');
    expect(targetMatch(t)?.values).toEqual(['GENE001', 'GENE002']);
  });

  it('falls back to the default when the selection is cleared', () => {
    expect(target([scatter([])], 'GENE072')?.kind).toBe('default');
  });

  it('stays empty with no selection and no default', () => {
    expect(target([], null)).toBeNull();
    expect(target([], '  ')).toBeNull();
  });
});

describe('targetMatch', () => {
  it('matches the default on the id column of the own collection', () => {
    expect(targetMatch(target([], 'GENE072'))).toEqual({
      column: 'feature_id',
      values: ['GENE072'],
      ownCollection: true,
    });
  });
});

describe('defaultRecordFilter', () => {
  it('is an equality filter on the id column with no selection source', () => {
    const f = defaultRecordFilter('card', 'dc-1', 'feature_id', 'GENE072');
    expect(f.source).toBeUndefined();
    expect(f.value).toEqual(['GENE072']);
    expect(f.column_name).toBe('feature_id');
    expect(f.metadata?.dc_id).toBe('dc-1');
    // Not a selection, so the card can never follow its own default as a pick.
    expect(readRecordSelection([f], { dcId: 'dc-1' })).toBeNull();
  });
});

describe('recordEcho', () => {
  it('names the default value', () => {
    expect(recordEcho(target([], 'GENE072'), 1)).toBe('default: GENE072');
  });

  it('counts the selected records', () => {
    expect(recordEcho(target([scatter(['a', 'b', 'c'])], 'GENE072'), 3)).toBe('selected: 3');
    expect(recordEcho(target([scatter(['a'])]), null)).toBe('selected: 1');
  });

  it('says nothing when the card is empty', () => {
    expect(recordEcho(null, null)).toBeUndefined();
  });
});
