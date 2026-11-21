import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Collapse,
  Group,
  Modal,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import { Network, Table2 } from 'lucide-react';

import {
  deleteProjectJoin,
  deleteProjectLink,
  listLinkResolvers,
  listProjectJoins,
  listProjectLinks,
  updateProjectLink,
  useBrandAccents,
  useIsStaticBundle,
} from 'depictio-react-core';
import type { DCLink, ProjectJoinEntry, ResolverInfo } from 'depictio-react-core';

import { STROKE, useGlassPages } from '../../chrome/variants/glass/pages';
import { DcTypeIcon } from '../dcTypeIcon';
import ConnectionsMap from './ConnectionsMap';
import type { ProjectJoin } from './ConnectionsMap';
import JoinCreateModal from './JoinCreateModal';
import { joinDashboardsSentence, readableApiError } from './joinForm';
import LinkEditModal from './LinkEditModal';
import { LinkMappingModal } from './LinkMappingInspector';

interface DataCollectionOption {
  id: string;
  tag: string;
  type: string;
}

interface LinksSectionProps {
  projectId: string;
  dataCollections: DataCollectionOption[];
  /** Demo / public mode: still render the buttons so the affordance stays
   *  visible, but disable their action paths. */
  canMutate: boolean;
  /** Why `canMutate` is false: a public/demo deployment, a published (locked)
   *  project, or the user's role (a viewer, a non-member). Picks the tooltip. */
  blockedReason?: 'demo' | 'locked' | 'permission';
  /** Lifts links state to the parent. */
  onLinksChange?: (links: DCLink[]) => void;
  /** The project's joins, drawn beside the links in Glass's map view. */
  joins?: ProjectJoin[];
  /** Bumped by the page when a link changed elsewhere (the collection viewer). */
  reloadKey?: number;
  /** Open a collection picked on the map in the page's collection viewer. */
  onOpenDc?: (dcId: string) => void;
  /** Called after a join was created or deleted, so the page can re-read the
   *  project (the joined table appears in the collections and on the map). */
  onJoinsChange?: () => void;
}

/** Sortable column header for the links table. */
const LinkSortTh: React.FC<{
  label: string;
  k: 'source' | 'target' | 'resolver';
  sortKey: string;
  dir: 'asc' | 'desc';
  onSort: (k: 'source' | 'target' | 'resolver') => void;
}> = ({ label, k, sortKey, dir, onSort }) => (
  <Table.Th
    style={{ cursor: 'pointer', whiteSpace: 'nowrap', userSelect: 'none' }}
    onClick={() => onSort(k)}
  >
    <Group gap={2} wrap="nowrap">
      <Text size="sm" fw={600}>
        {label}
      </Text>
      <Icon
        icon={
          sortKey === k
            ? dir === 'asc'
              ? 'mdi:menu-up'
              : 'mdi:menu-down'
            : 'mdi:unfold-more-horizontal'
        }
        width={14}
        color={sortKey === k ? undefined : 'var(--mantine-color-gray-5)'}
      />
    </Group>
  </Table.Th>
);

const LinksSection: React.FC<LinksSectionProps> = ({
  projectId,
  dataCollections,
  canMutate,
  blockedReason = 'permission',
  onLinksChange,
  joins = [],
  reloadKey = 0,
  onOpenDc,
  onJoinsChange,
}) => {
  const accent = useBrandAccents();
  const glass = useGlassPages();
  // A static bundle reads its links from the file: nothing to add, edit,
  // switch or inspect (a link's value mapping is computed on the server).
  const offline = useIsStaticBundle();
  // Glass opens on the map; the table stays one click away.
  const [view, setView] = useState<'map' | 'table'>('map');
  const [links, setLinks] = useState<DCLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [resolvers, setResolvers] = useState<ResolverInfo[]>([]);
  const [modalOpened, setModalOpened] = useState(false);
  const [editing, setEditing] = useState<DCLink | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  // Table joins (a join of two tables, stored as its own `joined_<name>` table).
  const [joinEntries, setJoinEntries] = useState<ProjectJoinEntry[]>([]);
  const [canEditJoins, setCanEditJoins] = useState(false);
  const [joinsRefreshKey, setJoinsRefreshKey] = useState(0);
  const [joinModalOpened, setJoinModalOpened] = useState(false);
  const [joinToDelete, setJoinToDelete] = useState<ProjectJoinEntry | null>(null);
  const [deletingJoin, setDeletingJoin] = useState(false);
  // Bumped on every openCreate / openEdit so the modal re-mounts fresh.
  // Mantine searchable Selects sometimes retain their display text after a
  // programmatic `value=''` reset; remounting sidesteps that entirely and
  // guarantees "Target data collection" (and every other field) starts blank
  // when the user clicks Add link a second time.
  const [modalKey, setModalKey] = useState(0);
  // Read-only mapping inspection, opened straight from a row's magnifier so
  // checking what a link resolves to doesn't mean entering the edit form.
  const [inspecting, setInspecting] = useState<DCLink | null>(null);
  // Collapsed by default to keep the Overview tab compact, but open when the
  // project has joins: they are listed in here and would otherwise stay hidden.
  const [opened, { toggle: toggleOpened, open }] = useDisclosure(false);
  const userToggled = useRef(false);
  const toggle = () => {
    userToggled.current = true;
    toggleOpened();
  };
  useEffect(() => {
    if (joinEntries.length > 0 && !userToggled.current) open();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [joinEntries.length]);
  const [filter, setFilter] = useState('');
  const [sortKey, setSortKey] = useState<'source' | 'target' | 'resolver'>('source');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const onSort = (k: 'source' | 'target' | 'resolver') => {
    if (k === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(k);
      setSortDir('asc');
    }
  };

  const dcById = useMemo(() => {
    const map = new Map<string, DataCollectionOption>();
    dataCollections.forEach((d) => map.set(d.id, d));
    return map;
  }, [dataCollections]);

  // Resolve a link endpoint to a display tag, handling `tag:<tag>` placeholders
  // (template-imported links) and falling back to the stored tag / stripped id.
  const endpointTag = (idRef?: string, tagRef?: string) =>
    (idRef && dcById.get(idRef)?.tag) ||
    tagRef ||
    (idRef || '').replace(/^tag:/, '') ||
    '—';
  const srcTag = (l: DCLink) =>
    endpointTag(l.source_dc_id, (l as { source_dc_tag?: string }).source_dc_tag);
  const tgtTag = (l: DCLink) =>
    endpointTag(l.target_dc_id, (l as { target_dc_tag?: string }).target_dc_tag);
  // An endpoint's collection type, by id or (template placeholders) by tag,
  // so the table shows the same type icon as the manager and the map.
  const dcByTag = useMemo(
    () => new Map(dataCollections.map((d) => [d.tag, d] as const)),
    [dataCollections],
  );
  const endpointCell = (idRef: string | undefined, tag: string) => (
    <Group gap={6} wrap="nowrap">
      <DcTypeIcon
        type={(idRef && dcById.get(idRef)?.type) || dcByTag.get(tag)?.type}
        size={14}
        withTooltip={false}
      />
      <span>{tag}</span>
    </Group>
  );
  const resolverOf = (l: DCLink) => l.link_config?.resolver || 'direct';

  const visibleLinks = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const list = links.filter(
      (l) =>
        !q ||
        srcTag(l).toLowerCase().includes(q) ||
        tgtTag(l).toLowerCase().includes(q) ||
        resolverOf(l).toLowerCase().includes(q) ||
        (l.description || '').toLowerCase().includes(q),
    );
    const cmp = (a: DCLink, b: DCLink) => {
      if (sortKey === 'target') return tgtTag(a).localeCompare(tgtTag(b));
      if (sortKey === 'resolver') return resolverOf(a).localeCompare(resolverOf(b));
      return srcTag(a).localeCompare(srcTag(b));
    };
    return [...list].sort((a, b) => (sortDir === 'asc' ? cmp(a, b) : -cmp(a, b)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [links, filter, sortKey, sortDir, dcById]);

  useEffect(() => {
    setLoading(true);
    listProjectLinks(projectId)
      .then((rows) => {
        setLinks(rows);
        onLinksChange?.(rows);
      })
      .catch((err: Error) => {
        notifications.show({
          color: 'red',
          title: 'Failed to load links',
          message: err.message,
        });
      })
      .finally(() => setLoading(false));
  }, [projectId, refreshKey, reloadKey, onLinksChange]);

  // A static bundle has no server to list joins from.
  useEffect(() => {
    if (offline) return;
    listProjectJoins(projectId)
      .then((res) => {
        setJoinEntries(res.joins);
        setCanEditJoins(res.can_edit);
      })
      .catch((err: Error) => {
        notifications.show({
          color: 'red',
          title: 'Failed to load joins',
          message: err.message,
        });
      });
  }, [projectId, offline, joinsRefreshKey, reloadKey]);

  // Resolvers list is roughly static; fetch once on mount.
  useEffect(() => {
    if (offline) return;
    listLinkResolvers(projectId)
      .then(setResolvers)
      .catch(() => {
        // Static fallback inside the modal — silent.
      });
  }, [projectId, offline]);

  const refresh = () => setRefreshKey((k) => k + 1);
  const refreshJoins = () => {
    setJoinsRefreshKey((k) => k + 1);
    onJoinsChange?.();
  };

  const handleDeleteJoin = async () => {
    if (!joinToDelete) return;
    setDeletingJoin(true);
    try {
      await deleteProjectJoin(projectId, joinToDelete.name);
      notifications.show({
        color: 'green',
        title: 'Join deleted',
        message: joinToDelete.name,
      });
      setJoinToDelete(null);
      refreshJoins();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Failed to delete join',
        message: readableApiError(err, 'The join could not be deleted.'),
      });
    } finally {
      setDeletingJoin(false);
    }
  };

  const handleDelete = async (link: DCLink) => {
    try {
      await deleteProjectLink(projectId, link.id);
      notifications.show({
        color: 'green',
        title: 'Link deleted',
        message: `${dcById.get(link.source_dc_id)?.tag || 'source'} → ${
          dcById.get(link.target_dc_id)?.tag || 'target'
        }`,
      });
      refresh();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Failed to delete link',
        message: (err as Error).message,
      });
    }
  };

  const handleToggle = async (link: DCLink) => {
    try {
      await updateProjectLink(projectId, link.id, { enabled: !link.enabled });
      refresh();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Failed to toggle link',
        message: (err as Error).message,
      });
    }
  };

  const openCreate = () => {
    setEditing(null);
    setModalKey((k) => k + 1);
    setModalOpened(true);
  };

  const openEdit = (link: DCLink) => {
    setEditing(link);
    setModalKey((k) => k + 1);
    setModalOpened(true);
  };

  const closeInspect = () => setInspecting(null);

  const closeModal = () => {
    setModalOpened(false);
    // Clear `editing` too — without this, a saved edit would leave the
    // modal in "edit" mode if it were ever re-mounted with the stale value.
    setEditing(null);
  };

  const disabledTip = canMutate
    ? undefined
    : blockedReason === 'demo'
      ? 'Disabled in public/demo mode'
      : blockedReason === 'locked'
        ? 'This project is published and read-only.'
        : 'Only project owners and editors can change links.';
  const joinTip = canMutate
    ? undefined
    : blockedReason === 'permission'
      ? 'Only project owners and editors can add joins.'
      : disabledTip;

  // The joined table is connected to the two tables it combines: drawn as an
  // edge from each source to it, so the map does not list it as "not connected".
  const mapJoins = useMemo<ProjectJoin[]>(
    () => [
      ...joins,
      ...joinEntries.flatMap((j) =>
        j.result_dc_id
          ? [j.left_dc_id, j.right_dc_id]
              .filter((id): id is string => !!id && id !== j.result_dc_id)
              .map((id) => ({
                left_dc: id,
                right_dc: j.result_dc_id as string,
                on_columns: j.on_columns,
                how: j.how,
                name: j.name,
              }))
          : [],
      ),
    ],
    [joins, joinEntries],
  );
  const deleteResultTag = joinToDelete
    ? joinToDelete.result_tag || joinToDelete.result_dc_tag || `joined_${joinToDelete.name}`
    : '';
  const deleteUsedBy = joinToDelete
    ? joinDashboardsSentence(deleteResultTag, joinToDelete.dashboards)
    : null;
  const joinCountLabel = `${joinEntries.length} ${joinEntries.length === 1 ? 'join' : 'joins'}`;

  const joinsList =
    joinEntries.length > 0 ? (
      <Stack gap="xs" pt="sm" data-testid="joins-list">
        <Group gap="xs">
          <Icon icon="mdi:table-merge-cells" width={18} />
          <Title order={5}>Joins</Title>
          <Badge variant="light" size="sm">
            {joinEntries.length}
          </Badge>
        </Group>
        <ScrollArea type="auto" offsetScrollbars>
          <Table verticalSpacing="xs" striped highlightOnHover fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Name</Table.Th>
                <Table.Th>Tables</Table.Th>
                <Table.Th>On columns</Table.Th>
                <Table.Th>Type</Table.Th>
                <Table.Th>Rows</Table.Th>
                <Table.Th>Result table</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {joinEntries.map((j) => (
                <Table.Tr key={j.name} data-testid="join-row">
                  <Table.Td>
                    <Text fz="sm" fw={600}>
                      {j.name}
                    </Text>
                  </Table.Td>
                  <Table.Td style={{ whiteSpace: 'nowrap' }}>
                    <Text fz="xs" ff="monospace">
                      {(j.left_tag || j.left_dc) + ' ⋈ ' + (j.right_tag || j.right_dc)}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text fz="xs" ff="monospace">
                      {j.on_columns.join(', ')}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge size="sm" variant="light">
                      {j.how}
                    </Badge>
                  </Table.Td>
                  <Table.Td>{j.row_count ?? '—'}</Table.Td>
                  <Table.Td>
                    <Group gap={6} wrap="nowrap">
                      <Text fz="xs" ff="monospace">
                        {j.result_tag || j.result_dc_tag || '—'}
                      </Text>
                      {j.last_error && (
                        <Tooltip label={j.last_error} multiline w={320} withArrow>
                          <Badge size="sm" color="red" variant="light">
                            Not rebuilt
                          </Badge>
                        </Tooltip>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    {!offline && canEditJoins && canMutate && (
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        <Tooltip label="Delete join" withArrow>
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            onClick={() => setJoinToDelete(j)}
                            aria-label={`Delete join ${j.name}`}
                            data-testid="delete-join-btn"
                          >
                            <Icon icon="mdi:delete" width={16} />
                          </ActionIcon>
                        </Tooltip>
                      </Group>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </Stack>
    ) : null;

  const linksTable = (
            <Stack gap="sm">
              <TextInput
                placeholder="Filter links…"
                leftSection={<Icon icon="mdi:magnify" width={16} />}
                value={filter}
                onChange={(e) => setFilter(e.currentTarget.value)}
                size="xs"
              />
              <Table verticalSpacing="xs" striped highlightOnHover fz="sm">
          <Table.Thead>
            <Table.Tr>
              <LinkSortTh label="Source DC" k="source" sortKey={sortKey} dir={sortDir} onSort={onSort} />
              <Table.Th>Source column</Table.Th>
              <LinkSortTh label="Target DC" k="target" sortKey={sortKey} dir={sortDir} onSort={onSort} />
              <LinkSortTh label="Resolver" k="resolver" sortKey={sortKey} dir={sortDir} onSort={onSort} />
              <Table.Th>Enabled</Table.Th>
              <Table.Th>Description</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visibleLinks.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={7}>
                  <Text size="sm" c="dimmed" ta="center" py="sm">
                    No links match “{filter}”.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {visibleLinks.map((link) => {
              return (
                <Table.Tr key={link.id}>
                  <Table.Td>{endpointCell(link.source_dc_id, srcTag(link))}</Table.Td>
                  <Table.Td>
                    <Text fz="xs" ff="monospace">
                      {link.source_column}
                    </Text>
                  </Table.Td>
                  <Table.Td>{endpointCell(link.target_dc_id, tgtTag(link))}</Table.Td>
                  <Table.Td style={{ whiteSpace: 'nowrap' }}>
                    {/* Badge clips its label by default, which made the widest
                        resolver name read "sample_map…" once the description
                        column claimed the slack. */}
                    <Badge
                      size="sm"
                      variant="light"
                      styles={{ label: { overflow: 'visible' } }}
                    >
                      {link.link_config?.resolver || 'direct'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    {offline ? (
                      <Text fz="xs" c={link.enabled ? undefined : 'dimmed'}>
                        {link.enabled ? 'On' : 'Off'}
                      </Text>
                    ) : (
                      <Tooltip label={disabledTip} disabled={canMutate}>
                        <Switch
                          checked={link.enabled}
                          onChange={() => handleToggle(link)}
                          disabled={!canMutate}
                          size="xs"
                        />
                      </Tooltip>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text fz="xs" lineClamp={1}>
                      {link.description || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {!offline && (
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        <Tooltip label="Inspect mapping" withArrow>
                          <ActionIcon
                            variant="subtle"
                            color="teal"
                            onClick={() => setInspecting(link)}
                            aria-label="Inspect mapping"
                            data-testid="inspect-link-btn"
                          >
                            <Icon icon="mdi:magnify-scan" width={16} />
                          </ActionIcon>
                        </Tooltip>
                        <Tooltip label={disabledTip} disabled={canMutate}>
                          <ActionIcon
                            variant="subtle"
                            onClick={() => openEdit(link)}
                            disabled={!canMutate}
                            aria-label="Edit link"
                          >
                            <Icon icon="mdi:pencil" width={16} />
                          </ActionIcon>
                        </Tooltip>
                        <Tooltip label={disabledTip} disabled={canMutate}>
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            onClick={() => handleDelete(link)}
                            disabled={!canMutate}
                            aria-label="Delete link"
                          >
                            <Icon icon="mdi:delete" width={16} />
                          </ActionIcon>
                        </Tooltip>
                      </Group>
                    )}
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
            </Stack>
  );

  return (
    <Paper withBorder radius="md" p="sm" data-testid="links-section">
      {/* Same header structure as the Data Collections Manager: clickable
          title area, then the primary action, then the chevron as an
          ActionIcon on the far right. */}
      <Group justify="space-between" wrap="nowrap">
        <UnstyledButton
          onClick={toggle}
          style={{ flex: 1, minWidth: 0 }}
          data-testid="links-section-toggle"
        >
          <Group gap="xs" wrap="nowrap">
            <Icon icon="mdi:link-variant" width={20} />
            <Title order={4}>Cross-DC links</Title>
            <Badge variant="light" size="sm" data-testid="links-section-count">
              {joinEntries.length > 0
                ? `${links.length} ${links.length === 1 ? 'link' : 'links'} · ${joinCountLabel}`
                : links.length}
            </Badge>
          </Group>
        </UnstyledButton>
        <Group gap="xs" wrap="nowrap">
          <Tooltip
            label={offline ? 'Not available in a static bundle' : joinTip}
            disabled={canMutate && !offline}
          >
            <Button
              color={accent.secondary}
              data-testid="add-join-btn"
              leftSection={<Icon icon="mdi:table-merge-cells" width={16} />}
              onClick={() => setJoinModalOpened(true)}
              disabled={!canMutate || offline}
              size="xs"
            >
              Add join
            </Button>
          </Tooltip>
          {!offline && (
            <Tooltip label={disabledTip} disabled={canMutate}>
              <Button
                color={accent.secondary}
                data-testid="add-link-btn"
                leftSection={<Icon icon="mdi:plus" width={16} />}
                onClick={openCreate}
                disabled={!canMutate}
                size="xs"
              >
                Add link
              </Button>
            </Tooltip>
          )}
          <ActionIcon
            variant="subtle"
            color="gray"
            onClick={toggle}
            aria-label={opened ? 'Collapse cross-DC links' : 'Expand cross-DC links'}
          >
            <Icon icon={opened ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={22} />
          </ActionIcon>
        </Group>
      </Group>

      <Collapse in={opened}>
        {glass && (links.length > 0 || mapJoins.length > 0) ? (
          <>
            <div className="cm-bar">
              <SegmentedControl
                size="xs"
                value={view}
                onChange={(v) => setView(v as 'map' | 'table')}
                aria-label="Links view"
                data-testid="links-view-switch"
                data={[
                  {
                    value: 'map',
                    label: (
                      <Group gap={6} wrap="nowrap">
                        <Network size={14} strokeWidth={STROKE} aria-hidden />
                        <span>Map</span>
                      </Group>
                    ),
                  },
                  {
                    value: 'table',
                    label: (
                      <Group gap={6} wrap="nowrap">
                        <Table2 size={14} strokeWidth={STROKE} aria-hidden />
                        <span>Table</span>
                      </Group>
                    ),
                  },
                ]}
              />
            </div>
            {view === 'map' ? (
              <ConnectionsMap
                dataCollections={dataCollections}
                links={links}
                joins={mapJoins}
                canMutate={canMutate}
                onInspect={offline ? undefined : setInspecting}
                onEdit={offline ? undefined : openEdit}
                onOpenDc={onOpenDc}
              />
            ) : (
              <ScrollArea.Autosize mah={460} type="auto" offsetScrollbars>
                {linksTable}
              </ScrollArea.Autosize>
            )}
          </>
        ) : (
          <ScrollArea.Autosize mah={460} type="auto" offsetScrollbars pt="sm">
            {loading && <Text size="sm">Loading…</Text>}

            {!loading && links.length === 0 && (
              <Text size="sm" c="dimmed">
                {glass
                  ? 'Nothing is connected yet. A link lets a filter on one data collection narrow another.'
                  : 'No cross-DC links defined. Add one to connect a column in one data collection to rows in another via a resolver (direct, sample mapping, pattern, regex, or wildcard).'}
              </Text>
            )}

            {!loading && links.length > 0 && linksTable}
          </ScrollArea.Autosize>
        )}
        {joinsList}
      </Collapse>

      {!offline && (
        <>
          <JoinCreateModal
            opened={joinModalOpened}
            projectId={projectId}
            dataCollections={dataCollections}
            links={links}
            existingJoinNames={joinEntries.map((j) => j.name)}
            onClose={() => setJoinModalOpened(false)}
            onCreated={refreshJoins}
          />

          <Modal
            opened={!!joinToDelete}
            onClose={deletingJoin ? () => {} : () => setJoinToDelete(null)}
            title="Delete join"
            centered
            data-testid="delete-join-modal"
          >
            {joinToDelete && (
              <Stack gap="md">
                <Text size="sm">
                  Delete join <b>{joinToDelete.name}</b>? Its table{' '}
                  <b>{deleteResultTag}</b> is removed;{' '}
                  <b>{joinToDelete.left_tag || joinToDelete.left_dc}</b> and{' '}
                  <b>{joinToDelete.right_tag || joinToDelete.right_dc}</b> stay.
                  {!deleteUsedBy && (
                    <>
                      {' '}Dashboards that use <b>{deleteResultTag}</b> will show no data.
                    </>
                  )}
                </Text>
                {deleteUsedBy && (
                  <Text size="sm" c="red" data-testid="delete-join-dashboards">
                    {deleteUsedBy}
                  </Text>
                )}
                <Group justify="flex-end" gap="xs">
                  <Button
                    variant="default"
                    onClick={() => setJoinToDelete(null)}
                    disabled={deletingJoin}
                  >
                    Cancel
                  </Button>
                  <Button color="red" onClick={handleDeleteJoin} loading={deletingJoin}>
                    Delete join
                  </Button>
                </Group>
              </Stack>
            )}
          </Modal>

          <LinkMappingModal
            opened={!!inspecting}
            projectId={projectId}
            link={inspecting}
            sourceTag={inspecting ? srcTag(inspecting) : ''}
            targetTag={inspecting ? tgtTag(inspecting) : ''}
            onClose={closeInspect}
          />

          <LinkEditModal
            key={modalKey}
            opened={modalOpened}
            projectId={projectId}
            link={editing}
            dataCollections={dataCollections}
            resolvers={resolvers}
            onClose={closeModal}
            onSaved={() => {
              closeModal();
              refresh();
            }}
          />
        </>
      )}
    </Paper>
  );
};

export default LinksSection;
