import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Anchor,
  Badge,
  Button,
  Center,
  Group,
  Paper,
  Space,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardListEntry, ProjectListEntry } from 'depictio-react-core';

import DashboardsToolbar from './DashboardsToolbar';
import DashboardThumbnailView from './views/DashboardThumbnailView';
import DashboardListView from './views/DashboardListView';
import DashboardTableView from './views/DashboardTableView';
import { useDashboardViewPrefs } from './hooks/useDashboardViewPrefs';
import { useDashboardFilters } from './hooks/useDashboardFilters';
import { useDashboardPinsAndRecents } from './hooks/useDashboardPinsAndRecents';
import {
  type GroupedDashboards,
  groupByParent,
  projectNameLookup,
} from './lib/splitDefaultSections';

interface DashboardsListProps {
  dashboards: DashboardListEntry[];
  projects: ProjectListEntry[];
  currentUserEmail: string | null;
  /** When true, pin button is rendered but disabled. Public/demo deployments
   *  pass this so anon visitors don't accumulate per-browser preferences that
   *  bleed across visitor sessions. */
  pinDisabled?: boolean;
  onView: (d: DashboardListEntry) => void;
  onEdit: (d: DashboardListEntry) => void;
  onDelete: (d: DashboardListEntry) => void;
  onDuplicate: (d: DashboardListEntry) => void;
  onExport: (d: DashboardListEntry) => void;
  onCreateClick: () => void;
  onBulkExport: (dashboards: DashboardListEntry[]) => void;
  onBulkDelete: (dashboards: DashboardListEntry[]) => void;
}

const RECENTS_VISIBLE_CAP = 8;

export interface CategoryInfo {
  label: string;
  color: string;
}

const SectionHeader: React.FC<{
  icon: string;
  color: string;
  label: string;
  count: number;
}> = ({ icon, color, label, count }) => (
  <Group gap="xs">
    <Icon icon={icon} width={18} color={color} />
    <Text size="lg" fw={700}>
      {label} ({count})
    </Text>
  </Group>
);

// Custom chevron with a fixed-size wrapper so the rotation transform doesn't
// shift the bounding box between open/closed states.
const FIXED_CHEVRON = (
  <span
    style={{
      display: 'inline-flex',
      width: 18,
      height: 18,
      alignItems: 'center',
      justifyContent: 'center',
    }}
  >
    <Icon icon="tabler:chevron-right" width={18} />
  </span>
);

const ACCORDION_STYLES = {
  chevron: {
    transition: 'transform 200ms ease',
    '&[data-rotate]': {
      transform: 'rotate(90deg)',
    },
  },
};

const DashboardsList: React.FC<DashboardsListProps> = ({
  dashboards,
  projects,
  currentUserEmail,
  pinDisabled = false,
  onView,
  onEdit,
  onDelete,
  onDuplicate,
  onExport,
  onCreateClick,
  onBulkExport,
  onBulkDelete,
}) => {
  const projectNames = useMemo(() => projectNameLookup(projects), [projects]);
  const {
    prefs,
    setView,
    setGroupBy,
    setSortBy,
    setSearch,
    setFilters,
    setDensity,
    setOnlyPinned,
    clearFilters,
  } = useDashboardViewPrefs();
  const { pinnedIds, recents, togglePin } = useDashboardPinsAndRecents();

  const filterCtx = useMemo(
    () => ({ projectNames, currentUserEmail }),
    [projectNames, currentUserEmail],
  );

  const { sections, totalAfterSearch } = useDashboardFilters(
    dashboards,
    prefs,
    filterCtx,
  );

  // Build the project / owner option lists for the toolbar dropdowns from the
  // currently-loaded dashboards (cheap, no extra fetch).
  const projectOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const d of dashboards) {
      if (d.parent_dashboard_id) continue;
      if (!d.project_id) continue;
      const id = String(d.project_id);
      if (!seen.has(id)) {
        seen.set(id, projectNames.get(id) ?? id);
      }
    }
    return Array.from(seen.entries())
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [dashboards, projectNames]);

  const ownerOptions = useMemo(() => {
    const set = new Set<string>();
    for (const d of dashboards) {
      if (d.parent_dashboard_id) continue;
      const email = d.permissions?.owners?.[0]?.email;
      if (email) set.add(email);
    }
    return [
      { value: '__mine__', label: 'Mine' },
      ...Array.from(set)
        .sort()
        .map((email) => ({ value: email, label: email })),
    ];
  }, [dashboards]);

  // Pinned + Recently opened sections derive from the same filter pipeline
  // so the global search/filter still applies. Both are flat
  // GroupedDashboards[] piles rendered with the chosen view.
  const allGrouped = useMemo(() => groupByParent(dashboards), [dashboards]);
  const allGroupedById = useMemo(() => {
    const map = new Map<string, GroupedDashboards>();
    for (const g of allGrouped) {
      map.set(String(g.parent.dashboard_id), g);
    }
    return map;
  }, [allGrouped]);

  const filteredById = useMemo(() => {
    const set = new Set<string>();
    for (const s of sections) {
      for (const g of s.groups) set.add(String(g.parent.dashboard_id));
    }
    return set;
  }, [sections]);

  const pinnedGroups = useMemo<GroupedDashboards[]>(() => {
    const list: GroupedDashboards[] = [];
    for (const id of pinnedIds) {
      if (!filteredById.has(id)) continue;
      const g = allGroupedById.get(id);
      if (g) list.push(g);
    }
    return list;
  }, [pinnedIds, allGroupedById, filteredById]);

  const recentGroups = useMemo<GroupedDashboards[]>(() => {
    const list: GroupedDashboards[] = [];
    const seen = new Set<string>();
    for (const r of recents) {
      if (seen.has(r.id)) continue;
      if (pinnedIds.has(r.id)) continue;
      if (!filteredById.has(r.id)) continue;
      const g = allGroupedById.get(r.id);
      if (g) {
        list.push(g);
        seen.add(r.id);
      }
      if (list.length >= RECENTS_VISIBLE_CAP) break;
    }
    return list;
  }, [recents, pinnedIds, allGroupedById, filteredById]);

  // The "Favorites only" toolbar toggle filters every visible pile to just the
  // pinned items. Applied here (post `useDashboardFilters`) because pin state
  // lives outside the search/filter pipeline.
  const effectiveSections = useMemo(() => {
    if (!prefs.onlyPinned) return sections;
    return sections
      .map((s) => ({
        ...s,
        groups: s.groups.filter((g) =>
          pinnedIds.has(String(g.parent.dashboard_id)),
        ),
      }))
      .filter((s) => s.groups.length > 0);
  }, [sections, prefs.onlyPinned, pinnedIds]);

  const effectiveRecentGroups = useMemo(
    () => (prefs.onlyPinned ? [] : recentGroups),
    [prefs.onlyPinned, recentGroups],
  );

  // Map each visible dashboard ID to its section's label/color so list & table
  // views can render a Category column without re-deriving from the raw groupBy
  // (the source of truth lives in `useDashboardFilters`).
  const categoryById = useMemo(() => {
    const map = new Map<string, CategoryInfo>();
    for (const s of effectiveSections) {
      for (const g of s.groups) {
        map.set(String(g.parent.dashboard_id), {
          label: s.label,
          color: s.iconColor,
        });
      }
    }
    return map;
  }, [effectiveSections]);

  // Flat ordered list for list/table views: pinned items first (so the user's
  // "promote" intent survives flattening), then everything else in section
  // order. Each id appears at most once.
  const flatOrderedGroups = useMemo<GroupedDashboards[]>(() => {
    const seen = new Set<string>();
    const list: GroupedDashboards[] = [];
    for (const g of pinnedGroups) {
      const id = String(g.parent.dashboard_id);
      if (seen.has(id)) continue;
      list.push(g);
      seen.add(id);
    }
    for (const s of effectiveSections) {
      for (const g of s.groups) {
        const id = String(g.parent.dashboard_id);
        if (seen.has(id)) continue;
        list.push(g);
        seen.add(id);
      }
    }
    return list;
  }, [pinnedGroups, effectiveSections]);

  // Default-open accordion sections (Thumbnails view only). Re-applies on the
  // emptiness signature change AND on groupBy change (section keys flip
  // entirely so the prior open-set is stale). User toggles win until groupBy
  // changes again.
  const [openSections, setOpenSections] = useState<string[]>([]);
  const [userToggled, setUserToggled] = useState(false);
  useEffect(() => {
    setUserToggled(false);
  }, [prefs.groupBy]);

  const defaultOpenKeys = useMemo(() => {
    const keys: string[] = [];
    if (pinnedGroups.length > 0) keys.push('__pinned__');
    if (effectiveRecentGroups.length > 0) keys.push('__recent__');
    for (const s of effectiveSections) {
      if (s.groups.length > 0) keys.push(s.key);
    }
    return keys;
  }, [pinnedGroups.length, effectiveRecentGroups.length, effectiveSections]);
  const defaultOpenSig = defaultOpenKeys.join('|');

  useEffect(() => {
    if (userToggled) return;
    if (dashboards.length === 0) return;
    setOpenSections(defaultOpenSig ? defaultOpenSig.split('|') : []);
  }, [userToggled, dashboards.length, defaultOpenSig]);

  // Renderer for the thumbnails view (used inside accordion sections).
  const renderThumbnailsFor = useCallback(
    (groups: GroupedDashboards[]) => (
      <DashboardThumbnailView
        groups={groups}
        projectNames={projectNames}
        currentUserEmail={currentUserEmail}
        pinnedIds={pinnedIds}
        pinDisabled={pinDisabled}
        onView={onView}
        onEdit={onEdit}
        onDelete={onDelete}
        onDuplicate={onDuplicate}
        onExport={onExport}
        onTogglePin={togglePin}
      />
    ),
    [
      projectNames,
      currentUserEmail,
      pinnedIds,
      pinDisabled,
      onView,
      onEdit,
      onDelete,
      onDuplicate,
      onExport,
      togglePin,
    ],
  );

  // Bare empty state when the user has no dashboards at all.
  if (dashboards.length === 0) {
    return (
      <Center mih={400}>
        <Stack align="center" gap="md">
          <Icon
            icon="material-symbols:dashboard-outline"
            width={48}
            color="var(--mantine-color-dimmed)"
          />
          <Title order={4}>No dashboards yet</Title>
          <Text c="dimmed">
            Create your first dashboard or import an existing one.
          </Text>
          <Button leftSection={<Icon icon="mdi:plus" width={14} />} onClick={onCreateClick}>
            New dashboard
          </Button>
        </Stack>
      </Center>
    );
  }

  const noResults = totalAfterSearch === 0 && prefs.search.trim().length > 0;

  // Shared chrome: toolbar + optional banners + content.
  const chrome = (content: React.ReactNode) => (
    <Stack gap="md">
      <DashboardsToolbar
        prefs={prefs}
        projectOptions={projectOptions}
        ownerOptions={ownerOptions}
        pinnedCount={pinnedGroups.length}
        pinDisabled={pinDisabled}
        setView={setView}
        setGroupBy={setGroupBy}
        setSortBy={setSortBy}
        setSearch={setSearch}
        setFilters={setFilters}
        setOnlyPinned={setOnlyPinned}
        clearFilters={clearFilters}
      />

      {pinDisabled && (
        <Paper p="xs" radius="md" withBorder>
          <Group gap="xs">
            <Icon icon="mdi:information-outline" width={16} />
            <Text size="sm" c="dimmed">
              Pinning and recently-opened tracking are disabled in public mode.
            </Text>
          </Group>
        </Paper>
      )}

      {noResults ? (
        <Paper p="xl" radius="md" withBorder>
          <Stack align="center" gap="sm">
            <Icon
              icon="mdi:magnify-close"
              width={36}
              color="var(--mantine-color-dimmed)"
            />
            <Text fw={500}>No dashboards match your search</Text>
            <Text size="sm" c="dimmed">
              Try a different keyword or
              <Anchor component="button" onClick={clearFilters} ml={4}>
                clear filters
              </Anchor>
              .
            </Text>
            <Badge variant="light" color="gray">
              Searched: <strong>"{prefs.search}"</strong>
            </Badge>
          </Stack>
        </Paper>
      ) : (
        content
      )}
    </Stack>
  );

  // List & Table modes flatten everything into a single section with a
  // Category column. Pinned items float to the top of the flat list.
  if (prefs.view === 'list' || prefs.view === 'table') {
    if (flatOrderedGroups.length === 0 && !noResults) {
      return chrome(
        <Paper p="xl" radius="md" withBorder>
          <Text c="dimmed" ta="center">
            Nothing to show.
          </Text>
        </Paper>,
      );
    }

    const flatContent =
      prefs.view === 'list' ? (
        <DashboardListView
          groups={flatOrderedGroups}
          projectNames={projectNames}
          currentUserEmail={currentUserEmail}
          pinnedIds={pinnedIds}
          pinDisabled={pinDisabled}
          categoryById={categoryById}
          onView={onView}
          onEdit={onEdit}
          onDelete={onDelete}
          onDuplicate={onDuplicate}
          onExport={onExport}
          onTogglePin={togglePin}
        />
      ) : (
        <DashboardTableView
          groups={flatOrderedGroups}
          projectNames={projectNames}
          currentUserEmail={currentUserEmail}
          pinnedIds={pinnedIds}
          pinDisabled={pinDisabled}
          density={prefs.density}
          categoryById={categoryById}
          onView={onView}
          onEdit={onEdit}
          onDelete={onDelete}
          onDuplicate={onDuplicate}
          onExport={onExport}
          onTogglePin={togglePin}
          onSetDensity={setDensity}
          onBulkExport={(ids) => {
            const targets = ids
              .map((id) => allGroupedById.get(id)?.parent)
              .filter((d): d is DashboardListEntry => Boolean(d));
            onBulkExport(targets);
          }}
          onBulkDelete={(ids) => {
            const targets = ids
              .map((id) => allGroupedById.get(id)?.parent)
              .filter((d): d is DashboardListEntry => Boolean(d));
            onBulkDelete(targets);
          }}
        />
      );

    return chrome(flatContent);
  }

  // Thumbnails view keeps the accordion-per-section layout.
  const accordionItems: React.ReactNode[] = [];

  const pileSections: {
    key: string;
    icon: string;
    color: string;
    label: string;
    groups: GroupedDashboards[];
  }[] = [
    {
      key: '__pinned__',
      icon: 'mdi:star',
      color: 'var(--mantine-color-yellow-6)',
      label: 'Pinned',
      groups: pinnedGroups,
    },
    {
      key: '__recent__',
      icon: 'mdi:clock-outline',
      color: 'var(--mantine-color-violet-6)',
      label: 'Recently opened',
      groups: effectiveRecentGroups,
    },
  ];

  for (const pile of pileSections) {
    if (pile.groups.length === 0) continue;
    accordionItems.push(
      <Accordion.Item value={pile.key} key={pile.key}>
        <Accordion.Control>
          <SectionHeader
            icon={pile.icon}
            color={pile.color}
            label={pile.label}
            count={pile.groups.length}
          />
        </Accordion.Control>
        <Accordion.Panel>
          <Space h={10} />
          {renderThumbnailsFor(pile.groups)}
        </Accordion.Panel>
      </Accordion.Item>,
    );
  }

  for (const s of effectiveSections) {
    if (s.groups.length === 0 && (prefs.search.trim() || prefs.groupBy !== 'none')) {
      // When the user is searching or grouping, hide empty buckets entirely
      // — only default-section placeholders should remain visible.
      continue;
    }
    accordionItems.push(
      <Accordion.Item value={s.key} key={s.key}>
        <Accordion.Control>
          <SectionHeader
            icon={s.icon}
            color={s.iconColor}
            label={s.label}
            count={s.groups.length}
          />
        </Accordion.Control>
        <Accordion.Panel>
          <Space h={10} />
          {s.groups.length === 0 ? (
            <Text c="dimmed" size="sm">
              Nothing here yet.
            </Text>
          ) : (
            renderThumbnailsFor(s.groups)
          )}
        </Accordion.Panel>
      </Accordion.Item>,
    );
  }

  return chrome(
    <Accordion
      multiple
      value={openSections}
      onChange={(v) => {
        setUserToggled(true);
        setOpenSections(v as string[]);
      }}
      variant="default"
      chevronPosition="left"
      chevron={FIXED_CHEVRON}
      styles={ACCORDION_STYLES}
    >
      {accordionItems}
    </Accordion>,
  );
};

export default DashboardsList;
