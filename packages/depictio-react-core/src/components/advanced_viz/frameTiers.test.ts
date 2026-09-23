import { describe, expect, it } from 'vitest';

import { frameTiers } from './frameTiers';

describe('frameTiers', () => {
  it('keeps both tiers as given in the popover and the rail', () => {
    for (const placement of ['popover', 'rail'] as const) {
      expect(frameTiers(placement, 'enc', 'cos')).toEqual({ primary: 'enc', cosmetic: 'cos' });
      expect(frameTiers(placement, null, 'cos')).toEqual({ cosmetic: 'cos' });
      expect(frameTiers(placement, 'enc', undefined)).toEqual({ primary: 'enc' });
    }
  });

  it('leaves the cosmetic tier in the popover under header when there is an encoding tier', () => {
    expect(frameTiers('header', 'enc', 'cos')).toEqual({ primary: 'enc', cosmetic: 'cos' });
  });

  it('promotes the cosmetic tier into the header strip when the renderer has no encoding tier', () => {
    // Nothing left as `cosmetic` means nothing left for the popover: the
    // controls are drawn in one place, the strip.
    expect(frameTiers('header', undefined, 'cos')).toEqual({ primary: 'cos' });
    expect(frameTiers('header', null, 'cos')).toEqual({ primary: 'cos' });
  });

  it('publishes nothing when the renderer has no controls at all', () => {
    expect(frameTiers('header', null, null)).toEqual({});
    expect(frameTiers('rail', undefined, undefined)).toEqual({});
  });
});
