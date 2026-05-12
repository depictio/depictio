/**
 * Global Filters store — survives tab navigation within a dashboard family.
 *
 * Per-tab interactive filters reset when the user clicks into a sibling tab
 * (see App.tsx — every dashboard fetch reseeds the local filter array). This
 * store sits one level above that lifecycle: it is keyed on the *parent*
 * dashboard ID so child tabs of the same multi-tab dashboard share the same
 * promoted filters, story selection, and per-user values.
 *
 * Definitions live on the parent dashboard document in MongoDB. Values and
 * the active story live in `user_dashboard_state` per (user, parent
 * dashboard) so collaborators don't overwrite each other.
 */

import { create } from 'zustand';
import {
  deleteGlobalFilter as apiDeleteGlobalFilter,
  deleteStory as apiDeleteStory,
  fetchGlobalFiltersState,
  patchActiveStory,
  patchGlobalFilterValue,
  upsertGlobalFilter,
  upsertStory,
  type GlobalFilterDef,
  type Story,
} from 'depictio-react-core';

interface PatchTimers {
  values: Record<string, ReturnType<typeof setTimeout> | undefined>;
  activeStory?: ReturnType<typeof setTimeout>;
}

interface GlobalFiltersState {
  parentDashboardId: string | null;
  definitions: GlobalFilterDef[];
  values: Record<string, unknown>;
  stories: Story[];
  activeStoryId: string | null;
  hydrated: boolean;

  // Internal: debounce handles per filter id and one for active story.
  _timers: PatchTimers;

  hydrate: (parentDashboardId: string) => Promise<void>;
  setValue: (filterId: string, value: unknown) => void;
  promote: (def: GlobalFilterDef) => Promise<void>;
  demote: (filterId: string) => Promise<void>;
  upsertStoryDef: (story: Story) => Promise<void>;
  removeStory: (storyId: string) => Promise<void>;
  setActiveStory: (storyId: string | null) => void;
  reset: () => void;
}

const DEBOUNCE_MS = 300;

export const useGlobalFiltersStore = create<GlobalFiltersState>((set, get) => ({
  parentDashboardId: null,
  definitions: [],
  values: {},
  stories: [],
  activeStoryId: null,
  hydrated: false,
  _timers: { values: {} },

  hydrate: async (parentDashboardId: string) => {
    // Idempotent: re-hydrating the same parent is a no-op so tab switches
    // within a family don't re-fetch.
    const current = get();
    if (current.parentDashboardId === parentDashboardId && current.hydrated) {
      return;
    }
    set({
      parentDashboardId,
      hydrated: false,
      definitions: [],
      values: {},
      stories: [],
      activeStoryId: null,
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
        stories: state.stories,
        activeStoryId: state.last_active_story_id,
        hydrated: true,
      });
    } catch (err) {
      // A dashboard with no global filters yet returns an empty payload, not
      // an error — so reaching this path means a real network/auth failure.
      // Keep the store empty but hydrated=true so the rail simply doesn't
      // render rather than spinning forever.
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
      // Seed default if not present
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
        // Also strip from any story that pre-promoted this filter
        stories: s.stories.map((st) => ({
          ...st,
          default_global_filter_ids: st.default_global_filter_ids.filter(
            (id) => id !== filterId,
          ),
        })),
      };
    });
  },

  upsertStoryDef: async (story) => {
    const { parentDashboardId } = get();
    if (!parentDashboardId) {
      throw new Error('No parent dashboard hydrated; cannot upsert story.');
    }
    await upsertStory(parentDashboardId, story);
    set((s) => {
      const idx = s.stories.findIndex((st) => st.id === story.id);
      return {
        stories:
          idx >= 0
            ? s.stories.map((st, i) => (i === idx ? story : st))
            : [...s.stories, story],
      };
    });
  },

  removeStory: async (storyId) => {
    const { parentDashboardId } = get();
    if (!parentDashboardId) return;
    await apiDeleteStory(parentDashboardId, storyId);
    set((s) => ({
      stories: s.stories.filter((st) => st.id !== storyId),
      activeStoryId: s.activeStoryId === storyId ? null : s.activeStoryId,
    }));
  },

  setActiveStory: (storyId) => {
    const { parentDashboardId, _timers, stories, definitions, values } = get();
    // Seed any default global filters declared by the story that aren't
    // present yet (no value at all) so its entry point lands with the right
    // scope. We only seed; we never clobber a user-set value.
    let nextValues = values;
    if (storyId) {
      const story = stories.find((s) => s.id === storyId);
      if (story) {
        nextValues = { ...values };
        for (const fid of story.default_global_filter_ids) {
          if (!(fid in nextValues)) {
            const def = definitions.find((d) => d.id === fid);
            if (def && def.default_state !== undefined) {
              nextValues[fid] = def.default_state;
            }
          }
        }
      }
    }
    set({ activeStoryId: storyId, values: nextValues });
    if (!parentDashboardId) return;
    if (_timers.activeStory) clearTimeout(_timers.activeStory);
    _timers.activeStory = setTimeout(() => {
      void patchActiveStory(parentDashboardId, storyId).catch((err) => {
        console.warn('Failed to persist active story:', err);
      });
    }, DEBOUNCE_MS);
  },

  reset: () => {
    const { _timers } = get();
    Object.values(_timers.values).forEach((t) => t && clearTimeout(t));
    if (_timers.activeStory) clearTimeout(_timers.activeStory);
    set({
      parentDashboardId: null,
      definitions: [],
      values: {},
      stories: [],
      activeStoryId: null,
      hydrated: false,
      _timers: { values: {} },
    });
  },
}));
