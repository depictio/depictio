/**
 * The colours of "what changed", one meaning each, wherever it shows: the
 * What's new panels, the notifications bell, the project timeline, and the
 * run scopes of the version history (epic #1399).
 *
 * - new (a run, the "New" side of the dashboard view): the primary blue
 * - data rewritten or recomputed: teal
 * - the dashboard's definition: violet
 * - discussion: pink
 * - something went wrong: orange (emptied, partial) and red (failed)
 * - neutral (a pipeline statistic, abandoned): gray
 *
 * Mantine colour names, never hex: the theme (and dark mode) resolves them.
 */
export const CHANGE_COLOR = {
  new: 'blue',
  data: 'teal',
  dashboard: 'violet',
  comment: 'pink',
  warning: 'orange',
  failed: 'red',
  neutral: 'gray',
} as const;

/** How a recipe output relates to the runs, in the colours above. */
export const SCOPE_COLOR = {
  run: CHANGE_COLOR.new,
  aggregate: CHANGE_COLOR.data,
  pipeline: CHANGE_COLOR.neutral,
} as const;
