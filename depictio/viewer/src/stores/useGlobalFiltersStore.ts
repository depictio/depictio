/**
 * Global Filters + Journeys store — survives tab navigation within a
 * dashboard family.
 *
 * Per-tab interactive filters reset when the user clicks into a sibling tab
 * (see App.tsx — every dashboard fetch reseeds the local filter array). This
 * store sits one level above that lifecycle: it is keyed on the *parent*
 * dashboard ID so child tabs of the same multi-tab dashboard share the same
 * promoted filters, journey selection, and per-user values.
 *
 * Definitions (global filters + journeys) live on the parent dashboard
 * document in MongoDB. Values, active journey, and per-journey resume
 * bookkeeping live in `user_dashboard_state` per (user, parent dashboard) so
 * collaborators don't overwrite each other.
 */

import { create } from 'zustand';
import {
  deleteGlobalFilter as apiDeleteGlobalFilter,
  deleteJourney as apiDeleteJourney,
  fetchGlobalFiltersState,
  patchActiveJourney,
  patchGlobalFilterValue,
  upsertGlobalFilter,
  upsertJourney,
  type GlobalFilterDef,
  type InteractiveFilter,
  type Journey,
  type JourneyStop,
} from 'depictio-react-core';

interface PatchTimers {
  values: Record<string, ReturnType<typeof setTimeout> | undefined>;
}

/** Payload emitted to App.tsx when a journey stop is applied. App.tsx is
 *  responsible for navigating to `anchor_tab_id` (if different from current)
 *  and replacing the per-tab `filters` state with `local_filter_state`. */
export interface ApplyStopRequest {
  journeyId: string;
  stop: JourneyStop;
}

interface GlobalFiltersStoreState {
  parentDashboardId: string | null;
  definitions: GlobalFilterDef[];
  values: Record<string, unknown>;

  journeys: Journey[];
  activeJourneyId: string | null;
  activeJourneyStopId: string | null;
  /** Per-journey resume bookkeeping: `{ [journeyId]: lastActiveStopId }`. */
  journeyStops: Record<string, string>;

  hydrated: boolean;
  _timers: PatchTimers;

  hydrate: (parentDashboardId: string) => Promise<void>;

  setValue: (filterId: string, value: unknown) => void;
  promote: (def: GlobalFilterDef) => Promise<void>;
  demote: (filterId: string) => Promise<void>;

  upsertJourneyDef: (journey: Journey) => Promise<void>;
  removeJourney: (journeyId: string) => Promise<void>;

  /** Activate a journey + optionally a specific stop. If `stopId` is null,
   *  resumes the user's last stop for that journey (or the first stop). The
   *  caller is responsible for invoking the returned `ApplyStopRequest` to
   *  navigate / apply per-tab filters. */
  setActiveJourney: (journeyId: string | null, stopId?: string | null) => ApplyStopRequest | null;

  /** Apply a specific stop's snapshot — replaces global values, returns the
   *  request payload App.tsx needs to navigate + replay per-tab filters.
   *  Persists `last_active_journey_stop_id` so refresh resumes here. */
  applyJourneyStop: (journeyId: string, stop: JourneyStop) => ApplyStopRequest;

  /** Save current state as a new stop. If `journeyId` is null, creates a new
   *  journey with this snapshot as Stop 1. Returns the new/updated journey
   *  so the UI can highlight it. */
  saveCurrentAsStop: (args: {
    journeyId: string | null;
    journeyName?: string;
    stopName: string;
    currentDashboardId: string;
    currentLocalFilters: InteractiveFilter[];
  }) => Promise<Journey>;

  reset: () => void;
}

const DEBOUNCE_MS = 300;

function genId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36).slice(-4)}`;
}

export const useGlobalFiltersStore = create<GlobalFiltersStoreState>((set, get) => ({
  parentDashboardId: null,
  definitions: [],
  values: {},
  journeys: [],
  activeJourneyId: null,
  activeJourneyStopId: null,
  journeyStops: {},
  hydrated: false,
  _timers: { values: {} },

  hydrate: async (parentDashboardId: string) => {
    const current = get();
    if (current.parentDashboardId === parentDashboardId && current.hydrated) {
      return;
    }
    set({
      parentDashboardId,
      hydrated: false,
      definitions: [],
      values: {},
      journeys: [],
      activeJourneyId: null,
      activeJourneyStopId: null,
      journeyStops: {},
    });
    try {
      const state = await fetchGlobalFiltersState(parentDashboardId);
      // Seed values from default_state for any filter without an override.
      const seeded: Record<string, unknown> = { ...state.user_values };
      for (const def of state.definitions) {
        if (!(def.id in seeded) && def.default_state !== undefined) {
          seeded[def.id] = def.default_state;
        }
      }
      set({
        definitions: state.definitions,
        values: seeded,
        journeys: state.journeys,
        activeJourneyId: state.last_active_journey_id,
        activeJourneyStopId: state.last_active_journey_stop_id,
        journeyStops: state.journey_stops ?? {},
        hydrated: true,
      });
    } catch (err) {
      console.warn('useGlobalFiltersStore.hydrate failed:', err);
      set({ hydrated: true });
    }
  },

  setValue: (filterId, value) => {
    const { parentDashboardId, _timers } = get();
    set((s) => ({ values: { ...s.values, [filterId]: value } }));
    if (!parentDashboardId) return;
    if (_timers.values[filterId]) {
      clearTimeout(_timers.values[filterId]);
    }
    _timers.values[filterId] = setTimeout(() => {
      void patchGlobalFilterValue(parentDashboardId, filterId, value).catch((err) => {
        console.warn('Failed to persist global filter value:', err);
      });
    }, DEBOUNCE_MS);
  },

  promote: async (def) => {
    const { parentDashboardId } = get();
    if (!parentDashboardId) {
      throw new Error('No parent dashboard hydrated; cannot promote filter.');
    }
    await upsertGlobalFilter(parentDashboardId, def);
    set((s) => {
      const idx = s.definitions.findIndex((d) => d.id === def.id);
      const definitions =
        idx >= 0
          ? s.definitions.map((d, i) => (i === idx ? def : d))
          : [...s.definitions, def];
      const values = { ...s.values };
      if (!(def.id in values) && def.default_state !== undefined) {
        values[def.id] = def.default_state;
      }
      return { definitions, values };
    });
  },

  demote: async (filterId) => {
    const { parentDashboardId } = get();
    if (!parentDashboardId) return;
    await apiDeleteGlobalFilter(parentDashboardId, filterId);
    set((s) => {
      const values = { ...s.values };
      delete values[filterId];
      return {
        definitions: s.definitions.filter((d) => d.id !== filterId),
        values,
      };
    });
  },

  upsertJourneyDef: async (journey) => {
    const { parentDashboardId } = get();
    if (!parentDashboardId) {
      throw new Error('No parent dashboard hydrated; cannot upsert journey.');
    }
    await upsertJourney(parentDashboardId, journey);
    set((s) => {
      const idx = s.journeys.findIndex((j) => j.id === journey.id);
      return {
        journeys:
          idx >= 0
            ? s.journeys.map((j, i) => (i === idx ? journey : j))
            : [...s.journeys, journey],
      };
    });
  },

  removeJourney: async (journeyId) => {
    const { parentDashboardId } = get();
    if (!parentDashboardId) return;
    await apiDeleteJourney(parentDashboardId, journeyId);
    set((s) => {
      const { [journeyId]: _drop, ...rest } = s.journeyStops;
      void _drop;
      return {
        journeys: s.journeys.filter((j) => j.id !== journeyId),
        activeJourneyId: s.activeJourneyId === journeyId ? null : s.activeJourneyId,
        activeJourneyStopId:
          s.activeJourneyId === journeyId ? null : s.activeJourneyStopId,
        journeyStops: rest,
      };
    });
  },

  setActiveJourney: (journeyId, stopId) => {
    const { parentDashboardId, journeys, journeyStops } = get();

    if (journeyId === null) {
      // Exit journey: clear active state, KEEP current filter values.
      set({ activeJourneyId: null, activeJourneyStopId: null });
      if (parentDashboardId) {
        void patchActiveJourney(parentDashboardId, null, null).catch((err) => {
          console.warn('Failed to clear active journey:', err);
        });
      }
      return null;
    }

    const journey = journeys.find((j) => j.id === journeyId);
    if (!journey || journey.stops.length === 0) return null;

    // Resume bookkeeping: caller-provided stopId > per-journey last-active > first stop.
    const targetStopId = stopId ?? journeyStops[journeyId] ?? journey.stops[0].id;
    const target = journey.stops.find((s) => s.id === targetStopId) ?? journey.stops[0];
    return get().applyJourneyStop(journeyId, target);
  },

  applyJourneyStop: (journeyId, stop) => {
    const { parentDashboardId } = get();
    set((s) => ({
      activeJourneyId: journeyId,
      activeJourneyStopId: stop.id,
      journeyStops: { ...s.journeyStops, [journeyId]: stop.id },
      // Replace global values with the stop's snapshot. Stale keys (filters
      // demoted since the stop was saved) are tolerated by mergeWithGlobal.
      values: { ...stop.global_filter_state },
    }));
    if (parentDashboardId) {
      void patchActiveJourney(parentDashboardId, journeyId, stop.id).catch((err) => {
        console.warn('Failed to persist active journey:', err);
      });
    }
    return { journeyId, stop };
  },

  saveCurrentAsStop: async ({
    journeyId,
    journeyName,
    stopName,
    currentDashboardId,
    currentLocalFilters,
  }) => {
    const { parentDashboardId, journeys, values } = get();
    if (!parentDashboardId) {
      throw new Error('No parent dashboard hydrated; cannot save journey stop.');
    }
    const newStop: JourneyStop = {
      id: genId('stop'),
      name: stopName,
      anchor_tab_id: currentDashboardId,
      // Snapshot of current global values + per-tab local filters.
      global_filter_state: { ...values },
      local_filter_state: currentLocalFilters.map((f) => ({ ...f })),
    };

    let target: Journey;
    if (journeyId === null) {
      target = {
        id: genId('journey'),
        name: journeyName ?? 'New journey',
        stops: [newStop],
        pinned: false,
      };
    } else {
      const existing = journeys.find((j) => j.id === journeyId);
      if (!existing) throw new Error(`Journey ${journeyId} not found.`);
      target = { ...existing, stops: [...existing.stops, newStop] };
    }

    await upsertJourney(parentDashboardId, target);
    set((s) => {
      const idx = s.journeys.findIndex((j) => j.id === target.id);
      const journeys =
        idx >= 0
          ? s.journeys.map((j, i) => (i === idx ? target : j))
          : [...s.journeys, target];
      // Saving a step *into* a journey makes that step the active one — matches
      // user expectation that "save → now I'm on the step I just saved".
      return {
        journeys,
        activeJourneyId: target.id,
        activeJourneyStopId: newStop.id,
        journeyStops: { ...s.journeyStops, [target.id]: newStop.id },
      };
    });
    if (parentDashboardId) {
      void patchActiveJourney(parentDashboardId, target.id, newStop.id).catch((err) => {
        console.warn('Failed to persist active journey after save:', err);
      });
    }
    return target;
  },

  reset: () => {
    const { _timers } = get();
    Object.values(_timers.values).forEach((t) => t && clearTimeout(t));
    set({
      parentDashboardId: null,
      definitions: [],
      values: {},
      journeys: [],
      activeJourneyId: null,
      activeJourneyStopId: null,
      journeyStops: {},
      hydrated: false,
      _timers: { values: {} },
    });
  },
}));
