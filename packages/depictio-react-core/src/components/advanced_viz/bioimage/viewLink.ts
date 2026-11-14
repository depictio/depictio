// Tiles that share a `view_link` name move together: a pan or zoom on one is
// applied to the others, in level-0 pixels. Module-level, like the image info
// registry: the tiles sit in separate parts of the React tree.

export interface LinkedCamera {
  zoom: number;
  target: readonly [number, number];
}

type Listener = (camera: LinkedCamera, from: string) => void;

const groups = new Map<string, Map<string, Listener>>();

/** Follow the group's moves; returns the unsubscribe. `id` is the tile's own
 *  key, so it never receives its own moves back. */
export function joinViewLink(group: string, id: string, listener: Listener): () => void {
  let members = groups.get(group);
  if (!members) {
    members = new Map();
    groups.set(group, members);
  }
  members.set(id, listener);
  return () => {
    const current = groups.get(group);
    if (!current) return;
    current.delete(id);
    if (current.size === 0) groups.delete(group);
  };
}

/** Tell the other tiles of the group where `id` is now looking. */
export function moveViewLink(group: string, id: string, camera: LinkedCamera): void {
  for (const [member, listener] of groups.get(group) ?? []) {
    if (member !== id) listener(camera, id);
  }
}
