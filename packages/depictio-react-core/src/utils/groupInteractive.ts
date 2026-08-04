import type { FilterSectionSpec, StoredMetadata } from '../api';

/**
 * Bucket interactive components into ordered groups.
 *
 * - Components with the same `group` string land in the same bucket and
 *   retain their original ordering within it.
 * - Components without a `group` are returned as singletons (one bucket per
 *   component) so the renderer can treat them uniformly.
 *
 * The first appearance of a group preserves its position in the overall list
 * so YAML order drives sidebar layout.
 */
export interface InteractiveGroup {
  /** Stable key — group name when grouped, component index when singleton. */
  key: string;
  /** Group label rendered as the card title. ``undefined`` for singletons. */
  groupName?: string;
  members: StoredMetadata[];
}

export function groupInteractiveComponents(
  components: StoredMetadata[],
): InteractiveGroup[] {
  const groups: InteractiveGroup[] = [];
  const indexByName = new Map<string, number>();

  for (const m of components) {
    const groupName = typeof m.group === 'string' && m.group ? m.group : undefined;
    if (!groupName) {
      groups.push({ key: m.index, members: [m] });
      continue;
    }
    const existingIdx = indexByName.get(groupName);
    if (existingIdx !== undefined) {
      groups[existingIdx].members.push(m);
    } else {
      indexByName.set(groupName, groups.length);
      groups.push({ key: `group:${groupName}`, groupName, members: [m] });
    }
  }
  return groups;
}

/**
 * Outer level of the filter panel: one bucket per `section`, each holding the
 * groups built by `groupInteractiveComponents`.
 *
 * Components with no `section` collect into a single leading bucket with no
 * name, which the panel renders bare (no accordion header). That is what makes
 * the feature additive: a dashboard that never sets `section` produces exactly
 * one unnamed bucket and renders as it did before sections existed.
 */
export interface InteractiveSection {
  /** Stable key — section name, or `''` for the unsectioned bucket. */
  key: string;
  /** `undefined` for the unsectioned bucket. */
  sectionName?: string;
  spec?: FilterSectionSpec;
  groups: InteractiveGroup[];
}

export function sectionInteractiveComponents(
  components: StoredMetadata[],
  specs: FilterSectionSpec[] = [],
): InteractiveSection[] {
  const specByName = new Map(specs.map((s) => [s.name, s]));

  // Declared sections come first, in declaration order, even when a component
  // for a later-declared one appears earlier in stored_metadata.
  const order: string[] = specs.map((s) => s.name);
  const bucketed = new Map<string, StoredMetadata[]>();
  const unsectioned: StoredMetadata[] = [];

  for (const m of components) {
    const name = typeof m.section === 'string' && m.section ? m.section : undefined;
    if (!name) {
      unsectioned.push(m);
      continue;
    }
    if (!bucketed.has(name)) {
      bucketed.set(name, []);
      if (!specByName.has(name)) order.push(name);
    }
    bucketed.get(name)!.push(m);
  }

  const out: InteractiveSection[] = [];
  if (unsectioned.length > 0) {
    out.push({ key: '', groups: groupInteractiveComponents(unsectioned) });
  }
  for (const name of order) {
    const members = bucketed.get(name);
    // A section declared in filter_sections but with no component is skipped
    // rather than rendered as an empty accordion item.
    if (!members || members.length === 0) continue;
    out.push({
      key: `section:${name}`,
      sectionName: name,
      spec: specByName.get(name),
      groups: groupInteractiveComponents(members),
    });
  }
  return out;
}

/** Components that survive the filter panel's search box. */
export function matchesFilterSearch(m: StoredMetadata, needle: string): boolean {
  if (!needle) return true;
  const q = needle.toLowerCase();
  return (
    (m.title || '').toLowerCase().includes(q) ||
    (m.column_name || '').toLowerCase().includes(q) ||
    (typeof m.group === 'string' ? m.group.toLowerCase().includes(q) : false)
  );
}
