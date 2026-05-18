import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  Group,
  Paper,
  Table,
  Text,
  ThemeIcon,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardListEntry } from 'depictio-react-core';
import DashboardActionsMenu from '../DashboardActionsMenu';
import type { CategoryInfo } from '../DashboardsList';
import type { GroupedDashboards } from '../lib/splitDefaultSections';
import { isOwnedByEmail } from '../lib/splitDefaultSections';
import { coerceString, isImagePath } from '../lib/format';
import type { Density } from '../hooks/useDashboardViewPrefs';

export interface DashboardTableViewProps {
  groups: GroupedDashboards[];
  projectNames: Map<string, string>;
  currentUserEmail: string | null;
  pinnedIds: Set<string>;
  pinDisabled: boolean;
  density: Density;
  /** When provided, a Category column is rendered (and made sortable) so the
   *  section the dashboard would have lived in is surfaced inline. */
  categoryById?: Map<string, CategoryInfo>;
  onView: (d: DashboardListEntry) => void;
  onEdit: (d: DashboardListEntry) => void;
  onDelete: (d: DashboardListEntry) => void;
  onDuplicate: (d: DashboardListEntry) => void;
  onExport: (d: DashboardListEntry) => void;
  onTogglePin: (id: string) => void;
  onSetDensity: (d: Density) => void;
  onBulkExport: (ids: string[]) => void;
  onBulkDelete: (ids: string[]) => void;
}

type SortKey =
  | 'title'
  | 'category'
  | 'project'
  | 'owner'
  | 'modified'
  | 'visibility'
  | 'tabs';
type SortDir = 'asc' | 'desc';

interface Row {
  id: string;
  dashboard: DashboardListEntry;
  childCount: number;
  isOwner: boolean;
  projectName: string;
  ownerEmail: string;
  isPublic: boolean;
  lastSavedTs: string;
  titleText: string;
  categoryLabel: string;
  categoryColor: string;
}

function compareRows(a: Row, b: Row, key: SortKey, dir: SortDir): number {
  const mul = dir === 'asc' ? 1 : -1;
  switch (key) {
    case 'title':
      return mul * a.titleText.localeCompare(b.titleText);
    case 'category':
      return mul * a.categoryLabel.localeCompare(b.categoryLabel);
    case 'project':
      return mul * a.projectName.localeCompare(b.projectName);
    case 'owner':
      return mul * a.ownerEmail.localeCompare(b.ownerEmail);
    case 'modified':
      return mul * a.lastSavedTs.localeCompare(b.lastSavedTs);
    case 'visibility':
      return mul * Number(b.isPublic) - mul * Number(a.isPublic);
    case 'tabs':
      return mul * (a.childCount - b.childCount);
    default:
      return 0;
  }
}

const SortHeader: React.FC<{
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
}> = ({ label, active, dir, onClick }) => (
  <UnstyledButton
    onClick={onClick}
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      fontWeight: 600,
    }}
    aria-label={`Sort by ${label}`}
  >
    {label}
    <Icon
      icon={
        active
          ? dir === 'asc'
            ? 'mdi:chevron-up'
            : 'mdi:chevron-down'
          : 'mdi:unfold-more-horizontal'
      }
      width={14}
      style={{ opacity: active ? 1 : 0.4 }}
    />
  </UnstyledButton>
);

const DashboardTableView: React.FC<DashboardTableViewProps> = ({
  groups,
  projectNames,
  currentUserEmail,
  pinnedIds,
  pinDisabled,
  density,
  categoryById,
  onView,
  onEdit,
  onDelete,
  onDuplicate,
  onExport,
  onTogglePin,
  onSetDensity,
  onBulkExport,
  onBulkDelete,
}) => {
  const [sortKey, setSortKey] = useState<SortKey>('modified');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const rows = useMemo<Row[]>(() => {
    const list: Row[] = groups.map((g) => {
      const id = String(g.parent.dashboard_id);
      const cat = categoryById?.get(id);
      return {
        id,
        dashboard: g.parent,
        childCount: g.children.length,
        isOwner: isOwnedByEmail(g.parent, currentUserEmail),
        projectName: g.parent.project_id
          ? (projectNames.get(String(g.parent.project_id)) ?? '')
          : '',
        ownerEmail: g.parent.permissions?.owners?.[0]?.email ?? '',
        isPublic: Boolean(g.parent.is_public),
        lastSavedTs: coerceString(g.parent.last_saved_ts, ''),
        titleText: g.parent.title || g.parent.dashboard_id,
        categoryLabel: cat?.label ?? '',
        categoryColor: cat?.color ?? 'var(--mantine-color-gray-6)',
      };
    });
    list.sort((a, b) => compareRows(a, b, sortKey, sortDir));
    return list;
  }, [groups, projectNames, currentUserEmail, categoryById, sortKey, sortDir]);

  const sortableColumns = useMemo<{ key: SortKey; label: string }[]>(
    () => [
      { key: 'title', label: 'Title' },
      ...(categoryById ? ([{ key: 'category', label: 'Category' }] as const) : []),
      { key: 'project', label: 'Project' },
      { key: 'owner', label: 'Owner' },
      { key: 'modified', label: 'Modified' },
      { key: 'visibility', label: 'Visibility' },
      { key: 'tabs', label: 'Tabs' },
    ],
    [categoryById],
  );

  // Prune ids that no longer match a visible row (after a delete, a search,
  // a filter change, etc.) so the bulk-action bar's count and the
  // `onBulkDelete`/`onBulkExport` payloads can never include stale ids.
  useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const visible = new Set(rows.map((r) => r.id));
      let changed = false;
      const next = new Set<string>();
      for (const id of prev) {
        if (visible.has(id)) next.add(id);
        else changed = true;
      }
      return changed ? next : prev;
    });
  }, [rows]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'modified' ? 'desc' : 'asc');
    }
  };

  const allIds = rows.map((r) => r.id);
  const allSelected = allIds.length > 0 && allIds.every((id) => selected.has(id));
  const someSelected = !allSelected && allIds.some((id) => selected.has(id));

  const toggleAll = () => {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(allIds));
    }
  };

  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectedRows = rows.filter((r) => selected.has(r.id));
  const allSelectedAreOwned =
    selectedRows.length > 0 && selectedRows.every((r) => r.isOwner);

  const verticalSpacing = density === 'compact' ? 4 : 'sm';

  return (
    <Paper withBorder radius="md" p={0}>
      {selected.size > 0 && (
        <Group
          p="sm"
          gap="md"
          justify="space-between"
          style={{
            borderBottom: '1px solid var(--mantine-color-default-border)',
            background: 'var(--mantine-color-default-hover)',
          }}
        >
          <Text size="sm" fw={500}>
            {selected.size} selected
          </Text>
          <Group gap="xs">
            <Button
              variant="light"
              size="xs"
              leftSection={<Icon icon="mdi:download" width={14} />}
              onClick={() => onBulkExport(Array.from(selected))}
            >
              Export
            </Button>
            <Tooltip
              label={
                allSelectedAreOwned ? 'Delete selected' : 'You can only delete dashboards you own'
              }
              withinPortal
            >
              <span>
                <Button
                  variant="light"
                  color="red"
                  size="xs"
                  leftSection={<Icon icon="tabler:trash" width={14} />}
                  disabled={!allSelectedAreOwned}
                  onClick={() => onBulkDelete(Array.from(selected))}
                >
                  Delete
                </Button>
              </span>
            </Tooltip>
            <Button variant="subtle" size="xs" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
          </Group>
        </Group>
      )}

      <Group justify="flex-end" px="sm" pt="xs" gap="xs">
        <Tooltip label="Density" withinPortal>
          <ActionIcon.Group>
            <ActionIcon
              variant={density === 'cozy' ? 'filled' : 'subtle'}
              color={density === 'cozy' ? 'orange' : 'gray'}
              onClick={() => onSetDensity('cozy')}
              aria-label="Cozy density"
            >
              <Icon icon="mdi:format-line-spacing" width={16} />
            </ActionIcon>
            <ActionIcon
              variant={density === 'compact' ? 'filled' : 'subtle'}
              color={density === 'compact' ? 'orange' : 'gray'}
              onClick={() => onSetDensity('compact')}
              aria-label="Compact density"
            >
              <Icon icon="mdi:format-align-justify" width={16} />
            </ActionIcon>
          </ActionIcon.Group>
        </Tooltip>
      </Group>

      <Table.ScrollContainer minWidth={800}>
        <Table verticalSpacing={verticalSpacing} highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ width: 36 }}>
                <Checkbox
                  checked={allSelected}
                  indeterminate={someSelected}
                  onChange={toggleAll}
                  aria-label="Select all"
                />
              </Table.Th>
              <Table.Th style={{ width: 36 }} aria-label="Pin" />
              {sortableColumns.map((col) => (
                <Table.Th key={col.key}>
                  <SortHeader
                    label={col.label}
                    active={sortKey === col.key}
                    dir={sortDir}
                    onClick={() => toggleSort(col.key)}
                  />
                </Table.Th>
              ))}
              <Table.Th style={{ width: 36 }} aria-label="Actions" />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => {
              const icon = coerceString(r.dashboard.icon, 'mdi:view-dashboard');
              const iconColor = coerceString(r.dashboard.icon_color, 'orange');
              const totalTabs = r.childCount + 1;
              const isPinned = pinnedIds.has(r.id);
              return (
                <Table.Tr key={r.id}>
                  <Table.Td>
                    <Checkbox
                      checked={selected.has(r.id)}
                      onChange={() => toggleOne(r.id)}
                      aria-label={`Select ${r.titleText}`}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Tooltip
                      label={
                        pinDisabled
                          ? 'Pinning is disabled in public mode'
                          : isPinned
                            ? 'Unpin'
                            : 'Pin to top'
                      }
                      withinPortal
                    >
                      <ActionIcon
                        variant="transparent"
                        size="sm"
                        onClick={() => onTogglePin(r.id)}
                        disabled={pinDisabled}
                        aria-label={isPinned ? 'Unpin dashboard' : 'Pin dashboard'}
                      >
                        <Icon
                          icon={isPinned ? 'mdi:star' : 'mdi:star-outline'}
                          width={16}
                          color={
                            isPinned
                              ? 'var(--mantine-color-yellow-5)'
                              : 'var(--mantine-color-gray-5)'
                          }
                        />
                      </ActionIcon>
                    </Tooltip>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      {isImagePath(icon) ? (
                        <img
                          src={icon}
                          alt=""
                          style={{
                            width: 22,
                            height: 22,
                            objectFit: 'contain',
                            borderRadius: 4,
                            flexShrink: 0,
                          }}
                        />
                      ) : (
                        <ThemeIcon
                          color={iconColor}
                          radius="sm"
                          size={22}
                          variant="filled"
                          style={{ flexShrink: 0 }}
                        >
                          <Icon icon={icon} width={14} />
                        </ThemeIcon>
                      )}
                      <UnstyledButton
                        onClick={() => onView(r.dashboard)}
                        style={{ textAlign: 'left' }}
                      >
                        <Text fw={500} size="sm">
                          {r.titleText}
                        </Text>
                      </UnstyledButton>
                    </Group>
                  </Table.Td>
                  {categoryById && (
                    <Table.Td>
                      {r.categoryLabel ? (
                        <Badge
                          variant="dot"
                          size="sm"
                          color={r.categoryColor}
                          styles={{ root: { textTransform: 'none' } }}
                        >
                          {r.categoryLabel}
                        </Badge>
                      ) : (
                        <Text size="xs" c="dimmed">
                          —
                        </Text>
                      )}
                    </Table.Td>
                  )}
                  <Table.Td>
                    {r.projectName ? (
                      <Badge color="teal" variant="light" size="sm">
                        {r.projectName}
                      </Badge>
                    ) : (
                      <Text size="xs" c="dimmed">
                        —
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {r.ownerEmail ? (
                      <Text size="sm">{r.ownerEmail}</Text>
                    ) : (
                      <Text size="xs" c="dimmed">
                        —
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {r.lastSavedTs ? r.lastSavedTs.slice(0, 16).replace('T', ' ') : 'Never'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge
                      color={r.isPublic ? 'green' : 'grape'}
                      variant="light"
                      size="sm"
                    >
                      {r.isPublic ? 'Public' : 'Private'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap" align="center">
                      <Icon
                        icon="mdi:tab"
                        width={12}
                        color="var(--mantine-color-dimmed)"
                      />
                      <Text size="sm" c={r.childCount > 0 ? undefined : 'dimmed'}>
                        {totalTabs}
                      </Text>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <DashboardActionsMenu
                      dashboard={r.dashboard}
                      isOwner={r.isOwner}
                      onView={onView}
                      onEdit={onEdit}
                      onDelete={onDelete}
                      onDuplicate={onDuplicate}
                      onExport={onExport}
                      triggerSize="sm"
                    />
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Paper>
  );
};

export default DashboardTableView;
