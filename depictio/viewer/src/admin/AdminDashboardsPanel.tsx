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

import { listAllDashboards } from 'depictio-react-core';
import type { AdminDashboard } from 'depictio-react-core';

function formatLastSaved(raw: unknown): string {
  if (!raw || typeof raw !== 'string') return 'Never';
  const d = new Date(raw.replace('Z', '+00:00'));
  if (Number.isNaN(d.getTime())) return raw;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const AdminDashboardsPanel: React.FC = () => {
  const [dashboards, setDashboards] = useState<AdminDashboard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listAllDashboards()
      .then((list) => {
        if (cancelled) return;
        setDashboards(list);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load dashboards');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const sortedDashboards = useMemo(
    () =>
      [...dashboards].sort((a, b) => {
        const ax = (a.title ?? a.dashboard_id ?? '').toLowerCase();
        const bx = (b.title ?? b.dashboard_id ?? '').toLowerCase();
        return ax.localeCompare(bx);
      }),
    [dashboards],
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

  if (sortedDashboards.length === 0) {
    return (
      <Center mih={200}>
        <Stack align="center" gap="xs">
          <Icon icon="ph:empty-bold" width={48} color="var(--mantine-color-dimmed)" />
          <Text c="dimmed">No dashboards available.</Text>
        </Stack>
      </Center>
    );
  }

  return (
    <Accordion radius="md" variant="separated" multiple>
      {sortedDashboards.map((dashboard) => {
        const dashboardId = dashboard.dashboard_id;
        const title = dashboard.title || dashboardId;
        const ownerEmail = dashboard.permissions?.owners?.[0]?.email ?? 'Unknown';
        const headerLabel = `${title} — ${ownerEmail}`;
        const viewers = dashboard.permissions?.viewers ?? [];
        const isPublic =
          Boolean(dashboard.is_public) || viewers.some((v) => v?.email === '*');
        const componentCount = Array.isArray(dashboard.stored_metadata)
          ? dashboard.stored_metadata.length
          : 0;
        return (
          <Accordion.Item key={dashboardId} value={dashboardId}>
            <Accordion.Control>
              <Group justify="space-between" wrap="nowrap">
                <Text fw={500} size="lg" style={{ flex: 1, minWidth: 0 }} truncate>
                  {headerLabel}
                </Text>
                <Badge
                  color={isPublic ? 'blue' : 'gray'}
                  variant="light"
                  size="md"
                  radius="sm"
                >
                  {isPublic ? 'Public' : 'Private'}
                </Badge>
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="xs">
                <Group gap="xs">
                  <Text fw="bold" size="sm">
                    Dashboard ID:
                  </Text>
                  <Text size="sm">{dashboardId}</Text>
                </Group>
                <Group gap="xs">
                  <Text fw="bold" size="sm">
                    Owner:
                  </Text>
                  <Text size="sm">{ownerEmail}</Text>
                </Group>
                <Group gap="xs" align="flex-start">
                  <Text fw="bold" size="sm">
                    Viewers:
                  </Text>
                  {viewers.length === 0 ? (
                    <Text size="sm">None</Text>
                  ) : (
                    <List size="sm" style={{ flex: 1 }}>
                      {viewers.map((v, i) => (
                        <List.Item key={`${v?.email ?? i}`}>{v?.email ?? '*'}</List.Item>
                      ))}
                    </List>
                  )}
                </Group>
                <Group gap="xs">
                  <Text fw="bold" size="sm">
                    Components:
                  </Text>
                  <Text size="sm">{componentCount}</Text>
                </Group>
                <Group gap="xs">
                  <Text fw="bold" size="sm">
                    Last saved:
                  </Text>
                  <Text size="sm">{formatLastSaved(dashboard.last_saved_ts)}</Text>
                </Group>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        );
      })}
    </Accordion>
  );
};

export default AdminDashboardsPanel;
