import { useMemo } from 'react';

import type { DashboardListEntry } from 'depictio-react-core';
import {
  type GroupedDashboards,
  groupByParent,
  isOwnedByEmail,
  splitDefaultSections,
} from '../lib/splitDefaultSections';
import type {
  DashboardFilters,
  DashboardViewPrefs,
  GroupBy,
  SortBy,
} from './useDashboardViewPrefs';

export interface DashboardSection {
  key: string;
  label: string;
  icon: string;
  iconColor: string;
  groups: GroupedDashboards[];
}

interface FilterContext {
  projectNames: Map<string, string>;
  currentUserEmail: string | null;
}

function matchesSearch(
  group: GroupedDashboards,
  search: string,
  projectNames: Map<string, string>,
): boolean {
  if (!search.trim()) return true;
  const q = search.trim().toLowerCase();
  const d = group.parent;
  const haystack: string[] = [];
  if (d.title) haystack.push(String(d.title));
  if (typeof d.subtitle === 'string') haystack.push(d.subtitle);
  if (d.project_id) {
    const name = projectNames.get(String(d.project_id));
    if (name) haystack.push(name);
  }
  const owner = d.permissions?.owners?.[0]?.email;
  if (owner) haystack.push(owner);
  if (typeof d.workflow_system === 'string') haystack.push(d.workflow_system);
  return haystack.some((s) => s.toLowerCase().includes(q));
}

function matchesFilters(
  group: GroupedDashboards,
  filters: DashboardFilters,
  currentUserEmail: string | null,
): boolean {
  const d = group.parent;
  if (filters.projects.length > 0) {
    const pid = d.project_id ? String(d.project_id) : '';
    if (!filters.projects.includes(pid)) return false;
  }
  if (filters.owners.length > 0) {
    const ownerEmail = d.permissions?.owners?.[0]?.email ?? '';
    const wantsMine = filters.owners.includes('__mine__');
    const isMine = wantsMine && isOwnedByEmail(d, currentUserEmail);
    const explicit = filters.owners.includes(ownerEmail);
    if (!isMine && !explicit) return false;
  }
  if (filters.visibility === 'public' && !d.is_public) return false;
  if (filters.visibility === 'private' && d.is_public) return false;
  return true;
}

function compareGroups(
  a: GroupedDashboards,
  b: GroupedDashboards,
  sortBy: SortBy,
): number {
  switch (sortBy) {
    case 'name': {
      const at = a.parent.title || a.parent.dashboard_id;
      const bt = b.parent.title || b.parent.dashboard_id;
      return at.localeCompare(bt);
    }
    case 'owner': {
      const ao = a.parent.permissions?.owners?.[0]?.email ?? '';
      const bo = b.parent.permissions?.owners?.[0]?.email ?? '';
      return ao.localeCompare(bo);
    }
    case 'recent':
    default: {
      const at = typeof a.parent.last_saved_ts === 'string' ? a.parent.last_saved_ts : '';
      const bt = typeof b.parent.last_saved_ts === 'string' ? b.parent.last_saved_ts : '';
      // Recent first.
      return bt.localeCompare(at);
    }
  }
}

function defaultSections(
  entries: DashboardListEntry[],
  ctx: FilterContext,
  sortBy: SortBy,
): DashboardSection[] {
  const split = splitDefaultSections(entries, ctx.currentUserEmail);
  return [
    {
      key: 'owned',
      label: 'Owned',
      icon: 'mdi:account-check',
      iconColor: 'var(--mantine-color-blue-6)',
      groups: [...split.owned].sort((a, b) => compareGroups(a, b, sortBy)),
    },
    {
      key: 'accessed',
      label: 'Accessed',
      icon: 'material-symbols:share-outline',
      iconColor: 'var(--mantine-color-green-5)',
      groups: [...split.accessed].sort((a, b) => compareGroups(a, b, sortBy)),
    },
    {
      key: 'public',
      label: 'Public',
      icon: 'mdi:earth',
      iconColor: 'var(--mantine-color-teal-6)',
      groups: split.public_,
    },
    {
      key: 'example',
      label: 'Example',
      icon: 'mdi:school-outline',
      iconColor: 'var(--mantine-color-orange-6)',
      groups: split.examples,
    },
  ];
}

const GROUP_ICONS: Record<GroupBy, { icon: string; iconColor: string }> = {
  none: { icon: 'mdi:folder', iconColor: 'var(--mantine-color-gray-6)' },
  project: { icon: 'mdi:folder-multiple', iconColor: 'var(--mantine-color-teal-7)' },
  owner: { icon: 'mdi:account', iconColor: 'var(--mantine-color-blue-6)' },
  visibility: { icon: 'material-symbols:public', iconColor: 'var(--mantine-color-teal-6)' },
  workflow: { icon: 'mdi:graph', iconColor: 'var(--mantine-color-orange-6)' },
};

function groupByKey(
  groups: GroupedDashboards[],
  groupBy: GroupBy,
  ctx: FilterContext,
  sortBy: SortBy,
): DashboardSection[] {
  if (groups.length === 0) return [];
  const buckets = new Map<string, { label: string; groups: GroupedDashboards[] }>();

  for (const g of groups) {
    let key = '__none__';
    let label = 'Other';
    switch (groupBy) {
      case 'project': {
        const pid = g.parent.project_id ? String(g.parent.project_id) : '';
        key = pid || '__noproject__';
        label = pid ? (ctx.projectNames.get(pid) ?? 'Unknown project') : 'No project';
        break;
      }
      case 'owner': {
        const owner = g.parent.permissions?.owners?.[0]?.email ?? '';
        key = owner || '__noowner__';
        label = owner || 'Unknown owner';
        break;
      }
      case 'visibility': {
        const isPublic = Boolean(g.parent.is_public);
        key = isPublic ? 'public' : 'private';
        label = isPublic ? 'Public' : 'Private';
        break;
      }
      case 'workflow': {
        const wf =
          typeof g.parent.workflow_system === 'string' ? g.parent.workflow_system : '';
        key = wf || '__noworkflow__';
        label = wf || 'No workflow';
        break;
      }
      default:
        break;
    }
    const bucket = buckets.get(key) ?? { label, groups: [] };
    bucket.groups.push(g);
    buckets.set(key, bucket);
  }

  // Sort buckets alphabetically by label, but keep "no X" buckets at the end.
  const entries = Array.from(buckets.entries()).sort(([ka, va], [kb, vb]) => {
    const aMissing = ka.startsWith('__no');
    const bMissing = kb.startsWith('__no');
    if (aMissing !== bMissing) return aMissing ? 1 : -1;
    return va.label.localeCompare(vb.label);
  });

  const { icon, iconColor } = GROUP_ICONS[groupBy] ?? GROUP_ICONS.none;
  return entries.map(([key, bucket]) => ({
    key,
    label: bucket.label,
    icon,
    iconColor,
    groups: [...bucket.groups].sort((a, b) => compareGroups(a, b, sortBy)),
  }));
}

/** Apply search → filters → sort → group. Returns the final sectioned view
 *  the renderer should iterate, plus a flat filtered list for empty-state /
 *  count UI.
 *
 *  Note: example dashboards are split into a separate section by default,
 *  but when group-by ≠ 'none' we want them to bucket with their natural
 *  group (project/owner/etc.) instead of being hidden in their own
 *  "Examples" pile. */
export interface UseDashboardFiltersResult {
  sections: DashboardSection[];
  totalAfterSearch: number;
}

export function useDashboardFilters(
  entries: DashboardListEntry[],
  prefs: DashboardViewPrefs,
  ctx: FilterContext,
): UseDashboardFiltersResult {
  return useMemo(() => {
    const allGrouped = groupByParent(entries);
    const afterSearch = allGrouped.filter((g) =>
      matchesSearch(g, prefs.search, ctx.projectNames),
    );
    const afterFilters = afterSearch.filter((g) =>
      matchesFilters(g, prefs.filters, ctx.currentUserEmail),
    );

    const sections =
      prefs.groupBy === 'none'
        ? defaultSections(
            afterFilters.flatMap((g) => [g.parent, ...g.children]),
            ctx,
            prefs.sortBy,
          )
        : groupByKey(afterFilters, prefs.groupBy, ctx, prefs.sortBy);

    return { sections, totalAfterSearch: afterSearch.length };
  }, [entries, prefs, ctx.projectNames, ctx.currentUserEmail]);
}
