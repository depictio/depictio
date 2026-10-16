import { describe, expect, it } from 'vitest';

import { createHoverGate } from './hoverGate';

/** A scheduler the test steps by hand, one frame at a time. */
function manualFrames() {
  let next = 1;
  const queue = new Map<number, () => void>();
  return {
    schedule: (cb: () => void) => {
      const id = next++;
      queue.set(id, cb);
      return id;
    },
    cancel: (handle: unknown) => {
      queue.delete(handle as number);
    },
    frame() {
      const due = [...queue.values()];
      queue.clear();
      for (const cb of due) cb();
    },
    pending: () => queue.size,
  };
}

function setup() {
  const frames = manualFrames();
  const log: string[] = [];
  const gate = createHoverGate<string>({
    onEnter: (v) => log.push(`enter ${v}`),
    onClear: () => log.push('clear'),
    schedule: frames.schedule,
    cancel: frames.cancel,
  });
  return { frames, log, gate };
}

describe('createHoverGate', () => {
  it('applies a hover at once', () => {
    const { gate, log } = setup();
    gate.enter('A|1', 'residue 1');
    expect(log).toEqual(['enter residue 1']);
  });

  it('does nothing for a hover on the residue already applied', () => {
    const { gate, log } = setup();
    gate.enter('A|1', 'atom 1');
    gate.enter('A|1', 'atom 2');
    gate.enter('A|1', 'atom 3');
    expect(log).toEqual(['enter atom 1']);
  });

  it('clears one frame after a leave, not before', () => {
    const { gate, log, frames } = setup();
    gate.enter('A|1', 'r1');
    gate.leave();
    expect(log).toEqual(['enter r1']);
    frames.frame();
    expect(log).toEqual(['enter r1', 'clear']);
  });

  it('shows no gap when the pointer moves from one residue to the next', () => {
    const { gate, log, frames } = setup();
    gate.enter('A|1', 'r1');
    gate.leave();
    gate.enter('A|2', 'r2');
    frames.frame();
    expect(log).toEqual(['enter r1', 'enter r2']);
    expect(frames.pending()).toBe(0);
  });

  it('keeps the highlight when the pointer leaves an atom and re-enters the same residue', () => {
    const { gate, log, frames } = setup();
    gate.enter('A|1', 'atom 1');
    gate.leave();
    gate.enter('A|1', 'atom 2');
    frames.frame();
    expect(log).toEqual(['enter atom 1']);
  });

  it('applies the same residue again after it was cleared', () => {
    const { gate, log, frames } = setup();
    gate.enter('A|1', 'first');
    gate.leave();
    frames.frame();
    gate.enter('A|1', 'second');
    expect(log).toEqual(['enter first', 'clear', 'enter second']);
  });

  it('schedules one clear for repeated leaves and ignores a leave with nothing applied', () => {
    const { gate, log, frames } = setup();
    gate.leave();
    expect(frames.pending()).toBe(0);
    gate.enter('A|1', 'r1');
    gate.leave();
    gate.leave();
    expect(frames.pending()).toBe(1);
    frames.frame();
    gate.leave();
    expect(frames.pending()).toBe(0);
    expect(log).toEqual(['enter r1', 'clear']);
  });

  it('clears at once when the pointer leaves the tile, and drops the pending clear', () => {
    const { gate, log, frames } = setup();
    gate.enter('A|1', 'r1');
    gate.leave();
    gate.clear();
    expect(log).toEqual(['enter r1', 'clear']);
    expect(frames.pending()).toBe(0);
    frames.frame();
    expect(log).toEqual(['enter r1', 'clear']);
  });

  it('treats a different entity as a different hover', () => {
    const { gate, log } = setup();
    gate.enter('P1|A|10', 'P1 10');
    gate.enter('P2|A|10', 'P2 10');
    expect(log).toEqual(['enter P1 10', 'enter P2 10']);
  });

  it('on dispose, clears what is applied and drops a pending frame, so nothing fires later', () => {
    const { gate, log, frames } = setup();
    gate.enter('A|1', 'r1');
    gate.leave();
    gate.dispose();
    expect(log).toEqual(['enter r1', 'clear']);
    frames.frame();
    expect(log).toEqual(['enter r1', 'clear']);
    // Nothing applied: disposing again is silent.
    gate.dispose();
    expect(log).toEqual(['enter r1', 'clear']);
  });

  it('keeps working after a dispose (a remount in development runs it twice)', () => {
    const { gate, log } = setup();
    gate.dispose();
    gate.enter('A|1', 'r1');
    expect(log).toEqual(['enter r1']);
  });
});
