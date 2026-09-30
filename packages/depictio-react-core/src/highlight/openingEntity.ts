/**
 * Opening-entity agreement: "the protein tiles of this dashboard open on the
 * same entity".
 *
 * Before any click, each protein tile picks its own opening entity from its
 * own table (molecule_3d the entity with the most residue rows, an msa the
 * alignment with the most rows), so two tiles of one dashboard could open on
 * two different structures. This store lets them agree: keyed by the entity
 * column NAME they filter on (the same key residue picks travel on), the
 * first tile that resolves its opening entity claims the key, and the others
 * adopt that value when they hold it and fall back to their own choice
 * otherwise. A filter naming one entity, or the reader's own pick, still wins
 * in each tile; this only decides the opening.
 *
 * The claimant owns the key: it may move it (its opening changes when the
 * dashboard's pickers change what is in scope) and releases it when it
 * unmounts, so another tile can claim it. A tile reloading (its own opening
 * back to null for a moment) keeps its claim, so a refetch never hands the
 * opening over to another tile. Claims and
 * releases run in effects, never during render, so React StrictMode's double
 * mount (effect, cleanup, effect) ends in the same state as a single mount.
 *
 * Scope: one store per dashboard view, provided by `HighlightProvider` next to
 * the hover bus. Outside a provider the hook returns the tile's own choice.
 */
import { createContext, useContext, useEffect, useSyncExternalStore } from 'react';

export interface OpeningEntityStore {
  /** The entity in force for `key`, or null when no tile claimed it. */
  get(key: string): string | null;
  /** Claim `key` for `owner` with `entity`. The first claimant wins; later
   *  claims by the same owner move the value. Returns the value in force. */
  claim(key: string, owner: string, entity: string): string;
  /** Drop `owner`'s claim on `key` (a no-op for anyone else). */
  release(key: string, owner: string): void;
  subscribe(listener: () => void): () => void;
  dispose(): void;
}

export function createOpeningEntityStore(): OpeningEntityStore {
  const claims = new Map<string, { owner: string; entity: string }>();
  const listeners = new Set<() => void>();
  const notify = () => {
    for (const l of [...listeners]) l();
  };
  return {
    get: (key) => claims.get(key)?.entity ?? null,
    claim(key, owner, entity) {
      const current = claims.get(key);
      if (current && current.owner !== owner) return current.entity;
      if (current?.entity === entity) return entity;
      claims.set(key, { owner, entity });
      notify();
      return entity;
    },
    release(key, owner) {
      if (claims.get(key)?.owner !== owner) return;
      claims.delete(key);
      notify();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    dispose() {
      claims.clear();
      listeners.clear();
    },
  };
}

/**
 * The opening a tile shows: the shared one when the tile holds it (or when
 * the tile cannot tell yet what it holds, `held` null), else its own.
 */
export function adoptOpeningEntity(
  shared: string | null,
  own: string | null,
  held: readonly string[] | null,
): string | null {
  if (shared !== null && (held === null || held.includes(shared))) return shared;
  return own;
}

export const OpeningEntityContext = createContext<OpeningEntityStore | null>(null);

const noopSubscribe = () => () => {};
const nullSnapshot = () => null;

/**
 * Share a tile's opening entity under `key` (the entity column name) and
 * return the one it should open on.
 *
 * `own` is what the tile would open on by itself, once it knows (null while
 * it is still loading: nothing new is claimed then, an earlier claim stays). `held` is every entity the
 * tile can show; the shared value is adopted only when it is among them.
 * `key` null, or no provider above, turns sharing off.
 */
export function useSharedOpeningEntity(
  key: string | null | undefined,
  owner: string,
  own: string | null,
  held: readonly string[] | null,
): string | null {
  const ctx = useContext(OpeningEntityContext);
  const store = key ? ctx : null;
  const shared = useSyncExternalStore(
    store ? store.subscribe : noopSubscribe,
    store && key ? () => store.get(key) : nullSnapshot,
    nullSnapshot,
  );

  const vacant = shared === null;
  useEffect(() => {
    if (!store || !key || own === null) return;
    // The store ignores a claim against another owner, so this only takes a
    // vacant key or moves this tile's own claim. Re-run when the key falls
    // vacant, so a waiting tile takes over from one that unmounted.
    store.claim(key, owner, own);
  }, [store, key, owner, own, vacant]);
  // Released on unmount (and on a key change) only, so moving the claim
  // never passes through a vacant key another tile could grab.
  useEffect(() => {
    if (!store || !key) return undefined;
    return () => store.release(key, owner);
  }, [store, key, owner]);

  return adoptOpeningEntity(shared, own, held);
}
