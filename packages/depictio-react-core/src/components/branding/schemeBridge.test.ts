import { describe, expect, it } from 'vitest';
import type { MantineColorScheme } from '@mantine/core';

import { createSchemeBridge } from './schemeBridge';

function appProvider(start: MantineColorScheme) {
  let scheme = start;
  const writes: MantineColorScheme[] = [];
  return {
    read: () => scheme,
    write: (next: MantineColorScheme) => {
      writes.push(next);
      scheme = next;
    },
    writes,
  };
}

describe('scheme bridge', () => {
  it('reads the app scheme', () => {
    const app = appProvider('dark');
    expect(createSchemeBridge(app.read, app.write).get('light')).toBe('dark');
  });

  it('a toggle inside the scope writes through to the app, once', () => {
    const app = appProvider('light');
    const bridge = createSchemeBridge(app.read, app.write);
    bridge.set('dark');
    bridge.set('dark');
    expect(app.writes).toEqual(['dark']);
  });

  it('an app change reaches the nested provider, and only while subscribed', () => {
    const app = appProvider('light');
    const bridge = createSchemeBridge(app.read, app.write);
    const seen: MantineColorScheme[] = [];
    bridge.subscribe((s) => seen.push(s));
    bridge.follow('dark');
    bridge.unsubscribe();
    bridge.follow('light');
    expect(seen).toEqual(['dark']);
  });
});
