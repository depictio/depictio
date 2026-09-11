import React, { useMemo } from 'react';
import {
  Anchor,
  Badge,
  Button,
  Center,
  Group,
  Paper,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { ProjectListEntry } from 'depictio-react-core';

import ProjectsToolbar from './ProjectsToolbar';
import ProjectTableView from './views/ProjectTableView';
import { useProjectViewPrefs } from './hooks/useProjectViewPrefs';
import { useProjectPins } from './hooks/useProjectPins';
import { parseTemplate } from './template';
import SharedViewBanner from '../components/listing/SharedViewBanner';
import type { SharedViewScope } from '../components/listing/SharedViewBanner';
import { listingUrl } from '../lib/listingUrl';
import { matchesTemplateFilter, useBrandAccents } from 'depictio-react-core';

interface ProjectsListProps {
  projects: ProjectListEntry[];
  currentUserId: string | null;
  isAdmin: boolean;
  /** True in public/demo mode — keeps the empty-state Create Project button
   *  visible but disabled, with a tooltip explaining why. Also disables the
   *  pin button so anon visitors don't accumulate per-browser pins that
   *  bleed across visitor sessions. */
  createDisabled: boolean;
  onCreateClick: () => void;
  onView: (project: ProjectListEntry) => void;
  onEdit: (project: ProjectListEntry) => void;
  onDelete: (project: ProjectListEntry) => void;
}

const ProjectsList: React.FC<ProjectsListProps> = ({
  projects,
  currentUserId,
  isAdmin,
  createDisabled,
  onCreateClick,
  onView,
  onEdit,
  onDelete,
}) => {
  const accent = useBrandAccents();
  const {
    prefs,
    arrivedScoped,
    setSearch,
    setFilters,
    setOnlyPinned,
    setDensity,
    clearFilters,
  } = useProjectViewPrefs();
  const { pinnedIds, togglePin } = useProjectPins();

  // Template options for the filter popover, derived from the loaded projects
  // so the dropdown only offers pipelines actually present. Each source
  // contributes an "all pipelines" entry alongside its individual pipelines,
  // which is what lets one link scope to a whole source or a single pipeline.
  const templateOptions = useMemo(() => {
    const bySource = new Map<string, Set<string>>();
    for (const p of projects) {
      const t = parseTemplate(p);
      if (!t?.source) continue;
      const pipelines = bySource.get(t.source) ?? new Set<string>();
      if (t.repo) pipelines.add(t.repo);
      bySource.set(t.source, pipelines);
    }
    const options: { value: string; label: string }[] = [];
    for (const source of Array.from(bySource.keys()).sort()) {
      const pipelines = Array.from(bySource.get(source) ?? []).sort();
      if (pipelines.length > 1) {
        options.push({ value: source, label: `${source} (all pipelines)` });
      }
      for (const repo of pipelines) {
        options.push({ value: `${source}/${repo}`, label: `${source} / ${repo}` });
      }
      if (pipelines.length === 0) options.push({ value: source, label: source });
    }
    return options;
  }, [projects]);

  // Pipeline: search → filters → onlyPinned → split into sections.
  const filtered = useMemo(() => {
    const q = prefs.search.trim().toLowerCase();
    return projects.filter((p) => {
      if (q) {
        const owner = p.permissions?.owners?.[0]?.email ?? '';
        const tmpl = parseTemplate(p);
        const haystack = [
          p.name,
          owner,
          tmpl?.full ?? '',
          tmpl?.source ?? '',
          tmpl?.repo ?? '',
        ]
          .join(' ')
          .toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      if (prefs.filters.types.length > 0) {
        const t = p.project_type === 'advanced' ? 'advanced' : 'basic';
        if (!prefs.filters.types.includes(t)) return false;
      }
      if (prefs.filters.visibility === 'public' && !p.is_public) return false;
      if (prefs.filters.visibility === 'private' && p.is_public) return false;
      if (!matchesTemplateFilter(p.template_origin, prefs.filters.templates)) {
        return false;
      }
      if (prefs.onlyPinned) {
        const id = String(p._id ?? p.id ?? '');
        if (!pinnedIds.has(id)) return false;
      }
      return true;
    });
  }, [projects, prefs, pinnedIds]);

  // Pinned-first ordering: pinned rows float to the top of the table while
  // the rest preserve API order. Keeps a single flat table (per the user's
  // ask to drop collapsible sections) without losing the pin affordance.
  const ordered = useMemo<ProjectListEntry[]>(() => {
    const pinned: ProjectListEntry[] = [];
    const rest: ProjectListEntry[] = [];
    for (const p of filtered) {
      const id = String(p._id ?? p.id ?? '');
      if (pinnedIds.has(id)) pinned.push(p);
      else rest.push(p);
    }
    return [...pinned, ...rest];
  }, [filtered, pinnedIds]);

  const pinnedCount = useMemo(
    () =>
      filtered.reduce(
        (n, p) => (pinnedIds.has(String(p._id ?? p.id ?? '')) ? n + 1 : n),
        0,
      ),
    [filtered, pinnedIds],
  );

  // Bare empty state when there are no projects at all (independent of
  // search/filter). Mirrors the previous ProjectsList empty-state card.
  if (projects.length === 0) {
    return (
      <Center mih={400}>
        <Paper p="xl" radius="md" withBorder maw={500} miw={300}>
          <Stack align="center" gap="md">
            <Icon
              icon="material-symbols:folder-off-outline"
              width={64}
              height={64}
              color="var(--mantine-color-gray-5)"
            />
            <Title order={3} c="dimmed">
              No projects available
            </Title>
            <Text c="dimmed" ta="center">
              {createDisabled
                ? 'Project creation is disabled on this public/demo instance for non-admin users.'
                : 'Create your first project to start organizing data collections and dashboards.'}
            </Text>
            <Tooltip
              label="Project creation is disabled in public/demo mode for non-admin users"
              disabled={!createDisabled}
              withArrow
            >
              <Button
                color={accent.secondary}
                variant="filled"
                onClick={onCreateClick}
                disabled={createDisabled}
                leftSection={<Icon icon="mdi:plus" width={18} />}
                style={{ fontFamily: 'Virgil' }}
              >
                Create Project
              </Button>
            </Tooltip>
          </Stack>
        </Paper>
      </Center>
    );
  }

  // What the shared link narrowed to, spelled out for the banner.
  const scopeChips: SharedViewScope[] = [];
  for (const value of prefs.filters.templates) {
    const opt = templateOptions.find((o) => o.value === value);
    scopeChips.push({
      key: `t:${value}`,
      label: opt?.label ?? value,
      onRemove: () =>
        setFilters({
          ...prefs.filters,
          templates: prefs.filters.templates.filter((v) => v !== value),
        }),
    });
  }
  for (const t of prefs.filters.types) {
    scopeChips.push({
      key: `y:${t}`,
      label: t === 'basic' ? 'Basic' : 'Advanced',
      onRemove: () =>
        setFilters({
          ...prefs.filters,
          types: prefs.filters.types.filter((v) => v !== t),
        }),
    });
  }
  if (prefs.filters.visibility !== 'all') {
    scopeChips.push({
      key: 'v',
      label: prefs.filters.visibility === 'public' ? 'Public only' : 'Private only',
      onRemove: () => setFilters({ ...prefs.filters, visibility: 'all' }),
    });
  }
  if (prefs.onlyPinned) {
    scopeChips.push({
      key: 'pinned',
      label: 'Favorites only',
      onRemove: () => setOnlyPinned(false),
    });
  }
  if (prefs.search.trim()) {
    scopeChips.push({
      key: 'q',
      label: `"${prefs.search.trim()}"`,
      onRemove: () => setSearch(''),
    });
  }

  // A template scope reads just as well on the dashboards listing, and "show
  // me this pipeline" usually means both.
  const crossLink =
    prefs.filters.templates.length > 0
      ? {
          href: listingUrl('/dashboards', { template: prefs.filters.templates }),
          label: 'See the matching dashboards',
        }
      : undefined;

  const showBanner = arrivedScoped && scopeChips.length > 0;

  const noResults =
    filtered.length === 0 &&
    (prefs.search.trim().length > 0 ||
      prefs.filters.types.length > 0 ||
      prefs.filters.visibility !== 'all' ||
      prefs.filters.templates.length > 0 ||
      prefs.onlyPinned);

  return (
    <Stack gap="md">
      <ProjectsToolbar
        prefs={prefs}
        templateOptions={templateOptions}
        matchingCount={filtered.length}
        showFilterChips={!showBanner}
        pinnedCount={pinnedCount}
        pinDisabled={createDisabled}
        setSearch={setSearch}
        setFilters={setFilters}
        setOnlyPinned={setOnlyPinned}
        clearFilters={clearFilters}
      />

      {showBanner && (
        <SharedViewBanner
          scope={scopeChips}
          shown={filtered.length}
          total={projects.length}
          noun="project"
          crossLink={crossLink}
          color={accent.secondary}
          onClearAll={clearFilters}
        />
      )}

      {createDisabled && (
        <Paper p="xs" radius="md" withBorder>
          <Group gap="xs">
            <Icon icon="mdi:information-outline" width={16} />
            <Text size="sm" c="dimmed">
              Pinning is disabled in public mode.
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
            <Text fw={500}>No projects match your search</Text>
            <Text size="sm" c="dimmed">
              Try a different keyword or
              <Anchor component="button" onClick={clearFilters} ml={4}>
                clear filters
              </Anchor>
              .
            </Text>
            {prefs.search && (
              <Badge variant="light" color="gray">
                Searched: <strong>"{prefs.search}"</strong>
              </Badge>
            )}
          </Stack>
        </Paper>
      ) : (
        <ProjectTableView
          projects={ordered}
          currentUserId={currentUserId}
          isAdmin={isAdmin}
          pinnedIds={pinnedIds}
          pinDisabled={createDisabled}
          density={prefs.density}
          onSetDensity={setDensity}
          onView={onView}
          onEdit={onEdit}
          onDelete={onDelete}
          onTogglePin={togglePin}
        />
      )}
    </Stack>
  );
};

export default ProjectsList;
