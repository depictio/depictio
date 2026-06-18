import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Collapse,
  Group,
  Paper,
  ScrollArea,
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

import {
  deleteProjectLink,
  listLinkResolvers,
  listProjectLinks,
  updateProjectLink,
} from 'depictio-react-core';
import type { DCLink, ResolverInfo } from 'depictio-react-core';

import LinkEditModal from './LinkEditModal';

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
  /** Lifts links state to the parent so JoinsGraph can render edges. */
  onLinksChange?: (links: DCLink[]) => void;
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
  onLinksChange,
}) => {
  const [links, setLinks] = useState<DCLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [resolvers, setResolvers] = useState<ResolverInfo[]>([]);
  const [modalOpened, setModalOpened] = useState(false);
  const [editing, setEditing] = useState<DCLink | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  // Bumped on every openCreate / openEdit so the modal re-mounts fresh.
  // Mantine searchable Selects sometimes retain their display text after a
  // programmatic `value=''` reset; remounting sidesteps that entirely and
  // guarantees "Target data collection" (and every other field) starts blank
  // when the user clicks Add link a second time.
  const [modalKey, setModalKey] = useState(0);
  // Collapsed by default to keep the Overview tab compact.
  const [opened, { toggle }] = useDisclosure(false);
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
  }, [projectId, refreshKey, onLinksChange]);

  // Resolvers list is roughly static; fetch once on mount.
  useEffect(() => {
    listLinkResolvers(projectId)
      .then(setResolvers)
      .catch(() => {
        // Static fallback inside the modal — silent.
      });
  }, [projectId]);

  const refresh = () => setRefreshKey((k) => k + 1);

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

  const closeModal = () => {
    setModalOpened(false);
    // Clear `editing` too — without this, a saved edit would leave the
    // modal in "edit" mode if it were ever re-mounted with the stale value.
    setEditing(null);
  };

  const disabledTip = canMutate ? undefined : 'Disabled in public/demo mode';

  return (
    <Paper withBorder radius="md" p="sm">
      <Group justify="space-between" wrap="nowrap">
        <UnstyledButton onClick={toggle} style={{ flex: 1, minWidth: 0 }}>
          <Group gap="xs" wrap="nowrap">
            <Icon icon="mdi:link-variant" width={20} />
            <Title order={4}>Cross-DC links</Title>
            <Badge variant="light" size="sm">
              {links.length}
            </Badge>
            <Box style={{ flex: 1 }} />
            <Icon icon={opened ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={22} />
          </Group>
        </UnstyledButton>
        <Tooltip label={disabledTip} disabled={canMutate}>
          <Button
            data-testid="add-link-btn"
            leftSection={<Icon icon="mdi:plus" width={16} />}
            onClick={openCreate}
            disabled={!canMutate}
            size="xs"
          >
            Add link
          </Button>
        </Tooltip>
      </Group>

      <Collapse in={opened}>
        <ScrollArea.Autosize mah={460} type="auto" offsetScrollbars pt="sm">
          {loading && <Text size="sm">Loading…</Text>}

          {!loading && links.length === 0 && (
            <Text size="sm" c="dimmed">
              No cross-DC links defined. Add one to connect a column in one data
              collection to rows in another via a resolver (direct, sample
              mapping, pattern, regex, or wildcard).
            </Text>
          )}

          {!loading && links.length > 0 && (
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
                  <Table.Td>{srcTag(link)}</Table.Td>
                  <Table.Td>
                    <Text fz="xs" ff="monospace">
                      {link.source_column}
                    </Text>
                  </Table.Td>
                  <Table.Td>{tgtTag(link)}</Table.Td>
                  <Table.Td>
                    <Badge size="sm" variant="light">
                      {link.link_config?.resolver || 'direct'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Tooltip label={disabledTip} disabled={canMutate}>
                      <Switch
                        checked={link.enabled}
                        onChange={() => handleToggle(link)}
                        disabled={!canMutate}
                        size="xs"
                      />
                    </Tooltip>
                  </Table.Td>
                  <Table.Td>
                    <Text fz="xs" lineClamp={1}>
                      {link.description || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} justify="flex-end">
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
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
            </Stack>
          )}
        </ScrollArea.Autosize>
      </Collapse>

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
    </Paper>
  );
};

export default LinksSection;
