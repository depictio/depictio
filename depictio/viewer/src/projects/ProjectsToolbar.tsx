import React from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Indicator,
  MultiSelect,
  Popover,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type {
  ProjectFilters,
  ProjectViewPrefs,
  ProjectTypeFilter,
  VisibilityFilter,
} from './hooks/useProjectViewPrefs';
import { emptyProjectFilters } from './hooks/useProjectViewPrefs';
import { useBrandAccents } from 'depictio-react-core';
import ShareViewButton from '../components/listing/ShareViewButton';

export type FilterOption = { value: string; label: string };

export interface ProjectsToolbarProps {
  prefs: ProjectViewPrefs;
  templateOptions: FilterOption[];
  /** Rows currently on screen, for the share confirmation's wording. */
  matchingCount: number;
  /** False while the shared-view banner is up: it lists the same filters, and
   *  two identical chip rows one above the other reads as a bug. */
  showFilterChips?: boolean;
  pinnedCount: number;
  pinDisabled: boolean;
  setSearch: (s: string) => void;
  setFilters: (f: ProjectFilters) => void;
  setOnlyPinned: (b: boolean) => void;
  clearFilters: () => void;
}

const TYPE_DATA = [
  { value: 'basic', label: 'Basic' },
  { value: 'advanced', label: 'Advanced' },
];

const VISIBILITY_DATA = [
  { value: 'all', label: 'All' },
  { value: 'public', label: 'Public only' },
  { value: 'private', label: 'Private only' },
];

const FilterPopover: React.FC<{
  prefs: ProjectViewPrefs;
  templateOptions: FilterOption[];
  setFilters: (f: ProjectFilters) => void;
}> = ({ prefs, templateOptions, setFilters }) => {
  const accent = useBrandAccents();
  const activeCount =
    prefs.filters.types.length +
    prefs.filters.templates.length +
    (prefs.filters.visibility !== 'all' ? 1 : 0);

  return (
    <Popover position="bottom-end" shadow="md" withinPortal width={320}>
      <Popover.Target>
        <Tooltip label="Filters" withinPortal>
          <Indicator
            label={activeCount}
            size={16}
            color={accent.tertiary}
            disabled={activeCount === 0}
            offset={4}
          >
            <ActionIcon
              variant={activeCount > 0 ? 'light' : 'default'}
              color={activeCount > 0 ? accent.tertiary : undefined}
              size="lg"
              radius="md"
              aria-label={`Filters${activeCount > 0 ? ` (${activeCount} active)` : ''}`}
            >
              <Icon icon="mdi:filter-variant" width={18} />
            </ActionIcon>
          </Indicator>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={600} size="sm">
              Filters
            </Text>
            {activeCount > 0 && (
              <Button
                variant="subtle"
                size="compact-xs"
                onClick={() => setFilters(emptyProjectFilters())}
              >
                Clear all
              </Button>
            )}
          </Group>

          <MultiSelect
            label="Type"
            placeholder="Any type"
            data={TYPE_DATA}
            value={prefs.filters.types}
            onChange={(v) =>
              setFilters({ ...prefs.filters, types: v as ProjectTypeFilter[] })
            }
            clearable
            comboboxProps={{ withinPortal: false }}
          />

          <Select
            label="Visibility"
            data={VISIBILITY_DATA}
            value={prefs.filters.visibility}
            onChange={(v) =>
              v &&
              setFilters({
                ...prefs.filters,
                visibility: v as VisibilityFilter,
              })
            }
            allowDeselect={false}
            comboboxProps={{ withinPortal: false }}
          />

          <MultiSelect
            label="Template"
            placeholder={
              templateOptions.length === 0
                ? 'No templated projects loaded'
                : 'Any template'
            }
            description="Pick a source for every pipeline under it, or one pipeline on its own."
            data={templateOptions}
            value={prefs.filters.templates}
            onChange={(v) => setFilters({ ...prefs.filters, templates: v })}
            disabled={templateOptions.length === 0}
            searchable
            clearable
            comboboxProps={{ withinPortal: false }}
          />
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

const ProjectsToolbar: React.FC<ProjectsToolbarProps> = ({
  prefs,
  templateOptions,
  matchingCount,
  showFilterChips = true,
  pinnedCount,
  pinDisabled,
  setSearch,
  setFilters,
  setOnlyPinned,
  clearFilters,
}) => {
  const accent = useBrandAccents();
  const activeFilterChips: { key: string; label: string; onRemove: () => void }[] =
    [];
  for (const t of prefs.filters.types) {
    activeFilterChips.push({
      key: `t:${t}`,
      label: t === 'basic' ? 'Basic' : 'Advanced',
      onRemove: () =>
        setFilters({
          ...prefs.filters,
          types: prefs.filters.types.filter((x) => x !== t),
        }),
    });
  }
  for (const s of prefs.filters.templates) {
    const opt = templateOptions.find((o) => o.value === s);
    activeFilterChips.push({
      key: `s:${s}`,
      label: opt?.label ?? s,
      onRemove: () =>
        setFilters({
          ...prefs.filters,
          templates: prefs.filters.templates.filter((x) => x !== s),
        }),
    });
  }
  if (prefs.filters.visibility !== 'all') {
    activeFilterChips.push({
      key: 'v',
      label:
        prefs.filters.visibility === 'public' ? 'Public only' : 'Private only',
      onRemove: () => setFilters({ ...prefs.filters, visibility: 'all' }),
    });
  }
  if (prefs.onlyPinned) {
    activeFilterChips.unshift({
      key: 'pinned',
      label: 'Favorites only',
      onRemove: () => setOnlyPinned(false),
    });
  }

  const hasSearch = prefs.search.trim().length > 0;
  const hasAnyActive = hasSearch || activeFilterChips.length > 0;

  return (
    <Stack gap="xs" mb="md">
      <Group gap="xs" wrap="nowrap" align="center">
        <TextInput
          placeholder="Search projects…"
          value={prefs.search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          leftSection={<Icon icon="mdi:magnify" width={16} />}
          rightSection={
            prefs.search ? (
              <ActionIcon
                variant="subtle"
                color="gray"
                onClick={() => setSearch('')}
                aria-label="Clear search"
              >
                <Icon icon="mdi:close" width={14} />
              </ActionIcon>
            ) : null
          }
          style={{ flex: 1, minWidth: 0 }}
        />

        <Tooltip
          label={
            pinDisabled
              ? 'Pinning is disabled in public mode'
              : prefs.onlyPinned
                ? 'Show all projects'
                : `Show favorites only${pinnedCount ? ` (${pinnedCount})` : ''}`
          }
          withinPortal
        >
          <ActionIcon
            variant={prefs.onlyPinned ? 'light' : 'default'}
            color={prefs.onlyPinned ? 'yellow' : undefined}
            size="lg"
            radius="md"
            onClick={() => setOnlyPinned(!prefs.onlyPinned)}
            disabled={pinDisabled || (pinnedCount === 0 && !prefs.onlyPinned)}
            aria-label="Toggle favorites filter"
            aria-pressed={prefs.onlyPinned}
          >
            <Icon
              icon={prefs.onlyPinned ? 'mdi:star' : 'mdi:star-outline'}
              width={18}
            />
          </ActionIcon>
        </Tooltip>

        <FilterPopover
          prefs={prefs}
          templateOptions={templateOptions}
          setFilters={setFilters}
        />

        <ShareViewButton
          describes={
            hasAnyActive
              ? `this filtered view (${matchingCount} project${matchingCount === 1 ? '' : 's'})`
              : 'the full project list'
          }
        />
      </Group>

      {showFilterChips && activeFilterChips.length > 0 && (
        <Group gap="xs" wrap="wrap" align="center">
          {activeFilterChips.map((chip) => (
            <Badge
              key={chip.key}
              variant="light"
              color={accent.tertiary}
              rightSection={
                <ActionIcon
                  size="xs"
                  variant="transparent"
                  color={accent.tertiary}
                  onClick={chip.onRemove}
                  aria-label={`Remove filter ${chip.label}`}
                >
                  <Icon icon="mdi:close" width={12} />
                </ActionIcon>
              }
              style={{ paddingRight: 4 }}
            >
              {chip.label}
            </Badge>
          ))}
          {hasAnyActive && (
            <Button
              variant="subtle"
              color="gray"
              size="compact-xs"
              onClick={clearFilters}
              leftSection={<Icon icon="mdi:close" width={12} />}
            >
              Clear all
            </Button>
          )}
        </Group>
      )}
    </Stack>
  );
};

export default ProjectsToolbar;
