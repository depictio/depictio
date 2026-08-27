import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Code,
  Group,
  Table,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { ProjectListEntry } from 'depictio-react-core';

import ProjectActionsMenu from '../ProjectActionsMenu';
import { parseTemplate, TemplateChip } from '../template';
import { determineRole } from '../lib/projectRole';
import type { Density } from '../hooks/useProjectViewPrefs';
import { coerceString } from '../../dashboards/lib/format';
import ColumnPicker from '../../components/ColumnPicker';
import { type ColumnDef, useTableColumns } from '../../lib/useTableColumns';
import { useBrandAccents } from 'depictio-react-core';
import {
  formatDateTime,
  formatDateTimeVerbose,
  formatRelative,
  timestampSortKey,
} from '../../lib/datetime';

export interface ProjectTableViewProps {
  projects: ProjectListEntry[];
  currentUserId: string | null;
  isAdmin: boolean;
  pinnedIds: Set<string>;
  pinDisabled: boolean;
  density: Density;
  onSetDensity: (d: Density) => void;
  onView: (p: ProjectListEntry) => void;
  onEdit: (p: ProjectListEntry) => void;
  onDelete: (p: ProjectListEntry) => void;
  onTogglePin: (id: string) => void;
}

type ColumnKey =
  | 'name'
  | 'type'
  | 'visibility'
  | 'template'
  | 'owner'
  | 'role'
  | 'members'
  | 'workflows'
  | 'data'
  | 'joins'
  | 'created'
  | 'modified'
  | 'yaml'
  | 'id';

type SortDir = 'asc' | 'desc';

/** Column catalogue. Order here is the render order; `defaultVisible: false`
 *  keeps the extra metadata columns opt-in so the default table stays readable. */
const ALL_COLUMNS: ColumnDef<ColumnKey>[] = [
  { key: 'name', label: 'Name', alwaysVisible: true },
  { key: 'type', label: 'Type' },
  { key: 'visibility', label: 'Visibility' },
  { key: 'template', label: 'Template' },
  { key: 'owner', label: 'Owner' },
  { key: 'role', label: 'Your role', defaultVisible: false },
  { key: 'members', label: 'Members', description: 'Members with access', defaultVisible: false },
  { key: 'workflows', label: 'Workflows' },
  { key: 'data', label: 'DC', description: 'Data collections' },
  { key: 'joins', label: 'Joins', defaultVisible: false },
  { key: 'created', label: 'Created', description: 'Created (local time)' },
  { key: 'modified', label: 'Modified', description: 'Last modified (local time)' },
  { key: 'yaml', label: 'YAML', description: 'YAML config path', defaultVisible: false },
  { key: 'id', label: 'ID', description: 'Project ID', defaultVisible: false },
];

const STORAGE_KEY = 'depictio.projects.tableColumns.v1';

interface Row {
  id: string;
  project: ProjectListEntry;
  isAdvanced: boolean;
  isPublic: boolean;
  ownerEmail: string;
  role: string;
  memberCount: number | null;
  /** Count for advanced projects; null for basic (rendered as "NA"). */
  workflowCount: number | null;
  /** Sum of data collections across the project (or via workflows for
   *  advanced projects). null when the field isn't on the entry. */
  dataCollectionCount: number | null;
  joinCount: number | null;
  createdRaw: string;
  modifiedRaw: string;
  yamlPath: string;
  templateLabel: string;
  templateParsed: ReturnType<typeof parseTemplate>;
  canMutate: boolean;
}

/** Total data collections on a project. The API stores DCs under each
 *  workflow's `data_collections` (top-level `data_collections` is present
 *  but empty in current payloads), so we sum across workflows and only fall
 *  back to the top-level array when no workflow has any. Returns null when
 *  neither location yields a number. */
function countDataCollections(p: ProjectListEntry): number | null {
  let total = 0;
  let foundAny = false;
  if (Array.isArray(p.workflows)) {
    for (const wf of p.workflows) {
      const dcs = (wf as { data_collections?: unknown }).data_collections;
      if (Array.isArray(dcs)) {
        total += dcs.length;
        foundAny = true;
      }
    }
  }
  if (foundAny) return total;
  const top = (p as { data_collections?: unknown }).data_collections;
  if (Array.isArray(top)) return top.length;
  return null;
}

/** Distinct users named anywhere in the permissions blob. The wildcard viewer
 *  `"*"` means "everyone" and isn't a countable member, so it's skipped. */
function countMembers(p: ProjectListEntry): number | null {
  const perms = p.permissions as
    | Record<string, Array<{ _id?: string; id?: string; email?: string } | string> | undefined>
    | undefined;
  if (!perms) return null;
  const ids = new Set<string>();
  let saw = false;
  for (const group of ['owners', 'editors', 'viewers'] as const) {
    const members = perms[group];
    if (!Array.isArray(members)) continue;
    saw = true;
    for (const m of members) {
      if (typeof m === 'string') continue; // wildcard "*"
      const key = m._id ?? m.id ?? m.email;
      if (key) ids.add(String(key));
    }
  }
  return saw ? ids.size : null;
}

function countArray(value: unknown): number | null {
  return Array.isArray(value) ? value.length : null;
}

function compareNullable(a: number | null, b: number | null, dir: SortDir): number {
  const mul = dir === 'asc' ? 1 : -1;
  // Nulls sort last regardless of direction so "NA" rows don't move around.
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return mul * (a - b);
}

function compareRows(a: Row, b: Row, key: ColumnKey, dir: SortDir): number {
  const mul = dir === 'asc' ? 1 : -1;
  switch (key) {
    case 'name':
      return mul * a.project.name.localeCompare(b.project.name);
    case 'type':
      return mul * Number(a.isAdvanced) - mul * Number(b.isAdvanced);
    case 'visibility':
      return mul * Number(b.isPublic) - mul * Number(a.isPublic);
    case 'template':
      return mul * a.templateLabel.localeCompare(b.templateLabel);
    case 'owner':
      return mul * a.ownerEmail.localeCompare(b.ownerEmail);
    case 'role':
      return mul * a.role.localeCompare(b.role);
    case 'members':
      return compareNullable(a.memberCount, b.memberCount, dir);
    case 'workflows':
      return compareNullable(a.workflowCount, b.workflowCount, dir);
    case 'data':
      return compareNullable(a.dataCollectionCount, b.dataCollectionCount, dir);
    case 'joins':
      return compareNullable(a.joinCount, b.joinCount, dir);
    // Timestamps are compared as epoch ms rather than lexically: the wire
    // format is not always the same shape (naive vs ISO with offset), so
    // string ordering would interleave the two.
    case 'created':
      return mul * (timestampSortKey(a.createdRaw) - timestampSortKey(b.createdRaw));
    case 'modified':
      return mul * (timestampSortKey(a.modifiedRaw) - timestampSortKey(b.modifiedRaw));
    case 'yaml':
      return mul * a.yamlPath.localeCompare(b.yamlPath);
    case 'id':
      return mul * a.id.localeCompare(b.id);
    default:
      return 0;
  }
}

const SortHeader: React.FC<{
  label: string;
  ariaLabel?: string;
  tooltip?: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
}> = ({ label, ariaLabel, tooltip, active, dir, onClick }) => {
  const button = (
    <UnstyledButton
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontWeight: 600,
      }}
      aria-label={`Sort by ${ariaLabel ?? tooltip ?? label}`}
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
const TimeCell: React.FC<{ raw: string; empty?: string }> = ({ raw, empty = '—' }) => {
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

const CountCell: React.FC<{ icon: string; value: number | null; nullLabel?: string }> = ({
  icon,
  value,
  nullLabel = '—',
}) => (
  <Group gap={4} wrap="nowrap" align="center">
    <Icon icon={icon} width={12} color="var(--mantine-color-dimmed)" />
    {value === null ? (
      <Text size="sm" c="dimmed">
        {nullLabel}
      </Text>
    ) : (
      <Text size="sm" c={value > 0 ? undefined : 'dimmed'}>
        {value}
      </Text>
    )}
  </Group>
);

const ProjectTableView: React.FC<ProjectTableViewProps> = ({
  projects,
  currentUserId,
  isAdmin,
  pinnedIds,
  pinDisabled,
  density,
  onSetDensity,
  onView,
  onEdit,
  onDelete,
  onTogglePin,
}) => {
  const accent = useBrandAccents();
  const [sortKey, setSortKey] = useState<ColumnKey>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const { visibleColumns, isVisible, allColumns, toggle, reset, isCustomized } =
    useTableColumns<ColumnKey>(STORAGE_KEY, ALL_COLUMNS);

  const rows = useMemo<Row[]>(() => {
    const list: Row[] = projects.map((p) => {
      const role = determineRole(p, currentUserId);
      const tmpl = parseTemplate(p);
      const isAdvanced = p.project_type === 'advanced';
      // Basic projects don't expose user-managed workflows (they wrap a single
      // implicit one), so the count would always be 0/1 and read as wrong —
      // surface it as "NA" instead.
      const workflowCount = isAdvanced
        ? Array.isArray(p.workflows)
          ? p.workflows.length
          : 0
        : null;
      return {
        id: String(p._id ?? p.id ?? ''),
        project: p,
        isAdvanced,
        isPublic: Boolean(p.is_public),
        ownerEmail: p.permissions?.owners?.[0]?.email ?? '',
        role: role ?? '',
        memberCount: countMembers(p),
        workflowCount,
        dataCollectionCount: countDataCollections(p),
        joinCount: countArray(p.joins),
        createdRaw: coerceString(p.registration_time, ''),
        // Projects that have never been edited since creation carry no
        // `last_modified`; fall back to the creation time so the column reads
        // as a real modification date rather than a blank.
        modifiedRaw:
          coerceString(p.last_modified, '') || coerceString(p.registration_time, ''),
        yamlPath: coerceString(p.yaml_config_path, ''),
        templateLabel: tmpl ? `${tmpl.source}/${tmpl.repo || ''}`.trim() : '',
        templateParsed: tmpl,
        canMutate: role === 'Owner' || isAdmin,
      };
    });
    list.sort((a, b) => compareRows(a, b, sortKey, sortDir));
    return list;
  }, [projects, currentUserId, isAdmin, sortKey, sortDir]);

  // A hidden column must not keep driving the sort order, otherwise the table
  // looks arbitrarily ordered with no visible sort indicator.
  useEffect(() => {
    if (!isVisible(sortKey)) {
      setSortKey('name');
      setSortDir('asc');
    }
  }, [isVisible, sortKey]);

  const toggleSort = (key: ColumnKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      // Time columns are far more useful newest-first.
      setSortDir(key === 'created' || key === 'modified' ? 'desc' : 'asc');
    }
  };

  const renderCell = (r: Row, key: ColumnKey): React.ReactNode => {
    switch (key) {
      case 'name':
        return (
          <UnstyledButton onClick={() => onView(r.project)} style={{ textAlign: 'left' }}>
            <Text fw={500} size="sm">
              {r.project.name}
            </Text>
          </UnstyledButton>
        );
      case 'type':
        return (
          <Badge
            color={r.isAdvanced ? 'orange' : 'cyan'}
            variant="light"
            size="sm"
            // Mantine clamps the INNER `.mantine-Badge-label` with
            // overflow:hidden + text-overflow:ellipsis, so styling the root
            // alone still renders "ADVAN…". These labels are short and fixed.
            styles={{ root: { maxWidth: 'none' }, label: { overflow: 'visible' } }}
          >
            {r.isAdvanced ? 'Advanced' : 'Basic'}
          </Badge>
        );
      case 'visibility':
        return (
          <Badge
            color={r.isPublic ? 'green' : 'grape'}
            variant="light"
            size="sm"
            leftSection={<Icon icon={r.isPublic ? 'mdi:earth' : 'mdi:lock-outline'} width={11} />}
            styles={{ root: { maxWidth: 'none' }, label: { overflow: 'visible' } }}
          >
            {r.isPublic ? 'Public' : 'Private'}
          </Badge>
        );
      case 'template':
        return r.templateParsed ? <TemplateChip parsed={r.templateParsed} verbose /> : <Dash />;
      case 'owner':
        return r.ownerEmail ? <Text size="sm">{r.ownerEmail}</Text> : <Dash />;
      case 'role':
        return r.role ? (
          <Badge variant="outline" size="sm" styles={{ root: { textTransform: 'none' } }}>
            {r.role}
          </Badge>
        ) : (
          <Dash />
        );
      case 'members':
        return <CountCell icon="mdi:account-group-outline" value={r.memberCount} />;
      case 'workflows':
        return <CountCell icon="mdi:graph" value={r.workflowCount} nullLabel="NA" />;
      case 'data':
        return <CountCell icon="mdi:database-outline" value={r.dataCollectionCount} />;
      case 'joins':
        return <CountCell icon="mdi:vector-link" value={r.joinCount} />;
      case 'created':
        return <TimeCell raw={r.createdRaw} empty="Unknown" />;
      case 'modified':
        return <TimeCell raw={r.modifiedRaw} />;
      case 'yaml':
        return r.yamlPath ? (
          <Tooltip label={r.yamlPath} withinPortal>
            <Text size="xs" lineClamp={1} style={{ maxWidth: 200 }}>
              {r.yamlPath}
            </Text>
          </Tooltip>
        ) : (
          <Dash />
        );
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

  // NOTE: deliberately not wrapping in `Table.ScrollContainer` — its inner
  // overflow:auto + min-width interaction confuses the Mantine Accordion's
  // panel-height measurement and clips the table to ~40px. A plain overflow
  // wrapper sidesteps that while still giving horizontal scroll on narrow
  // viewports.
  return (
    <div
      style={{
        border: '1px solid var(--mantine-color-default-border)',
        borderRadius: 8,
      }}
    >
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
      <div style={{ overflowX: 'auto' }}>
        <Table
          verticalSpacing={density === 'compact' ? 4 : 'sm'}
          highlightOnHover
          miw={Math.max(700, visibleColumns.length * 145)}
        >
          <Table.Thead>
            <Table.Tr>
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
              <Table.Th style={{ width: 120, textAlign: 'right' }} aria-label="Actions" />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => {
              const isPinned = pinnedIds.has(r.id);
              return (
                <Table.Tr key={r.id}>
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
                        aria-label={isPinned ? 'Unpin project' : 'Pin project'}
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
                    <Group gap={4} wrap="nowrap" justify="flex-end">
                      <Tooltip label="Workflows & data collections" withinPortal>
                        <ActionIcon
                          variant="subtle"
                          color={accent.secondary}
                          size="sm"
                          component="a"
                          href={`/projects/${r.id}`}
                          aria-label="Open data manager"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Icon icon="mdi:database-outline" width={16} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip label="Roles and permissions" withinPortal>
                        <ActionIcon
                          variant="subtle"
                          color="blue"
                          size="sm"
                          component="a"
                          href={`/projects/${r.id}/permissions`}
                          aria-label="Open permissions"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Icon icon="mdi:shield-account-outline" width={16} />
                        </ActionIcon>
                      </Tooltip>
                      <ProjectActionsMenu
                        project={r.project}
                        canMutate={r.canMutate}
                        onEdit={onEdit}
                        onDelete={onDelete}
                        triggerSize="sm"
                      />
                    </Group>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </div>
    </div>
  );
};

export default ProjectTableView;
