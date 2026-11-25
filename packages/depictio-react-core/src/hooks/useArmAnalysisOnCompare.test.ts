import { describe, expect, it } from 'vitest';

import { armsOnPick } from './useArmAnalysisOnCompare';

describe('armsOnPick', () => {
  it('arms when a label column is picked', () => {
    expect(armsOnPick(null, 'col-1')).toBe(true);
    expect(armsOnPick('col-1', 'col-2')).toBe(true);
  });
  it('leaves a dashboard reopened with a column picked as it was', () => {
    expect(armsOnPick(undefined, 'col-1')).toBe(false);
  });
  it('does nothing on an unpick or an unchanged pick', () => {
    expect(armsOnPick('col-1', null)).toBe(false);
    expect(armsOnPick('col-1', 'col-1')).toBe(false);
  });
});
