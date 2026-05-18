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
  const { prefs, setSearch, setFilters, setOnlyPinned, clearFilters } =
    useProjectViewPrefs();
  const { pinnedIds, togglePin } = useProjectPins();

  // Template-source options for the filter popover — derived from the loaded
  // projects so the dropdown only offers sources actually present.
  const templateSourceOptions = useMemo(() => {
    const set = new Set<string>();
    for (const p of projects) {
      const t = parseTemplate(p);
      if (t?.source) set.add(t.source);
    }
    return Array.from(set)
      .sort()
      .map((s) => ({ value: s, label: s }));
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
      if (prefs.filters.templateSources.length > 0) {
        const t = parseTemplate(p);
        if (!t || !prefs.filters.templateSources.includes(t.source)) return false;
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
                ? 'Project creation is disabled on this public/demo instance.'
                : 'Create your first project to start organizing data collections and dashboards.'}
            </Text>
            <Tooltip
              label="Project creation is disabled in public/demo mode"
              disabled={!createDisabled}
              withArrow
            >
              <Button
                color="teal"
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

  const noResults =
    filtered.length === 0 &&
    (prefs.search.trim().length > 0 ||
      prefs.filters.types.length > 0 ||
      prefs.filters.visibility !== 'all' ||
      prefs.filters.templateSources.length > 0 ||
      prefs.onlyPinned);

  return (
    <Stack gap="md">
      <ProjectsToolbar
        prefs={prefs}
        templateSourceOptions={templateSourceOptions}
        pinnedCount={pinnedCount}
        pinDisabled={createDisabled}
        setSearch={setSearch}
        setFilters={setFilters}
        setOnlyPinned={setOnlyPinned}
        clearFilters={clearFilters}
      />

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
