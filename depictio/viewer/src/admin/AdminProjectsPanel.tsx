import React, { useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Alert,
  Badge,
  Center,
  Group,
  List,
  Loader,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { listAllProjects } from 'depictio-react-core';
import type { AdminProject } from 'depictio-react-core';

const AdminProjectsPanel: React.FC = () => {
  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listAllProjects()
      .then((list) => {
        if (cancelled) return;
        setProjects(list);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load projects');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const sortedProjects = useMemo(
    () =>
      [...projects].sort((a, b) => {
        const ax = (a.name ?? '').toLowerCase();
        const bx = (b.name ?? '').toLowerCase();
        return ax.localeCompare(bx);
      }),
    [projects],
  );

  if (loading) {
    return (
      <Center mih={200}>
        <Loader />
      </Center>
    );
  }

  if (error) {
    return (
      <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
        {error}
      </Alert>
    );
  }

  if (sortedProjects.length === 0) {
    return (
      <Center mih={200}>
        <Stack align="center" gap="xs">
          <Icon
            icon="material-symbols:folder-off-outline"
            width={48}
            color="var(--mantine-color-dimmed)"
          />
          <Text c="dimmed">No projects available.</Text>
        </Stack>
      </Center>
    );
  }

  return (
    <Accordion radius="md" variant="separated" multiple>
      {sortedProjects.map((project) => {
        const projectId = project.id ?? project._id ?? project.name;
        const ownerEmail = project.permissions?.owners?.[0]?.email ?? 'Unknown';
        const viewerCount = project.permissions?.viewers?.length ?? 0;
        return (
          <Accordion.Item key={String(projectId)} value={String(projectId)}>
            <Accordion.Control>
              <Group justify="space-between" wrap="nowrap">
                <Text fw={500} size="lg" style={{ flex: 1, minWidth: 0 }} truncate>
                  {project.name}
                </Text>
                <Group gap="xs">
                  {project.workflow_system && project.workflow_system !== 'none' && (
                    <Badge color="grape" variant="light" size="sm" radius="sm">
                      {project.workflow_system}
                    </Badge>
                  )}
                  <Badge
                    color={project.is_public ? 'green' : 'gray'}
                    variant="light"
                    size="md"
                    radius="sm"
                  >
                    {project.is_public ? 'Public' : 'Private'}
                  </Badge>
                </Group>
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                <Group gap="xs">
                  <Text fw="bold" size="sm">
                    Project ID:
                  </Text>
                  <Text size="sm">{String(projectId)}</Text>
                </Group>
                <Group gap="xs">
                  <Text fw="bold" size="sm">
                    Owner:
                  </Text>
                  <Text size="sm">{ownerEmail}</Text>
                </Group>
                {project.description && (
                  <Group gap="xs" align="flex-start">
                    <Text fw="bold" size="sm">
                      Description:
                    </Text>
                    <Text size="sm" style={{ flex: 1 }}>
                      {project.description}
                    </Text>
                  </Group>
                )}
                <Group gap="xs" align="flex-start">
                  <Text fw="bold" size="sm">
                    Viewers:
                  </Text>
                  {viewerCount === 0 ? (
                    <Text size="sm">None</Text>
                  ) : (
                    <List size="sm" style={{ flex: 1 }}>
                      {(project.permissions?.viewers ?? []).map((v, i) => (
                        <List.Item key={`${v.email ?? i}`}>{v.email ?? '*'}</List.Item>
                      ))}
                    </List>
                  )}
                </Group>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        );
      })}
    </Accordion>
  );
};

export default AdminProjectsPanel;
