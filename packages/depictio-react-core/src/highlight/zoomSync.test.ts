import { describe, expect, it } from 'vitest';

import {
  createZoomSyncStore,
  followsWindow,
  sameWindow,
  type ZoomSyncPersistence,
  type ZoomWindow,
  ZOOM_SYNC_MAX_REMEMBERED,
} from './zoomSync';

const memory = (initial: string[] = []): ZoomSyncPersistence & { stored: string[] } => {
  const p = {
    stored: initial,
    read: () => [...p.stored],
    write: (members: readonly string[]) => {
      p.stored = [...members];
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
  it('starts from the remembered members, none by default', () => {
    expect(createZoomSyncStore(memory()).isMember('a')).toBe(false);
    expect(createZoomSyncStore(memory(['a'])).isMember('a')).toBe(true);
  });

  it('ignores windows from a tile that is not a member', () => {
    const store = createZoomSyncStore(memory(['b']));
    let heard = 0;
    store.subscribe(() => heard++);
    store.publish(win());
    expect(store.current()).toBeNull();
    expect(heard).toBe(0);
  });

  it('remembers members and lets the tile turned on lead when no window holds', () => {
    const p = memory();
    const store = createZoomSyncStore(p);
    store.setMembers(['a'], true, 'a');
    expect(p.stored).toEqual(['a']);
    expect(store.leader()).toBe('a');
    store.setMembers(['a'], false);
    expect(p.stored).toEqual([]);
    expect(store.leader()).toBeNull();
  });

  it('has a joiner follow the window a member holds', () => {
    const store = createZoomSyncStore(memory(['a']));
    store.publish(win());
    store.setMembers(['b'], true, 'b');
    expect(store.leader()).toBeNull();
    expect(store.current()?.sourceIndex).toBe('a');
  });

  it('keeps the window for the members left after its source leaves', () => {
    const store = createZoomSyncStore(memory(['a', 'c']));
    store.publish(win());
    store.setMembers(['a'], false);
    store.setMembers(['b'], true, 'b');
    expect(store.leader()).toBeNull();
    expect(store.current()?.sourceIndex).toBe('a');
  });

  it('lets the source of the window lead when it joins again', () => {
    const store = createZoomSyncStore(memory(['a', 'c']));
    store.publish(win());
    store.setMembers(['a'], false);
    store.setMembers(['a'], true, 'a');
    expect(store.leader()).toBe('a');
    expect(store.current()).toBeNull();
  });

  it('leads a group join from its first tile that can lead', () => {
    const store = createZoomSyncStore(memory());
    store.register('3d', false);
    store.register('track');
    store.setMembers(['3d', 'track'], true);
    expect(store.leader()).toBe('track');
  });

  it('notifies once per new window and not for the same one again', () => {
    const store = createZoomSyncStore(memory(['a']));
    let heard = 0;
    store.subscribe(() => heard++);
    store.publish(win());
    store.publish(win({ start: 10.0002 }));
    store.publish(win({ start: 20 }));
    expect(heard).toBe(2);
    expect(store.current()?.start).toBe(20);
  });

  it('drops the window once the last member leaves', () => {
    const store = createZoomSyncStore(memory(['a', 'b']));
    store.publish(win());
    store.setMembers(['a'], false);
    expect(store.current()?.sourceIndex).toBe('a');
    store.setMembers(['b'], false);
    expect(store.current()).toBeNull();
  });

  it('lets a listener publish while the store notifies (the leader answering its join)', () => {
    const store = createZoomSyncStore(memory());
    const seen: Array<ZoomWindow | null> = [];
    store.subscribe(() => {
      if (store.leader() === 'a' && store.current() === null) store.publish(win());
    });
    store.subscribe(() => seen.push(store.current()));
    store.setMembers(['a', 'b'], true, 'a');
    expect(seen[seen.length - 1]?.sourceIndex).toBe('a');
  });

  it('counts registrations, so a tile drawn twice stays until both are gone', () => {
    const store = createZoomSyncStore(memory());
    const off1 = store.register('a');
    const off2 = store.register('a');
    off1();
    off1();
    expect(store.canSync('a')).toBe(true);
    off2();
    expect(store.canSync('a')).toBe(false);
  });

  it('forgets the oldest members past the cap', () => {
    const store = createZoomSyncStore(memory());
    const many = Array.from({ length: ZOOM_SYNC_MAX_REMEMBERED + 5 }, (_, i) => `t${i}`);
    store.setMembers(many, true);
    expect(store.isMember('t0')).toBe(false);
    expect(store.isMember(`t${many.length - 1}`)).toBe(true);
  });

  it('stops notifying once disposed', () => {
    const store = createZoomSyncStore(memory(['a']));
    let heard = 0;
    store.subscribe(() => heard++);
    store.dispose();
    store.publish(win());
    expect(heard).toBe(0);
  });
});
