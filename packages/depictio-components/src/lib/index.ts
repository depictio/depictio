/**
 * Depictio shared React components.
 *
 * Re-exports everything needed by:
 *   1. The Dash editor (via auto-generated Python wrappers — Dash consumes the
 *      compiled bundle from `depictio_components/depictio_components.min.js`).
 *   2. The React viewer SPA (via TypeScript workspace link — imports these
 *      source files directly for tree-shaking + type safety).
 */

export { default as DepictioCard } from './components/DepictioCard';
export { default as DepictioMultiSelect } from './components/DepictioMultiSelect';
export { default as DepictioRangeSlider } from './components/DepictioRangeSlider';

export type {
  DepictioCardProps,
  SecondaryMetric,
  CardComparison,
} from './components/DepictioCard';

export type {
  DepictioMultiSelectProps,
  MultiSelectOption,
} from './components/DepictioMultiSelect';

export type { DepictioRangeSliderProps } from './components/DepictioRangeSlider';

// Window-global registration for Dash's component-suites loader. Dash looks
// up components by `library.componentName` at runtime; attaching here lets
// Python wrappers reference `depictio_components.DepictioCard` without the
// component file needing a lifecycle import.
import DepictioCard from './components/DepictioCard';
import DepictioMultiSelect from './components/DepictioMultiSelect';
import DepictioRangeSlider from './components/DepictioRangeSlider';

if (typeof window !== 'undefined') {
  const w = window as unknown as Record<string, unknown>;
  const existing =
    (w.depictio_components as Record<string, unknown>) || {};
  w.depictio_components = {
    ...existing,
    DepictioCard,
    DepictioMultiSelect,
    DepictioRangeSlider,
  };
}
