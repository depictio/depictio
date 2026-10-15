import { describe, expect, it, vi } from 'vitest';

import { chooseEntity } from '../components/advanced_viz/molecule/residueData';
import { adoptOpeningEntity, createOpeningEntityStore } from './openingEntity';

describe('createOpeningEntityStore', () => {
  it('lets the first claimant set the key and ignores later claimants', () => {
    const store = createOpeningEntityStore();
    expect(store.get('entity')).toBeNull();
    expect(store.claim('entity', 'mol', 'alphafold2__T1')).toBe('alphafold2__T1');
    expect(store.claim('entity', 'msa', 'colabfold__T1')).toBe('alphafold2__T1');
    expect(store.get('entity')).toBe('alphafold2__T1');
  });

  it('lets the owner move its claim, and keys are independent', () => {
    const store = createOpeningEntityStore();
    store.claim('entity', 'mol', 'A');
    store.claim('entity', 'mol', 'B');
    store.claim('family', 'msa', 'F1');
    expect(store.get('entity')).toBe('B');
    expect(store.get('family')).toBe('F1');
  });

  it('frees the key only when its owner releases it', () => {
    const store = createOpeningEntityStore();
    store.claim('entity', 'mol', 'A');
    store.release('entity', 'msa');
    expect(store.get('entity')).toBe('A');
    store.release('entity', 'mol');
    expect(store.get('entity')).toBeNull();
    expect(store.claim('entity', 'msa', 'C')).toBe('C');
  });

  it('notifies subscribers on a change only', () => {
    const store = createOpeningEntityStore();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.claim('entity', 'mol', 'A');
    store.claim('entity', 'mol', 'A');
    store.claim('entity', 'msa', 'B');
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    store.release('entity', 'mol');
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('ends in the same state after a StrictMode mount, cleanup, mount', () => {
    // What useSharedOpeningEntity does: claim in one effect, release in the
    // other's cleanup. A double mount replays it for every tile in tree order.
    const store = createOpeningEntityStore();
    const mount = (owner: string, own: string) => store.claim('entity', owner, own);
    const unmount = (owner: string) => store.release('entity', owner);
    mount('mol', 'A');
    mount('msa', 'B');
    unmount('mol');
    unmount('msa');
    mount('mol', 'A');
    mount('msa', 'B');
    expect(store.get('entity')).toBe('A');
  });
});

describe('adoptOpeningEntity', () => {
  it('adopts the shared opening when the tile holds it', () => {
    expect(adoptOpeningEntity('A', 'B', ['A', 'B'])).toBe('A');
  });

  it('falls back to its own choice when it does not hold the shared one', () => {
    expect(adoptOpeningEntity('A', 'B', ['B', 'C'])).toBe('B');
  });

  it('keeps its own choice when nothing is shared', () => {
    expect(adoptOpeningEntity(null, 'B', ['B'])).toBe('B');
    expect(adoptOpeningEntity(null, null, null)).toBeNull();
  });

  it('takes the shared value while the tile does not know what it holds yet', () => {
    expect(adoptOpeningEntity('A', null, null)).toBe('A');
  });
});

describe('chooseEntity with an agreed opening', () => {
  const available = ['A', 'B', 'C'];
  const rowEntities = ['B', 'A'];

  it('opens on the agreed entity over its own largest one', () => {
    expect(chooseEntity({ fromFilters: null, picked: null, rowEntities, available, opening: 'C' })).toBe(
      'C',
    );
  });

  it('lets a filter naming one entity and the reader pick win', () => {
    expect(chooseEntity({ fromFilters: 'A', picked: null, rowEntities, available, opening: 'C' })).toBe(
      'A',
    );
    expect(chooseEntity({ fromFilters: null, picked: 'A', rowEntities, available, opening: 'C' })).toBe(
      'A',
    );
  });

  it('ignores an agreed entity with no structure', () => {
    expect(chooseEntity({ fromFilters: null, picked: null, rowEntities, available, opening: 'Z' })).toBe(
      'B',
    );
  });
});
