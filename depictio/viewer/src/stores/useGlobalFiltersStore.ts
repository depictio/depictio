/**
 * Global Filters + Journeys store — survives tab navigation within a
 * dashboard family.
 *
 * Per-tab interactive filters reset when the user clicks into a sibling tab
 * (see App.tsx — every dashboard fetch reseeds the local filter array). This
 * store sits one level above that lifecycle: it is keyed on the *parent*
 * dashboard ID so child tabs of the same multi-tab dashboard share the same
 * promoted filters, journeys, and per-user values.
 *
 * Journeys here are the new declarative pin-based funnels: each step is a
 * filter pin (global or local). No per-step snapshots — the user's current
 * filter values flow through the pinned chain to produce live row counts.
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
  type FunnelStep,
  type GlobalFilterDef,
  type Journey,
} from 'depictio-react-core';

interface PatchTimers {
  values: Record<string, ReturnType<typeof setTimeout> | undefined>;
}

export interface PinDescriptor {
  scope: 'global' | 'local';
  tab_id: string;
  global_filter_id?: string;
  component_index?: string;
  label?: string;
  order_within_tab?: number;
  /** dc_id of the component being pinned. Required for local pins on
   *  multi-DC tabs so the backend applies the filter to the right DC.
   *  Globals don't need it — `_step_applies_to_target` uses
   *  `GlobalFilterDef.links[].dc_id` for them. */
  source_dc_id?: string;
}

interface GlobalFiltersStoreState {
  parentDashboardId: string | null;
  definitions: GlobalFilterDef[];
  values: Record<string, unknown>;

  journeys: Journey[];
  activeJourneyId: string | null;

  hydrated: boolean;
  _timers: PatchTimers;

  hydrate: (parentDashboardId: string) => Promise<void>;

  setValue: (filterId: string, value: unknown) => void;
  promote: (def: GlobalFilterDef) => Promise<void>;
  demote: (filterId: string) => Promise<void>;

  upsertJourneyDef: (journey: Journey) => Promise<void>;
  removeJourney: (journeyId: string) => Promise<void>;

  setActiveJourney: (journeyId: string | null) => void;

  /** Pin a filter as a new step on the active funnel.
   *
   * Creates a default funnel if none exists and activates it. The new step
   * is appended at the end of its tab's block in the steps list; the
   * server runs the final tab-order resort on upsert. */
  pinFilterToActiveFunnel: (pin: PinDescriptor) => Promise<void>;

  /** Remove the matching step from the active funnel. Matches by
   *  step id, or by (scope, ref) when stepId is omitted. */
  unpinFilterFromActiveFunnel: (matcher: {
    stepId?: string;
    scope?: 'global' | 'local';
    global_filter_id?: string;
    tab_id?: string;
    component_index?: string;
  }) => Promise<void>;

  /** Swap a step with its neighbor in the same tab. No-op at tab
   *  boundaries (the funnel modal's Steps panel disables the affordance). */
  reorderStepWithinTab: (
    journeyId: string,
    stepId: string,
    direction: 'up' | 'down',
  ) => Promise<void>;

  /** UI helper: is this filter currently a step in the active funnel? */
  isFilterPinned: (matcher: {
    scope: 'global' | 'local';
    global_filter_id?: string;
    tab_id?: string;
    component_index?: string;
  }) => boolean;

  reset: () => void;
}

const DEBOUNCE_MS = 300;

function genId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36).slice(-4)}`;
}

function stepMatches(
  step: FunnelStep,
  matcher: {
    scope?: 'global' | 'local';
    global_filter_id?: string;
    tab_id?: string;
    component_index?: string;
  },
): boolean {
  if (matcher.scope && step.scope !== matcher.scope) return false;
  if (step.scope === 'global') {
    // Require the matcher to name a specific global_filter_id. A bare
    // `{ scope: 'global' }` would otherwise match every global step in the
    // funnel — a footgun if `unpinFilterFromActiveFunnel({ scope: 'global' })`
    // is ever called without the id (the interface allows it).
    if (!matcher.global_filter_id) return false;
    return step.global_filter_id === matcher.global_filter_id;
  }
  // local — require both tab_id and component_index for a positive match.
  // Same reasoning: a bare `{ scope: 'local' }` would otherwise sweep up
  // every local step.
  if (!matcher.tab_id || !matcher.component_index) return false;
  if (step.tab_id !== matcher.tab_id) return false;
  return step.component_index === matcher.component_index;
}

/** Active funnel = journey matching `activeJourneyId`, or the first one
 *  defined (default-pick policy). Null when no journeys exist yet. */
function pickActiveFunnel(state: GlobalFiltersStoreState): Journey | null {
  return (
    state.journeys.find((j) => j.id === state.activeJourneyId) ??
    state.journeys[0] ??
    null
  );
}

/** Sentinel error thrown by `pinFilterToActiveFunnel` when there is no
 *  funnel for the step to land in. The host (App.tsx) catches it and
 *  surfaces a "Create funnel" CTA — we deliberately do NOT auto-create
 *  a placeholder-named funnel because users want to name funnels
 *  intentionally. */
export class NoActiveFunnelError extends Error {
  constructor() {
    super('No active funnel — create one in Settings → Funnels first.');
    this.name = 'NoActiveFunnelError';
  }
}

export const useGlobalFiltersStore = create<GlobalFiltersStoreState>((set, get) => ({
  parentDashboardId: null,
  definitions: [],
  values: {},
  journeys: [],
  activeJourneyId: null,
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
    });
    try {
      const state = await fetchGlobalFiltersState(parentDashboardId);
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
    set((s) => ({
      journeys: s.journeys.filter((j) => j.id !== journeyId),
      activeJourneyId: s.activeJourneyId === journeyId ? null : s.activeJourneyId,
    }));
  },

  setActiveJourney: (journeyId) => {
    const { parentDashboardId } = get();
    set({ activeJourneyId: journeyId });
    if (parentDashboardId) {
      void patchActiveJourney(parentDashboardId, journeyId).catch((err) => {
        console.warn('Failed to persist active journey:', err);
      });
    }
  },

  pinFilterToActiveFunnel: async (pin) => {
    const state = get();
    if (!state.parentDashboardId) {
      throw new Error('No parent dashboard hydrated; cannot pin filter.');
    }
    const funnel = pickActiveFunnel(state);
    if (!funnel) {
      throw new NoActiveFunnelError();
    }
    const { parentDashboardId } = state;

    // Insert at the end of this step's tab block so the server's resort is
    // a no-op in the common case.
    const sameTabSteps = funnel.steps.filter((s) => s.tab_id === pin.tab_id);
    const orderWithinTab =
      pin.order_within_tab ??
      (sameTabSteps.length === 0
        ? 0
        : Math.max(...sameTabSteps.map((s) => s.order_within_tab)) + 1);

    const newStep: FunnelStep = {
      id: genId('step'),
      scope: pin.scope,
      tab_id: pin.tab_id,
      global_filter_id: pin.scope === 'global' ? (pin.global_filter_id ?? null) : null,
      component_index: pin.scope === 'local' ? (pin.component_index ?? null) : null,
      order_within_tab: orderWithinTab,
      label: pin.label ?? null,
      source_dc_id: pin.scope === 'local' ? (pin.source_dc_id ?? null) : null,
    };

    // Append in tab order: find the last step whose tab_id matches and insert
    // right after it. If no match, append at end (server resort will fix).
    const idx = funnel.steps.map((s) => s.tab_id).lastIndexOf(pin.tab_id);
    const nextSteps =
      idx >= 0
        ? [...funnel.steps.slice(0, idx + 1), newStep, ...funnel.steps.slice(idx + 1)]
        : [...funnel.steps, newStep];

    const updated: Journey = { ...funnel, steps: nextSteps };
    await upsertJourney(parentDashboardId, updated);
    set((s) => ({
      journeys: s.journeys.map((j) => (j.id === updated.id ? updated : j)),
    }));
  },

  unpinFilterFromActiveFunnel: async (matcher) => {
    const state = get();
    if (!state.parentDashboardId) return;
    const funnel = pickActiveFunnel(state);
    if (!funnel) return;
    const { parentDashboardId } = state;

    const nextSteps = funnel.steps.filter((step) => {
      if (matcher.stepId) return step.id !== matcher.stepId;
      return !stepMatches(step, matcher);
    });
    if (nextSteps.length === funnel.steps.length) return; // no change

    const updated: Journey = { ...funnel, steps: nextSteps };
    await upsertJourney(parentDashboardId, updated);
    set((s) => ({
      journeys: s.journeys.map((j) => (j.id === updated.id ? updated : j)),
    }));
  },

  reorderStepWithinTab: async (journeyId, stepId, direction) => {
    const { parentDashboardId, journeys } = get();
    if (!parentDashboardId) return;
    const funnel = journeys.find((j) => j.id === journeyId);
    if (!funnel) return;

    const idx = funnel.steps.findIndex((s) => s.id === stepId);
    if (idx < 0) return;
    const me = funnel.steps[idx];
    const neighborIdx = direction === 'up' ? idx - 1 : idx + 1;
    if (neighborIdx < 0 || neighborIdx >= funnel.steps.length) return;
    const neighbor = funnel.steps[neighborIdx];
    if (neighbor.tab_id !== me.tab_id) return; // can't cross tabs

    // Swap order_within_tab values + positions.
    const nextSteps = funnel.steps.slice();
    nextSteps[idx] = { ...neighbor, order_within_tab: me.order_within_tab };
    nextSteps[neighborIdx] = { ...me, order_within_tab: neighbor.order_within_tab };

    const updated: Journey = { ...funnel, steps: nextSteps };
    await upsertJourney(parentDashboardId, updated);
    set((s) => ({
      journeys: s.journeys.map((j) => (j.id === updated.id ? updated : j)),
    }));
  },

  isFilterPinned: (matcher) => {
    const funnel = pickActiveFunnel(get());
    if (!funnel) return false;
    return funnel.steps.some((step) => stepMatches(step, matcher));
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
      hydrated: false,
      _timers: { values: {} },
    });
  },
}));
