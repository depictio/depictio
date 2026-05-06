import type { StoredMetadata } from '../api';

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
