import { describe, expect, it } from 'vitest';

import { chooseAxisColumns, isNumericSpecType } from './axisSelection';

const specs = [
  { name: 'sample', type: 'object' },
  { name: 'group', type: 'utf8' },
  { name: 'reads', type: 'int64' },
  { name: 'dup_rate', type: 'float64' },
  { name: 'gc', type: 'Float32' },
  { name: 'passed', type: 'bool' },
];

describe('isNumericSpecType', () => {
  it('accepts the numeric spec types and refuses the rest', () => {
    expect(isNumericSpecType('int64')).toBe(true);
    expect(isNumericSpecType('UInt32')).toBe(true);
    expect(isNumericSpecType('float64')).toBe(true);
    expect(isNumericSpecType('object')).toBe(false);
    expect(isNumericSpecType('bool')).toBe(false);
    expect(isNumericSpecType(undefined)).toBe(false);
  });
});

describe('chooseAxisColumns', () => {
  it('infers every numeric column, minus the role columns', () => {
    const choice = chooseAxisColumns({
      candidates: specs,
      sampleCol: 'sample',
      groupCol: 'group',
      maxAxes: 12,
    });
    expect(choice.columns).toEqual(['reads', 'dup_rate', 'gc']);
    expect(choice.truncated).toBe(0);
  });

  it('never draws the sample column as an axis, even when it is numeric', () => {
    const choice = chooseAxisColumns({
      candidates: [{ name: 'run_id', type: 'int64' }, { name: 'reads', type: 'int64' }],
      sampleCol: 'run_id',
      maxAxes: 12,
    });
    expect(choice.columns).toEqual(['reads']);
  });

  it('caps the inferred set and reports what it left out', () => {
    const choice = chooseAxisColumns({
      candidates: specs,
      sampleCol: 'sample',
      groupCol: 'group',
      maxAxes: 2,
    });
    expect(choice.columns).toEqual(['reads', 'dup_rate']);
    expect(choice.truncated).toBe(1);
  });

  it('keeps a declared list whole, in its own order, and never truncates it', () => {
    const choice = chooseAxisColumns({
      candidates: specs,
      declared: ['gc', 'reads', 'dup_rate'],
      sampleCol: 'sample',
      maxAxes: 2,
    });
    expect(choice.columns).toEqual(['gc', 'reads', 'dup_rate']);
    expect(choice.truncated).toBe(0);
  });

  it('drops a declared column the collection does not carry', () => {
    const choice = chooseAxisColumns({
      candidates: specs,
      declared: ['reads', 'renamed_in_3_0', 'gc', 'reads'],
      sampleCol: 'sample',
      maxAxes: 12,
    });
    expect(choice.columns).toEqual(['reads', 'gc']);
  });

  it('takes a declared list as given when the specs are unavailable', () => {
    const choice = chooseAxisColumns({
      candidates: [],
      declared: ['reads', 'gc'],
      sampleCol: 'sample',
      maxAxes: 12,
    });
    expect(choice.columns).toEqual(['reads', 'gc']);
  });
});
