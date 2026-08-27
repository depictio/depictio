import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  Code,
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
import { dashboardHref, dashboardLinkClickHandler } from '../lib/dashboardLinks';
import { isOwnedByEmail } from '../lib/splitDefaultSections';
import { coerceString, isImagePath, resolveAssetUrl } from '../lib/format';
import { WORKFLOW_COLOR_MAP, WORKFLOW_ICON_MAP } from '../lib/workflowIcons';
import type { Density } from '../hooks/useDashboardViewPrefs';
import ColumnPicker from '../../components/ColumnPicker';
import { type ColumnDef, useTableColumns } from '../../lib/useTableColumns';
import {
  formatDateTime,
  formatDateTimeVerbose,
  formatRelative,
  timestampSortKey,
} from '../../lib/datetime';
import { useBrandAccents } from 'depictio-react-core';

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

type ColumnKey =
  | 'title'
  | 'subtitle'
  | 'category'
  | 'project'
  | 'owner'
  | 'created'
  | 'modified'
  | 'visibility'
  | 'tabs'
  | 'components'
  | 'workflow'
  | 'version'
  | 'id';

type SortDir = 'asc' | 'desc';

/** Column catalogue. Order here is the render order; `defaultVisible: false`
 *  keeps the extra metadata columns opt-in so the default table stays readable. */
const ALL_COLUMNS: ColumnDef<ColumnKey>[] = [
  { key: 'title', label: 'Title', alwaysVisible: true },
  { key: 'subtitle', label: 'Subtitle', defaultVisible: false },
  { key: 'category', label: 'Category' },
  { key: 'project', label: 'Project' },
  { key: 'owner', label: 'Owner' },
  { key: 'created', label: 'Created', description: 'Created (local time)' },
  { key: 'modified', label: 'Modified', description: 'Last modified (local time)' },
  { key: 'visibility', label: 'Visibility' },
  { key: 'tabs', label: 'Tabs' },
  { key: 'components', label: 'Components', defaultVisible: false },
  { key: 'workflow', label: 'Workflow', description: 'Workflow system', defaultVisible: false },
  { key: 'version', label: 'Version', defaultVisible: false },
  { key: 'id', label: 'ID', description: 'Dashboard ID', defaultVisible: false },
];

const STORAGE_KEY = 'depictio.dashboards.tableColumns.v1';

interface Row {
  id: string;
  dashboard: DashboardListEntry;
  childCount: number;
  componentCount: number | null;
  isOwner: boolean;
  projectName: string;
  ownerEmail: string;
  isPublic: boolean;
  lastSavedTs: string;
  createdTs: string;
  titleText: string;
  subtitle: string;
  workflowSystem: string;
  version: string;
  categoryLabel: string;
  categoryColor: string;
}

function compareNullable(a: number | null, b: number | null, dir: SortDir): number {
  const mul = dir === 'asc' ? 1 : -1;
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return mul * (a - b);
}

function compareRows(a: Row, b: Row, key: ColumnKey, dir: SortDir): number {
  const mul = dir === 'asc' ? 1 : -1;
  switch (key) {
    case 'title':
      return mul * a.titleText.localeCompare(b.titleText);
    case 'subtitle':
      return mul * a.subtitle.localeCompare(b.subtitle);
    case 'category':
      return mul * a.categoryLabel.localeCompare(b.categoryLabel);
    case 'project':
      return mul * a.projectName.localeCompare(b.projectName);
    case 'owner':
      return mul * a.ownerEmail.localeCompare(b.ownerEmail);
    // Timestamps are compared as epoch ms rather than lexically: the wire
    // format is not always the same shape (naive vs ISO with offset), so
    // string ordering would interleave the two.
    case 'created':
      return mul * (timestampSortKey(a.createdTs) - timestampSortKey(b.createdTs));
    case 'modified':
      return mul * (timestampSortKey(a.lastSavedTs) - timestampSortKey(b.lastSavedTs));
    case 'visibility':
      return mul * Number(b.isPublic) - mul * Number(a.isPublic);
    case 'tabs':
      return mul * (a.childCount - b.childCount);
    case 'components':
      return compareNullable(a.componentCount, b.componentCount, dir);
    case 'workflow':
      return mul * a.workflowSystem.localeCompare(b.workflowSystem);
    case 'version':
      return mul * a.version.localeCompare(b.version, undefined, { numeric: true });
    case 'id':
      return mul * a.id.localeCompare(b.id);
    default:
      return 0;
  }
}

const SortHeader: React.FC<{
  label: string;
  tooltip?: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
}> = ({ label, tooltip, active, dir, onClick }) => {
  const button = (
    <UnstyledButton
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontWeight: 600,
      }}
      aria-label={`Sort by ${tooltip ?? label}`}
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
  return tooltip ? (
    <Tooltip label={tooltip} withinPortal>
      {button}
    </Tooltip>
  ) : (
    button
  );
};

const Dash: React.FC = () => (
  <Text size="xs" c="dimmed">
    —
  </Text>
);

/** Absolute local time in the cell, with a tooltip spelling out the timezone
 *  and the original UTC value so a "why is this 2h off?" question answers
 *  itself (issue #932). */
const TimeCell: React.FC<{ raw: string; empty?: string }> = ({ raw, empty = 'Never' }) => {
  if (!raw) {
    return (
      <Text size="xs" c="dimmed">
        {empty}
      </Text>
    );
  }
  return (
    <Tooltip label={`${formatDateTimeVerbose(raw)} · ${formatRelative(raw)}`} withinPortal>
      <Text size="sm" style={{ whiteSpace: 'nowrap' }}>
        {formatDateTime(raw)}
      </Text>
    </Tooltip>
  );
};

const CountCell: React.FC<{ icon: string; value: number | null }> = ({ icon, value }) => (
  <Group gap={4} wrap="nowrap" align="center">
    <Icon icon={icon} width={12} color="var(--mantine-color-dimmed)" />
    {value === null ? (
      <Text size="sm" c="dimmed">
        —
      </Text>
    ) : (
      <Text size="sm" c={value > 0 ? undefined : 'dimmed'}>
        {value}
      </Text>
    )}
  </Group>
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
  const accent = useBrandAccents();
  const [sortKey, setSortKey] = useState<ColumnKey>('modified');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // The Category column only makes sense when the caller supplies the mapping;
  // drop it from the picker entirely otherwise so users can't enable a column
  // that would always render as "—".
  const columnCatalogue = useMemo(
    () => (categoryById ? ALL_COLUMNS : ALL_COLUMNS.filter((c) => c.key !== 'category')),
    [categoryById],
  );
  const { visibleColumns, isVisible, allColumns, toggle, reset, isCustomized } =
    useTableColumns<ColumnKey>(STORAGE_KEY, columnCatalogue);

  const rows = useMemo<Row[]>(() => {
    const list: Row[] = groups.map((g) => {
      const id = String(g.parent.dashboard_id);
      const cat = categoryById?.get(id);
      const meta = g.parent.stored_metadata;
      const versionRaw = g.parent.version;
      return {
        id,
        dashboard: g.parent,
        childCount: g.children.length,
        // `stored_metadata` is only projected for admin listings; show "—"
        // rather than a misleading 0 when the field isn't on the payload.
        componentCount: Array.isArray(meta) ? meta.length : null,
        isOwner: isOwnedByEmail(g.parent, currentUserEmail),
        projectName: g.parent.project_id
          ? (projectNames.get(String(g.parent.project_id)) ?? '')
          : '',
        ownerEmail: g.parent.permissions?.owners?.[0]?.email ?? '',
        isPublic: Boolean(g.parent.is_public),
        lastSavedTs: coerceString(g.parent.last_saved_ts, ''),
        createdTs: coerceString(g.parent.creation_time, ''),
        titleText: g.parent.title || g.parent.dashboard_id,
        subtitle: coerceString(g.parent.subtitle, ''),
        workflowSystem: coerceString(g.parent.workflow_system, ''),
        version:
          typeof versionRaw === 'number' || typeof versionRaw === 'string'
            ? String(versionRaw)
            : '',
        categoryLabel: cat?.label ?? '',
        categoryColor: cat?.color ?? 'var(--mantine-color-gray-6)',
      };
    });
    list.sort((a, b) => compareRows(a, b, sortKey, sortDir));
    return list;
  }, [groups, projectNames, currentUserEmail, categoryById, sortKey, sortDir]);

  // A hidden column must not keep driving the sort order, otherwise the table
  // looks arbitrarily ordered with no visible sort indicator.
  useEffect(() => {
    if (!isVisible(sortKey)) {
      setSortKey('title');
      setSortDir('asc');
    }
  }, [isVisible, sortKey]);

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

  const toggleSort = (key: ColumnKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      // Time columns are far more useful newest-first.
      setSortDir(key === 'modified' || key === 'created' ? 'desc' : 'asc');
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

  const renderCell = (r: Row, key: ColumnKey): React.ReactNode => {
    switch (key) {
      case 'title': {
        const icon = coerceString(r.dashboard.icon, 'mdi:view-dashboard');
        const iconColor = coerceString(r.dashboard.icon_color, accent.tertiary);
        return (
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
              component="a"
              href={dashboardHref(String(r.dashboard.dashboard_id))}
              onClick={dashboardLinkClickHandler(() => onView(r.dashboard))}
              style={{ textAlign: 'left', color: 'inherit' }}
            >
              <Text fw={500} size="sm">
                {r.titleText}
              </Text>
            </UnstyledButton>
          </Group>
        );
      }
      case 'subtitle':
        return r.subtitle ? (
          <Text size="sm" lineClamp={1}>
            {r.subtitle}
          </Text>
        ) : (
          <Dash />
        );
      case 'category':
        return r.categoryLabel ? (
          <Badge
            variant="dot"
            size="sm"
            color={r.categoryColor}
            styles={{ root: { textTransform: 'none' } }}
          >
            {r.categoryLabel}
          </Badge>
        ) : (
          <Dash />
        );
      case 'project': {
        if (!r.projectName) return <Dash />;
        const pid = (r.dashboard.project_id as string | undefined) || null;
        return (
          <Badge
            color={accent.secondary}
            variant="light"
            size="sm"
            component={pid ? 'a' : 'div'}
            href={pid ? `/projects/${pid}` : undefined}
            onClick={(e: React.MouseEvent) => e.stopPropagation()}
            style={{ cursor: pid ? 'pointer' : undefined, maxWidth: '100%' }}
          >
            {r.projectName}
          </Badge>
        );
      }
      case 'owner':
        return r.ownerEmail ? <Text size="sm">{r.ownerEmail}</Text> : <Dash />;
      case 'created':
        return <TimeCell raw={r.createdTs} empty="Unknown" />;
      case 'modified':
        return <TimeCell raw={r.lastSavedTs} />;
      case 'visibility':
        return (
          <Badge color={r.isPublic ? 'green' : 'grape'} variant="light" size="sm">
            {r.isPublic ? 'Public' : 'Private'}
          </Badge>
        );
      case 'tabs':
        return <CountCell icon="mdi:tab" value={r.childCount + 1} />;
      case 'components':
        return <CountCell icon="mdi:shape-outline" value={r.componentCount} />;
      case 'workflow': {
        if (!r.workflowSystem || r.workflowSystem === 'none') return <Dash />;
        // Match the Project badge's shape (light variant, size sm) but use the
        // workflow system's own brand colour and logo, so the cell reads the
        // same way the create/edit modals present the system.
        const logo = WORKFLOW_ICON_MAP[r.workflowSystem];
        return (
          <Badge
            color={WORKFLOW_COLOR_MAP[r.workflowSystem] ?? 'indigo'}
            variant="light"
            size="sm"
            leftSection={
              logo ? (
                <img
                  src={resolveAssetUrl(logo)}
                  alt=""
                  style={{ width: 12, height: 12, objectFit: 'contain', display: 'block' }}
                />
              ) : undefined
            }
            style={{ maxWidth: '100%' }}
          >
            {r.workflowSystem}
          </Badge>
        );
      }
      case 'version':
        return r.version ? <Text size="sm">{r.version}</Text> : <Dash />;
      case 'id':
        return (
          <Tooltip label={r.id} withinPortal>
            <Code style={{ fontSize: 11 }}>{r.id.slice(-8)}</Code>
          </Tooltip>
        );
      default:
        return null;
    }
  };

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
        <ColumnPicker
          columns={allColumns}
          isVisible={isVisible}
          onToggle={toggle}
          onReset={reset}
          isCustomized={isCustomized}
          visibleCount={visibleColumns.length}
        />
        <Tooltip label="Density" withinPortal>
          <ActionIcon.Group>
            <ActionIcon
              variant={density === 'cozy' ? 'filled' : 'subtle'}
              color={density === 'cozy' ? accent.tertiary : 'gray'}
              onClick={() => onSetDensity('cozy')}
              aria-label="Cozy density"
            >
              <Icon icon="mdi:format-line-spacing" width={16} />
            </ActionIcon>
            <ActionIcon
              variant={density === 'compact' ? 'filled' : 'subtle'}
              color={density === 'compact' ? accent.tertiary : 'gray'}
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
              {visibleColumns.map((col) => (
                <Table.Th key={col.key}>
                  <SortHeader
                    label={col.label}
                    tooltip={col.description}
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
                  {visibleColumns.map((col) => (
                    <Table.Td key={col.key}>{renderCell(r, col.key)}</Table.Td>
                  ))}
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
