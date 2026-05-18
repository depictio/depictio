import React from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Indicator,
  Menu,
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
  DashboardFilters,
  DashboardViewPrefs,
  GroupBy,
  SortBy,
  ViewMode,
} from './hooks/useDashboardViewPrefs';

export interface DashboardsToolbarProps {
  prefs: DashboardViewPrefs;
  projectOptions: { value: string; label: string }[];
  ownerOptions: { value: string; label: string }[];
  pinnedCount: number;
  pinDisabled: boolean;
  setView: (v: ViewMode) => void;
  setGroupBy: (g: GroupBy) => void;
  setSortBy: (s: SortBy) => void;
  setSearch: (s: string) => void;
  setFilters: (f: DashboardFilters) => void;
  setOnlyPinned: (b: boolean) => void;
  clearFilters: () => void;
}

interface ViewOption {
  value: ViewMode;
  label: string;
  icon: string;
  description: string;
}

const VIEW_OPTIONS: ViewOption[] = [
  {
    value: 'thumbnails',
    label: 'Thumbnails',
    icon: 'mdi:view-grid-outline',
    description: 'Cards with screenshot previews',
  },
  {
    value: 'list',
    label: 'Tiles',
    icon: 'mdi:card-multiple-outline',
    description: 'Compact cards without previews',
  },
  {
    value: 'table',
    label: 'Table',
    icon: 'mdi:table',
    description: 'Sortable columns + bulk select',
  },
];

const GROUP_DATA = [
  { value: 'none', label: 'Default sections' },
  { value: 'project', label: 'Project' },
  { value: 'owner', label: 'Owner' },
  { value: 'visibility', label: 'Visibility' },
  { value: 'workflow', label: 'Workflow' },
];

const SORT_DATA = [
  { value: 'recent', label: 'Recently modified' },
  { value: 'name', label: 'Name (A→Z)' },
  { value: 'owner', label: 'Owner' },
];

const VISIBILITY_DATA = [
  { value: 'all', label: 'All' },
  { value: 'public', label: 'Public only' },
  { value: 'private', label: 'Private only' },
];

const ViewPicker: React.FC<{
  value: ViewMode;
  onChange: (v: ViewMode) => void;
}> = ({ value, onChange }) => {
  const current = VIEW_OPTIONS.find((o) => o.value === value) ?? VIEW_OPTIONS[0];
  return (
    <Menu position="bottom-end" shadow="md" withinPortal width={220}>
      <Menu.Target>
        <Tooltip label={`View: ${current.label}`} withinPortal>
          <ActionIcon
            variant="default"
            size="lg"
            radius="md"
            aria-label={`Change view (currently ${current.label})`}
          >
            <Icon icon={current.icon} width={18} />
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>View</Menu.Label>
        {VIEW_OPTIONS.map((opt) => (
          <Menu.Item
            key={opt.value}
            leftSection={<Icon icon={opt.icon} width={16} />}
            rightSection={
              opt.value === value ? <Icon icon="mdi:check" width={14} /> : null
            }
            onClick={() => onChange(opt.value)}
          >
            <div>
              <div style={{ fontWeight: 500 }}>{opt.label}</div>
              <div
                style={{
                  fontSize: 11,
                  color: 'var(--mantine-color-dimmed)',
                }}
              >
                {opt.description}
              </div>
            </div>
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
};

const FilterPopover: React.FC<{
  prefs: DashboardViewPrefs;
  projectOptions: { value: string; label: string }[];
  ownerOptions: { value: string; label: string }[];
  setFilters: (f: DashboardFilters) => void;
}> = ({ prefs, projectOptions, ownerOptions, setFilters }) => {
  const activeCount =
    prefs.filters.projects.length +
    prefs.filters.owners.length +
    (prefs.filters.visibility !== 'all' ? 1 : 0);

  return (
    <Popover position="bottom-end" shadow="md" withinPortal width={320}>
      <Popover.Target>
        <Tooltip label="Filters" withinPortal>
          <Indicator
            label={activeCount}
            size={16}
            color="orange"
            disabled={activeCount === 0}
            offset={4}
          >
            <ActionIcon
              variant={activeCount > 0 ? 'light' : 'default'}
              color={activeCount > 0 ? 'orange' : undefined}
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
                onClick={() =>
                  setFilters({ projects: [], owners: [], visibility: 'all' })
                }
              >
                Clear all
              </Button>
            )}
          </Group>

          <MultiSelect
            label="Project"
            placeholder="Any project"
            data={projectOptions}
            value={prefs.filters.projects}
            onChange={(v) => setFilters({ ...prefs.filters, projects: v })}
            searchable
            clearable
            comboboxProps={{ withinPortal: false }}
          />

          <MultiSelect
            label="Owner"
            placeholder="Any owner"
            data={ownerOptions}
            value={prefs.filters.owners}
            onChange={(v) => setFilters({ ...prefs.filters, owners: v })}
            searchable
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
                visibility: v as DashboardFilters['visibility'],
              })
            }
            allowDeselect={false}
            comboboxProps={{ withinPortal: false }}
          />
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
};

const DashboardsToolbar: React.FC<DashboardsToolbarProps> = ({
  prefs,
  projectOptions,
  ownerOptions,
  pinnedCount,
  pinDisabled,
  setView,
  setGroupBy,
  setSortBy,
  setSearch,
  setFilters,
  setOnlyPinned,
  clearFilters,
}) => {
  // Sort selector is meaningless in Table view (column headers handle sort).
  const showSort = prefs.view !== 'table';

  const activeFilterChips: { key: string; label: string; onRemove: () => void }[] = [];
  for (const id of prefs.filters.projects) {
    const opt = projectOptions.find((o) => o.value === id);
    activeFilterChips.push({
      key: `p:${id}`,
      label: opt?.label ?? id,
      onRemove: () =>
        setFilters({
          ...prefs.filters,
          projects: prefs.filters.projects.filter((p) => p !== id),
        }),
    });
  }
  for (const id of prefs.filters.owners) {
    const opt = ownerOptions.find((o) => o.value === id);
    activeFilterChips.push({
      key: `o:${id}`,
      label: opt?.label ?? id,
      onRemove: () =>
        setFilters({
          ...prefs.filters,
          owners: prefs.filters.owners.filter((o) => o !== id),
        }),
    });
  }
  if (prefs.filters.visibility !== 'all') {
    activeFilterChips.push({
      key: 'v',
      label: prefs.filters.visibility === 'public' ? 'Public only' : 'Private only',
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
          placeholder="Search dashboards…"
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

        <Select
          data={GROUP_DATA}
          value={prefs.groupBy}
          onChange={(v) => v && setGroupBy(v as GroupBy)}
          allowDeselect={false}
          leftSection={<Icon icon="mdi:folder-multiple-outline" width={14} />}
          w={190}
          aria-label="Group by"
        />

        {showSort && (
          <Select
            data={SORT_DATA}
            value={prefs.sortBy}
            onChange={(v) => v && setSortBy(v as SortBy)}
            allowDeselect={false}
            leftSection={<Icon icon="mdi:sort" width={14} />}
            w={190}
            aria-label="Sort by"
          />
        )}

        <Tooltip
          label={
            pinDisabled
              ? 'Pinning is disabled in public mode'
              : prefs.onlyPinned
                ? 'Show all dashboards'
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
          projectOptions={projectOptions}
          ownerOptions={ownerOptions}
          setFilters={setFilters}
        />

        <ViewPicker value={prefs.view} onChange={setView} />
      </Group>

      {activeFilterChips.length > 0 && (
        <Group gap="xs" wrap="wrap" align="center">
          {activeFilterChips.map((chip) => (
            <Badge
              key={chip.key}
              variant="light"
              color="orange"
              rightSection={
                <ActionIcon
                  size="xs"
                  variant="transparent"
                  color="orange"
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

export default DashboardsToolbar;
