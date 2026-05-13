import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
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
import { coerceString, formatLastSaved } from '../../dashboards/lib/format';

export interface ProjectTableViewProps {
  projects: ProjectListEntry[];
  currentUserId: string | null;
  isAdmin: boolean;
  pinnedIds: Set<string>;
  pinDisabled: boolean;
  onView: (p: ProjectListEntry) => void;
  onEdit: (p: ProjectListEntry) => void;
  onDelete: (p: ProjectListEntry) => void;
  onTogglePin: (id: string) => void;
}

type SortKey =
  | 'name'
  | 'type'
  | 'visibility'
  | 'template'
  | 'owner'
  | 'workflows'
  | 'data'
  | 'created';
type SortDir = 'asc' | 'desc';

interface Row {
  id: string;
  project: ProjectListEntry;
  isAdvanced: boolean;
  isPublic: boolean;
  ownerEmail: string;
  /** Count for advanced projects; null for basic (rendered as "NA"). */
  workflowCount: number | null;
  /** Sum of data collections across the project (or via workflows for
   *  advanced projects). null when the field isn't on the entry. */
  dataCollectionCount: number | null;
  createdRaw: string;
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

function compareNullable(a: number | null, b: number | null, dir: SortDir): number {
  const mul = dir === 'asc' ? 1 : -1;
  // Nulls sort last regardless of direction so "NA" rows don't move around.
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return mul * (a - b);
}

function compareRows(a: Row, b: Row, key: SortKey, dir: SortDir): number {
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
    case 'workflows':
      return compareNullable(a.workflowCount, b.workflowCount, dir);
    case 'data':
      return compareNullable(a.dataCollectionCount, b.dataCollectionCount, dir);
    case 'created':
      return mul * a.createdRaw.localeCompare(b.createdRaw);
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
      aria-label={`Sort by ${ariaLabel ?? label}`}
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

const SORTABLE_COLUMNS: {
  key: SortKey;
  label: string;
  ariaLabel?: string;
  tooltip?: string;
}[] = [
  { key: 'name', label: 'Name' },
  { key: 'type', label: 'Type' },
  { key: 'visibility', label: 'Visibility' },
  { key: 'template', label: 'Template' },
  { key: 'owner', label: 'Owner' },
  { key: 'workflows', label: 'Workflows' },
  { key: 'data', label: 'DC', ariaLabel: 'Data Collections', tooltip: 'Data Collections' },
  { key: 'created', label: 'Created' },
];

const ProjectTableView: React.FC<ProjectTableViewProps> = ({
  projects,
  currentUserId,
  isAdmin,
  pinnedIds,
  pinDisabled,
  onView,
  onEdit,
  onDelete,
  onTogglePin,
}) => {
  const [sortKey, setSortKey] = useState<SortKey>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

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
        workflowCount,
        dataCollectionCount: countDataCollections(p),
        createdRaw: coerceString(p.registration_time, ''),
        templateLabel: tmpl ? `${tmpl.source}/${tmpl.repo || ''}`.trim() : '',
        templateParsed: tmpl,
        canMutate: role === 'Owner' || isAdmin,
      };
    });
    list.sort((a, b) => compareRows(a, b, sortKey, sortDir));
    return list;
  }, [projects, currentUserId, isAdmin, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
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
        overflowX: 'auto',
        border: '1px solid var(--mantine-color-default-border)',
        borderRadius: 8,
      }}
    >
      <Table verticalSpacing="sm" highlightOnHover miw={1050}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ width: 36 }} aria-label="Pin" />
              {SORTABLE_COLUMNS.map((col) => (
                <Table.Th key={col.key}>
                  <SortHeader
                    label={col.label}
                    ariaLabel={col.ariaLabel}
                    tooltip={col.tooltip}
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
              const created = r.createdRaw
                ? formatLastSaved(r.createdRaw)
                : '—';
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
                  <Table.Td>
                    <UnstyledButton
                      onClick={() => onView(r.project)}
                      style={{ textAlign: 'left' }}
                    >
                      <Text fw={500} size="sm">
                        {r.project.name}
                      </Text>
                    </UnstyledButton>
                  </Table.Td>
                  <Table.Td>
                    <Badge
                      color={r.isAdvanced ? 'orange' : 'cyan'}
                      variant="light"
                      size="sm"
                    >
                      {r.isAdvanced ? 'Advanced' : 'Basic'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Badge
                      color={r.isPublic ? 'green' : 'grape'}
                      variant="light"
                      size="sm"
                      leftSection={
                        <Icon
                          icon={r.isPublic ? 'mdi:earth' : 'mdi:lock-outline'}
                          width={11}
                        />
                      }
                    >
                      {r.isPublic ? 'Public' : 'Private'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    {r.templateParsed ? (
                      <TemplateChip parsed={r.templateParsed} verbose />
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
                    <Group gap={4} wrap="nowrap" align="center">
                      <Icon
                        icon="mdi:graph"
                        width={12}
                        color="var(--mantine-color-dimmed)"
                      />
                      {r.workflowCount === null ? (
                        <Text size="sm" c="dimmed">
                          NA
                        </Text>
                      ) : (
                        <Text
                          size="sm"
                          c={r.workflowCount > 0 ? undefined : 'dimmed'}
                        >
                          {r.workflowCount}
                        </Text>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap" align="center">
                      <Icon
                        icon="mdi:database-outline"
                        width={12}
                        color="var(--mantine-color-dimmed)"
                      />
                      {r.dataCollectionCount === null ? (
                        <Text size="sm" c="dimmed">
                          —
                        </Text>
                      ) : (
                        <Text
                          size="sm"
                          c={r.dataCollectionCount > 0 ? undefined : 'dimmed'}
                        >
                          {r.dataCollectionCount}
                        </Text>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{created}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap" justify="flex-end">
                      <Tooltip label="Workflows & data collections" withinPortal>
                        <ActionIcon
                          variant="subtle"
                          color="cyan"
                          size="sm"
                          component="a"
                          href={`/projects-beta/${r.id}`}
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
                          href={`/projects-beta/${r.id}/permissions`}
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
  );
};

export default ProjectTableView;
