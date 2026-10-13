import { describe, expect, it } from 'vitest';

import { createAutoRunGate } from './autoRun';

describe('createAutoRunGate', () => {
  it('dispatches once per request key', () => {
    const gate = createAutoRunGate();
    expect(gate.claim('k1', true, true)).toBe(true);
    expect(gate.claim('k1', true, true)).toBe(false);
    expect(gate.claim('k2', true, true)).toBe(true);
    expect(gate.claim('k2', true, true)).toBe(false);
  });

  it('never dispatches when auto_run is off or the groups are not ready', () => {
    const gate = createAutoRunGate();
    expect(gate.claim('k1', false, true)).toBe(false);
    expect(gate.claim('k1', true, false)).toBe(false);
    // Becoming ready later still claims the key once.
    expect(gate.claim('k1', true, true)).toBe(true);
  });

  it('lets a remount claim the same key again, for the cache to answer', () => {
    const gate = createAutoRunGate();
    expect(gate.claim('k1', true, true)).toBe(true);
    gate.reset();
    expect(gate.claim('k1', true, true)).toBe(true);
  });
});
