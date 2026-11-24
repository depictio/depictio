import { describe, expect, it } from 'vitest';

import { mergeValues } from './useInteractiveData';

describe('mergeValues (#1418)', () => {
  it('keeps the listed order and appends the kept and found values once', () => {
    // 1,000 of 4,333 families listed; the selection and a server search add
    // the ones past the cut.
    expect(mergeValues(['f_1', 'f_2'], ['f_3052'], ['f_2', 'f_3052', 'f_3'])).toEqual([
      'f_1',
      'f_2',
      'f_3052',
      'f_3',
    ]);
  });

  it('returns the listed values alone when nothing is added', () => {
    expect(mergeValues(['a', 'b'])).toEqual(['a', 'b']);
  });
});
