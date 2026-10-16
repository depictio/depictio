import { describe, expect, it } from 'vitest';

import {
  createZoomSyncStore,
  followsWindow,
  sameWindow,
  type ZoomSyncPersistence,
  type ZoomWindow,
} from './zoomSync';

const memory = (initial = false): ZoomSyncPersistence & { stored: boolean } => {
  const p = {
    stored: initial,
    read: () => p.stored,
    write: (on: boolean) => {
      p.stored = on;
    },
  };
  return p;
};

const win = (over: Partial<ZoomWindow> = {}): ZoomWindow => ({
  sourceIndex: 'a',
  entity: 'P1',
  positionColumn: 'position',
  start: 10,
  end: 50,
  fit: false,
  ...over,
});

describe('followsWindow', () => {
  it('follows another tile on the same axis', () => {
    expect(followsWindow(win(), { index: 'b', entity: 'P1', positionColumn: 'position' })).toBe(true);
  });

  it('ignores its own window and the lack of one', () => {
    expect(followsWindow(win(), { index: 'a', entity: 'P1', positionColumn: 'position' })).toBe(false);
    expect(followsWindow(null, { index: 'b' })).toBe(false);
  });

  it('ignores another position column or another entity', () => {
    expect(followsWindow(win(), { index: 'b', entity: 'P1', positionColumn: 'state' })).toBe(false);
    expect(followsWindow(win(), { index: 'b', entity: 'P2', positionColumn: 'position' })).toBe(false);
  });

  it('follows when either side does not know its entity or column', () => {
    expect(followsWindow(win(), { index: 'b', entity: null, positionColumn: 'position' })).toBe(true);
    expect(followsWindow(win({ entity: undefined }), { index: 'b', entity: 'P2' })).toBe(true);
    expect(followsWindow(win({ positionColumn: undefined }), { index: 'b', positionColumn: 'x' })).toBe(true);
  });
});

describe('sameWindow', () => {
  it('treats edges a rounding error apart as the same', () => {
    expect(sameWindow(win(), win({ start: 10.0001 }))).toBe(true);
    expect(sameWindow(win(), win({ start: 10.5 }))).toBe(false);
  });

  it('tells sources and fit apart', () => {
    expect(sameWindow(win(), win({ sourceIndex: 'b' }))).toBe(false);
    expect(sameWindow(win(), win({ fit: true }))).toBe(false);
    expect(sameWindow(null, null)).toBe(true);
    expect(sameWindow(win(), null)).toBe(false);
  });
});

describe('createZoomSyncStore', () => {
  it('starts from the remembered switch, off by default', () => {
    expect(createZoomSyncStore(memory()).isEnabled()).toBe(false);
    expect(createZoomSyncStore(memory(true)).isEnabled()).toBe(true);
  });

  it('ignores windows while off', () => {
    const store = createZoomSyncStore(memory());
    let heard = 0;
    store.subscribe(() => heard++);
    store.publish(win());
    expect(store.current()).toBeNull();
    expect(heard).toBe(0);
  });

  it('remembers the switch and names the tile that turned it on', () => {
    const p = memory();
    const store = createZoomSyncStore(p);
    store.setEnabled(true, 'a');
    expect(p.stored).toBe(true);
    expect(store.leader()).toBe('a');
    store.setEnabled(false, 'b');
    expect(p.stored).toBe(false);
    expect(store.leader()).toBeNull();
  });

  it('notifies once per new window and not for the same one again', () => {
    const store = createZoomSyncStore(memory(true));
    let heard = 0;
    store.subscribe(() => heard++);
    store.publish(win());
    store.publish(win({ start: 10.0002 }));
    store.publish(win({ start: 20 }));
    expect(heard).toBe(2);
    expect(store.current()?.start).toBe(20);
  });

  it('drops the window in force when the switch goes off', () => {
    const store = createZoomSyncStore(memory(true));
    store.publish(win());
    store.setEnabled(false);
    expect(store.current()).toBeNull();
    store.setEnabled(true, 'b');
    expect(store.current()).toBeNull();
  });

  it('lets a listener publish while the store notifies (the leader answering the switch)', () => {
    const store = createZoomSyncStore(memory());
    const seen: Array<ZoomWindow | null> = [];
    store.subscribe(() => {
      if (store.leader() === 'a' && store.current() === null) store.publish(win());
    });
    store.subscribe(() => seen.push(store.current()));
    store.setEnabled(true, 'a');
    expect(seen.at(-1)?.sourceIndex).toBe('a');
  });

  it('stops notifying once disposed', () => {
    const store = createZoomSyncStore(memory(true));
    let heard = 0;
    store.subscribe(() => heard++);
    store.dispose();
    store.publish(win());
    expect(heard).toBe(0);
  });
});
