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

import type { DataPinFields } from './api';

/** Per-collection Delta commit. `null` means "this one reads live data",
 *  which is how a component escapes a dashboard-wide pin. */
export type DataVersionPins = Record<string, number | null>;

export interface DataVersionState {
  /** Stored dashboard version whose data stamps set the baseline. */
  asOfVersionId?: string | null;
  /** Per-collection overrides applied on top of `asOfVersionId`. */
  pins?: DataVersionPins;
  /**
   * Stored dashboard version to read component *definitions* from, instead of
   * the live document.
   *
   * Travels beside the pins because it answers the other half of the same
   * question. A render endpoint reads the component from the live dashboard
   * document, so pinning only the data draws a past version's numbers with
   * today's chart definition: a histogram shown as the box plot it later
   * became. The server reads the definition out of that version itself, so
   * nothing in a request body can change which collection is read.
   */
  definitionVersionId?: string | null;
  /**
   * The tab the pins were chosen on. Requests that are not per component (a
   * filter's options, the banners' status) resolve `as_of_version` against
   * this tab's family.
   */
  dashboardId?: string | null;
}

const DataVersionContext = createContext<DataVersionState>({});

export interface DataVersionProviderProps extends DataVersionState {
  children: React.ReactNode;
}

export const DataVersionProvider: React.FC<DataVersionProviderProps> = ({
  asOfVersionId,
  pins,
  definitionVersionId,
  dashboardId,
  children,
}) => {
  // Keyed on content, not identity: callers build these inline, so a new
  // object every render would re-run every renderer's fetch effect.
  const pinKey = JSON.stringify(pins ?? {});
  const value = useMemo(
    () => ({ asOfVersionId, pins, definitionVersionId, dashboardId }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [asOfVersionId, pinKey, definitionVersionId, dashboardId],
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
 * The data half of a request: `as_of_version` and `data_versions`, without the
 * definition. What a filter's options and the status endpoint take, since
 * neither draws a component.
 */
export function dataPinBody(state: DataVersionState): DataPinFields {
  const body: DataPinFields = {};
  if (state.asOfVersionId) body.as_of_version = state.asOfVersionId;
  const pins = state.pins;
  if (pins && Object.keys(pins).length > 0) body.data_versions = { ...pins };
  return body;
}

/**
 * The time-travel fields to merge into a render request body.
 *
 * Returns an empty object when nothing is pinned, so an unpinned request is
 * byte-identical to what it was before this feature existed — no cache key
 * changes, no behaviour change for every existing caller.
 */
export function dataVersionBody(state: DataVersionState): Record<string, unknown> {
  const body: Record<string, unknown> = { ...dataPinBody(state) };
  if (state.definitionVersionId) body.definition_version = state.definitionVersionId;
  return body;
}

/**
 * Is anything on screen read from past data?
 *
 * True under a version's data or any numeric pin. A `null` pin alone is not
 * past data: it only says "stay live", which means something only under a
 * version.
 */
export function isDataVersionActive(state: DataVersionState): boolean {
  if (state.asOfVersionId) return true;
  return Object.values(state.pins ?? {}).some((v) => typeof v === 'number');
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
  /** For `renderDefinitionKey`: a definition read from another version is a
   *  different definition, even when the local metadata did not change. */
  definitionVersionId: string | null;
} {
  const state = useDataVersions();
  const body = useMemo(
    () => dataVersionBody(state),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.asOfVersionId, JSON.stringify(state.pins ?? {}), state.definitionVersionId],
  );
  return { body, key: JSON.stringify(body), definitionVersionId: state.definitionVersionId ?? null };
}
