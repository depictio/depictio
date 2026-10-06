/**
 * What the dashboard Guide says about one tab, read from the dashboard itself.
 *
 * The Guide is generic — every dashboard gets the same parts in the same
 * order — but each part is filled with the tab the reader came from: its real
 * tabs and groups, the filter sections in its panel, the components a
 * selection can be made on, the actions its tiles carry. Building that is pure
 * work on the dashboard documents, so it lives here, away from the React page,
 * where it can be unit-tested (the vitest setup is node-only).
 *
 * Every rule below reads the same predicate the real UI reads — `groupTabs`
 * for the sidebar, `sectionComponents` for the grid and the panel,
 * `actionsFor` / `supportsSelectionGrouping` for the tile chrome — so the
 * Guide cannot describe a control the page does not draw.
 */

import type {
  DashboardSummary,
  FilterSectionSpec,
  FloatingComponent,
  PersistentSection,
  StoredMetadata,
} from '../api';
import { actionsFor } from '../components/chrome/chromeActions';
import { canCopyToTab } from '../components/copyToTab';
import { tabDisplayName } from '../components/tabFamily';
import { groupTabs } from '../components/tabGroups';
import { isMapSelectionEnabled, supportsSelectionGrouping } from '../selection';
import { sectionComponents } from '../utils/groupInteractive';

// ---------------------------------------------------------------------------
// Author settings
// ---------------------------------------------------------------------------

export interface GuideSettings {
  /** Whether the Guide is offered at all (sidebar entry, header icon, route). */
  enabled: boolean;
  /** The author's note for the top of the Guide, trimmed; '' when none. */
  intro: string;
  /** The main tab's id: the document the settings are read from and saved to. */
  mainTabId: string | null;
}

/** The fields the settings are read from, on a dashboard or a summary. Loose
 *  on purpose: the open document is typed with an index signature, and a
 *  server that predates the fields sends neither. */
interface GuideSource {
  dashboard_id?: string;
  parent_dashboard_id?: string | null;
  show_guide?: unknown;
  guide_intro?: unknown;
}

/**
 * The Guide's settings for the family `dashboard` belongs to.
 *
 * They live on the main tab. On the main tab itself the open document is the
 * source, so an author's change shows before the tab list is refetched; on a
 * child tab it is the main tab's entry in the list. A server that predates the
 * fields sends neither, which reads as "on, no intro" — the Guide is opt-out.
 */
export function resolveGuideSettings(
  dashboard: GuideSource | null | undefined,
  tabs: readonly GuideSource[],
): GuideSettings {
  const main = tabs.find((t) => !t.parent_dashboard_id) ?? null;
  const isMain = Boolean(dashboard) && !dashboard?.parent_dashboard_id;
  const source = isMain ? dashboard : main;
  return {
    enabled: source?.show_guide !== false,
    intro: typeof source?.guide_intro === 'string' ? source.guide_intro.trim() : '',
    mainTabId:
      (isMain ? dashboard?.dashboard_id : main?.dashboard_id) ??
      dashboard?.parent_dashboard_id ??
      null,
  };
}

// ---------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------

export interface GuideTab<T extends DashboardSummary = DashboardSummary> {
  tab: T;
  id: string;
  /** The name the sidebar pill shows. */
  label: string;
  /** The tab's one-line description, when it has one. */
  subtitle: string | null;
  isMain: boolean;
  /** The tab the reader opened the Guide from. */
  isCurrent: boolean;
}

export interface GuideTabGroup<T extends DashboardSummary = DashboardSummary> {
  /** The sidebar heading, or null for the main tab and the ungrouped tabs. */
  group: string | null;
  tabs: GuideTab<T>[];
}

/** A section of the tab's canvas. */
export interface GuideGridSection {
  name: string;
  spec?: FilterSectionSpec;
  /** How many components it holds. */
  members: number;
  /** Pinned to every tab of the family (`persistent`). */
  pinned: boolean;
  /** Set when the section is drawn here on behalf of another tab. */
  fromTab: string | null;
}

/** A section of the filter panel. */
export interface GuideFilterSection {
  name: string;
  spec?: FilterSectionSpec;
  /** How many filter controls it holds on this tab. */
  controls: number;
  /** On every tab, its values kept across tab switches. */
  persistent: boolean;
}

export type GuideSelectionKind = 'map' | 'figure' | 'table' | 'image' | 'advanced_viz';

/** A component a selection can be made on, which then filters like a filter. */
export interface GuideSelectionSource {
  index: string;
  title: string;
  kind: GuideSelectionKind;
  /** The family's floating map, reached from the map panel on every tab. */
  floating: boolean;
}

export type GuideActionKey =
  | 'group'
  | 'inspect'
  | 'catalog'
  | 'description'
  | 'metadata'
  | 'fullscreen'
  | 'download'
  | 'reset';

export type GuideEditActionKey =
  | 'drag'
  | 'edit'
  | 'duplicate'
  | 'move-section'
  | 'copy-tab'
  | 'font-size'
  | 'delete';

export interface GuideAction<K extends string = GuideActionKey> {
  key: K;
  /** The icon the real control shows. */
  icon: string;
  /** The real control's tooltip or menu label. */
  label: string;
  /** One line on what it does. */
  meaning: string;
  /** How many components on this tab carry it. */
  count: number;
}

export interface GuideModel<T extends DashboardSummary = DashboardSummary> {
  tabs: {
    groups: GuideTabGroup<T>[];
    /** Every tab of the family, current one included. */
    count: number;
    /** The named groups, in sidebar order. */
    groupNames: string[];
    current: GuideTab<T> | null;
  };
  sections: {
    /** Sections on this tab that fold, in the order the canvas draws them. */
    foldable: GuideGridSection[];
    /** Of those, the ones pinned to every tab. */
    pinned: GuideGridSection[];
    /** Pinned sections drawn here on behalf of another tab: the ones whose
     *  header says "Filtered" and reads their numbers as n / N. */
    fannedOut: GuideGridSection[];
  };
  filters: {
    /** The panel's named sections, in panel order. */
    sections: GuideFilterSection[];
    /** Controls in no section. */
    unsectioned: number;
    /** Every control in the panel. */
    total: number;
    /** The sections pinned to every tab. */
    persistent: GuideFilterSection[];
  };
  /** Where a lasso, box or click can filter the dashboard on this tab. */
  selection: GuideSelectionSource[];
  /** Whether the family has a map panel (a floating map), on every tab. */
  mapPanel: boolean;
  /** Actions the tiles on this tab carry, in the order the chrome draws them;
   *  only those at least one tile here has. */
  actions: GuideAction[];
  /** The editor's per-tile actions (its ⋮ menu); empty outside the editor. */
  editActions: GuideAction<GuideEditActionKey>[];
  analysis: {
    /** The header offers Analysis on this surface. */
    available: boolean;
    /** Tiles here a group can be made from (the ones Analysis outlines). */
    selectable: number;
  };
}

export interface GuideModelInput<T extends DashboardSummary = DashboardSummary> {
  /** The tab family in sidebar order, main tab first. */
  tabs: readonly T[];
  /** The tab the Guide was opened from. */
  currentId: string | null;
  /** The tab's own canvas components (cards, figures, tables, …), as drawn. */
  components: readonly StoredMetadata[];
  /** The tab's `grid_sections`. */
  gridSections?: readonly FilterSectionSpec[] | null;
  /** Pinned grid sections other tabs own, drawn on this one. */
  fannedOutSections?: readonly PersistentSection[];
  /** The filter panel's controls on this tab, fanned-out ones included. */
  panelComponents: readonly StoredMetadata[];
  /** The panel's section specs, fanned-out ones included. */
  panelSections?: readonly FilterSectionSpec[] | null;
  /** The family's floating components (the map panel). */
  floating?: readonly FloatingComponent[];
  /** Whether the header offers Analysis here — pass the header's own condition. */
  analysisAvailable: boolean;
  /** The component inspector is on (its action joins the chrome). */
  inspector?: boolean;
  /** 'edit' adds the editor's per-tile menu. */
  mode?: 'view' | 'edit';
}

// ---------------------------------------------------------------------------
// The actions, as the chrome labels them
// ---------------------------------------------------------------------------

type ActionInfo = Pick<GuideAction, 'icon' | 'label' | 'meaning'>;

/** Labels are the controls' own tooltips (see components/chrome). */
export const GUIDE_ACTIONS: Record<GuideActionKey, ActionInfo> = {
  group: {
    icon: 'mdi:select-group',
    label: 'Save selection as group',
    meaning: 'With Analysis on: marks the tiles you can select on, then keeps a selection as a group.',
  },
  inspect: {
    icon: 'mdi:dock-right',
    label: 'Inspect',
    meaning: 'Opens the component in the inspector on the right.',
  },
  catalog: {
    icon: 'mdi:hammer',
    label: 'From the tools catalog',
    meaning: 'The component came from a catalog recipe; shows which one.',
  },
  description: {
    icon: 'mdi:text-box-outline',
    label: 'About this component',
    meaning: "The author's note on what the component shows.",
  },
  metadata: {
    icon: 'mdi:information-outline',
    label: 'Component metadata',
    meaning: 'Where the data comes from: data collection, columns and settings.',
  },
  fullscreen: {
    icon: 'mdi:fullscreen',
    label: 'Toggle fullscreen',
    meaning: 'Fills the screen with it; Esc or the same icon brings it back.',
  },
  download: {
    icon: 'mdi:download',
    label: 'Download CSV',
    meaning: 'Saves the rows the table shows, filters applied, as a CSV file.',
  },
  reset: {
    icon: 'bx:reset',
    label: 'Reset selection',
    meaning: 'Clears the selection made on it. Turns orange, and stays visible, while it filters.',
  },
};

/** The chrome's left-to-right order (`ComponentChrome`): the grouping action
 *  leads, then the inspector, provenance, prose, and the type's own actions. */
const ACTION_ORDER: GuideActionKey[] = [
  'group',
  'inspect',
  'catalog',
  'description',
  'metadata',
  'fullscreen',
  'download',
  'reset',
];

/** The editor's tile menu (`GridItemEditOverlay`) and the grip beside it. */
export const GUIDE_EDIT_ACTIONS: Record<GuideEditActionKey, ActionInfo> = {
  drag: {
    icon: 'mdi:dots-grid',
    label: 'Drag to move',
    meaning: 'Grab it to move the tile; its edges resize it.',
  },
  edit: {
    icon: 'tabler:edit',
    label: 'Edit',
    meaning: 'Opens the component in the builder.',
  },
  duplicate: {
    icon: 'tabler:copy',
    label: 'Duplicate',
    meaning: 'Adds a copy right below it (cards, filters and figures).',
  },
  'move-section': {
    icon: 'mdi:format-list-group',
    label: 'Move to section',
    meaning: "Files it under another of this tab's sections, or none.",
  },
  'copy-tab': {
    icon: 'mdi:content-duplicate',
    label: 'Copy to tab…',
    meaning: 'Puts a copy on another tab of this dashboard.',
  },
  'font-size': {
    icon: 'mdi:format-font-size-increase',
    label: 'Font size',
    meaning: "The figure's own text size, on top of the reader's setting.",
  },
  delete: {
    icon: 'tabler:trash',
    label: 'Delete',
    meaning: 'Removes it from the tab.',
  },
};

const EDIT_ACTION_ORDER: GuideEditActionKey[] = [
  'drag',
  'edit',
  'duplicate',
  'move-section',
  'copy-tab',
  'font-size',
  'delete',
];

const DUPLICATABLE = new Set(['card', 'interactive', 'figure']);

// ---------------------------------------------------------------------------
// Builders
// ---------------------------------------------------------------------------

function componentTitle(m: StoredMetadata): string {
  const title = typeof m.title === 'string' ? m.title.trim() : '';
  if (title) return title;
  const column = typeof m.column_name === 'string' ? m.column_name : '';
  return column || m.component_type;
}

/** The actions `ComponentChrome` draws on `m`, outside of hover state. */
export function tileActions(
  m: StoredMetadata,
  opts: { analysisAvailable: boolean; inspector?: boolean },
): GuideActionKey[] {
  const out: GuideActionKey[] = [];
  const selectable = supportsSelectionGrouping(m, true);
  if (opts.analysisAvailable && selectable) out.push('group');
  if (opts.inspector) out.push('inspect');
  if (m.catalog_source) out.push('catalog');
  const description = typeof m.description === 'string' ? m.description.trim() : '';
  if (description && m.component_type !== 'advanced_viz') out.push('description');
  for (const a of actionsFor(m.component_type)) {
    if (a === 'metadata' || a === 'fullscreen' || a === 'download') out.push(a);
    // The renderers wire a reset only where a selection can be made.
    else if (a === 'reset' && selectable) out.push('reset');
  }
  return out;
}

function countActions<K extends string>(
  tiles: readonly StoredMetadata[],
  order: readonly K[],
  info: Record<K, ActionInfo>,
  actionsOf: (m: StoredMetadata) => readonly K[],
): GuideAction<K>[] {
  const counts = new Map<K, number>();
  for (const m of tiles) {
    for (const key of new Set(actionsOf(m))) counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return order
    .filter((key) => (counts.get(key) ?? 0) > 0)
    .map((key) => ({ key, ...info[key], count: counts.get(key) ?? 0 }));
}

function selectionKind(m: StoredMetadata): GuideSelectionKind | null {
  switch (m.component_type) {
    case 'map':
    case 'figure':
    case 'table':
    case 'image':
    case 'advanced_viz':
      return supportsSelectionGrouping(m, true) ? m.component_type : null;
    default:
      return null;
  }
}

export function buildGuideModel<T extends DashboardSummary>(
  input: GuideModelInput<T>,
): GuideModel<T> {
  const {
    tabs,
    currentId,
    components,
    gridSections,
    fannedOutSections = [],
    panelComponents,
    panelSections,
    floating = [],
    analysisAvailable,
    inspector = false,
    mode = 'view',
  } = input;

  // Tabs, as the sidebar groups them.
  const groups: GuideTabGroup<T>[] = groupTabs(tabs).map((section) => ({
    group: section.group,
    tabs: section.tabs.map((tab) => ({
      tab,
      id: tab.dashboard_id,
      label: tabDisplayName(tab),
      subtitle: tab.subtitle?.trim() || null,
      isMain: !tab.parent_dashboard_id,
      isCurrent: tab.dashboard_id === currentId,
    })),
  }));
  const current = groups.flatMap((g) => g.tabs).find((t) => t.isCurrent) ?? null;

  // The canvas: the tab's own sections that fold, then the pinned ones other
  // tabs fan out here. A `plain` section is a heading with no fold.
  const ownSections: GuideGridSection[] = sectionComponents(
    [...components],
    [...(gridSections ?? [])],
  )
    .filter((s) => s.sectionName && s.spec?.appearance !== 'plain')
    .map((s) => ({
      name: s.sectionName as string,
      spec: s.spec,
      members: s.members.length,
      pinned: Boolean(s.spec?.persistent),
      fromTab: null,
    }));
  const fannedOut: GuideGridSection[] = fannedOutSections
    .filter((s) => s.kind === 'grid' && s.components.length > 0)
    .map((s) => ({
      name: s.spec.name,
      spec: s.spec,
      members: s.components.length,
      pinned: true,
      fromTab: s.owner_tab_title ?? null,
    }));
  const isTop = (s: GuideGridSection) => s.spec?.pin !== 'bottom';
  const foldable = [
    ...fannedOut.filter(isTop),
    ...ownSections,
    ...fannedOut.filter((s) => !isTop(s)),
  ];

  // The filter panel, bucketed exactly as the panel buckets it.
  const panelBuckets = sectionComponents([...panelComponents], [...(panelSections ?? [])]);
  const filterSections: GuideFilterSection[] = panelBuckets
    .filter((s) => s.sectionName)
    .map((s) => ({
      name: s.sectionName as string,
      spec: s.spec,
      controls: s.members.length,
      persistent: Boolean(s.spec?.persistent),
    }));
  const unsectioned = panelBuckets.find((s) => !s.sectionName)?.members.length ?? 0;

  // Where a selection filters: the tab's selectable tiles, then the map panel.
  const tiles = [...components, ...fannedOutSections.flatMap((s) => s.components.map((c) => c.metadata))];
  const selection: GuideSelectionSource[] = [];
  const seen = new Set<string>();
  for (const m of tiles) {
    const kind = selectionKind(m);
    if (!kind || seen.has(m.index)) continue;
    seen.add(m.index);
    selection.push({ index: m.index, title: componentTitle(m), kind, floating: false });
  }
  for (const f of floating) {
    const m = f.metadata;
    if (seen.has(m.index) || !isMapSelectionEnabled(m, true)) continue;
    seen.add(m.index);
    selection.push({ index: m.index, title: componentTitle(m), kind: 'map', floating: true });
  }

  const actions = countActions(tiles, ACTION_ORDER, GUIDE_ACTIONS, (m) =>
    tileActions(m, { analysisAvailable, inspector }),
  );

  const hasSections = (gridSections ?? []).length > 0;
  const hasOtherTabs = tabs.length > 1;
  const editActions =
    mode === 'edit'
      ? countActions(components, EDIT_ACTION_ORDER, GUIDE_EDIT_ACTIONS, (m) => {
          const keys: GuideEditActionKey[] = ['drag', 'edit'];
          if (DUPLICATABLE.has(m.component_type)) keys.push('duplicate');
          if (hasSections) keys.push('move-section');
          if (hasOtherTabs && canCopyToTab(m)) keys.push('copy-tab');
          if (m.component_type === 'figure') keys.push('font-size');
          keys.push('delete');
          return keys;
        })
      : [];

  return {
    tabs: {
      groups,
      count: tabs.length,
      groupNames: groups.flatMap((g) => (g.group ? [g.group] : [])),
      current,
    },
    sections: {
      foldable,
      pinned: foldable.filter((s) => s.pinned),
      fannedOut,
    },
    filters: {
      sections: filterSections,
      unsectioned,
      total: panelComponents.length,
      persistent: filterSections.filter((s) => s.persistent),
    },
    selection,
    mapPanel: floating.some((f) => f.metadata.component_type === 'map'),
    actions,
    editActions,
    analysis: {
      available: analysisAvailable,
      selectable: tiles.filter((m) => supportsSelectionGrouping(m, true)).length,
    },
  };
}
