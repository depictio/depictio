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
import { Globe, LayoutDashboard, Lock } from 'lucide-react';

import { listAllDashboards } from 'depictio-react-core';
import type { AdminDashboard } from 'depictio-react-core';

import { STROKE, useGlassPages } from '../chrome/variants/glass/pages';
import { formatDateTime } from '../lib/datetime';
import Facts from './Facts';

function formatLastSaved(raw: unknown): string {
  if (!raw || typeof raw !== 'string') return 'Never';
  return formatDateTime(raw, raw);
}

const AdminDashboardsPanel: React.FC = () => {
  const glass = useGlassPages();
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
    <Accordion radius="md" variant="separated" multiple className={glass ? 'ga-rows' : undefined}>
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
              {glass ? (
                <Group gap="sm" wrap="nowrap">
                  <LayoutDashboard
                    size={17}
                    strokeWidth={STROKE}
                    className="ga-row-icon"
                    style={{ color: 'var(--mantine-color-logoOrange-filled)' }}
                    aria-hidden
                  />
                  <Stack gap={1} style={{ flex: 1, minWidth: 0 }}>
                    <Text fw={550} size="sm" truncate>
                      {title}
                    </Text>
                    <Text size="xs" c="dimmed" truncate>
                      {ownerEmail}
                    </Text>
                  </Stack>
                  <Badge
                    color="gray"
                    size="sm"
                    leftSection={
                      isPublic ? (
                        <Globe size={12} strokeWidth={STROKE} />
                      ) : (
                        <Lock size={12} strokeWidth={STROKE} />
                      )
                    }
                  >
                    {isPublic ? 'Public' : 'Private'}
                  </Badge>
                </Group>
              ) : (
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
              )}
            </Accordion.Control>
            <Accordion.Panel>
              <Facts
                items={[
                  { label: 'Dashboard ID', value: dashboardId },
                  { label: 'Owner', value: ownerEmail },
                  {
                    label: 'Viewers',
                    top: true,
                    value:
                      viewers.length === 0 ? (
                        glass ? 'None' : <Text size="sm">None</Text>
                      ) : glass ? (
                        <Stack gap={2}>
                          {viewers.map((v, i) => (
                            <Text key={`${v?.email ?? i}`} size="sm">
                              {v?.email ?? '*'}
                            </Text>
                          ))}
                        </Stack>
                      ) : (
                        <List size="sm" style={{ flex: 1 }}>
                          {viewers.map((v, i) => (
                            <List.Item key={`${v?.email ?? i}`}>{v?.email ?? '*'}</List.Item>
                          ))}
                        </List>
                      ),
                  },
                  { label: 'Components', value: String(componentCount) },
                  { label: 'Last saved', value: formatLastSaved(dashboard.last_saved_ts) },
                ]}
              />
            </Accordion.Panel>
          </Accordion.Item>
        );
      })}
    </Accordion>
  );
};

export default AdminDashboardsPanel;
