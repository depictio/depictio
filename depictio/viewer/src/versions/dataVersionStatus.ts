/**
 * What the data-version banners say, from the server's per-collection status
 * (`POST /dashboards/data_version_status/{id}`).
 *
 * The banners used to infer coverage and then generalise: "every value on this
 * dashboard is computed from the pinned dataset version", "layout, components
 * and data are all from this version". Neither was true. A version can pin one
 * collection, leave another live on purpose and have recorded nothing for a
 * third, and some component types (MultiQC, JBrowse, advanced visualisations)
 * never read a pin at all. So the text names collections, grouped by what the
 * server says happens to each, and never makes a claim about "all" data.
 *
 * Kept free of runtime imports so a dev check can bundle and execute it.
 */

import type { DataVersionCollectionStatus } from 'depictio-react-core';

/** A per-collection pin as the editor holds it, named for display. `version`
 *  null is a collection kept on its latest data under a version's data. */
export interface PinnedLabel {
  dcId: string;
  label: string;
  version: number | null;
}

export interface GroupedStatus {
  pinned: Array<{ dcId: string; label: string; version: number | null }>;
  live: Array<{ dcId: string; label: string; reason: string | null }>;
  notVersioned: Array<{ dcId: string; label: string; reason: string | null }>;
}

/** A collection's name: its tag, else its id. */
export function collectionLabel(status: Pick<DataVersionCollectionStatus, 'dc_id' | 'data_collection_tag'>): string {
  return status.data_collection_tag || status.dc_id;
}

export function groupStatus(collections: readonly DataVersionCollectionStatus[]): GroupedStatus {
  const grouped: GroupedStatus = { pinned: [], live: [], notVersioned: [] };
  for (const c of collections) {
    const base = { dcId: c.dc_id, label: collectionLabel(c) };
    if (c.status === 'pinned') {
      grouped.pinned.push({
        ...base,
        version: typeof c.delta_version === 'number' ? c.delta_version : null,
      });
    } else if (c.status === 'live') {
      grouped.live.push({ ...base, reason: c.reason ?? null });
    } else {
      grouped.notVersioned.push({ ...base, reason: c.reason ?? null });
    }
  }
  return grouped;
}

const list = (names: string[]) => names.join(', ');

/**
 * One or more sentences naming which collections are pinned, which are live
 * and which have no data version. Every collection is named in exactly one
 * group, and nothing is said about collections the status did not list.
 */
export function describeDataVersionStatus(
  collections: readonly DataVersionCollectionStatus[],
): string {
  if (collections.length === 0) return 'No data collection on this tab.';
  const { pinned, live, notVersioned } = groupStatus(collections);
  const parts: string[] = [];
  if (pinned.length > 0) {
    parts.push(
      `Past data: ${list(
        pinned.map((p) => (p.version === null ? p.label : `${p.label} (v${p.version})`)),
      )}.`,
    );
  }
  if (live.length > 0) {
    parts.push(`Latest data: ${list(live.map((l) => l.label))}.`);
  }
  if (notVersioned.length > 0) {
    parts.push(
      `No data version recorded, so the latest data is shown: ${list(
        notVersioned.map((n) => n.label),
      )}.`,
    );
  }
  return parts.join(' ');
}

/** The note about tiles that never read a pin, or null when there are none. */
export function currentDataOnlyNote(count: number): string | null {
  if (count <= 0) return null;
  return count === 1
    ? 'The tile marked Current data shows the latest data.'
    : `The ${count} tiles marked Current data show the latest data.`;
}
