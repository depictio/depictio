/**
 * The continuous colour scales every advanced-viz renderer that exposes one
 * offers. Single definition on the React side; its Python twin is `ColourScale`
 * in depictio/models/components/advanced_viz/configs.py and must list the same
 * names in the same order, because a persisted config value is validated there.
 */
export const COLOUR_SCALES = [
  'Viridis',
  'Plasma',
  'Inferno',
  'Magma',
  'Cividis',
  'RdBu',
  'Spectral',
] as const;

export type ColourScale = (typeof COLOUR_SCALES)[number];
