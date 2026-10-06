/**
 * Copying a component onto a sibling tab, as a pure transform of that tab's
 * dashboard document.
 *
 * The editor's "Copy to tab…" fetches the target tab, hands it here with the
 * component, and saves what comes back. Kept free of React and of the network
 * so the placement rules can be tested: they are what decides whether the copy
 * lands where the author will look for it.
 */
import type { Layout } from 'react-grid-layout';

import type { DashboardData, StoredMetadata } from '../api';
import { extractLayoutItems, stripBoxPrefix } from '../utils/leftPanelLayout';

/**
 * Component types a copy works for on another tab. Interactive controls are
 * left out: a filter acts on its own tab's components, the value it holds is
 * that tab's state, a grouped control would arrive without the rest of its
 * group card, and a persistent filter section is already how a filter is
 * shared across tabs. A floating map is left out too: it lives in the
 * family-wide map panel, not in a tab's grid.
 */
const COPYABLE_TYPES = new Set([
  'text',
  'card',
  'figure',
  'table',
  'image',
  'map',
  'multiqc',
  'advanced_viz',
]);

export function canCopyToTab(m: Pick<StoredMetadata, 'component_type' | 'placement'>): boolean {
  if (!COPYABLE_TYPES.has(m.component_type)) return false;
  return !(m.component_type === 'map' && m.placement === 'floating');
}

/** Size of the copy when the source has no layout entry to borrow it from. */
const DEFAULT_SIZE = { w: 6, h: 4 };

/** The row under everything a layout array holds. */
function bottomOf(items: Layout[]): number {
  return items.reduce((max, it) => Math.max(max, (Number(it.y) || 0) + (Number(it.h) || 0)), 0);
}

/**
 * Append `entry` under everything else, in an array layout or in each
 * breakpoint of a breakpoint-keyed one (each at its own bottom), keeping the
 * container's shape.
 */
function appendAtBottom(layoutData: unknown, entry: Omit<Layout, 'y'>): unknown {
  const place = (items: Layout[]) => [...items, { ...entry, y: bottomOf(items) } as Layout];
  if (!layoutData || Array.isArray(layoutData)) {
    return place((layoutData as Layout[] | null) ?? []);
  }
  if (typeof layoutData === 'object') {
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(layoutData as Record<string, unknown>)) {
      out[key] = Array.isArray(value) ? place(value as Layout[]) : value;
    }
    return out;
  }
  return place([]);
}

/** Grid section names the target tab has, declared or only used. */
function gridSectionNames(target: DashboardData): Set<string> {
  const names = new Set((target.grid_sections ?? []).map((s) => s.name));
  for (const m of target.stored_metadata ?? []) {
    if (m.component_type !== 'interactive' && typeof m.section === 'string' && m.section.trim()) {
      names.add(m.section.trim());
    }
  }
  return names;
}

/** `base`, or `base-2`, `base-3`… whichever no component of the tab uses. */
function freeTag(base: string, taken: Set<string>): string {
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base}-${n}`)) n += 1;
  return `${base}-${n}`;
}

export interface CopyToTabInput {
  /** The component as stored on its own tab. */
  source: StoredMetadata;
  /** The source tab's `right_panel_layout_data`, to borrow the copy's size. */
  sourceLayoutData: unknown;
  /** The tab copied to, as fetched. */
  target: DashboardData;
  /** The copy's index, a fresh UUID. */
  newId: string;
}

/**
 * The target tab with a copy of `source` added: a new index (and a new tag if
 * the source had one), every other field kept, at the bottom of the grid with
 * the source's width, height and column. It keeps its section if the target
 * tab has one of that name, and is unsectioned otherwise.
 */
export function copyComponentToTab({
  source,
  sourceLayoutData,
  target,
  newId,
}: CopyToTabInput): { dashboard: DashboardData; component: StoredMetadata } {
  // A JSON round trip, not a shallow spread: the copy must share no nested
  // object (dict_kwargs, config…) with the source, and it is JSON that the
  // save sends anyway.
  const component = JSON.parse(JSON.stringify(source)) as StoredMetadata;
  component.index = newId;
  // Mongo-side identifiers riding along would make the copy look like the
  // source document to the backend.
  const scratch = component as Record<string, unknown>;
  delete scratch._id;
  delete scratch.id;

  const metadata = target.stored_metadata ?? [];
  if (typeof source.tag === 'string' && source.tag) {
    const taken = new Set(metadata.map((m) => m.tag).filter((t): t is string => typeof t === 'string'));
    component.tag = freeTag(`${source.tag}-copy`, taken);
  }

  const section = typeof source.section === 'string' ? source.section.trim() : '';
  if (!section || !gridSectionNames(target).has(section)) delete component.section;

  const from = extractLayoutItems(sourceLayoutData).find(
    (it) => stripBoxPrefix(String(it.i)) === source.index,
  );
  const entry = {
    i: `box-${newId}`,
    x: from?.x ?? 0,
    w: from?.w ?? DEFAULT_SIZE.w,
    h: from?.h ?? DEFAULT_SIZE.h,
  };

  return {
    component,
    dashboard: {
      ...target,
      stored_metadata: [...metadata, component],
      right_panel_layout_data: appendAtBottom(target.right_panel_layout_data, entry),
    },
  };
}
