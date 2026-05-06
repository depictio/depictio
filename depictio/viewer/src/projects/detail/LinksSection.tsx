import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Paper,
  Stack,
  Switch,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
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

  const dcById = useMemo(() => {
    const map = new Map<string, DataCollectionOption>();
    dataCollections.forEach((d) => map.set(d.id, d));
    return map;
  }, [dataCollections]);

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
    setModalOpened(true);
  };

  const openEdit = (link: DCLink) => {
    setEditing(link);
    setModalOpened(true);
  };

  const disabledTip = canMutate ? undefined : 'Disabled in public/demo mode';

  return (
    <Paper withBorder radius="md" p="md">
      <Group justify="space-between" mb="sm">
        <Group gap="xs">
          <Icon icon="mdi:link-variant" width={20} />
          <Title order={4}>Cross-DC links</Title>
          <Badge variant="light" size="sm">
            {links.length}
          </Badge>
        </Group>
        <Tooltip label={disabledTip} disabled={canMutate}>
          <Button
            leftSection={<Icon icon="mdi:plus" width={16} />}
            onClick={openCreate}
            disabled={!canMutate}
            size="xs"
          >
            Add link
          </Button>
        </Tooltip>
      </Group>

      {loading && <Text size="sm">Loading…</Text>}

      {!loading && links.length === 0 && (
        <Text size="sm" c="dimmed">
          No cross-DC links defined. Add one to connect a column in one data
          collection to rows in another via a resolver (direct, sample
          mapping, pattern, regex, or wildcard).
        </Text>
      )}

      {!loading && links.length > 0 && (
        <Table verticalSpacing="xs" striped highlightOnHover fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Source DC</Table.Th>
              <Table.Th>Source column</Table.Th>
              <Table.Th>Target DC</Table.Th>
              <Table.Th>Resolver</Table.Th>
              <Table.Th>Enabled</Table.Th>
              <Table.Th>Description</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {links.map((link) => {
              const src = dcById.get(link.source_dc_id);
              const tgt = dcById.get(link.target_dc_id);
              return (
                <Table.Tr key={link.id}>
                  <Table.Td>{src?.tag || link.source_dc_id}</Table.Td>
                  <Table.Td>
                    <Text fz="xs" ff="monospace">
                      {link.source_column}
                    </Text>
                  </Table.Td>
                  <Table.Td>{tgt?.tag || link.target_dc_id}</Table.Td>
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
      )}

      <LinkEditModal
        opened={modalOpened}
        projectId={projectId}
        link={editing}
        dataCollections={dataCollections}
        resolvers={resolvers}
        onClose={() => setModalOpened(false)}
        onSaved={() => {
          setModalOpened(false);
          refresh();
        }}
      />
    </Paper>
  );
};

export default LinksSection;
