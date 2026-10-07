/**
 * Every action a reader or an author can take on a dashboard tile, by type.
 *
 * The Guide's "component actions" part reads this to say what each icon does.
 * The row is composed from the same table the chrome draws from
 * (`actionsFor`) plus the actions around it that depend on the tile rather
 * than its type (grouping, inspector, catalog, description) and the ones a
 * renderer adds to the row itself (load all, viz settings, show data). Icons,
 * colours and labels come from `actionStyles`, which the buttons read too.
 *
 * What a renderer draws inside the tile (Plotly's toolbar, a table's column
 * headers, a card's hover) is not in any table the code shares, so it is
 * written out here, next to the row it complements.
 */

import {
  EDIT_MENU_STYLE,
  TILE_ACTION_STYLE,
  type EditMenuStyleKey,
  type TileActionStyle,
  type TileActionStyleKey,
} from '../components/chrome/actionStyles';
import { actionsFor, canDuplicate } from '../components/chrome/chromeActions';
import { canCopyToTab } from '../components/copyToTab';
import { canHighlight } from '../components/highlightTile';

export type GuideTileType =
  | 'figure'
  | 'card'
  | 'table'
  | 'map'
  | 'multiqc'
  | 'advanced_viz'
  | 'text'
  | 'image'
  | 'interactive';

/** The types the Guide offers, in the order its switch lists them. */
export const GUIDE_TILE_TYPES: readonly GuideTileType[] = [
  'figure',
  'card',
  'table',
  'map',
  'multiqc',
  'advanced_viz',
  'text',
  'image',
  'interactive',
];

/** One action of a tile's hover row. */
export interface GuideRowAction extends TileActionStyle {
  key: TileActionStyleKey;
  /** What it does, in one line. */
  meaning: string;
  /** When the tile shows it; absent when it always does. */
  when?: string;
}

/** Something the renderer draws inside the tile rather than in the row. */
export interface GuideOwnControl {
  icon: string;
  label: string;
  meaning: string;
  /**
   * Where it is in a live tile, as a selector inside the tile: what the Guide
   * rings when a reader points at the line. Absent where the control has no
   * element of its own (a gesture), or none worth pointing at.
   */
  target?: string;
  /** Only on a tile with selection on: Plotly's toolbar carries its select
   *  buttons either way, so the element alone does not say it works. */
  selection?: true;
}

/** Plotly's own toolbar buttons, by the title Plotly gives them. */
const modebarButton = (title: string) => `.modebar-btn[data-title="${title}"]`;

export interface GuideEditAction extends TileActionStyle {
  key: EditMenuStyleKey | 'drag' | 'resize';
  meaning: string;
  when?: string;
}

// ---------------------------------------------------------------------------
// The hover row
// ---------------------------------------------------------------------------

const MEANING: Record<TileActionStyleKey, string> = {
  group: 'Marks a tile a selection can be made on; with a selection, saves it as a group.',
  inspect: 'Opens the component in the inspector beside the page.',
  catalog: 'The tools-catalog recipe the component came from.',
  description: "The author's note on what the component shows.",
  metadata: 'Where the data comes from: data collection, columns and settings.',
  fullscreen: 'Fills the screen with the tile; Esc or the same icon brings it back.',
  download: 'Saves the rows the table shows, filters applied, as a CSV file.',
  reset: 'Clears the selection made on the tile. Orange, and on screen, while it filters.',
  drag: 'Grab it to move the tile.',
  loadAll: 'Draws every point or row instead of the sample shown; may be slow.',
  settings: 'Display options for this view only: metric, scale, colours, sizes.',
  data: 'The rows behind the view, in a table you can sort and filter.',
  source: 'Opens the tab the view comes from.',
  menu: "The editor's menu for the tile.",
};

/** Whether a selection can be made on a tile of this type, and how. */
const SELECTION_WHEN: Partial<Record<GuideTileType, string>> = {
  figure: 'Scatter plots with selection on',
  table: 'Tables with row selection on',
  map: 'Maps with selection on',
  image: 'Image grids with selection on',
  advanced_viz: 'Views with selection on',
};

/** Actions a renderer adds to the row, after the chrome's own, in its order. */
const EXTRAS: Partial<
  Record<GuideTileType, { key: TileActionStyleKey; when?: string; meaning?: string }[]>
> = {
  figure: [
    { key: 'loadAll', when: 'When the figure shows a sample of its points' },
    // `link: tab:<name>` (FigureBlock). The minimal style draws the same link
    // in the figure's header instead, listed with what is inside the tile.
    {
      key: 'source',
      when: 'Figures linked to a tab, in the default style',
      meaning: 'Opens the tab the figure sums up.',
    },
  ],
  table: [{ key: 'loadAll', when: 'When the table shows a page of its rows' }],
  map: [{ key: 'settings', when: 'Once the map has drawn' }, { key: 'data' }],
  advanced_viz: [
    { key: 'settings', when: 'Views with options' },
    { key: 'data' },
    { key: 'loadAll', when: 'When the data was reduced' },
    { key: 'source', when: 'Highlighted from another tab' },
  ],
};

const action = (key: TileActionStyleKey, when?: string, meaning = MEANING[key]): GuideRowAction => ({
  key,
  ...(TILE_ACTION_STYLE[key] as TileActionStyle),
  meaning,
  ...(when ? { when } : {}),
});

/**
 * The hover row of a tile of `type`, left to right as `ComponentChrome` draws
 * it, with the conditions under which each action is there.
 */
export function rowActionsFor(type: GuideTileType): GuideRowAction[] {
  const selection = SELECTION_WHEN[type];
  const out: GuideRowAction[] = [];
  if (selection) out.push(action('group', `With Analysis on · ${selection.toLowerCase()}`));
  out.push(action('inspect', 'With the inspector on'));
  out.push(action('catalog', 'Tiles added from the tools catalog'));
  // An advanced view prints its description under its title; only the minimal
  // style's header, which shows the short subtitle there, leaves it to the icon.
  out.push(
    action(
      'description',
      type === 'advanced_viz'
        ? 'In the minimal style, when the author wrote one'
        : 'When the author wrote one',
    ),
  );
  for (const key of actionsFor(type)) {
    if (key === 'reset') {
      if (type === 'interactive') {
        out.push(action('reset', undefined, 'Clears the value picked in this filter.'));
      } else if (selection) {
        out.push(action('reset', selection));
      }
    } else if (key === 'download') {
      out.push(action('download'));
    } else if (key === 'metadata' || key === 'fullscreen') {
      out.push(action(key));
    }
  }
  for (const extra of EXTRAS[type] ?? []) out.push(action(extra.key, extra.when, extra.meaning));
  return out;
}

// ---------------------------------------------------------------------------
// What the renderer draws inside the tile
// ---------------------------------------------------------------------------

const PLOT_TOOLBAR: GuideOwnControl[] = [
  {
    icon: 'mdi:magnify-plus-outline',
    label: 'Zoom and pan',
    meaning: "Plotly's toolbar, top right on hover: drag to zoom, then pan; double-click resets.",
    target: `${modebarButton('Zoom')}, ${modebarButton('Pan')}, .modebar-group`,
  },
  {
    icon: 'mdi:camera-outline',
    label: 'Download image',
    meaning: 'The camera in the same toolbar saves the plot as a PNG.',
    target: '.modebar-btn[data-title^="Download plot"]',
  },
  {
    icon: 'mdi:format-list-bulleted',
    label: 'Legend',
    meaning: 'Click an entry to hide it, double-click to show it alone.',
    target: '.legend',
  },
];

const LASSO = `${modebarButton('Lasso Select')}, ${modebarButton('Box Select')}`;

const OWN: Record<GuideTileType, GuideOwnControl[]> = {
  figure: [
    ...PLOT_TOOLBAR,
    {
      icon: 'mdi:lasso',
      label: 'Lasso or box select',
      meaning: 'On a scatter plot with selection on, the points you draw around filter the tab.',
      target: LASSO,
      selection: true,
    },
    {
      icon: 'mdi:arrow-top-right',
      label: 'Link to a tab',
      meaning: 'A figure that sums up a tab, or comes from one, links to it from its header.',
      target: '.depictio-figure-header-source',
    },
  ],
  card: [
    {
      icon: 'mdi:cursor-default-outline',
      label: 'Hover the title',
      meaning: "How the number is computed, and the author's note.",
      target: '.depictio-card .mantine-Card-section',
    },
    {
      icon: 'mdi:chart-box-outline',
      label: 'The strip under the value',
      meaning: 'The distribution or the top values behind the number, when the card has one.',
      target: '.depictio-card .mantine-Card-section + *',
    },
    {
      icon: 'mdi:arrow-top-right',
      label: 'Link to a tab',
      meaning: 'A card the author linked opens the tab that explains it.',
      target: 'a.depictio-card-link',
    },
  ],
  table: [
    {
      icon: 'mdi:sort',
      label: 'Sort and filter columns',
      meaning: "Click a header to sort; its menu filters the column. Drag a header's edge to resize.",
      target: '.ag-header-row-column',
    },
    {
      icon: 'mdi:checkbox-marked-outline',
      label: 'Select rows',
      meaning: 'With row selection on, the rows you tick filter the rest of the tab.',
      target: '.ag-pinned-left-cols-container, .ag-selection-checkbox',
    },
  ],
  map: [
    {
      icon: 'mdi:magnify-plus-outline',
      label: 'Zoom and pan',
      meaning: 'Scroll to zoom, drag to pan; the toolbar on hover resets the view.',
      target: '.modebar-group, .maplibregl-ctrl-group',
    },
    {
      icon: 'mdi:lasso',
      label: 'Lasso or click',
      meaning: 'With selection on, the stations you draw around or click filter the tab.',
      target: LASSO,
      selection: true,
    },
  ],
  multiqc: [
    ...PLOT_TOOLBAR.slice(0, 2),
    {
      icon: 'mdi:toggle-switch-outline',
      label: 'General statistics',
      meaning: 'Switch between reads (Mean, R1, R2) and between a table and violins.',
      target: '.mantine-SegmentedControl-root',
    },
  ],
  advanced_viz: [
    ...PLOT_TOOLBAR.slice(0, 2),
    {
      icon: 'mdi:lasso',
      label: 'Select',
      meaning: 'On views with selection on (an embedding, a Manhattan), a selection filters the tab.',
      target: LASSO,
      selection: true,
    },
  ],
  text: [
    {
      icon: 'mdi:link-variant',
      label: 'Links to tabs',
      meaning: 'A link to another tab opens it; middle-click opens it in a new browser tab.',
      target: 'a[href]',
    },
  ],
  image: [
    {
      icon: 'mdi:sort-ascending',
      label: 'Sort the grid',
      meaning: 'By a column of the data, in either direction.',
      target: '.mantine-Select-root',
    },
    {
      icon: 'mdi:magnify',
      label: 'Preview',
      meaning: 'Opens the image full size; with selection on, a click selects it instead.',
      target: 'img',
    },
  ],
  interactive: [
    {
      icon: 'mdi:form-dropdown',
      label: 'Pick values',
      meaning: 'Every component reading the same data follows; the panel counts what is set.',
      target: '.mantine-InputWrapper-root, .mantine-Slider-root, .mantine-SegmentedControl-root',
    },
  ],
};

export function ownControlsFor(type: GuideTileType): GuideOwnControl[] {
  return OWN[type];
}

// ---------------------------------------------------------------------------
// The editor
// ---------------------------------------------------------------------------

const EDIT_MEANING: Record<GuideEditAction['key'], string> = {
  drag: 'Grab the grip to move the tile.',
  resize: 'Drag the bottom-right corner to resize it.',
  edit: 'Opens the component in the builder.',
  duplicate: 'Adds a copy beside it.',
  'move-section': "Files it under another of the tab's sections, or none.",
  'copy-tab': 'Puts a copy on another tab of the dashboard.',
  highlight: 'Shows it on another tab, restyled; edits made here show there too.',
  'font-size': "The figure's own text size, on top of the reader's setting.",
  delete: 'Removes it from the tab.',
};

/**
 * What an author can do to a tile in the editor: the grip, the resize corner,
 * then the ⋮ menu in its order (`GridItemEditOverlay`). With `type`, only what
 * that type's menu offers; without, everything, each with when it shows.
 */
export function editActionsFor(
  type?: GuideTileType,
  ctx: { hasSections?: boolean; hasOtherTabs?: boolean } = {},
): GuideEditAction[] {
  const { hasSections = true, hasOtherTabs = true } = ctx;
  const all: GuideEditAction[] = [
    { key: 'drag', ...(TILE_ACTION_STYLE.drag as TileActionStyle), meaning: EDIT_MEANING.drag },
    {
      key: 'resize',
      icon: 'mdi:resize-bottom-right',
      color: 'gray',
      label: 'Resize',
      meaning: EDIT_MEANING.resize,
    },
  ];
  const menu = (key: EditMenuStyleKey, show: boolean, when?: string) => {
    if (!show) return;
    all.push({
      key,
      ...(EDIT_MENU_STYLE[key] as TileActionStyle),
      meaning: EDIT_MEANING[key],
      ...(when ? { when } : {}),
    });
  };
  const has = (pred: (t: string) => boolean) => (type ? pred(type) : true);
  menu('edit', true);
  menu('duplicate', has(canDuplicate), type ? undefined : 'Cards, filters and figures');
  menu('move-section', hasSections, 'When the tab has sections');
  menu(
    'copy-tab',
    hasOtherTabs && has((t) => canCopyToTab({ component_type: t })),
    type ? undefined : 'Every tile but filters',
  );
  menu(
    'highlight',
    hasOtherTabs && has((t) => canHighlight({ component_type: t })),
    type ? undefined : 'Figures and advanced views',
  );
  menu('font-size', has((t) => t === 'figure'), type ? undefined : 'Figures');
  menu('delete', true);
  return all;
}
