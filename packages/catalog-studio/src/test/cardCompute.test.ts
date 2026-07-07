import { describe, it, expect } from 'vitest';
import { computeCard } from '../viz/cardCompute';

const rows = [
  { g: 'a', v: 10 },
  { g: 'b', v: 20 },
  { g: 'a', v: 30 },
  { g: 'c', v: '' },
];

describe('computeCard', () => {
  it('count ignores empty', () => {
    expect(computeCard(rows, 'v', 'count')).toBe(3);
  });
  it('average', () => {
    expect(computeCard(rows, 'v', 'average')).toBe(20);
  });
  it('sum / min / max / range', () => {
    expect(computeCard(rows, 'v', 'sum')).toBe(60);
    expect(computeCard(rows, 'v', 'min')).toBe(10);
    expect(computeCard(rows, 'v', 'max')).toBe(30);
    expect(computeCard(rows, 'v', 'range')).toBe(20);
  });
  it('median', () => {
    expect(computeCard(rows, 'v', 'median')).toBe(20);
  });
  it('nunique / mode on categorical', () => {
    expect(computeCard(rows, 'g', 'nunique')).toBe(3);
    expect(computeCard(rows, 'g', 'mode')).toBe('a');
  });
  it('std_dev', () => {
    // values 10,20,30 → mean 20, population variance 66.67, std ~8.16
    expect(computeCard(rows, 'v', 'std_dev')).toBeCloseTo(8.165, 2);
  });
});
