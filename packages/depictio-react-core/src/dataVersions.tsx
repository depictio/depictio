/**
 * Which Delta commit each data collection should be read at, for the whole
 * render tree.
 *
 * A pin has to reach *every* renderer — cards, figures, tables, maps, images —
 * and those live in the shared component package, well below the viewer that
 * owns the pin. Threading a prop through each would mean touching every
 * renderer's signature and every call site; context puts the decision where
 * it is made and reads it where the fetch happens.
 *
 * Two grains, matching the API:
 *
 *   `asOfVersionId`  — a stored dashboard version. The backend expands it into
 *                      per-collection pins from that version's stamps, so the
 *                      client never has to know which commit each collection
 *                      was at.
 *   `pins`           — explicit per-collection overrides, which is how one
 *                      component shows older data while the rest stays live.
 *
 * Both travel in the request body rather than as a fetch-time argument,
 * because the pin is part of *what was asked for*, not of how it was asked.
 * That also makes it visible to the render cache keys on both sides.
 */

import React, { createContext, useContext, useMemo } from 'react';

/** Per-collection Delta commit. `null` means "this one reads live data",
 *  which is how a component escapes a dashboard-wide pin. */
export type DataVersionPins = Record<string, number | null>;

export interface DataVersionState {
  /** Stored dashboard version whose data stamps set the baseline. */
  asOfVersionId?: string | null;
  /** Per-collection overrides applied on top of `asOfVersionId`. */
  pins?: DataVersionPins;
}

const DataVersionContext = createContext<DataVersionState>({});

export interface DataVersionProviderProps extends DataVersionState {
  children: React.ReactNode;
}

export const DataVersionProvider: React.FC<DataVersionProviderProps> = ({
  asOfVersionId,
  pins,
  children,
}) => {
  // Keyed on content, not identity: callers build `pins` inline, so a new
  // object every render would re-run every renderer's fetch effect.
  const pinKey = JSON.stringify(pins ?? {});
  const value = useMemo(
    () => ({ asOfVersionId, pins }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [asOfVersionId, pinKey],
  );

  return (
    <DataVersionContext.Provider value={value}>
      {children}
    </DataVersionContext.Provider>
  );
};

export function useDataVersions(): DataVersionState {
  return useContext(DataVersionContext);
}

/**
 * The time-travel fields to merge into a render request body.
 *
 * Returns an empty object when nothing is pinned, so an unpinned request is
 * byte-identical to what it was before this feature existed — no cache key
 * changes, no behaviour change for every existing caller.
 *
 * `componentOverride` is the component-level grain: a modal comparing one
 * component across versions passes its own pin here and ignores whatever the
 * dashboard is showing.
 */
export function dataVersionBody(
  state: DataVersionState,
  componentOverride?: { dcId?: string | null; deltaVersion?: number | null },
): Record<string, unknown> {
  const body: Record<string, unknown> = {};

  if (state.asOfVersionId) body.as_of_version = state.asOfVersionId;

  const pins: DataVersionPins = { ...(state.pins ?? {}) };
  if (componentOverride?.dcId) {
    // `undefined` means "no opinion, inherit"; `null` is an explicit
    // "this component reads live data" and must survive into the body.
    if (componentOverride.deltaVersion !== undefined) {
      pins[componentOverride.dcId] = componentOverride.deltaVersion;
    }
  }

  if (Object.keys(pins).length > 0) body.data_versions = pins;

  return body;
}

/** Convenience for renderers: the effective pin for one collection, or
 *  undefined when it reads live data. */
export function useDataVersionFor(dcId?: string | null): number | null | undefined {
  const { pins } = useDataVersions();
  if (!dcId || !pins) return undefined;
  return pins[dcId];
}

/**
 * What a renderer needs: the request-body fragment plus a stable string to put
 * in its fetch effect's dependency list.
 *
 * The key matters as much as the body. Renderers key their effects on
 * `JSON.stringify(filters)` and friends; without the version in that list, a
 * pin change would update the body but never re-run the fetch, leaving the old
 * data on screen under the new label. Returning both from one hook makes it
 * hard to wire up one and forget the other.
 */
export function useDataVersionRequest(): {
  body: Record<string, unknown>;
  key: string;
} {
  const state = useDataVersions();
  const body = useMemo(
    () => dataVersionBody(state),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.asOfVersionId, JSON.stringify(state.pins ?? {})],
  );
  return { body, key: JSON.stringify(body) };
}

/** True when anything at all is pinned — drives the "you are looking at past
 *  data" banner, which must appear whenever the view is not live. */
export function useIsTimeTravelling(): boolean {
  const { asOfVersionId, pins } = useDataVersions();
  if (asOfVersionId) return true;
  return Object.values(pins ?? {}).some((v) => v !== null && v !== undefined);
}
