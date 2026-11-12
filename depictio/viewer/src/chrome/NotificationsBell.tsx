import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Button,
  Group,
  Indicator,
  Popover,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { fetchAllDashboards, fetchChangesInbox, type InboxItem } from 'depictio-react-core';

import { useChangesSinceEnabled } from '../hooks/useChangesSinceEnabled';
import { useCurrentUser } from '../hooks/useCurrentUser';
import { formatRelative } from '../lib/datetime';
import { NameChip } from '../projects/badges';
import {
  useProjectIngestionEvents,
  type IngestionFinishedPayload,
} from '../notifications/projectEvents';

const POLL_MS = 60_000;
const CHIPS_SHOWN = 3;

/** Where a notification leads: a project's Runs tab with the first new run in
 *  focus, or the dashboard (which draws its own marks). */
export function projectRunsHref(projectId: string, runTag?: string): string {
  const base = `/projects/${encodeURIComponent(projectId)}`;
  return runTag ? `${base}?tab=runs&run=${encodeURIComponent(runTag)}` : base;
}

export function itemHref(item: InboxItem): string {
  return item.scope_kind === 'project'
    ? projectRunsHref(item.scope_id, item.new_run_tags[0])
    : `/dashboard/${encodeURIComponent(item.scope_id)}`;
}

const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`;

const NotificationRow: React.FC<{ item: InboxItem }> = ({ item }) => {
  const shown = item.new_run_tags.slice(0, CHIPS_SHOWN);
  const hidden = item.new_run_tags.length - shown.length;
  const parts: string[] = [];
  if (item.dashboard_versions > 0) {
    parts.push(plural(item.dashboard_versions, 'dashboard change'));
  }
  if (item.refreshed.length > 0) {
    parts.push(`${item.refreshed.join(', ')} refreshed`);
  }
  return (
    <UnstyledButton
      component="a"
      href={itemHref(item)}
      data-testid="notification-item"
      data-scope-kind={item.scope_kind}
      data-scope-id={item.scope_id}
      p="xs"
      style={{ borderRadius: 'var(--mantine-radius-sm)' }}
    >
      <Group gap="xs" wrap="nowrap" align="flex-start">
        <Icon
          icon={item.scope_kind === 'project' ? 'mdi:jira' : 'material-symbols:dashboard'}
          width={18}
          style={{ flexShrink: 0, marginTop: 2 }}
        />
        <Stack gap={4} style={{ minWidth: 0 }}>
          <Text size="sm" fw={600} truncate>
            {item.title || (item.scope_kind === 'project' ? 'Project' : 'Dashboard')}
          </Text>
          {item.new_run_tags.length > 0 && (
            <Group gap={4} wrap="wrap">
              <Text size="xs">{plural(item.new_run_tags.length, 'new run')}:</Text>
              {shown.map((tag) => (
                <NameChip key={tag} size="xs">
                  {tag}
                </NameChip>
              ))}
              {hidden > 0 && (
                <Text size="xs" c="dimmed">
                  +{hidden}
                </Text>
              )}
            </Group>
          )}
          {parts.length > 0 && (
            <Text size="xs" c="dimmed">
              {parts.join(' · ')}
            </Text>
          )}
          {item.at && (
            <Text size="xs" c="dimmed">
              {formatRelative(item.at)}
            </Text>
          )}
        </Stack>
      </Group>
    </UnstyledButton>
  );
};

/**
 * The bell of a signed-in reader: what is new in the dashboards and projects
 * they follow (new runs, refreshed collections, dashboard changes), counted on
 * the icon and listed in a popover. Polls the inbox every minute while the tab
 * is visible, and listens for live "ingestion finished" events on the projects
 * involved to show a toast. Renders nothing while the feature is off, for
 * anonymous or temporary readers, and where the server holds no marks.
 */
export interface BellTriggerProps {
  count: number;
  label: string;
  onClick: () => void;
}

interface NotificationsBellProps {
  /** Where the panel opens, from the bell. */
  position?: 'right-end' | 'bottom-end';
  /** A shell's own button (the glass top keys); the default is a Mantine ActionIcon. */
  renderTrigger?: (props: BellTriggerProps) => React.ReactElement;
}

const NotificationsBell: React.FC<NotificationsBellProps> = ({
  position = 'right-end',
  renderTrigger,
}) => {
  const enabledByServer = useChangesSinceEnabled();
  const { user } = useCurrentUser();
  const eligible = enabledByServer && Boolean(user) && !user?.is_temporary;

  const [items, setItems] = useState<InboxItem[]>([]);
  const [heldByServer, setHeldByServer] = useState(false);
  const [opened, setOpened] = useState(false);
  // dashboard id -> project id, for the dashboards the reader follows.
  const [dashboardProject, setDashboardProject] = useState<Record<string, string>>({});
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const dashboardProjectRef = useRef(dashboardProject);
  dashboardProjectRef.current = dashboardProject;
  const announced = useRef(new Set<string>());

  const refresh = useCallback(async () => {
    try {
      const inbox = await fetchChangesInbox();
      setItems(inbox.items);
      setHeldByServer(inbox.server_held);
    } catch {
      // keep what we have; the next tick retries
    }
  }, []);

  useEffect(() => {
    if (!eligible) return undefined;
    void refresh();
    const tick = () => {
      if (!document.hidden) void refresh();
    };
    const timer = window.setInterval(tick, POLL_MS);
    document.addEventListener('visibilitychange', tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [eligible, refresh]);

  // The inbox names dashboards, not their projects; one listing resolves them.
  const dashboardIds = items.filter((i) => i.scope_kind === 'dashboard').map((i) => i.scope_id);
  const unresolved = dashboardIds.some((id) => !(id in dashboardProject));
  useEffect(() => {
    if (!eligible || !unresolved) return undefined;
    let cancelled = false;
    fetchAllDashboards()
      .then((all) => {
        if (cancelled) return;
        const map: Record<string, string> = {};
        for (const d of all) if (d.project_id) map[d.dashboard_id] = String(d.project_id);
        setDashboardProject((prev) => ({ ...prev, ...map }));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [eligible, unresolved]);

  const projectIds = useMemo(() => {
    const ids = new Set<string>();
    for (const item of items) {
      if (item.scope_kind === 'project') ids.add(item.scope_id);
      else if (dashboardProject[item.scope_id]) ids.add(dashboardProject[item.scope_id]);
    }
    return [...ids];
  }, [items, dashboardProject]);

  const onFinished = useCallback(
    (event: IngestionFinishedPayload) => {
      if (announced.current.has(event.run_id)) return;
      announced.current.add(event.run_id);
      const name = event.project_name || 'a project';
      const labels = event.run_tags.length > 0 ? event.run_tags : event.collections;
      const marked = itemsRef.current.find(
        (i) =>
          i.scope_kind === 'dashboard' &&
          dashboardProjectRef.current[i.scope_id] === event.project_id,
      );
      notifications.show({
        id: `ingestion-${event.run_id}`,
        title: `New data in ${name}`,
        autoClose: 20_000,
        message: (
          <Stack gap="xs" data-testid="ingestion-toast">
            {labels.length > 0 && (
              <Group gap={4} wrap="wrap">
                {labels.slice(0, CHIPS_SHOWN).map((label) => (
                  <NameChip key={label} size="xs">
                    {label}
                  </NameChip>
                ))}
                {labels.length > CHIPS_SHOWN && (
                  <Text size="xs" c="dimmed">
                    +{labels.length - CHIPS_SHOWN}
                  </Text>
                )}
              </Group>
            )}
            <Group gap="xs">
              <Button
                component="a"
                size="compact-xs"
                variant="light"
                href={projectRunsHref(event.project_id, event.run_tags[0])}
                data-testid="ingestion-toast-open-project"
              >
                Open project
              </Button>
              {marked && (
                <Button
                  component="a"
                  size="compact-xs"
                  variant="subtle"
                  href={`/dashboard/${encodeURIComponent(marked.scope_id)}`}
                  data-testid="ingestion-toast-open-dashboard"
                >
                  Open dashboard
                </Button>
              )}
            </Group>
          </Stack>
        ),
      });
      void refresh();
    },
    [refresh],
  );

  useProjectIngestionEvents(projectIds, onFinished, eligible && heldByServer);

  if (!eligible || !heldByServer) return null;

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      position={position}
      width={340}
      shadow="md"
      withArrow
    >
      <Popover.Target>
        {(() => {
          const label = items.length > 0 ? `Notifications, ${items.length} new` : 'Notifications';
          const onClick = () => {
            setOpened((o) => !o);
            void refresh();
          };
          if (renderTrigger) {
            return (
              <Indicator
                label={<span data-testid="notifications-count">{items.length}</span>}
                size={16}
                disabled={items.length === 0}
                offset={4}
              >
                {renderTrigger({ count: items.length, label, onClick })}
              </Indicator>
            );
          }
          return (
            <Indicator
              label={<span data-testid="notifications-count">{items.length}</span>}
              size={16}
              disabled={items.length === 0}
              offset={4}
            >
              <ActionIcon
                variant="subtle"
                color="gray"
                size="lg"
                aria-label={label}
                data-testid="notifications-bell"
                onClick={onClick}
              >
                <Icon icon="mdi:bell-outline" width={22} />
              </ActionIcon>
            </Indicator>
          );
        })()}
      </Popover.Target>
      <Popover.Dropdown data-testid="notifications-panel" p="xs">
        <Text size="xs" fw={600} c="dimmed" px="xs" pb={4}>
          Since your last visit
        </Text>
        {items.length === 0 ? (
          <Text size="sm" c="dimmed" px="xs" py="sm">
            Nothing new.
          </Text>
        ) : (
          <ScrollArea.Autosize mah={360} type="auto">
            <Stack gap={2}>
              {items.map((item) => (
                <NotificationRow key={`${item.scope_kind}:${item.scope_id}`} item={item} />
              ))}
            </Stack>
          </ScrollArea.Autosize>
        )}
      </Popover.Dropdown>
    </Popover>
  );
};

export default NotificationsBell;
