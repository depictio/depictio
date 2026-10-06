/**
 * How each tile action looks: its icon, its colour and its label, stated once.
 *
 * The chrome's buttons, the actions renderers add to the row (load all, viz
 * settings, show data, the source-tab link) and the editor's tile menu all read
 * their glyph and colour from here. So does the dashboard Guide, which draws
 * the same actions in its legend: one table rather than a copy per surface is
 * what keeps the Guide from showing an action in a colour the tile does not.
 *
 * Pure data, no React, so the Guide's model and its tests can read it too.
 */

export interface TileActionStyle {
  /** Iconify name, as the control draws it at rest. */
  icon: string;
  /**
   * Mantine colour the control is drawn in (`variant="subtle"` at rest).
   * Absent means the theme's primary colour.
   */
  color?: string;
  /** The control's tooltip, or its menu label. */
  label: string;
}

/** The row a tile shows on hover, in the order the chrome draws it. */
export const TILE_ACTION_STYLE = {
  /** Analysis on: "save selection as group" and its passive marker. Drawn in
   *  the grouping colour (`useGroupingColor`), not a fixed one. */
  group: { icon: 'mdi:select-group', label: 'Save selection as group' },
  inspect: { icon: 'mdi:dock-right', color: 'grape', label: 'Inspect' },
  catalog: { icon: 'mdi:hammer', color: 'violet', label: 'From the tools catalog' },
  description: { icon: 'mdi:text-box-outline', color: 'teal', label: 'About this component' },
  metadata: { icon: 'mdi:information-outline', color: 'cyan', label: 'Component metadata' },
  fullscreen: { icon: 'mdi:fullscreen', color: 'indigo', label: 'Toggle fullscreen' },
  download: { icon: 'mdi:download', color: 'green', label: 'Download CSV' },
  reset: { icon: 'bx:reset', color: 'orange', label: 'Reset selection' },
  drag: { icon: 'mdi:dots-grid', color: 'gray', label: 'Drag to move' },
  loadAll: { icon: 'mdi:database-arrow-down', color: 'gray', label: 'Load all' },
  settings: { icon: 'tabler:adjustments-horizontal', color: 'teal', label: 'Viz settings' },
  data: { icon: 'tabler:table', color: 'violet', label: 'Show data' },
  source: { icon: 'mdi:arrow-top-right', label: 'Open in its tab' },
  /** The editor's per-tile menu trigger. */
  menu: { icon: 'tabler:dots-vertical', label: 'Component actions' },
} as const satisfies Record<string, TileActionStyle>;

export type TileActionStyleKey = keyof typeof TILE_ACTION_STYLE;

/** Second states of two of them: the icon a toggle swaps to while on. */
export const FULLSCREEN_EXIT_ICON = 'mdi:fullscreen-exit';
export const LOAD_ALL_ACTIVE_ICON = 'mdi:arrow-collapse-vertical';

/** The editor's tile menu (`GridItemEditOverlay`), in menu order. */
export const EDIT_MENU_STYLE = {
  edit: { icon: 'tabler:edit', label: 'Edit' },
  duplicate: { icon: 'tabler:copy', label: 'Duplicate' },
  'move-section': { icon: 'mdi:format-list-group', label: 'Move to section' },
  'copy-tab': { icon: 'mdi:content-duplicate', label: 'Copy to tab…' },
  highlight: { icon: 'mdi:star-four-points-outline', label: 'Highlight on…' },
  'font-size': { icon: 'mdi:format-font-size-increase', label: 'Font size' },
  delete: { icon: 'tabler:trash', color: 'red', label: 'Delete' },
} as const satisfies Record<string, TileActionStyle>;

export type EditMenuStyleKey = keyof typeof EDIT_MENU_STYLE;
