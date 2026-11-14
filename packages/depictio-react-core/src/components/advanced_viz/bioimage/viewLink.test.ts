import { describe, expect, it, vi } from 'vitest';

import { joinViewLink, moveViewLink } from './viewLink';

describe('view link', () => {
  it('passes a move to the other tiles of the group, never back to the mover', () => {
    const a = vi.fn();
    const b = vi.fn();
    const other = vi.fn();
    const leaveA = joinViewLink('g', 'a', a);
    joinViewLink('g', 'b', b);
    joinViewLink('h', 'c', other);
    moveViewLink('g', 'a', { zoom: 1, target: [10, 20] });
    expect(a).not.toHaveBeenCalled();
    expect(b).toHaveBeenCalledWith({ zoom: 1, target: [10, 20] }, 'a');
    expect(other).not.toHaveBeenCalled();
    leaveA();
    moveViewLink('g', 'b', { zoom: 2, target: [0, 0] });
    expect(a).not.toHaveBeenCalled();
  });
});
