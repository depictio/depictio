/**
 * Filters the interactive controls in the Visualizations step apply to every
 * other preview, as on a dashboard. Session-only (never persisted, never
 * exported): they exist to show the author how the components react.
 */
import { create } from 'zustand';
import type { InteractiveFilter } from 'depictio-react-core';

const isEmpty = (v: unknown) =>
  v == null || v === '' || (Array.isArray(v) && v.length === 0);

interface PreviewFilters {
  filters: InteractiveFilter[];
  /** Replace the filter of one control (by its component index); an empty value removes it. */
  upsert: (f: InteractiveFilter) => void;
  clear: () => void;
}

export const usePreviewFilters = create<PreviewFilters>((set) => ({
  filters: [],
  upsert: (f) =>
    set((s) => ({
      filters: isEmpty(f.value) ? s.filters.filter((x) => x.index !== f.index) : [...s.filters.filter((x) => x.index !== f.index), f],
    })),
  clear: () => set({ filters: [] }),
}));
